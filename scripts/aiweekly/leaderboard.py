"""排行榜编排层：多源池调度 / 区域优先级 / 快照与缓存兜底 / 周变化 / 选型结论。

单榜源解析器见 `leaderboard_sources.py`，成本与资料卡富化见 `model_meta.py`
（P1#1 Phase 3 拆分，本文件只负责「怎么组合、怎么兜底」）。

设计原则：
① 每源独立容错，单源失败不影响其他榜；
② 抓取失败不脑补、不空白，回退本地缓存快照并标注数据截止日；
③ 基于本地缓存计算「周变化 ↑↓」；
④ 排行榜描述字段以 model_profiles.json（资料卡）为唯一权威源。
"""
import json
from datetime import datetime
from pathlib import Path

from aiweekly.utils import (
    _http_get, _probe, _detect_region, _retry_fetch, _resolved_proxy,
    _parse_date_arg, _parse_snapshot_date,
)
from aiweekly.news import LEADERBOARD_STALE_DAYS
from aiweekly.model_meta import (
    COST_PATH, DEFAULT_PROFILES, PENDING_PROFILES,
    _load_cost_table, _COST_TABLE, _match_cost, _enrich_cost, _apply_profile_as_truth,
)
from aiweekly.leaderboard_sources import (
    LM_ARENA_URL, AA_URL, HF_DS_API, HF_LEADERBOARD_URL, DATALARNER_URL,
    LLMSTATS_URL, OC_LLM_URL, SV_GENERAL_URL, MS_MODELS_URL,
    ORG_PREFIXES, OPEN_SOURCE_MODEL_KEYWORDS, DL_ORG_SPLIT, _SUFFIX_RE,
    _clean_model_slug, _norm_model, _is_open_source_model, _split_dl_org,
    _parse_table_rows, _parse_ctx, _parse_money,
    fetch_lmarena_ranking, fetch_aa_ranking, fetch_hf_open_ranking,
    fetch_llmstats_ranking, fetch_datalearner_ranking,
    fetch_opencompass_ranking, fetch_superclue_ranking, fetch_modelscope_ranking,
)

SKILL_DIR = Path(__file__).resolve().parents[2]

CACHE_PATH = SKILL_DIR / "leaderboard_cache.json"
# 国内可直连权威榜快照（OpenCompass 司南，SSR 不可达时的兜底；非实时，标注截止日）
CN_SNAPSHOT_PATH = SKILL_DIR / "cn_leaderboard_snapshot.json"

__all__ = [
    "CACHE_PATH", "CN_SNAPSHOT_PATH", "_load_cn_snapshot", "_leaderboard_freshness",
    "LB_CRITERIA", "SOURCES", "_load_cache", "_save_cache",
    "_apply_deltas", "fetch_all_leaderboards", "_fill_from_cache", "_collect_leaderboard_models",
    "sync_model_profiles",
]


def _load_cn_snapshot() -> dict:
    """读取国内可直连榜快照（OpenCompass 司南，SSR 不可达时的兜底）。"""
    try:
        if CN_SNAPSHOT_PATH.exists():
            return json.loads(CN_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# _parse_snapshot_date 已迁移到 aiweekly.utils（顶部已 re-export）。


def _leaderboard_freshness(leaderboard: dict, report_date) -> dict:
    """计算排行榜各源快照距报告日的时效，判断是否需要「非本周抓取」告警。

    返回 dict：{max_age, stale, per_source, per_source_age, worst_source, worst_age}
    - max_age: 所有源中最大天数（无快照则为 -1）
    - stale: 是否存在超龄（> LEADERBOARD_STALE_DAYS）源
    - per_source: {key: ISO 8601 快照串 or None}（P1#21：语义明确、可对比、可排序）
    - per_source_age: {key: 距报告日天数 or None}（兼容模板渲染，向前端提供现成天数差）
    """
    # report_date 可能是 str（CLI --date）或 datetime，统一解析为 datetime
    if isinstance(report_date, str):
        report_date = _parse_date_arg(report_date)
    per_source, per_source_age = {}, {}
    worst_key, worst_age = None, -1
    groups = [
        ("comprehensive.lmarena", leaderboard.get("comprehensive", {}).get("lmarena", {})),
        ("comprehensive.aa", leaderboard.get("comprehensive", {}).get("aa", {})),
        ("open_source.ls", leaderboard.get("open_source", {}).get("ls", {})),
        ("open_source.hf", leaderboard.get("open_source", {}).get("hf", {})),
    ]
    for key, sub in groups:
        snap = (sub or {}).get("snapshot", "")
        d = _parse_snapshot_date(snap)
        if d is None:
            per_source[key] = None
            per_source_age[key] = None
            continue
        age = (report_date.date() - d).days
        per_source[key] = str(snap).strip()  # P1#21：保留原始 ISO 8601 快照串
        per_source_age[key] = age
        if age > worst_age:
            worst_key, worst_age = key, age
    max_age = max((a for a in per_source_age.values() if a is not None), default=-1)
    stale = any((a is not None and a > LEADERBOARD_STALE_DAYS) for a in per_source_age.values())
    return {
        "max_age": max_age,
        "stale": stale,
        "per_source": per_source,
        "per_source_age": per_source_age,
        "worst_source": worst_key,
        "worst_age": worst_age if worst_age >= 0 else None,
    }



# ---------- 国内可直连榜源解析器（尽力而为）----------
# 说明：OpenCompass / SuperCLUE / ModelScope 官网均为 JS 渲染 SPA，其数据 API
# 无法用简单 HTTP 稳定抓取（返回 SPA 兜底 HTML 或需鉴权）。下列解析器按「尽力而为」
# 实现——若抓到的是 SPA 兜底页（无 <table>）或解析失败，一律返回 None，
# 由多源池优雅降级到国内快照（cn_leaderboard_snapshot.json）或本地缓存。
# 一旦某源开放稳定 JSON API，只需在对应解析器里补全字段提取即可自动生效。



# 三榜各自的评分标准说明（渲染到页面「评分标准」行，数据驱动）；定义在多源池之前，
# 供 SOURCES 引用（模块级求值顺序要求）。
LB_CRITERIA = {
    "lmarena": ("评分标准：人类偏好 Elo（LMArena）。由真实用户对模型回答做匿名两两盲测、"
                "按「哪个回答更好」投票得出——衡量的是真实使用中的人类好感度（使用体感），"
                "并非某项知识 / 能力基准。分数越高代表越受人类偏好。"),
    "aa": ("评分标准：智能指数 Intelligence Index（Artificial Analysis）。综合多项权威能力基准"
           "归一化后的综合分（满分 100，越高越强），主要涵盖：MMLU-Pro（研究生级综合知识）、"
           "GPQA（研究生级科学问答）、Humanity's Last Exam / HLE（人类终极考试·极难跨学科学术题，逼近专家上限）。"),
    "ls": ("评分标准：LLM-Stats 综合分（LLM Stats Score）。基于多项公开基准归一化后的开源模型"
           "综合得分（满分 100，越高越强），主要涵盖：MMLU-Pro（研究生级综合知识）、GPQA（研究生级科学问答）、"
           "HumanEval（代码生成）、MATH（数学竞赛解题）、SWE-bench（软件工程实战·修复真实 GitHub issue）、"
           "HLE（人类终极考试）；同时标注许可证、上下文窗口与输入输出单价，便于自部署 / 商用评估。"),
    "hf": ("评分标准：Hugging Face Open LLM Leaderboard 平均分（Average ⬆️）。在多项权威基准上的"
           "加权平均分（满分 100，越高越强），主要涵盖：MMLU-Pro（研究生级综合知识）、MATH（数学竞赛解题）、"
           "HumanEval（代码生成）、GPQA（研究生级科学问答）、MuSR（多步逻辑推理·长篇谜题 / 谋杀推理等需多步推演）、"
           "IFEval（指令遵循·严格按格式与约束执行）。仅收录可复现的开源权重模型，强调可复现性与社区验证。"),
}


# ---------- 多源池（每个榜源带 region 标签，供 region 优先级排序）----------
SOURCES = {
    "aa": {"region": "global", "board": "comprehensive", "key": "aa",
           "fn": lambda n: fetch_aa_ranking(n),
           "label": "Artificial Analysis · 智能指数", "url": AA_URL,
           "criteria": LB_CRITERIA["aa"]},
    "lm": {"region": "global", "board": "comprehensive", "key": "lm",
           "fn": lambda n: fetch_lmarena_ranking(n),
           "label": "LMArena · 人类偏好 Elo", "url": LM_ARENA_URL,
           "criteria": LB_CRITERIA["lmarena"]},
    "oc": {"region": "cn", "board": "comprehensive",
           "fn": lambda n: fetch_opencompass_ranking(n),
           "label": "OpenCompass 司南 · LLM 综合榜", "url": OC_LLM_URL,
           "criteria": ("评分标准：OpenCompass 司南 LLM 综合榜。在知识/推理/数学/代码/智能体等多维度"
                        "权威基准上的加权平均均分（满分 100，越高越强）。")},
    "sv": {"region": "cn", "board": "comprehensive",
           "fn": lambda n: fetch_superclue_ranking(n),
           "label": "SuperCLUE · 中文通用智能指数", "url": SV_GENERAL_URL,
           "criteria": ("评分标准：SuperCLUE 中文通用能力总排行榜。聚焦中文场景的综合能力复合分"
                        "（满分 100，越高越强）。")},
    "ls": {"region": "global", "board": "open_source",
           "fn": lambda n: fetch_llmstats_ranking(n),
           "label": "LLM-Stats · 开源模型榜", "url": LLMSTATS_URL,
           "criteria": LB_CRITERIA["ls"]},
    "dl": {"region": "global", "board": "open_source",
           "fn": lambda n: fetch_datalearner_ranking(n),
           "label": "DataLearner · 开源模型榜", "url": DATALARNER_URL,
           "criteria": LB_CRITERIA["ls"]},
    "hf": {"region": "global", "board": "open_source",
           "fn": lambda n: fetch_hf_open_ranking(n * 2),
           "label": "Hugging Face · Open LLM Leaderboard", "url": HF_LEADERBOARD_URL,
           "criteria": LB_CRITERIA["hf"]},
    "ms": {"region": "cn", "board": "open_source",
           "fn": lambda n: fetch_modelscope_ranking(n),
           "label": "ModelScope 魔搭 · 开源模型热度", "url": MS_MODELS_URL,
           "criteria": ("评分标准：ModelScope 魔搭社区开源模型热度（按页面热度排序）。"
                        "反映国内开源生态活跃度，非能力基准。")},
}


def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _apply_deltas(rows, cache_rows, score_key=None):
    """rows 含 rank/model；cache_rows 为上期 {model: value}。
    rank: 数字下降=名次前进（正 delta）；score: 直接差。
    score_key 为 None 时按行自动判定（优先 score，否则 rank）。"""
    if not cache_rows:
        for r in rows:
            r["delta"] = None
        return rows
    if score_key is None:
        score_key = "score" if any(r.get("score") is not None for r in rows) else "rank"
    cache_map = {k.lower(): v for k, v in cache_rows.items()}
    for r in rows:
        prev = cache_map.get(r["model"].lower())
        cur = r.get(score_key)
        if prev is None or cur is None:
            r["delta"] = None
            continue
        r["delta"] = (prev - cur) if score_key == "rank" else round(cur - prev, 1)
    return rows


# _retry_fetch 已迁移到 aiweekly.utils（顶部已 re-export）。

def fetch_all_leaderboards(top_n: int = 15, region: str = "auto"):
    """抓取双排行榜，返回结构化数据；网络环境自适应。

    设计：
      - 多源池 SOURCES 每个榜源带 region 标签（cn/global）。
      - 按 detected region 排序优先级：国内环境优先国内源、国外环境优先国外源，
        依次 _retry_fetch 命中即用（每榜综合榜取 2 个源、开源榜取 1 个源）。
      - 国内环境且实时源全失败 -> 回退到国内快照 cn_leaderboard_snapshot.json（标注 is_cache）。
      - 国外环境或未知环境且实时源失败 -> 回退本地缓存 leaderboard_cache.json（标注 is_cache）。
      - 每个 slot 额外携带 source_region / is_cache，供前端来源区域徽章展示。
    """
    if region in ("auto", "cn", "global", "unknown"):
        detected = _detect_region() if region == "auto" else region
    else:
        detected = "global"
    proxy = _resolved_proxy()
    print(f"  🌐 网络环境判定：{detected}" + (f"（代理：{proxy}）" if proxy else ""))

    snapshot = datetime.now().astimezone().strftime("%Y-%m-%d")
    cache = _load_cache()
    cn_snap = _load_cn_snapshot()

    def try_board(board: str, need: int):
        """按 region 优先级尝试该 board 的源池，返回 [(source_spec, rows), ...]。"""
        pool = [s for s in SOURCES.values() if s["board"] == board]
        pool.sort(key=lambda s: 0 if s["region"] == detected else 1)
        hit = []
        for s in pool:
            rows = _retry_fetch(lambda: s["fn"](top_n))
            if rows:
                hit.append((s, rows))
                if len(hit) >= need:
                    break
        return hit

    def live_slot(s, rows):
        return {
            "source": s["label"], "url": s["url"], "snapshot": snapshot,
            "criteria": s["criteria"], "rows": rows[:top_n],
            "source_region": "cn" if s["region"] == "cn" else "global",
            "is_cache": False,
        }

    def snap_slot(src, snap_date):
        return {
            "source": src.get("source", ""), "url": src.get("url", ""),
            "snapshot": snap_date, "criteria": src.get("criteria", ""),
            "rows": src.get("rows", [])[:top_n],
            "source_region": "cn", "is_cache": True,
        }

    comp_hits = try_board("comprehensive", 2)
    os_hits = try_board("open_source", 1)

    # —— 综合榜（两列：lmarena / aa）——
    comp = {"lmarena": {"rows": []}, "aa": {"rows": []}}
    if comp_hits:
        # 按源 key 路由到正确槽位（避免 slot 名与承载数据相反）：
        # comp["lmarena"] 承载 LMArena 源，comp["aa"] 承载 Artificial Analysis 源。
        for s, rows in comp_hits:
            slot = "aa" if s.get("key") == "aa" else ("lmarena" if s.get("key") == "lm" else None)
            if slot:
                comp[slot] = live_slot(s, rows)
    # 综合榜不足 / 全失败：国内环境回退快照，否则回退本地缓存
    if not comp["lmarena"]["rows"]:
        if detected == "cn" and cn_snap.get("comprehensive"):
            for key in cn_snap["comprehensive"]:
                if not comp["lmarena"]["rows"]:
                    comp["lmarena"] = snap_slot(cn_snap["comprehensive"][key], cn_snap.get("snapshot_date", ""))
                elif not comp["aa"]["rows"]:
                    comp["aa"] = snap_slot(cn_snap["comprehensive"][key], cn_snap.get("snapshot_date", ""))
                else:
                    break
        elif cache.get("lmarena") or cache.get("aa"):
            _fill_from_cache(comp, cache, snapshot)
    elif not comp["aa"]["rows"] and detected == "cn" and cn_snap.get("comprehensive"):
        # 已有一个综合源命中：第二列用快照补足（仅国内环境）
        for key in cn_snap["comprehensive"]:
            comp["aa"] = snap_slot(cn_snap["comprehensive"][key], cn_snap.get("snapshot_date", ""))
            break

    # —— 开源榜（双列：LLM-Stats + Hugging Face）——
    os_board = {"ls": {"rows": []}, "hf": {"rows": []}}
    # LLM-Stats（llm-stats 主源，datalearner 兜底）
    ls_rows = _retry_fetch(lambda: fetch_llmstats_ranking(top_n)) or \
              _retry_fetch(lambda: fetch_datalearner_ranking(top_n))
    if ls_rows:
        os_board["ls"] = live_slot(SOURCES["ls"], ls_rows)
    elif detected == "cn" and cn_snap.get("open_source"):
        for key in cn_snap["open_source"]:
            os_board["ls"] = snap_slot(cn_snap["open_source"][key], cn_snap.get("snapshot_date", ""))
            break
    # Hugging Face（独立源，与 LLM-Stats 并排展示）
    hf_rows = _retry_fetch(lambda: fetch_hf_open_ranking(top_n * 2))
    if hf_rows:
        os_board["hf"] = live_slot(SOURCES["hf"], hf_rows)
    elif detected == "cn" and cn_snap.get("open_source"):
        for key in cn_snap["open_source"]:
            os_board["hf"] = snap_slot(cn_snap["open_source"][key], cn_snap.get("snapshot_date", ""))
            break
    # 兜底：本地缓存快照（标注 is_cache）
    _fill_from_cache(os_board, cache, snapshot)

    lm = comp["lmarena"].get("rows") or []
    aa = comp["aa"].get("rows") or []
    ls = os_board["ls"].get("rows") or []
    hf = os_board["hf"].get("rows") or []

    if lm:
        _apply_deltas(lm, cache.get("lmarena", {}))
    if aa:
        _apply_deltas(aa, cache.get("aa", {}))
    if ls:
        _apply_deltas(ls, cache.get("ls", {}) or cache.get("hf", {}))
    if hf:
        _apply_deltas(hf, cache.get("hf", {}) or cache.get("ls", {}))

    # —— LMArena 智能指数补全 ——
    # LMArena 公开页/API 仅暴露名次，无原始 Elo 分；用同模型在含真实
    # Intelligence Index 的列（Artificial Analysis）回填「智能指数」列。
    # 注意：comp["lmarena"] 实际承载 AA 数据（含分数），comp["aa"] 实际承载
    # LMArena 数据（仅名次）。两列模型名一致，故按模型名匹配回填。
    # 这里动态判定「含分列」为源、「缺分列」为目标，不依赖列名约定。
    _scored = next((rows for rows in (lm, aa)
                    if any(r.get("score") is not None for r in rows)), None)
    _unscored = next((rows for rows in (lm, aa) if rows is not _scored), None)
    if _scored and _unscored:
        _idx_map = {}
        for r in _scored:
            if r.get("score") is not None and r.get("model"):
                _idx_map[_norm_model(r["model"])] = r["score"]
                _idx_map[r["model"].lower()] = r["score"]
        for r in _unscored:
            if r.get("score") is None and r.get("model"):
                v = _idx_map.get(_norm_model(r["model"])) or _idx_map.get(r["model"].lower())
                if v is not None:
                    r["score"] = v

    # —— P1：选型支撑数据（性价比象限 / 跨源差异 / 本周结论）——
    def _ability(r):
        """能力近似分(0-100)：优先 score；否则以名次近似，仅供横向参考。"""
        if r.get("score") is not None:
            return float(r["score"])
        if r.get("rank") is not None:
            return round(max(0.0, 100 - (r["rank"] - 1) * 1.2), 1)
        return None

    import re as _re
    _paren = _re.compile(r'\s*\([^)]*\)$')
    def _vnorm(label):
        # 去掉末尾括号变体（如 “(max)” “(with fallback)”），避免同一模型的多个变体在象限里重复堆叠
        return _paren.sub('', label or '').strip().lower()

    value_chart, _seen = [], {}
    for src_rows in (lm, aa):
        for r in src_rows:
            price = r.get("price_out")
            ctx = r.get("context")
            ab = _ability(r)
            if price is None or ab is None:
                continue
            p = {
                "label": r.get("model", "?"), "price": price, "ability": ab,
                "context": (ctx // 1000) if isinstance(ctx, int) else None,
                "cn_access": r.get("cn_access"),
            }
            k = _vnorm(p["label"])
            if k not in _seen or (_seen[k]["ability"] or 0) < (p["ability"] or 0):
                _seen[k] = p
    value_chart = list(_seen.values())

    cross_diff = []
    if lm and aa:
        aa_map = {r["model"].lower(): r["rank"] for r in aa if r.get("rank")}
        for r in lm:
            ar = aa_map.get(r["model"].lower())
            if ar and r.get("rank"):
                cross_diff.append({"model": r["model"], "lm_rank": r["rank"],
                                   "aa_rank": ar, "diff": r["rank"] - ar})
        cross_diff.sort(key=lambda x: abs(x["diff"]), reverse=True)

    top = (aa or lm or [{}])[0] if (aa or lm) else {}
    top_name = top.get("model") if top else None
    cheap = next((r for r in aa if r.get("cn_access")
                  and "国内可直连" in r["cn_access"] and r.get("price_out") is not None
                  and r["price_out"] <= 2), None)
    if cheap:
        selection_note = (f"本周综合最强仍是 {top_name or '头部闭源模型'}；"
                          f"若看重成本与国内合规直连，{cheap['model']}（{cheap['price_out']}$/1M·out）"
                          f"是更务实的选型。")
    elif top_name:
        selection_note = (f"本周综合最强为 {top_name}；开源/自部署可关注 Qwen、Llama、DeepSeek 等家族"
                          f"（详见开源榜）。")
    else:
        selection_note = "本期源数据缺失，排名与结论仅供参考。"

    data = {
        "meta": {"region": detected, "proxy": proxy or "",
                 "note": ("已按国内网络环境优先采用国内可直连榜源" if detected == "cn"
                          else "已按国外网络环境优先采用国际榜源")},
        "comprehensive": {
            "lmarena": comp["lmarena"],
            "aa": comp["aa"],
        },
        "open_source": {
            "ls": os_board["ls"],
            "hf": os_board["hf"],
        },
        "selection_note": selection_note,
        "value_chart": value_chart,
        "cross_diff": cross_diff,
    }

    # 写回缓存供下次对比（按 slot 名 lmarena/aa/ls/hf 存模型->值）
    _save_cache({
        "lmarena": {r["model"]: r["rank"] if r.get("rank") is not None else r.get("score") for r in lm},
        "aa": {r["model"]: r["score"] if r.get("score") is not None else r.get("rank") for r in aa},
        "ls": {r["model"]: r["rank"] if r.get("rank") is not None else r.get("score") for r in ls},
        "hf": {r["model"]: r["rank"] if r.get("rank") is not None else r.get("score") for r in hf},
        "snapshot": snapshot,
    })
    return data


def _fill_from_cache(board: dict, cache: dict, snapshot: str):
    """实时源全失败时，用本地缓存快照填充（标注 is_cache）。board 为 {slot:{rows:[]}}。"""
    for slot, ckey in (("lmarena", "lmarena"), ("aa", "aa"),
                       ("ls", "ls"), ("ls", "hf"),
                       ("hf", "hf"), ("hf", "ls")):
        if slot in board and not board[slot]["rows"] and cache.get(ckey):
            cached_rows = [{"model": m, "rank": (v if isinstance(v, int) else None),
                            "score": (v if not isinstance(v, int) else None),
                            "org": "", "open_source": None}
                           for m, v in cache[ckey].items()]
            board[slot] = {
                "source": f"本地缓存快照（{cache.get('snapshot', '未知')}）", "url": "",
                "snapshot": cache.get("snapshot", ""), "criteria": "",
                "rows": cached_rows, "source_region": "cache", "is_cache": True,
            }
            break


def _collect_leaderboard_models(leaderboard_data):
    """收集排行榜中出现的所有模型名（去重保序）。"""
    models = []
    if not leaderboard_data:
        return models
    for board in ("lmarena", "aa"):
        for r in leaderboard_data.get("comprehensive", {}).get(board, {}).get("rows", []):
            m = r.get("model")
            if m:
                models.append(m)
    for r in leaderboard_data.get("open_source", {}).get("hf", {}).get("rows", []):
        m = r.get("model")
        if m:
            models.append(m)
    seen, uniq = set(), []
    for m in models:
        if m.lower() not in seen:
            seen.add(m.lower())
            uniq.append(m)
    return uniq


def sync_model_profiles(extra_profiles_path: str, leaderboard_data: dict):
    """模型档案同步（real-time archive update）：

    1. 自动加载技能目录下的 canonical 档案 model_profiles.json（无需手动 --profiles-json）；
    2. 若传入 --profiles-json，将其合并进 canonical 并写回，使档案随每次研究累积更新；
    3. 检测排行榜中出现、但档案缺失的模型，写入 model_profiles.pending.json 供后续联网核实；
    4. 返回合并后的档案 dict（注入 LEADERBOARD_DATA.model_profiles）。
    """
    base = {}
    if DEFAULT_PROFILES.exists():
        try:
            base = json.loads(DEFAULT_PROFILES.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ⚠️ 读取 canonical 模型档案失败：{e}")

    # 合并本次传入的新档案并写回 canonical（实时更新）
    if extra_profiles_path:
        try:
            extra = json.loads(Path(extra_profiles_path).read_text(encoding="utf-8"))
            if isinstance(extra, dict) and extra:
                base.update(extra)
                DEFAULT_PROFILES.write_text(
                    json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"📇 已合并 {len(extra)} 条新模型档案 -> {DEFAULT_PROFILES.name}（canonical 已更新）")
        except Exception as e:
            print(f"  ⚠️ 读取/合并 --profiles-json 失败：{e}")

    # 检测新上榜却缺档案的模型
    if leaderboard_data:
        models = _collect_leaderboard_models(leaderboard_data)
        lower_keys = {k.lower() for k in base}
        missing = [m for m in models if m.lower() not in lower_keys]
        if missing:
            PENDING_PROFILES.write_text(
                json.dumps(missing, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ⚠️ 发现 {len(missing)} 个新模型未建档，已写入 {PENDING_PROFILES.name}：{missing}")
            print(f"     → 请联网核实后通过 --profiles-json 合并，或更新 canonical 档案。")
        else:
            if PENDING_PROFILES.exists():
                PENDING_PROFILES.unlink()
            print(f"📇 模型档案齐全：{len(base)} 条覆盖全部 {len(models)} 个上榜模型")
    else:
        print("  ℹ️ 未提供排行榜数据，跳过新模型建档检测")

    return base

