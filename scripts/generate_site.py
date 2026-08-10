#!/usr/bin/env python3
"""
generate_site.py v2.0

将新闻 JSON（RSS 自治抓取，AI HOT 兼容 schema）渲染为 AI 新闻网站 HTML。
本技能**不内置任何第三方商业 API 依赖**；新闻默认全部来自 RSS 聚合。

可选外部增强：
  如果你希望用 AI HOT、或任何「AI 行业知识类」外部 API 增强报告可信度，
  请自行从其官方渠道获取数据并导出为 JSON（schema 见下），再用
  --external-news-json 注入。是否启用完全由你决定，风险自担（需遵守该 API 的服务条款）。

用法：
  # 用 RSS 抓取结果生成（默认，无任何第三方 API 依赖）
  python scripts/generate_site.py --api-json news.json --output AI_News.html

  # 叠加用户自备的外部 API 数据增强（例：AI HOT 导出 JSON）
  python scripts/generate_site.py --api-json news.json \
      --external-news-json aihot_export.json --external-source-name "AI HOT" \
      --external-source-url "https://aihot.virxact.com" -o AI_News.html

  # 从自定义排行榜 JSON 文件生成
  python scripts/generate_site.py --api-json news.json --ranking-json ranking.json -o AI_News.html

  # 跳过排行榜自动获取（显示「暂无实时数据」）
  python scripts/generate_site.py --api-json news.json --no-live-ranking -o AI_News.html

  # 仅查看预览数据（不生成 HTML）
  python scripts/generate_site.py --api-json news.json --dry-run

新闻 / 外部增强 JSON 格式（items 列表或 {"items": [...]}）：
  [{"title":"...","summary":"...","url":"...","source":"...",
    "publishedAt":"...","category":"ai-models","score":0}, ...]

排行榜 JSON 格式：
  [{"name":"...","developer":"...","open_source":false,"score":"92","rank":1}, ...]

输出：
  - 新闻卡片（分类色块缩略图 + 来源链接 + 相对时间）
  - 市场规模 + 融资趋势 Chart.js 图表
  - Top 10 模型排行榜表格（实时数据，标注来源与排名标准）
  - 搜索栏 + 分类筛选标签
  - 暗色模式 + 响应式布局
"""

import argparse
import logging
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import concurrent.futures
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ 缺少依赖(beautifulsoup4)。请使用仓库根目录的 run_report.sh 启动，"
          "或：python -m pip install -r requirements.txt")
    sys.exit(1)


# ── P0：拆分到 aiweekly 子包（外部 API 仍可通过本模块名访问，向后兼容）──
import aiweekly.utils as _au  # 内部直接用于 _PROXY_OVERRIDE 等可变全局状态
from aiweekly.utils import (
    _UA, _resolved_proxy, _configure_proxy, _build_opener,
    _http_get, _probe, _detect_region, _retry_fetch,
    _parse_date_arg, _parse_snapshot_date,
)
from aiweekly.translate import _ollama_translate, translate_en_summaries
from aiweekly.news import (
    SUMMARY_MAX, SUMMARY_TARGET, MUSTREAD_TOP_N, LEADERBOARD_STALE_DAYS,
    SOURCE_ALIASES, SOURCE_AUTHORITY, CATEGORY_WEIGHT,
    DEFAULT_SOURCE_AUTHORITY, DEFAULT_CATEGORY_WEIGHT, OPEN_SOURCE_PROVIDERS,
    merge_external_news, format_news_items,
    _normalize_source, _detect_lang, _normalize_summary,
    _is_open_source, _score_news, get_default_ranking,
)


logger = logging.getLogger(__name__)


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "news_site_template.html"


# ── 已迁移到 aiweekly.{news,translate,utils} ──
# 见本文件顶部 `from aiweekly.* import ...`；下方保留为本文件专属逻辑（榜单 / 市场 / 看点 / 生成）。
# 注意：抓取层（fetch_*）的 `except Exception` 为**有意的 best-effort 容错**——
# 单源失败必须不阻断整条管线（回退缓存 / 标注「暂无实时数据」），属 P0#8 允许的
# 「保留并加合理性注释」情形；仅数据解析 / 文件读取处的异常已收窄为具体类型
# （json.JSONDecodeError / OSError）。


# ============ 大模型排行榜（双榜：综合榜 + 开源模型榜）============
# 综合榜：LMArena（人类偏好 Elo）+ Artificial Analysis 智能指数
# 开源榜：Hugging Face Open LLM Leaderboard
# 设计原则：① 每源独立容错，单源失败不影响其他榜；② 抓取失败不脑补、不空白，
#          回退到本地缓存快照并标注数据截止日；③ 基于本地缓存计算「周变化 ↑↓」。
LM_ARENA_URL = "https://lmarena.ai/leaderboard"
AA_URL = "https://artificialanalysis.ai/"
HF_DS_API = ("https://datasets-server.huggingface.co/rows"
             "?dataset=open-llm-leaderboard/contents&config=default"
             "&split=train")
HF_LEADERBOARD_URL = "https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard"
# 开源模型榜新源（替代 HF，用户指定）：LLM-Stats（含 score/license/context/价格）、DataLearner（含 HLE/开源情况）
DATALARNER_URL = "https://www.datalearner.com/leaderboards/open-source"
LLMSTATS_URL = "https://llm-stats.com/leaderboards/open-llm-leaderboard"

CACHE_PATH = SKILL_DIR / "leaderboard_cache.json"
COST_PATH = SKILL_DIR / "models_cost.json"
# 国内可直连权威榜快照（OpenCompass 司南，SSR 不可达时的兜底；非实时，标注截止日）
CN_SNAPSHOT_PATH = SKILL_DIR / "cn_leaderboard_snapshot.json"
# 模型资料卡 canonical 档案（按模型名索引，联网核实的机构/许可证/成本等）；
# 每次生成自动加载，新模型研究后合并写回，实现档案实时累积更新。
DEFAULT_PROFILES = SKILL_DIR / "model_profiles.json"
# 新上榜但档案缺失的模型清单（供后续联网核实），检测为空时自动删除。
PENDING_PROFILES = SKILL_DIR / "model_profiles.pending.json"

# 国内可直连榜源（SSR/可解析站点）。注意：OpenCompass / SuperCLUE / ModelScope 官网
# 均为 JS 渲染 SPA，其数据 API 无法用简单 HTTP 稳定抓取（返回 SPA 兜底 HTML / 需鉴权），
# 故这些 live 解析器按「尽力而为」实现——连不上或拿到的不是结构化数据就返回 None，
# 由多源池优雅降级到国内快照（CN_SNAPSHOT_PATH）或缓存。region 标签用于来源徽章与优先级。
OC_LLM_URL = "https://rank.opencompass.org.cn/leaderboard-llm"
SV_GENERAL_URL = "https://www.superclueai.com/generalpage"
MS_MODELS_URL = "https://modelscope.cn/models"

# 选型决策所需的「成本/上下文/可用性」参考表（公开资料整理，维护者周更；非实时）
# P0/P1 使用：每行模型按家族匹配后注入 price/context/commercial/cn_access 等字段；
# 未匹配到的家族一律返回 None（页面显示 —，绝不编造）。
def _load_cost_table() -> list:
    try:
        if COST_PATH.exists():
            return json.loads(COST_PATH.read_text(encoding="utf-8")).get("models", [])
    except Exception:
        pass
    return []


_COST_TABLE = _load_cost_table()


def _match_cost(model: str):
    """按模型名匹配家族，返回成本参考条目或 None。"""
    if not model:
        return None
    t = model.lower()
    for entry in _COST_TABLE:
        for k in entry.get("keys", []):
            if k.lower() in t:
                return entry
    return None


def _enrich_cost(row: dict) -> dict:
    """给排行行注入选型字段（成本/上下文/可用性）。无匹配则留 None。"""
    c = _match_cost(row.get("model", ""))
    if not c:
        row.setdefault("price_in", None)
        row.setdefault("price_out", None)
        row.setdefault("context", None)
        row.setdefault("multimodal", None)
        row.setdefault("cn_access", None)
        row.setdefault("best_for", None)
        row.setdefault("commercial", None)
        row.setdefault("currency", "USD")
        return row
    row["price_in"] = c.get("price_in")
    row["price_out"] = c.get("price_out")
    row["context"] = c.get("context")
    row["multimodal"] = c.get("multimodal")
    row["cn_access"] = c.get("cn_access")
    row["best_for"] = c.get("best_for")
    row["commercial"] = c.get("commercial")
    row["currency"] = c.get("currency", "USD")
    return row


def _apply_profile_as_truth(leaderboard: dict, profiles: dict):
    """以资料卡(model_profiles.json)为准：用卡片的权威值覆盖排行榜行里的描述性字段
    （成本/上下文/许可证/商用/模态/币种）。排名字段(rank/score/model/org)来自基准榜，
    不覆盖。卡片缺字段时保留榜单原值（成本表/实时抓取兜底）。

    这是用户确立的硬性规则：排行榜上展示的模型「资料」必须与资料卡一致，
    资料卡是唯一权威源；成本表(models_cost.json)仅作无卡片时的兜底。
    """
    _MAP = [("cost_in", "price_in"), ("cost_out", "price_out"),
            ("context", "context"), ("license", "license"),
            ("commercial", "commercial"), ("multimodal", "multimodal"),
            ("currency", "currency")]
    boards = []
    for b in (list((leaderboard.get("comprehensive") or {}).values())
              + list((leaderboard.get("open_source") or {}).values())):
        if isinstance(b, dict) and "rows" in b:
            boards.append(b)
    for b in boards:
        for r in b.get("rows", []):
            p = profiles.get((r.get("model") or "").lower())
            if not p:
                continue
            for cf, rf in _MAP:
                v = p.get(cf)
                if v in (None, "", "—"):
                    continue
                r[rf] = v


# 已知开发方前缀（用于从 LMArena 拼接 slug 中切分机构名）
ORG_PREFIXES = [
    "Anthropic", "OpenAI", "Google", "Meta", "Mistral AI", "DeepSeek", "Alibaba",
    "Qwen", "Moonshot", "xAI", "Zhipu", "Zai", "MiniMax", "NVIDIA", "IBM",
    "Microsoft", "Cohere", "01.AI", "Ai2", "AllenAI", "Databricks",
    "NousResearch", "Tencent", "Baidu", "StepFun", "Arcee", "Grok",
]


def _clean_model_slug(slug: str):
    """从 LMArena 的 'Anthropicclaude-fable-5' 这类拼接 slug 切出 (org, model)。"""
    for org in ORG_PREFIXES:
        if slug.lower().startswith(org.lower()):
            model = slug[len(org):].lstrip("-_ ").replace("-", " ").strip()
            return org, model[:60].title()
    return "", slug.replace("-", " ").strip()[:60].title()


# 跨源模型名归一化（用于 LMArena↔AA 智能指数回填匹配）：
# 小写、去分隔符、去前缀机构、去常见后缀词。注意：后缀词只去掉词本身，
# 不吞掉前面的数字（否则 "1.1" 会被拆成 "11" 再误删版本位，导致
# "Muse Spark 1.1 (xhigh)" 与 "Muse Spark 1.1" 匹配失败）。
# 机构名内嵌的 max（如 MiniMax）已由 ORG_PREFIXES 前缀剥离先行处理，不受影响。
_SUFFIX_RE = re.compile(r"(max|xhigh|high|thinking|withfallback|preview|pro|flash|sol|ultra)")


def _norm_model(name: str) -> str:
    if not name:
        return ""
    s = name.lower()
    for ch in " ()[]-_./":
        s = s.replace(ch, "")
    for p in ORG_PREFIXES:
        pk = p.lower().replace(" ", "")
        if s.startswith(pk):
            s = s[len(pk):]
            break
    return _SUFFIX_RE.sub("", s)


# 代理与网络 IO 已迁移到 aiweekly.utils（_PROXY_OVERRIDE / _resolved_proxy / _configure_proxy /
# _build_opener / _http_get / _probe / _detect_region）。本文件顶部已 re-export。

def fetch_lmarena_ranking(top_n: int = 15):
    """LMArena 综合排名（人类偏好 Elo）。解析排行榜页面服务端渲染的表格。"""
    try:
        html = _http_get(LM_ARENA_URL, timeout=60)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return None
        rows = tables[0].find_all("tr")
        out = []
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            try:
                rank = int(cells[1])
            except ValueError:
                continue
            org, model = _clean_model_slug(cells[0])
            if not model:
                continue
            out.append(_enrich_cost({
                "rank": rank, "model": model, "org": org,
                "open_source": _is_open_source(org) or _is_open_source_model(model),
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ LMArena 抓取失败：{e}")
        return None


# 开源模型的品牌/系列关键词（用于从模型名直接判定开源，覆盖 AA 等无机构字段的来源）
OPEN_SOURCE_MODEL_KEYWORDS = [
    "llama", "qwen", "deepseek", "mistral", "magistral", "gemma", "phi", "yi-",
    "olmo", "nemotron", "command r", "glm", "kimi", "grok", "falcon", "baichuan",
    "chatglm", "internlm", "minicpm", "vicuna", "wizardlm", "zephyr", "mixtral",
    "codellama", "cogvlm", "qwen3", "qwen2",
]


def _is_open_source_model(text: str) -> bool:
    """通过模型名/品牌关键词判定开源（与机构判定互补）。"""
    t = (text or "").lower()
    return any(k in t for k in OPEN_SOURCE_MODEL_KEYWORDS)


def fetch_aa_ranking(top_n: int = 15):
    """Artificial Analysis 智能指数（客观能力复合分）。

    数据全部来自 artificialanalysis.ai（源站本身即含成本/上下文/指数，未编造）：
      - 主页 data[] 数组：label + artificialAnalysisIntelligenceIndex + detailsUrl
      - 某模型详情页 data[] 数组（按 label 关联）：contextWindowTokens、pricing(inputPrice/outputPrice)
    """
    try:
        html = _http_get(AA_URL, timeout=45)
        # label + 智能指数 + 详情页 URL（用于二次抓取上下文/价格）
        entries = re.findall(
            r'"label":"([^"]+)","artificialAnalysisIntelligenceIndex":([\d.]+),'
            r'"detailsUrl":"([^"]+)"', html)
        if not entries:
            entries = [(m, s, "") for m, s in re.findall(
                r'"label":"([^"]+)","artificialAnalysisIntelligenceIndex":([\d.]+)', html)]
        if not entries:
            return None
        ranked = sorted(entries, key=lambda x: float(x[1]), reverse=True)

        # 上下文窗口 + 价格：从首个模型的详情页解析（按 label 关联）
        ctx_map, price_map = {}, {}
        detail_url = next((u for _, _, u in ranked if u), None)
        if detail_url:
            try:
                d = _http_get("https://artificialanalysis.ai" + detail_url, timeout=45)
                for m in re.finditer(r'"label":"([^"]+)","contextWindowTokens":(\d+)', d):
                    ctx_map[m.group(1)] = int(m.group(2))
                pre = re.compile(
                    r'"label":"([^"]+)"[^\[\]]*?"pricing":\[\s*\{"@type":"PropertyValue",'
                    r'"name":"inputPrice","value":([\d.]+)\},\s*\{"@type":"PropertyValue",'
                    r'"name":"outputPrice","value":([\d.]+)\}')
                for m in pre.finditer(d):
                    price_map[m.group(1)] = (float(m.group(2)), float(m.group(3)))
            except Exception as e:
                print(f"  ⚠️ AA 详情页（成本/上下文）抓取失败，相关字段将留空：{e}")

        out = []
        for i, (label, idx, _url) in enumerate(ranked[:top_n]):
            pin, pout = price_map.get(label, (None, None))
            row = {
                "rank": i + 1, "model": label, "score": round(float(idx), 1),
                "open_source": _is_open_source_model(label),
                "context": ctx_map.get(label),
                "price_in": pin, "price_out": pout,
            }
            out.append(_enrich_cost(row))
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ Artificial Analysis 抓取失败：{e}")
        return None


def fetch_hf_open_ranking(top_n: int = 30):
    """Hugging Face Open LLM Leaderboard（开源模型榜）。

    该数据集 rows API 单次 length 上限为 100 且按字母序返回（非按分数），
    故分页拉取全部模型后再按平均分降序取 Top，避免只看到字母序靠前的弱模型。
    """
    try:
        out = []
        offset = 0
        while True:
            url = HF_DS_API + f"&offset={offset}&length=100"
            data = json.loads(_http_get(url, timeout=45))
            rows = data.get("rows", [])
            if not rows:
                break
            for r in rows:
                row = r.get("row", {})
                name = row.get("eval_name") or row.get("Model") or ""
                if not name:
                    continue
                if "_" in name:
                    org, model = name.split("_", 1)
                else:
                    org, model = "", name
                avg = row.get("Average ⬆️") or row.get("Average") or ""
                lic = row.get("Hub License") or row.get("License") or "—"
                try:
                    score = float(avg)
                except (ValueError, TypeError):
                    score = None
                model = model.replace("_", " ").strip()
                # 去掉精度/量化后缀噪声（bfloat16 / fp16 / awq ...）
                model = re.sub(r'\s+(bfloat16|float16|fp16|float32|int8|int4|'
                               r'awq|gptq|8bit|4bit)\b.*$', '', model, flags=re.I)
                out.append(_enrich_cost({
                    "model": model,
                    "org": org,
                    "score": score,
                    "license": lic,
                }))
            if len(rows) < 100:
                break
            offset += 100
            if offset > 2000:
                break
        if not out:
            return None
        scored = [o for o in out if o["score"] is not None]
        scored.sort(key=lambda x: x["score"], reverse=True)
        for i, o in enumerate(scored):
            o["rank"] = i + 1
        return scored[:top_n]
    except Exception as e:
        print(f"  ⚠️ Hugging Face 开源榜抓取失败：{e}")
        return None


def _parse_table_rows(html: str):
    """从服务端渲染的 <table> 中提取所有行（每行为单元格文本列表）。"""
    tables = re.findall(r"<table[\s\S]*?</table>", html)
    if not tables:
        return []
    rows = []
    for tr in re.findall(r"<tr[\s\S]*?</tr>", tables[0]):
        cells = [re.sub(r"<[^>]+>", " ", c).strip() for c in
                 re.findall(r"<t[dh][\s\S]*?</t[dh]>", tr)]
        rows.append([c for c in cells if c != ""])
    return rows


def _parse_ctx(token: str):
    """'1.0M'->1_000_000；'128K'->128_000；'200000'->200000；否则 None。"""
    if not token:
        return None
    t = token.strip().upper().replace(",", "")
    try:
        if t.endswith("M"):
            return int(float(t[:-1]) * 1_000_000)
        if t.endswith("K"):
            return int(float(t[:-1]) * 1_000)
        return int(float(t))
    except ValueError:
        return None


def _parse_money(token: str):
    """'$3.00'->3.0；'—'/空->None。"""
    if not token:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", token)
    return float(m.group(1)) if m else None


# _parse_date_arg 已迁移到 aiweekly.utils（顶部已 re-export）。


def fetch_llmstats_ranking(top_n: int = 30):
    """LLM-Stats 开源模型榜（用户指定源）。

    实测表头（首列空占位，末列为机构；中间含众多基准列）：
        '' | Model | LLM Stats | Country | License | Context | Input $/M |
        Output $/M | Speed | ...（众多基准列）... | Organization
    含分数、机构、许可证、上下文、输入输出单价——直接注入榜单行（机构/成本/上下文/许可证）。

    修复：原先走 _parse_table_rows（逐行过滤空单元格），导致某行的空单元格被删掉、
    该行列索引与表头错位，机构列抓空。这里改用 BeautifulSoup 保留全部单元格
    （不过滤空单元格），按表头名称定位列，确保表头与数据行列索引严格对齐。
    """
    try:
        html = _http_get(LLMSTATS_URL, timeout=60)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return None
        rows = table.find_all("tr")
        if len(rows) < 2:
            return None
        # 定位表头：第一个含「Model」的行；记录数据起始行
        header_map, data_start = {}, None
        for ri, row in enumerate(rows):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if any("model" in c.lower() for c in cells):
                for i, h in enumerate(cells):
                    header_map[i] = h
                data_start = ri + 1
                break
        if data_start is None:
            return None

        def _col(sub: str, fallback: int) -> int:
            for i, h in header_map.items():
                if sub in h.lower():
                    return i
            return fallback

        model_i = _col("model", 1)
        score_i = _col("llm stats", 2)
        org_i = _col("organization", len(header_map) - 1)   # 机构：末列 Organization
        lic_i = _col("license", 4)
        ctx_i = _col("context", 5)
        in_i = _col("input", 6)
        out_i = _col("output", 7)
        out = []
        for row in rows[data_start:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= max(model_i, score_i, lic_i, ctx_i, in_i, out_i):
                continue
            model = cells[model_i].strip()
            if not model or not re.search(r"[A-Za-z]", model):
                continue
            try:
                score = float(cells[score_i])
            except (ValueError, TypeError):
                score = None
            org = cells[org_i].strip() if len(cells) > org_i else ""
            lic = cells[lic_i].strip()
            ctx = _parse_ctx(cells[ctx_i])
            pin = _parse_money(cells[in_i])
            pout = _parse_money(cells[out_i])
            commercial = "可自部署" if ("open" in lic.lower() or "mit" in lic.lower()
                                        or "apache" in lic.lower()) else "—"
            out.append(_enrich_cost({
                "rank": len(out) + 1, "model": model, "org": org,
                "score": score, "license": lic, "context": ctx,
                "price_in": pin, "price_out": pout,
                "commercial": commercial, "open_source": True,
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ LLM-Stats 开源榜抓取失败：{e}")
        return None


# DataLearner 将「模型名 + 机构名」拼接在模型列末尾（如 "Kimi K3Moonshot AI"），
# 机构总是拼在末尾，故按 endswith 切分，避免误伤模型名中的子串。
DL_ORG_SPLIT = [
    "Moonshot AI", "腾讯AI实验室", "智谱AI", "MiniMax", "DeepSeek", "阿里",
    "百度", "StepFun", "阶跃", "Mistral AI", "Meta", "OpenAI", "Anthropic",
    "Google", "xAI", "NVIDIA", "Microsoft", "Cohere", "01.AI", "Ai2",
    "Databricks", "NousResearch", "Zhipu", "Qwen", "Alibaba", "Tencent",
    "Grok", "Arcee",
]


def _split_dl_org(model: str):
    """从 DataLearner 合并的『模型名+机构名』切分机构（机构拼在末尾）。"""
    if not model:
        return "", model
    for p in sorted(DL_ORG_SPLIT, key=len, reverse=True):
        if model.endswith(p):
            m = model[: len(model) - len(p)].strip()
            if m:
                return p, m
    return "", model


def fetch_datalearner_ranking(top_n: int = 30):
    """DataLearner 开源模型榜（用户指定源，llm-stats 的备用源）。

    实测表头（共 10 列，首尾各一列空/占位）：
        '' | 排名 | 模型(含机构) | HLE | ARC-AGI-2 | FrontierMath | SWE-bench | τ²-Bench | 开源情况 | ''
    提供 HLE 综合分与「开源情况」（如 免费商用）作为分数与商用标注。

    注意：DataLearner 机构名拼在模型名末尾，且表格首尾有空列。这里用
    BeautifulSoup 保留全部单元格（不过滤空单元格），按表头名称定位列，
    避免页面结构漂移导致的错位。
    """
    try:
        html = _http_get(DATALARNER_URL, timeout=120)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return None
        rows = table.find_all("tr")
        if len(rows) < 2:
            return None
        # 定位表头：第一个含「模型」的行；同时记录数据起始行
        header_map, data_start = {}, None
        for ri, row in enumerate(rows):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if "模型" in cells:
                for i, h in enumerate(cells):
                    header_map[i] = h
                data_start = ri + 1
                break
        if data_start is None:
            return None

        def _col(sub: str, fallback: int) -> int:
            for i, h in header_map.items():
                if sub in h:
                    return i
            return fallback

        model_i = _col("模型", 2)
        score_i = _col("HLE", 3)
        open_i = _col("开源情况", 8)
        out = []
        for row in rows[data_start:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= max(model_i, score_i):
                continue
            model = cells[model_i].strip()
            if not model or not re.search(r"[A-Za-z]", model):
                continue
            try:
                score = float(cells[score_i])
            except (ValueError, TypeError):
                score = None
            org, clean_model = _split_dl_org(model)
            open_info = cells[open_i].strip() if len(cells) > open_i else "—"
            if not open_info:
                open_info = "—"
            out.append(_enrich_cost({
                "rank": len(out) + 1, "model": clean_model or model, "org": org,
                "score": score, "license": open_info, "context": None,
                "commercial": open_info, "open_source": True,
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ DataLearner 开源榜抓取失败：{e}")
        return None


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
    """计算排行榜各源快照距报告日的天数，判断是否需要「非本周抓取」告警。

    返回 dict：{max_age, stale, per_source: {key: age}, worst_source, worst_age}
    - max_age: 所有源中最大天数（无快照则为 -1）
    - stale: 是否存在超龄（> LEADERBOARD_STALE_DAYS）源
    """
    # report_date 可能是 str（CLI --date）或 datetime，统一解析为 datetime
    if isinstance(report_date, str):
        report_date = _parse_date_arg(report_date)
    per_source = {}
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
            continue
        age = (report_date.date() - d).days
        per_source[key] = age
        if age > worst_age:
            worst_key, worst_age = key, age
    max_age = max((a for a in per_source.values() if a is not None), default=-1)
    stale = any((a is not None and a > LEADERBOARD_STALE_DAYS) for a in per_source.values())
    return {
        "max_age": max_age,
        "stale": stale,
        "per_source": per_source,
        "worst_source": worst_key,
        "worst_age": worst_age if worst_age >= 0 else None,
    }



# ---------- 国内可直连榜源解析器（尽力而为）----------
# 说明：OpenCompass / SuperCLUE / ModelScope 官网均为 JS 渲染 SPA，其数据 API
# 无法用简单 HTTP 稳定抓取（返回 SPA 兜底 HTML 或需鉴权）。下列解析器按「尽力而为」
# 实现——若抓到的是 SPA 兜底页（无 <table>）或解析失败，一律返回 None，
# 由多源池优雅降级到国内快照（cn_leaderboard_snapshot.json）或本地缓存。
# 一旦某源开放稳定 JSON API，只需在对应解析器里补全字段提取即可自动生效。

def fetch_opencompass_ranking(top_n: int = 15):
    """OpenCompass 司南 LLM 综合榜（国内可直连）。"""
    try:
        html = _http_get(OC_LLM_URL, timeout=40)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return None  # SPA 未渲染出数据，降级
        rows = tables[0].find_all("tr")
        out = []
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 5:
                continue
            try:
                rank = int(cells[0])
            except ValueError:
                continue
            model = cells[1]
            if not model:
                continue
            org = cells[2] if len(cells) > 2 else ""
            open_src = "开源" in (cells[3] if len(cells) > 3 else "")
            try:
                score = float(cells[4])
            except ValueError:
                score = None
            out.append(_enrich_cost({
                "rank": rank, "model": model, "org": org,
                "open_source": open_src, "score": score,
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ OpenCompass 抓取失败：{e}")
        return None


def fetch_superclue_ranking(top_n: int = 15):
    """SuperCLUE 中文通用能力总排行榜（国内可直连）。"""
    try:
        html = _http_get(SV_GENERAL_URL, timeout=40)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return None
        rows = tables[0].find_all("tr")
        out = []
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            try:
                rank = int(cells[0])
            except ValueError:
                continue
            model = cells[1]
            if not model:
                continue
            org = cells[2] if len(cells) > 2 else ""
            open_src = "开源" in (cells[3] if len(cells) > 3 else "")
            # SuperCLUE 总分通常在第 4~5 列，取首个可解析浮点
            score = None
            for c in cells[4:7]:
                try:
                    score = float(c)
                    break
                except ValueError:
                    continue
            out.append(_enrich_cost({
                "rank": rank, "model": model, "org": org,
                "open_source": open_src, "score": score,
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ SuperCLUE 抓取失败：{e}")
        return None


def fetch_modelscope_ranking(top_n: int = 15):
    """ModelScope 魔搭开源模型热度榜（国内可直连，尽力而为）。"""
    try:
        html = _http_get(MS_MODELS_URL, timeout=40)
        soup = BeautifulSoup(html, "html.parser")
        # 热度榜为 SPA，若页面无结构化模型链接则降级
        links = soup.select("a[href*='/models/']")
        if not links:
            return None
        seen, out = set(), []
        for a in links:
            name = a.get_text(strip=True)
            if not name or name in seen or len(name) > 60:
                continue
            seen.add(name)
            out.append(_enrich_cost({
                "rank": len(out) + 1, "model": name, "org": "",
                "open_source": True, "score": None,
            }))
            if len(out) >= top_n:
                break
        return out if out else None
    except Exception as e:
        print(f"  ⚠️ ModelScope 抓取失败：{e}")
        return None


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

    snapshot = datetime.now().strftime("%Y-%m-%d")
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


# 图表默认值（仅在未通过 CLI 提供真实数据时使用，且明确标注为估算）
DEFAULT_MARKET_LABELS = ['2020','2021','2022','2023','2024','2025','2026E','2027F','2028F']
# 2026-W32 版基准：Grand View Research 2026（CAGR 30.6%），单位十亿美元（$B）
DEFAULT_MARKET_DATA = [103, 134, 176, 229, 299, 391, 540, 705, 921]
DEFAULT_FUNDING_LABELS = ['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1','26Q2']
# 2026-W32 版基准：Crunchbase H1 2026（Q1 305 / Q2 205，合计 510）+ CB Insights 2023-2025 年度均摊，单位十亿美元（$B）
DEFAULT_FUNDING_DATA = [72.4, 72.4, 72.4, 72.4, 79.9, 79.9, 79.9, 79.9, 110.0, 110.0, 110.0, 110.0, 305.0, 205.0]
# 中国分轨（国内源）：单位亿元（RMB）。来源：中国信通院 / 中商产业研究院《2025-2030 中国人工智能产业现状调查》
DEFAULT_CN_MARKET_LABELS = ['2024', '2025', '2026E']
DEFAULT_CN_MARKET_DATA = [9188, 12000, 17000]
# 中国 AI 一级市场融资（亿元，RMB）。来源：新浪创投Plus 2025 全年 + IT桔子 2026H1（一级市场股权融资，标签「人工智能」）
# M2 #8：补 2026H1 当期点，消除「图说 3076 亿但图里没有」的脱节
DEFAULT_CN_FUNDING_LABELS = ['2024', '2025', '2026H1']
DEFAULT_CN_FUNDING_DATA = [391.51, 656.04, 3076.82]
# 中国 2026H1 AI 融资赛道结构（亿元，RMB）。来源：IT桔子 2026H1 细分赛道统计
# M2 #7：把散文里的细分做成结构图（替代纯文本）
DEFAULT_CN_STRUCTURE_LABELS = ['大模型', '具身智能', 'AIGC 应用', '基础层']
DEFAULT_CN_STRUCTURE_DATA = [1598, 906, 596, 725]
# 中国 AI 融资头部集中度（亿元，RMB）。来源：IT桔子 2026H1（合计 3076 亿）
# M2 #9：TOP3 大模型独揽 930 亿（30%）；TOP4–30 名约 770 亿；其余赛道约 1376 亿
DEFAULT_CN_CONCENTRATION_LABELS = ['TOP3 大模型', 'TOP4–30 名', '其他赛道']
DEFAULT_CN_CONCENTRATION_DATA = [930, 770, 1376]
# 市场数据来源（默认值）——国内源优先、全球源作海外机构静态快照引用。
# 关键：即使未传 --*-source，也用真实署名，避免回退成「示例/估算」自损式免责。
# 国内网络友好：中国分轨均来自国内可达机构（信通院/中商/IT桔子/新浪创投Plus）；
# 全球分轨标注「海外机构，静态快照引用」，明确是静态引用而非实时外网抓取。
DEFAULT_MARKET_SOURCE = "Grand View Research 2026（全球 AI 市场规模，CAGR 30.6%；海外机构，静态快照引用）"
DEFAULT_FUNDING_SOURCE = "Crunchbase / CB Insights（全球 AI 融资，H1 2026 口径；海外机构，静态快照引用）"
DEFAULT_CN_MARKET_SOURCE = "中国信通院 · 中商产业研究院《2025–2030 中国人工智能产业现状调查》（中国核心产业规模）"
DEFAULT_CN_FUNDING_SOURCE = "新浪创投Plus 2025 国内一级市场 AI 行业统计 + IT桔子 2026H1（一级市场股权融资，标签「人工智能」）"
# 兜底免责（已不再默认触发；表述改为诚实的「静态快照」而非「示例/估算」）
ESTIMATE_NOTE = "数据快照（静态，非实时）"

def build_charts(market_data=None, market_labels=None,
                 funding_data=None, funding_labels=None,
                 cn_market_data=None, cn_market_labels=None,
                 cn_funding_data=None, cn_funding_labels=None,
                 cn_structure_data=None, cn_structure_labels=None,
                 cn_concentration_data=None, cn_concentration_labels=None) -> str:
    """生成 Chart.js 初始化代码。未提供真实数据时回退到标注清晰的估算值。
    支持全球(Global)与中国(CN)双来源：每类含市场规模与融资趋势，各自独立来源。
    M2：中国融资补 2026H1 当期点，并新增「赛道结构」与「头部集中度」两张分析图。"""
    m_data = market_data or DEFAULT_MARKET_DATA
    m_labels = market_labels or DEFAULT_MARKET_LABELS
    f_data = funding_data or DEFAULT_FUNDING_DATA
    f_labels = funding_labels or DEFAULT_FUNDING_LABELS
    cm_data = cn_market_data or DEFAULT_CN_MARKET_DATA
    cm_labels = cn_market_labels or DEFAULT_CN_MARKET_LABELS
    cf_data = cn_funding_data or DEFAULT_CN_FUNDING_DATA
    cf_labels = cn_funding_labels or DEFAULT_CN_FUNDING_LABELS
    cs_data = cn_structure_data or DEFAULT_CN_STRUCTURE_DATA
    cs_labels = cn_structure_labels or DEFAULT_CN_STRUCTURE_LABELS
    cc_data = cn_concentration_data or DEFAULT_CN_CONCENTRATION_DATA
    cc_labels = cn_concentration_labels or DEFAULT_CN_CONCENTRATION_LABELS
    return f"""
// Market size chart（M3 #11：实测 vs CAGR 外推 诚实区分）
const marketCtx = document.getElementById('marketSizeChart').getContext('2d');
// 标签以 F 结尾视为「预测/外推」（如 2027F/2028F），浅色虚线感；其余为实测/机构估算，实色
const marketIsForecast = {json.dumps([(l.strip().endswith('F')) for l in m_labels])};
const marketBarColors = marketIsForecast.map(f => f ? 'rgba(37,99,235,0.32)' : 'rgba(37,99,235,0.7)');
const marketBarBorders = marketIsForecast.map(f => f ? 'rgba(37,99,235,0.6)' : 'rgba(37,99,235,1)');
marketChart = new Chart(marketCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(m_labels)},
    datasets: [{{
      label: '市场规模（$B，约 ¥7.2/$）',
      data: {json.dumps(m_data)},
      backgroundColor: marketBarColors,
      borderColor: marketBarBorders,
      borderWidth: 1, borderRadius: 6,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => {{
        const f = marketIsForecast[c.dataIndex];
        return '$'+c.parsed.y+'B' + (f ? '（CAGR 外推，非实测）' : '（实测/机构估算）');
      }} }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => '$'+v+'B' }} }}
    }}
  }}
}});

// Funding trend chart
const fundCtx = document.getElementById('fundingChart').getContext('2d');
fundingChart = new Chart(fundCtx, {{
  type: 'line',
  data: {{
    labels: {json.dumps(f_labels)},
    datasets: [{{
      label: '融资额（$B，约 ¥7.2/$）',
      data: {json.dumps(f_data)},
      borderColor: 'rgba(124,58,237,1)',
      backgroundColor: 'rgba(124,58,237,0.1)',
      fill: true, tension: 0.3,
      pointRadius: 4, pointBackgroundColor: 'rgba(124,58,237,1)',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => '$'+v+'B' }} }}
    }}
  }}
}});

// --- 中国 AI 核心产业规模（亿元，RMB）--- M3 #10：叠加 YoY% 折线
const cnMarketCtx = document.getElementById('cnMarketChart').getContext('2d');
// 由数据自动算同比：第 i 年 = data[i]/data[i-1]-1（首年无）
const cnYoY = {json.dumps([None] + [round((cm_data[i]/cm_data[i-1]-1)*100, 1) for i in range(1, len(cm_data))])};
cnMarketChart = new Chart(cnMarketCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(cm_labels)},
    datasets: [
      {{
        label: '核心产业规模（亿元，RMB）',
        data: {json.dumps(cm_data)},
        backgroundColor: 'rgba(220,38,38,0.7)',
        borderColor: 'rgba(220,38,38,1)',
        borderWidth: 1, borderRadius: 6,
        yAxisID: 'y',
        order: 2,
      }},
      {{
        label: '同比增速 YoY（%）',
        data: cnYoY,
        type: 'line',
        borderColor: 'rgba(22,163,74,1)',
        backgroundColor: 'rgba(22,163,74,1)',
        borderWidth: 2, tension: 0.3,
        pointRadius: 4, pointBackgroundColor: 'rgba(22,163,74,1)',
        yAxisID: 'y2',
        order: 1,
      }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: true, labels: {{ color: '#64748b', boxWidth: 12, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: c => {{
        if (c.dataset.yAxisID === 'y2') {{
          return c.parsed.y == null ? 'YoY：—' : 'YoY：+'+c.parsed.y+'%';
        }}
        return c.parsed.y+'亿（RMB）' + (cnYoY[c.dataIndex] != null ? '  同比 +'+cnYoY[c.dataIndex]+'%' : '');
      }} }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ position: 'left', grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y2: {{ position: 'right', grid: {{ display: false }}, ticks: {{ color: '#16a34a', callback: v => v+'%' }}, suggestedMin: 0 }}
    }}
  }}
}});

// --- 中国 AI 融资趋势（亿元，RMB，年度）---
const cnFundCtx = document.getElementById('cnFundingChart').getContext('2d');
cnFundingChart = new Chart(cnFundCtx, {{
  type: 'line',
  data: {{
    labels: {json.dumps(cf_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {json.dumps(cf_data)},
      borderColor: 'rgba(220,38,38,1)',
      backgroundColor: 'rgba(220,38,38,0.1)',
      fill: true, tension: 0.3,
      pointRadius: 4, pointBackgroundColor: 'rgba(220,38,38,1)',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }}
    }}
  }}
}});

// --- 中国 2026H1 AI 融资赛道结构（亿元，RMB）--- M2 #7
const cnStructCtx = document.getElementById('cnStructureChart').getContext('2d');
cnStructureChart = new Chart(cnStructCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(cs_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {json.dumps(cs_data)},
      backgroundColor: ['rgba(220,38,38,0.78)','rgba(234,88,12,0.78)','rgba(217,119,6,0.78)','rgba(100,116,139,0.78)'],
      borderRadius: 6,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => c.parsed.x + ' 亿（RMB）' }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
    }}
  }}
}});

// --- 中国 AI 融资头部集中度（亿元，RMB）--- M2 #9
const cnConcCtx = document.getElementById('cnConcentrationChart').getContext('2d');
cnConcentrationChart = new Chart(cnConcCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(cc_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {json.dumps(cc_data)},
      backgroundColor: ['rgba(220,38,38,0.85)','rgba(234,88,12,0.7)','rgba(148,163,184,0.7)'],
      borderRadius: 6,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => c.parsed.x + ' 亿（占 3076 亿的 ' + (c.parsed.x/3076.82*100).toFixed(1) + '%）' }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
    }}
  }}
}});
"""

# 页脚「数据来源」基础列表（不含任何内置第三方商业 API；用户自备的外部 API 才会动态追加）
BASE_SOURCES = [
    ("LMMarketCap", "https://lmmarketcap.com"),
    ("Gartner", "https://gartner.com"),
    ("IDC", "https://idc.com"),
    ("Statista", "https://statista.com"),
    ("Crunchbase", "https://crunchbase.com"),
    ("Stanford HAI", "https://hai.stanford.edu"),
]


# ============ M1：本周市场信号（新闻 ↔ 宏观图 桥接）============
# 从本周新闻抽取融资 / 并购 / IPO / 大额融资轮 / 模型发布事件，做成「关于本周」的桥接卡，
# 让市场板块不再只是静态宏观百科，而是真正呼应本周发生的事（计划第九章 M1 #4/#5/#6）。
SIGNAL_WEIGHTS = {
    "融资": [("融资", 3), ("募资", 3), ("轮融资", 3), ("融资轮", 3),
             ("funding", 3), ("raised", 3), ("raise", 2), ("round", 2)],
    "并购": [("收购", 3), ("并购", 3), ("acqui", 3), ("merger", 3)],
    "IPO": [("ipo", 3), ("招股", 3), ("敲钟", 3), ("上市", 2)],
    "估值": [("估值", 2), ("valuation", 2), ("独角兽", 3), ("unicorn", 3)],
    "模型发布": [("新模型", 2), ("模型发布", 2), ("发布模型", 2)],
}
# 模型发布类信号词（须与「模型」同现才计入，避免「发布报告」误触发）
MODEL_HINTS = ["发布", "推出", "开源", "上线"]
# 中国 / 国内机构或币种关键词 -> 桥接到中国融资图
CN_HINTS = ["中国", "国内", "人民币", "亿元", "阿里", "腾讯", "字节", "月之暗面", "kimi",
            "deepseek", "阶跃", "智谱", "百度", "商汤", "科大讯飞", "minimax", "百川",
            "零一万物", "蚂蚁", "华为", "美团", "京东"]
AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(亿美金|亿美元|亿人民币|亿元人民币|亿元|亿|万美金|万美元|万元|万|"
    r"trillion|billion|\bn\b|\$b|\$\s*\d[\d.,]*\s*(?:b|bn|k|m)?)", re.I)


def _extract_market_signals(news_items, top_n=5):
    """从本周新闻抽取资本 / 模型发布信号，按信号强度打分取 Top N。

    返回每条：title / url / source / amount / types[] / bridge_label / bridge_region / score。
    桥接目标：中国机构或币种 -> 中国融资趋势；并购/IPO -> 全球融资趋势；纯模型发布 -> 能力榜。
    """
    signals = []
    for it in news_items:
        title = it.get("title", "") or ""
        summary = it.get("summary", "") or ""
        text = f"{title} {summary}"
        low = text.lower()
        score = 0
        types = set()
        for t, kws in SIGNAL_WEIGHTS.items():
            for kw, w in kws:
                if kw.lower() in low:
                    score += w
                    types.add(t)
        # 模型发布须与「模型」同现
        if "模型" in low and any(h in low for h in MODEL_HINTS):
            score += 2
            types.add("模型发布")
        if score < 2:
            continue
        am = AMOUNT_RE.search(text)
        amount = am.group(0).strip() if am else ""
        is_cn = any(h.lower() in low for h in CN_HINTS)
        if "并购" in types or "IPO" in types:
            bridge = ("全球融资趋势", "🌍 全球")
        elif is_cn:
            bridge = ("中国融资趋势", "🇨🇳 中国")
        elif types == {"模型发布"}:
            bridge = ("大模型排行榜", "🏆 能力榜")
        else:
            bridge = ("全球融资趋势", "🌍 全球")
        signals.append({
            "title": title,
            "url": it.get("url", "") or "",
            "source": it.get("source", "") or "",
            "lang": it.get("lang", "") or "",
            "cn_summary": it.get("cn_summary", "") or "",
            "amount": amount,
            "types": sorted(types),
            "bridge_label": bridge[0],
            "bridge_region": bridge[1],
            "score": score + (it.get("score", 0) or 0) * 0.1,
        })
    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals[:top_n]


def _compute_weekly_stats(news_items, market_signals, leaderboard_data):
    """聚合「本周数字看板」：新闻总量 / 国内外比 / 模型相关+新发布 / 融资&发布事件 / 在榜模型数 / 必读 Top3。

    - news_items 已含 mustRead / score / category / lang / title / url
    - market_signals 来自 _extract_market_signals（types 标记融资/并购/IPO/模型发布）
    - 全部为派生指标，不引入新外部数据源；失败场景（空数据）兜底返回零值结构。
    """
    items = news_items or []
    sigs = market_signals or []
    total = len(items)
    zh = sum(1 for n in items if n.get("lang") == "zh")
    en = total - zh
    # 兼容 ai-models / model 两种历史 category 写法
    _MODEL_CATS = {"ai-models", "model"}
    model_news = [n for n in items if n.get("category") in _MODEL_CATS]
    _rel_re = re.compile(r"发布|推出|开源|上线|preview|launch|released|open.?source", re.I)
    releases = [
        n for n in model_news
        if _rel_re.search(f"{n.get('title','')} {n.get('summary','')}")
    ]
    fund_events = [
        s for s in sigs
        if s.get("types") and (
            set(s.get("types", [])) & {"融资", "并购", "IPO", "模型发布"}
            or s.get("amount")
        )
    ]
    must = sorted(
        [n for n in items if n.get("mustRead")],
        key=lambda x: x.get("score", 0) or 0,
        reverse=True,
    )[:3]
    lb_models = _collect_leaderboard_models(leaderboard_data)
    return {
        "total": total,
        "zh": zh,
        "en": en,
        "model_news": len(model_news),
        "releases": len(releases),
        "fund_events": len(fund_events),
        "lb_models": len(lb_models),
        "must_read": [
            {"title": (n.get("title") or "").strip(),
             "url": n.get("url") or "#"}
            for n in must
        ],
    }


def _lb_name_map(leaderboard):
    """构建 模型名/机构名(小写) -> (名次, 源) 映射，供资本↔能力联动标注。"""
    m = {}
    if not isinstance(leaderboard, dict):
        return m
    for grp in ("comprehensive", "open_source"):
        block = leaderboard.get(grp, {})
        if not isinstance(block, dict):
            continue
        for src, payload in block.items():
            rows = payload.get("rows", []) if isinstance(payload, dict) else []
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                for key in ("model", "name", "org", "organization"):
                    v = (r.get(key) or "").lower().strip()
                    if v and v not in m:
                        m[v] = (i + 1, src)
    return m


def _render_market_signals_html(signals, lb_map):
    """服务端预渲染「本周市场信号」区块（即使 JS 不执行也可见）。"""
    if not signals:
        return ('<p class="ms-empty">本周新闻中未检出重大融资 / 并购 / IPO / 模型发布事件'
                '——市场板块维持宏观背景视角。</p>')
    cards = []
    for s in signals:
        types_html = " ".join(f'<span class="ms-type t-{t}">{t}</span>' for t in s["types"])
        amt = f'<span class="ms-amount">{s["amount"]}</span>' if s["amount"] else ""
        # 资本↔能力：检测标题是否含上榜模型/机构名
        title_low = s["title"].lower()
        on_lb = None
        for nm, (rk, src) in lb_map.items():
            if nm and nm in title_low:
                on_lb = (rk, src)
                break
        if on_lb:
            cap = f'<span class="ms-cap">↔ 能力榜 #{on_lb[0]}（{on_lb[1]}）</span>'
        else:
            cap = '<span class="ms-cap ms-cap-off">↔ 能力榜：未上榜</span>'
        url = s["url"] or "#"
        cards.append(
            f'<div class="ms-card">'
            f'<div class="ms-top">{types_html}{amt}</div>'
            f'<a class="ms-title" href="{url}" target="_blank" rel="noopener">{s["title"]}</a>'
            f'<div class="ms-meta"><span class="ms-bridge">{s["bridge_region"]} ↔ {s["bridge_label"]}</span>'
            f'{cap}<span class="ms-src">{s["source"]}</span></div>'
            f'</div>')
    head = (f'<p class="ms-head">从本周 <b>{len(signals)}</b> 条资本 / 模型发布信号看，'
            f'钱与能力正往这些方向集中（桥接下方宏观图）：</p>')
    return head + '<div class="ms-grid">' + "".join(cards) + '</div>'


# ============ 「AI 行业趋势洞察」×「关于本周」合作（计划第九章 用户议题）============
# 原本「趋势洞察」面板是模板写死的宏观百科，与本周新闻零联动。
# 做法：把 4 条宏观洞察上提到 Python，按周从本周信号 / 新闻抽「本周印证」证据行，
# 让每条宏观趋势都挂着本周真实发生的事；同时给 M1 信号卡加「印证趋势」标签，双向桥接。
TREND_INSIGHTS = [
    {
        "theme": "规模红利",
        "ico": "🌍→🇨🇳",
        "head": "规模：全球高速扩张，中国增速更快",
        "body": "全球 AI 市场 CAGR <b>30.6%</b>（Grand View Research），约每 2.5 年翻番；中国核心产业规模 "
                "<b>9188亿→1.2万亿→1.7万亿</b>（2024→2026E，中国信通院），三年近乎翻倍。",
        "tag": "PM / 开发者：国内仍是增量红利，优先盯本土落地场景",
        "tag_cls": "tag-pm",
        "keys": ["规模", "市场", "增速", "扩张", "信通院", "万亿", "增长", "产业"],
    },
    {
        "theme": "钱去哪了",
        "ico": "💰",
        "head": "钱去哪了：极端头部集中，但结构在变",
        "body": "全球 2026H1 融资 <b>$510B</b> 已超 2025 全年；中国 2026H1 AI 融资 <b>3076 亿</b>"
                "（占一级市场 48.6%），但 TOP3 大模型（DeepSeek/阶跃/Kimi）独揽 930 亿（30%），"
                "TOP30 超 1700 亿（过半）。",
        "tag": "开发者：通用大模型已是巨头决赛圈，别硬刚 base model",
        "tag_cls": "tag-dev",
        "keys": ["融资", "并购", "头部", "集中", "独角兽", "估值", "轮", "募资", "收购", "IPO"],
    },
    {
        "theme": "具身智能",
        "ico": "🤖",
        "head": "机会窗口：具身智能成第二增长极",
        "body": "中国 2026H1 具身智能（人形机器人）融资 <b>906 亿</b>（29.5%），“七武士”单家超 20 亿；"
                "世界模型成早期第一共识（6 家早期合计 97 亿）；AIGC 应用 596 亿（图片/视频生成最成熟）。",
        "tag": "开发者：现实机会在具身智能、AIGC 应用层、垂直行业 agent",
        "tag_cls": "tag-dev",
        "keys": ["具身", "机器人", "人形", "AIGC", "应用", "agent", "世界模型", "视频生成", "智能体"],
    },
    {
        "theme": "行动建议",
        "ico": "🎯",
        "head": "给三类读者的行动建议",
        "body": "<b>独立开发者</b>：用开源/免费 API（Hy3、Qwen、DeepSeek）做垂直场景应用。<br>"
                "<b>产品经理</b>：需求在“AI+传统行业”（制造/医疗/金融），用低成本模型验证 PMF。<br>"
                "<b>自媒体</b>：具身智能 + 应用层爆发是 2026 最强叙事，原始口径可向 IT桔子/信通院取。",
        "tag": "媒体：具身智能元年 / 应用层爆发 = 高传播选题",
        "tag_cls": "tag-media",
        "keys": [],  # 行动建议不挂本周印证（它是结论，不是可印证的事实趋势）
    },
]


def _match_insight_evidence(theme_keys, signals, news_items, top_k=2):
    """从本周信号 / 新闻中，为本条宏观趋势抽取「本周印证」证据。

    优先用 M1 信号（已带金额 / 链接），其次用本周新闻标题；按与主题词的重合度打分取 Top-K。
    返回 [{title, url, amount}]。
    """
    if not theme_keys:
        return []
    cands = []
    # 信号优先（已有金额与链接）
    for s in (signals or []):
        t = (s.get("title", "") or "").lower()
        hit = sum(1 for k in theme_keys if k.lower() in t)
        if hit:
            cands.append((hit, s.get("title", ""), s.get("url", "") or "", s.get("amount", "")))
    # 普通新闻补充（仅标题，无金额）
    for it in (news_items or []):
        t = (it.get("title", "") or "").lower()
        hit = sum(1 for k in theme_keys if k.lower() in t)
        if hit:
            cands.append((hit, it.get("title", ""), it.get("url", "") or "", ""))
    # 去重（按标题），按命中数降序
    seen = set()
    uniq = []
    for hit, title, url, amt in sorted(cands, key=lambda x: x[0], reverse=True):
        if not title or title in seen:
            continue
        seen.add(title)
        uniq.append({"title": title, "url": url, "amount": amt})
        if len(uniq) >= top_k:
            break
    return uniq


def _signal_theme(signal):
    """给 M1 信号卡标注它「印证」了哪条宏观趋势（双向桥接）。无匹配返回空串。"""
    t = (signal.get("title", "") or "").lower()
    best, best_hit = "", 0
    for th in TREND_INSIGHTS:
        if not th["keys"]:
            continue
        hit = sum(1 for k in th["keys"] if k.lower() in t)
        if hit > best_hit:
            best_hit, best = hit, th["theme"]
    # 标题无中文关键词命中时，回退到信号类型（融资/并购/IPO → 钱去哪了）
    if best_hit == 0:
        types = signal.get("types", []) or []
        if "并购" in types or "IPO" in types or "融资" in types:
            best = "钱去哪了"
    return best


def _render_trend_insights_html(signals, news_items):
    """服务端预渲染「AI 行业趋势洞察」面板（含本周印证行），注入 [TREND_INSIGHTS] 占位符。"""
    items = []
    for th in TREND_INSIGHTS:
        ev = _match_insight_evidence(th["keys"], signals, news_items)
        if ev:
            ev_parts = []
            for e in ev:
                amt = f' <b>{e["amount"]}</b>' if e["amount"] else ""
                if e["url"]:
                    ev_parts.append(
                        f'<a href="{e["url"]}" target="_blank" rel="noopener">{e["title"]}</a>{amt}')
                else:
                    ev_parts.append(f'{e["title"]}{amt}')
            ev_html = (f'<div class="insight-evidence">📌 本周印证：'
                       f'{"；".join(ev_parts)}</div>')
        else:
            ev_html = ""
        items.append(
            f'<div class="insight-item">'
            f'<div class="insight-head"><span class="insight-ico">{th["ico"]}</span>'
            f'<b>{th["head"]}</b></div>'
            f'<p>{th["body"]}</p>'
            f'{ev_html}'
            f'<span class="insight-tag {th["tag_cls"]}">{th["tag"]}</span>'
            f'</div>')
    return '<div class="insight-grid">' + "".join(items) + '</div>'


def _render_market_signals_html_with_theme(signals, lb_map):
    """M1 信号卡渲染（带「印证趋势」标签，与趋势洞察面板双向桥接）。"""
    if not signals:
        return ('<p class="ms-empty">本周新闻中未检出重大融资 / 并购 / IPO / 模型发布事件'
                '——市场板块维持宏观背景视角。</p>')
    cards = []
    for s in signals:
        types_html = " ".join(f'<span class="ms-type t-{t}">{t}</span>' for t in s["types"])
        amt = f'<span class="ms-amount">{s["amount"]}</span>' if s["amount"] else ""
        theme = _signal_theme(s)
        theme_html = (f'<span class="ms-theme">印证趋势：{theme}</span>'
                      if theme else '<span class="ms-theme ms-theme-off">印证趋势：—</span>')
        title_low = s["title"].lower()
        on_lb = None
        for nm, (rk, src) in lb_map.items():
            if nm and nm in title_low:
                on_lb = (rk, src)
                break
        if on_lb:
            cap = f'<span class="ms-cap">↔ 能力榜 #{on_lb[0]}（{on_lb[1]}）</span>'
        else:
            cap = '<span class="ms-cap ms-cap-off">↔ 能力榜：未上榜</span>'
        url = s["url"] or "#"
        # 英文信号卡：补中文注解（与新闻卡一致，方便英文不好的中文读者）
        cn_html = ""
        if s.get("lang") == "en" and s.get("cn_summary"):
            cn_html = (f'<div class="ms-cn"><span class="cn-badge">中文</span> '
                       f'{html.escape(s["cn_summary"])}</div>')
        cards.append(
            f'<div class="ms-card">'
            f'<div class="ms-top">{types_html}{amt}</div>'
            f'<a class="ms-title" href="{url}" target="_blank" rel="noopener">{html.escape(s["title"])}</a>'
            f'{cn_html}'
            f'<div class="ms-meta"><span class="ms-bridge">{s["bridge_region"]} ↔ {s["bridge_label"]}</span>'
            f'{cap}{theme_html}<span class="ms-src">{s["source"]}</span></div>'
            f'</div>')
    head = (f'<p class="ms-head">从本周 <b>{len(signals)}</b> 条资本 / 模型发布信号看，'
            f'钱与能力正往这些方向集中（桥接下方宏观图）：</p>')
    return head + '<div class="ms-grid">' + "".join(cards) + '</div>'


def generate(api_data: dict, ranking: list = None, output_path: str = None,
             date_range: str = None, ranking_source: str = "unavailable",
             market_data: list = None, market_labels: list = None,
             funding_data: list = None, funding_labels: list = None,
             market_source: str = None, funding_source: str = None,
             cn_market_data: list = None, cn_market_labels: list = None,
             cn_funding_data: list = None, cn_funding_labels: list = None,
             cn_market_source: str = None, cn_funding_source: str = None,
             ranking_criteria: str = None,
             external_source: tuple = None,
             insights: list = None, lead: str = None,
             keywords: list = None,
             keyword_search_base: str = "https://www.baidu.com/s?wd=",
             audience_summary: str = None,
             keyword_search_sources: str = None,
             leaderboard_data: dict = None,
             model_profiles: dict = None,
             report_date: str = None,
             data_snapshot: str = None,
             translate_en: bool = False,
             translate_model: str = "qwen2.5:7b",
             translate_workers: int = 6,
             translate_timeout: int = 25) -> str:
    """生成完整的新闻网站 HTML。

    Args:
        api_data: 新闻 JSON（RSS 兼容格式，含 items[]）
        ranking: 排行榜数据列表；None 表示无实时数据（显示"暂无排名数据"）
        output_path: 输出文件路径
        date_range: 日期范围标签
        ranking_source: 排行榜来源标签（live/json/default/unavailable）
        market_data/labels, funding_data/labels: 图表数据，未提供则回退标注清晰的估算值
        market_source, funding_source: 图表数据来源说明（用于页脚/注释）
        ranking_criteria: 排行榜排名标准说明（用于排行榜标题下方）
        external_source: 用户自备外部 API 的来源 (name, url)，用于页脚署名与链接
        insights: 「本周看点」编辑洞察列表（每项含 title/analysis/insight/related/kicker）
        lead: 「本周看点」顶部导语一句话（电梯演讲）
        keywords: 「本周看点」顶部关键词列表（每项 {term, note}），引导读者深挖
        keyword_search_base: 关键词点击后跳转的网页搜索基址（搜索词 = 「词语 AI 行业」）
        audience_summary: 面向受众的一句话结论（JSON 字符串 {开发者, PM, 媱}），渲染在关键词区上方
        keyword_search_sources: 可切换的搜索源 JSON 字符串 {name:url}，供关键词联动筛选
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"模板不存在：{TEMPLATE_PATH}")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Chart.js 内联:优先把本地 chart.umd.min.js 内联进 HTML,实现真正单文件;
    # 缺失时回退到 CDN(仅兜底,正常发布总是内联)。
    chart_lib_path = SKILL_DIR / "assets" / "chart.umd.min.js"
    if chart_lib_path.exists():
        chart_lib = chart_lib_path.read_text(encoding="utf-8")
        template = template.replace("[CHARTJS_LIB_PLACEHOLDER]", f"<script>{chart_lib}</script>")
    else:
        template = template.replace(
            "[CHARTJS_LIB_PLACEHOLDER]",
            '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>')

    # 英文报道中文总结（本地 Ollama，可选开启；best-effort，不阻断主流程）
    if translate_en:
        try:
            n_tr = translate_en_summaries(
                api_data.get("items", []), enabled=True,
                model=translate_model, max_workers=translate_workers, timeout=translate_timeout)
            if n_tr:
                print(f"🌐 英文报道中文总结：本地 Ollama 翻译 {n_tr} 条（模型 {translate_model}）")
        except Exception as e:
            print(f"  ⚠️ 英文翻译跳过（Ollama 不可用或异常）：{e}")

    # 格式化新闻数据（含信源/摘要归一化 + cn_summary 透传）
    news_items = format_news_items(api_data)
    # C0：重要度评分 + 🔥必读标记（仅排序/标记，不篡改事实字段）
    _score_news(news_items, report_date=report_date, top_n=MUSTREAD_TOP_N)
    # M1：从本周新闻抽取「资本/模型发布」信号，做成新闻↔宏观图桥接卡（服务端预渲染）
    market_signals = _extract_market_signals(news_items, top_n=5)
    # C2#8：聚合「本周数字看板」指标（总量/国内外比/模型发布/融资事件/在榜模型数/必读Top3）
    weekly_stats = _compute_weekly_stats(news_items, market_signals, leaderboard_data)

    # 排行榜数据（双榜：综合 + 开源）。None -> 空结构，模板渲染"暂无实时数据"
    final_leaderboard = leaderboard_data if leaderboard_data is not None else {
        "comprehensive": {"lmarena": {"rows": []}, "aa": {"rows": []}},
        "open_source": {"hf": {"rows": []}},
    }
    if model_profiles:
        final_leaderboard["model_profiles"] = model_profiles
        # 以资料卡为准：用卡片权威值覆盖排行榜行的描述性字段（成本/上下文/许可证等）
        _apply_profile_as_truth(final_leaderboard, model_profiles)
    # M1：构建 模型名/机构名 -> 名次 映射，供「资本↔能力」联动标注
    _lb_map = _lb_name_map(final_leaderboard)

    # C1#5：排行榜快照时效标注——超龄即告警，并把时效信息注入 meta 供模板渲染
    _lb_fresh = _leaderboard_freshness(final_leaderboard, report_date)
    final_leaderboard.setdefault("meta", {})
    final_leaderboard["meta"]["snapshot_max_age"] = _lb_fresh["max_age"]
    final_leaderboard["meta"]["snapshot_stale"] = _lb_fresh["stale"]
    final_leaderboard["meta"]["snapshot_per_source"] = _lb_fresh["per_source"]
    if _lb_fresh["stale"]:
        print(f"  ⚠️ 排行榜快照时效告警：最新快照距本期 {_lb_fresh['worst_age']} 天"
              f"（阈值 {LEADERBOARD_STALE_DAYS} 天），部分榜单为「非本周抓取」——"
              f"建议刷新 cn_leaderboard_snapshot.json 或加 --proxy 直连刷新。")
    else:
        print(f"  ✅ 排行榜快照时效 OK（最大龄 {_lb_fresh['max_age']} 天）。")

    # 图表代码
    chart_code = build_charts(market_data, market_labels, funding_data, funding_labels,
                             cn_market_data, cn_market_labels, cn_funding_data, cn_funding_labels)

    # M0：市场数据来源默认用真实署名（国内源优先），不再回退到「示例/估算」自损式免责
    market_source = market_source or DEFAULT_MARKET_SOURCE
    funding_source = funding_source or DEFAULT_FUNDING_SOURCE
    cn_market_source = cn_market_source or DEFAULT_CN_MARKET_SOURCE
    cn_funding_source = cn_funding_source or DEFAULT_CN_FUNDING_SOURCE

    # 数据充分性提示：真实数据点过少时,来源注释追加「数据不足」,避免把少量点伪装成趋势
    _insuff = "（数据不足，仅展示已核实区间）"
    if market_data is not None and len(market_data) < 3:
        market_source = (market_source or "") + _insuff
    if funding_data is not None and len(funding_data) < 3:
        funding_source = (funding_source or "") + _insuff
    if cn_market_data is not None and len(cn_market_data) < 2:
        cn_market_source = (cn_market_source or "") + _insuff
    if cn_funding_data is not None and len(cn_funding_data) < 2:
        cn_funding_source = (cn_funding_source or "") + _insuff

    # 替换占位符
    template = template.replace("[NEWS_DATA_PLACEHOLDER]",
                                json.dumps(news_items, ensure_ascii=False, indent=2))
    template = template.replace("[LEADERBOARD_DATA_PLACEHOLDER]",
                                json.dumps(final_leaderboard, ensure_ascii=False))
    template = template.replace("[CHART_DATA_PLACEHOLDER]", chart_code)

    if not date_range:
        today = (_parse_date_arg(report_date) if report_date
                 else datetime.now())
        week_ago = today - timedelta(days=7)
        date_range = f"{week_ago.year}/{week_ago.month}/{week_ago.day}–{today.month}/{today.day}"
    template = template.replace("[DATE_RANGE]", date_range)
    # 图表来源：提供真实来源则用之，否则标注为估算（全球 + 中国双来源）
    template = template.replace("[MARKET_SOURCE]", market_source)
    template = template.replace("[FUNDING_SOURCE]", funding_source)
    template = template.replace("[CN_MARKET_SOURCE]", cn_market_source)
    template = template.replace("[CN_FUNDING_SOURCE]", cn_funding_source)

    # 市场数据来源汇总（章节标题下 + 页脚）：国内 + 国外双来源并列
    _srcs = [s for s in [market_source, funding_source, cn_market_source, cn_funding_source] if s]
    market_summary = "；".join(_srcs) if _srcs else "数据快照（静态，非实时）"
    template = template.replace("[MARKET_SOURCE_SUMMARY]", market_summary)
    if _srcs:
        market_footer = "市场数据来源（国内+国外）：" + "；".join(_srcs)
    else:
        market_footer = "市场数据来源（静态快照，非实时）"
    template = template.replace("[MARKET_SOURCE_FOOTER]", market_footer)

    # 市场数据快照日期（让读者明确这是静态快照而非实时数据）
    if not data_snapshot:
        data_snapshot = (_parse_date_arg(report_date).strftime("%Y-%m-%d")
                         if report_date else datetime.now().strftime("%Y-%m-%d"))
    template = template.replace("[DATA_SNAPSHOT]", data_snapshot)

    # 页脚数据来源：基础列表 + 用户自备的外部 API（仅当用户显式提供）
    sources = list(BASE_SOURCES)
    news_extra = ""
    if external_source and external_source[0]:
        ext_name, ext_url = external_source[0], (external_source[1] or "")
        if ext_url:
            sources.append((ext_name, ext_url))
            news_extra = f' 与 <a href="{ext_url}" target="_blank">{ext_name}</a>'
        else:
            news_extra = f' 与 {ext_name}'
    all_sources_html = '、'.join(
        f'<a href="{u}" target="_blank">{n}</a>' for n, u in sources
    )
    template = template.replace("[ALL_SOURCES]", all_sources_html)
    template = template.replace("[NEWS_SOURCE_EXTRA]", news_extra)
    template = template.replace("[GEN_DATE]", datetime.now().isoformat(timespec="minutes"))  # P0#16

    # 在排行榜标题旁标注数据来源
    source_label = {
        "live": "LMMarketCap 实时数据",
        "json": "自定义数据",
        "default": "默认数据（可能过时）",
        "unavailable": "暂无实时数据",
    }.get(ranking_source, "暂无实时数据")
    template = template.replace("[RANKING_SOURCE]", source_label)

    # 本周看点（编辑洞察 + 关键词）：注入 JSON；若无 curated 数据则自动派生基线，
    # 确保头版核心区永不静默消失（curated --insights-json 仍优先覆盖）。
    _insights = insights
    if not _insights:
        _insights = _auto_insights(api_data)
        if _insights:
            print(f"📌 未传入 --insights-json，已自动派生 {len(_insights)} 条基线看点")
    # C1#6：看点去注水——过滤纯日报聚合类（如「8点1氪」），无论人工或自动路径
    if _insights:
        before = len(_insights)
        _insights = [it for it in _insights if not _is_daily_digest(it)]
        dropped = before - len(_insights)
        if dropped:
            print(f"  💧 看点去注水：已剔除 {dropped} 条纯日报聚合类看点")
    _lead = lead or _auto_lead(news_items, total_news=len(news_items), insights=_insights)
    # 关键词：优先用 curated；规范化确保每条都带分类标签(tag)，否则从本周新闻自动派生，
    # 保证「本周关键词」区永不空、且每条必有彩色分类标签。
    _kw = _normalize_keywords(keywords)
    if not _kw:
        _kw = _auto_keywords(api_data)
        if _kw:
            print(f"🏷️ 未传入有效关键词，已自动派生 {len(_kw)} 个带标签关键词")
    template = template.replace("[INSIGHTS_KEYWORDS_PLACEHOLDER]",
                                json.dumps(_kw or [], ensure_ascii=False))
    template = template.replace("[INSIGHTS_DATA_PLACEHOLDER]",
                                json.dumps(_insights or [], ensure_ascii=False))
    # C2#8：本周数字看板（JSON 注入，模板 JS 渲染；服务端兜底也写入静态 HTML）
    template = template.replace("[WEEKLY_STATS_PLACEHOLDER]",
                                json.dumps(weekly_stats or {}, ensure_ascii=False))
    template = template.replace("[LEAD]", _lead or "")
    # 受众结论：未传入则回退内置默认三段（开发者/PM/自媒体），确保「给本周的你」始终出现
    template = template.replace("AUDIENCE_SUMMARY_PLACEHOLDER",
                                json.dumps(audience_summary or _DEFAULT_AUDIENCE_SUMMARY, ensure_ascii=False))
    template = template.replace("KEYWORD_SEARCH_SOURCES_PLACEHOLDER",
                                keyword_search_sources or '{"baidu":"https://www.baidu.com/s?wd=","google":"https://www.google.com/search?q=","arxiv":"https://arxiv.org/search/?query="}')
    # 关键词网页搜索基址（默认百度；搜索词 = 「词语 AI 行业」）
    template = template.replace("[KEYWORD_SEARCH_BASE]", keyword_search_base)

    # 服务端静态预渲染：把「给本周的你」受众卡 + 关键词（含分类标签）直接写进 HTML，
    # 即使客户端 JS 不执行/出错，这两块也一定出现在页面里（不再依赖 renderInsights）。
    _aud = audience_summary or _DEFAULT_AUDIENCE_SUMMARY
    _aud_html = _render_audience_chips_html(_aud)
    _kw_html = _render_keyword_chips_html(_kw, search_sources=json.loads(keyword_search_sources) if keyword_search_sources else None, search_base=keyword_search_base)
    template = template.replace(
        '<div class="insights-audience-chips" id="insightsAudienceChips"><!-- JS generated --></div>',
        f'<div class="insights-audience-chips" id="insightsAudienceChips">{_aud_html}</div>' if _aud_html else
        '<div class="insights-audience-chips" id="insightsAudienceChips"></div>')
    template = template.replace(
        '<div class="insights-keywords-chips" id="insightsKeywordsChips"><!-- JS generated --></div>',
        f'<div class="insights-keywords-chips" id="insightsKeywordsChips">{_kw_html}</div>' if _kw_html else
        '<div class="insights-keywords-chips" id="insightsKeywordsChips"></div>')
    # M1：本周市场信号区块（服务端预渲染，与受众/关键词卡同样不依赖 JS）
    # 新版带「印证趋势」标签，与下方「AI 行业趋势洞察」面板双向桥接
    _ms_html = _render_market_signals_html_with_theme(market_signals, _lb_map)
    template = template.replace(
        '<div class="market-signals" id="marketSignals"><!-- JS generated --></div>',
        f'<div class="market-signals" id="marketSignals">{_ms_html}</div>')
    # 「AI 行业趋势洞察」×「关于本周」合作：宏观趋势面板按周挂「本周印证」证据行
    _ti_html = _render_trend_insights_html(market_signals, news_items)
    template = template.replace("[TREND_INSIGHTS]", _ti_html)
    # 受众块默认改可见（JS 仍会按数据二次管理 display）；无受众数据时回退隐藏
    if _aud_html:
        template = template.replace(
            '<div class="insights-audience" id="insightsAudience" style="display:none;">',
            '<div class="insights-audience" id="insightsAudience">')
    else:
        template = template.replace(
            '<div class="insights-audience" id="insightsAudience" style="display:none;">',
            '<div class="insights-audience" id="insightsAudience" style="display:none;">')

    if output_path:
        Path(output_path).write_text(template, encoding="utf-8")

    return template


def _validate_insights(data) -> list:
    """校验 insights.json 结构,返回错误字符串列表(空=通过)。"""
    errors = []
    if not isinstance(data, (dict, list)):
        return ["根节点必须是对象或数组"]
    keywords = data.get("keywords", []) if isinstance(data, dict) else []
    insights = data.get("insights", []) if isinstance(data, dict) else data
    if not isinstance(keywords, list):
        errors.append("keywords 必须是数组")
    for i, kw in enumerate(keywords):
        if not isinstance(kw, dict) or not kw.get("term") or not kw.get("note"):
            errors.append(f"keywords[{i}] 缺少 term 或 note")
            continue
        # note 允许字符串或「受众 -> 文案」对象；对象内值必须是字符串
        note = kw.get("note")
        if isinstance(note, dict):
            bad = [k for k, v in note.items() if not isinstance(v, str) or not v.strip()]
            if bad:
                errors.append(f"keywords[{i}].note 的受众项内容为空或非字符串: {', '.join(bad)}")
        elif not isinstance(note, str):
            errors.append(f"keywords[{i}].note 必须是字符串或「受众->文案」对象")
    # audience_summary（可选）：必须是「受众 -> 一句话结论」的对象
    if isinstance(data, dict) and data.get("audience_summary") is not None:
        aud = data.get("audience_summary")
        if not isinstance(aud, dict):
            errors.append("audience_summary 必须是对象（形如 {\"开发者\": \"...\"}）")
        else:
            bad = [k for k, v in aud.items() if not isinstance(v, str) or not v.strip()]
            if bad:
                errors.append(f"audience_summary 的受众项内容为空或非字符串: {', '.join(bad)}")
    if not isinstance(insights, list):
        errors.append("insights 必须是数组")
    else:
        req = ["kicker", "title", "analysis", "insight"]
        for i, ins in enumerate(insights):
            if not isinstance(ins, dict):
                errors.append(f"insights[{i}] 不是对象")
                continue
            missing = [k for k in req if not ins.get(k)]
            if missing:
                errors.append(f"insights[{i}] 缺少字段: {', '.join(missing)}")
    return errors


# ── 「本周看点」自动兜底（避免头版核心区静默消失）─────────────────
# 当调用方未传 --insights-json / --lead 时，从本周新闻自动派生基线看点，
# 保证「本周看点」始终有内容；人工 curated 数据仍优先覆盖。
_AUTO_KICKERS = {
    "ai-models": "模型",
    "ai-products": "产品",
    "industry": "行业",
    "paper": "论文",
    "tip": "技巧",
}
# 重要性信号词（命中越多权重越高）
_AUTO_SIGNALS = [
    ("发布", 3), ("开源", 3), ("融资", 3), ("收购", 3), ("登顶", 3), ("夺冠", 3),
    ("超越", 2), ("首发", 3), ("重磅", 3), ("推出", 2), ("基座", 2), ("模型", 1),
    ("agent", 2), ("智能体", 2), ("端侧", 2), ("具身", 2), ("突破", 3), ("论文", 2),
    ("夺冠", 3), ("刷新", 2), ("SOTA", 3), ("开源版", 3), ("上线", 2), ("封测", 2),
]


# 纯日报聚合类信源/标题特征（C1#6：看点去注水，排除这些条目作为「看点」）
_DAILY_DIGEST_MARKERS = ["8点1氪", "早讯", "早报", "日报", "每日速览", "今日速览",
                         "晚报", "晨读", "周报", "daily brief", "早知道", "三分钟速览",
                         "一氪早讯", "科技早报"]


def _is_daily_digest(item: dict) -> bool:
    """判断一条新闻是否为纯日报聚合类（不宜作为编辑「看点」）。"""
    text = f"{item.get('title', '')} {item.get('source', '')}".lower()
    return any(m.lower() in text for m in _DAILY_DIGEST_MARKERS)


def _find_related(seed: dict, items: list, exclude_titles: set, max_n: int = 2) -> list:
    """为一条看点补充 2 条相关新闻：优先同分类或共享信号词，排除日报聚合类与自身。

    返回 [{title, url, source}]，用于「同源深挖 + 异源佐证」的扩链。
    """
    seed_text = (seed.get("title", "") + " " + seed.get("summary", "")).lower()
    seed_cat = seed.get("category", "")
    scored = []
    for it in items:
        t = (it.get("title", "") or "").strip()
        if not t or t in exclude_titles:
            continue
        if _is_daily_digest(it):
            continue
        it_text = (it.get("title", "") + " " + it.get("summary", "")).lower()
        if it_text == seed_text:
            continue
        w = 0
        if it.get("category") == seed_cat:
            w += 2
        w += sum(1 for sig, _ in _AUTO_SIGNALS
                 if sig.lower() in it_text and sig.lower() in seed_text)
        if w <= 0:
            continue
        scored.append((w, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, it in scored[:max_n]:
        url = it.get("url", "")
        if not url:
            continue
        out.append({"title": (it.get("title", "") or "").strip(),
                    "url": url,
                    "source": it.get("source", "")})
    return out


def _auto_insights(api_data: dict, top_n: int = 6) -> list:
    """从新闻 JSON 自动派生基线「本周看点」列表。无网络依赖。"""
    try:
        items = format_news_items(api_data)
    except Exception:
        items = []
    if not items:
        return []

    scored = []
    for it in items:
        text = f"{it.get('title', '')} {it.get('summary', '')}".lower()
        score = float(it.get("score", 0) or 0)
        for sig, w in _AUTO_SIGNALS:
            if sig.lower() in text:
                score += w
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    seen_titles = set()
    for score, it in scored:
        if len(out) >= top_n:
            break
        title = (it.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        # C1#6：排除纯日报聚合类作为「看点」（去注水）
        if _is_daily_digest(it):
            continue
        seen_titles.add(title)
        cat = it.get("category", "industry")
        kicker = _AUTO_KICKERS.get(cat, "行业")
        summary = (it.get("summary") or "").strip()
        if len(summary) > 160:
            summary = summary[:160] + "…"
        # 基于类别给一句轻量编辑提示（明确为自动摘要，非人工深度洞察；即「对读者意味着什么」）
        hint = {
            "ai-models": "模型侧变动，往往直接决定你选型与成本。",
            "ai-products": "产品化信号，值得关注能否为你所用。",
            "industry": "行业格局信号，影响机会窗口。",
            "paper": "新方法可能半年内落地为工具链。",
            "tip": "可直接复用的实战经验。",
        }.get(cat, "本周值得追踪的动态。")
        # C1#6：扩链——原文 + 2 条相关（同分类/共享信号词，异源佐证）
        related_url = it.get("url", "")
        related = []
        if related_url:
            related.append({"title": f"原文：{it.get('source', '来源')}", "url": related_url})
        related += _find_related(it, items, seen_titles | {title}, max_n=2)
        out.append({
            "kicker": kicker,
            "title": title,
            "analysis": summary or title,
            "insight": f"（自动摘要）{hint}",
            "related": related,
        })
    return out


# 编辑视角主线主题（用于「本周看点」导语合成：从全量新闻聚合真实信号，而非仅数分类标签）
_EDITORIAL_THEMES = [
    ("模型军备竞赛", ["万亿", "参数", "大模型", "基座模型", "旗舰", "moe", "gpt", "claude",
                     "gemini", "kimi", "deepseek", "qwen", "智谱", "glm", "混元", "文心",
                     "豆包", "llama", "mistral"]),
    ("产品化与 Agent 落地", ["agent", "智能体", "copilot", "助手", "办公", "应用", "端侧",
                          "插件", "app", "工作流", "落地", "套件"]),
    ("开源生态", ["开源", "开源版", "权重", "开放权重", "llama", "mistral"]),
    ("资本与并购", ["融资", "估值", "亿美元", "收购", "并购", "ipo", "募资", "投资", "独角兽"]),
    ("算力与芯片", ["芯片", "gpu", "算力", "hbm", "英伟达", "nvidia", "自研芯片",
                  "数据中心", "云服务", "云厂商"]),
    ("多模态与具身", ["多模态", "视频生成", "图像", "语音", "具身", "机器人", "世界模型"]),
    ("监管与政策", ["监管", "政策", "合规", "出口管制", "反垄断", "立法", "备案", "安全审查"]),
]


def _lead_truncate(title: str, max_len: int = 20) -> str:
    """把证据标题压到适合导语的长度，超出加省略号。"""
    t = (title or "").strip()
    if len(t) <= max_len:
        return t
    return t[:max_len] + "…"


def _week_tone(top_theme_names: list) -> str:
    """基于 Top 主题构成给出一句宏观基调（纯映射，不编造）。"""
    names = set(top_theme_names)
    if "模型军备竞赛" in names and ("产品化与 Agent 落地" in names or "开源生态" in names):
        return "能力狂奔、落地追赶"
    if "资本与并购" in names and "模型军备竞赛" in names:
        return "资本与模型双线升温"
    if "监管与政策" in names:
        return "狂奔与收紧并行"
    if "算力与芯片" in names:
        return "算力底座持续承压"
    if "模型军备竞赛" in names:
        return "模型迭代明显提速"
    if "产品化与 Agent 落地" in names:
        return "从能力走向场景落地"
    if "资本与并购" in names:
        return "资本加注、整合加速"
    if "开源生态" in names:
        return "开源力量持续壮大"
    return "多线并进、密集发布"


def _auto_lead(news_items: list, total_news: int = 0, insights: list = None) -> str:
    """编辑视角导语：从全量新闻聚合真实主线主题 + 关键证据，合成 2~3 句电梯演讲。

    不编造——主题与证据锚点均来自本周真实新闻数据（标题/摘要/评分）。
    仅当无任何主题信号命中时才退化为旧版分类计数兜底，保证不静默。
    """
    items = news_items or []
    if not items:
        return "本周 AI 行业动态已汇总，详见下方新闻流。"

    # 1) 主题聚合：每条新闻按 score + 命中主题词加权
    theme_scores = {name: 0.0 for name, _ in _EDITORIAL_THEMES}
    theme_anchor = {}  # name -> (hits, score, title)
    for it in items:
        text = ((it.get("title") or "") + " " + (it.get("summary") or "")).lower()
        sc = float(it.get("score", 0) or 0)
        for name, kws in _EDITORIAL_THEMES:
            hits = sum(1 for k in kws if k in text)
            if not hits:
                continue
            theme_scores[name] += hits * (1 + sc * 0.5)
            cur = theme_anchor.get(name)
            # 优先「命中更多主题词、其次评分更高」的新闻作为证据锚点，更贴主题
            if cur is None or (hits, sc) > (cur[0], cur[1]):
                theme_anchor[name] = (hits, sc, it.get("title") or "")

    ranked = sorted(((s, n) for n, s in theme_scores.items() if s > 0), reverse=True)
    if not ranked:
        # 极端兜底：退化为旧版分类计数（保持不静默）
        kickers = {}
        for it in (insights or []):
            k = it.get("kicker", "行业")
            kickers[k] = kickers.get(k, 0) + 1
        top = sorted(kickers.items(), key=lambda x: x[1], reverse=True)[:2]
        theme = "、".join(t for t, _ in top) or "模型、产品"
        n = len(insights or [])
        return f"本周共 {total_news} 条 AI 动态，头号信号集中在「{theme}」——挑 {n} 条最值得你跟进的。"

    # 2) 取 Top 主题（最多 3 个），每条配一句真实证据
    top = ranked[:3]
    clauses = []
    for i, (_, name) in enumerate(top):
        anchor = theme_anchor.get(name)
        ev = _lead_truncate(anchor[2]) if anchor else ""
        num = "①②③"[i]
        clauses.append(f"{num}{name}（{ev}）")

    tone = _week_tone([n for _, n in top])
    if len(top) == 3:
        prefix = f"本周共 {total_news} 条 AI 动态，编辑视角看主线有三——"
    else:
        prefix = f"本周共 {total_news} 条 AI 动态，编辑视角看主线集中在——"
    return prefix + "；".join(clauses) + f"。整体是「{tone}」的一周。"


# ── 「给本周的你」默认受众结论（确保该区永不静默消失）─────────────────
# 面向三类读者的一句话结论；当 --audience-summary / insights.json 未提供时回退到此。
# 受众结论默认兜底（与关键词 note 的受众键保持一致：开发者 / PM / 自媒体），
# 保证即使不传 --audience-summary，「给本周的你」也始终出现。
_DEFAULT_AUDIENCE_SUMMARY = {
    "开发者": "用开源/免费 API（Hy3、Qwen、DeepSeek）做垂直场景应用，别硬刚 base model；推理成本与端侧化直接关系你的毛利。",
    "PM": "需求在「AI+传统行业」（制造/医疗/金融），用低成本模型快速验证 PMF；国产模型替代叙事持续。",
    "自媒体": "具身智能 + 应用层爆发是 2026 最强叙事；开源 VS 闭源、国产登顶都是高传播选题。",
}

# ── 关键词自动派生 + 分类标签 ───────────────────────────────────────
# 跟踪词 -> 分类标签（复用渲染器的 tag 色板：模型/资本/产品/安全/基建/监管）
_AUTO_TERM_TAGS = [
    ("DeepSeek", "模型"), ("Qwen", "模型"), ("千问", "模型"), ("Claude", "模型"),
    ("GPT", "模型"), ("Gemini", "模型"), ("开源", "模型"), ("多模态", "模型"),
    ("端侧", "产品"), ("Agent", "产品"), ("智能体", "产品"), ("应用", "产品"),
    ("具身智能", "资本"), ("融资", "资本"), ("估值", "资本"), ("收购", "资本"),
    ("推理成本", "基建"), ("算力", "基建"), ("芯片", "基建"), ("云", "基建"),
    ("监管", "监管"), ("合规", "监管"), ("政策", "监管"), ("安全", "安全"), ("隐私", "安全"),
]
# 关键词的每受众默认提示（note 为 {受众: 文案} 时渲染彩色受众标签）
_AUTO_KW_NOTE = {
    "开发者": "可作为选型 / 成本 / 落地的跟踪锚点，顺着它做资料搜集。",
    "PM": "反映需求与机会窗口，值得纳入路线图评估。",
    "自媒体": "是本周高热叙事，适合做选题与解读。",
}


def _infer_tag(term: str) -> str:
    """从跟踪词表推断关键词分类标签。"""
    if not term:
        return None
    t = term.lower()
    for cand, tag in _AUTO_TERM_TAGS:
        if cand.lower() in t:
            return tag
    return None


# 轻量 TF 聚类停用词（中英文功能词 + 过于通用的词，避免噪声主题词刷屏）
_KW_STOP = {
    # 中文功能/通用词
    "的", "了", "和", "与", "在", "是", "也", "等", "为", "对", "及", "或", "一个", "一种",
    "我们", "他们", "公司", "如何", "为什么", "什么", "可以", "通过", "使用", "表示", "称",
    "将", "已", "并", "其", "该", "这", "那", "有", "更", "中", "上", "下", "后", "前",
    "年", "月", "日", "周", "本周", "目前", "正在", "一款", "推出", "发布", "这款", "这一",
    "为何", "哪些", "一些", "这些", "那些", "据悉", "获悉", "报道", "消息", "计划", "支持",
    "提供", "显示", "认为", "成为", "可能", "已经", "开始", "继续", "包括", "以及", "研究",
    "团队", "科技", "企业", "平台", "服务", "系统", "能力", "网络", "行业", "技术", "数据",
    "市场", "发展", "方面", "进行", "用户", "今日", "全球", "中国", "美国", "国内", "国外",
    "人工智能", "模型", "智能", "学习", "算法", "宣布", "正式", "最新", "首次", "双方",
    "相关", "问题", "领域", "产品",
    # 英文
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "by", "as", "at", "from", "ai", "we", "our", "their", "its",
    "this", "that", "new", "now", "how", "why", "what", "more", "using", "via", "has",
    "have", "will", "can", "not", "but", "they", "you", "your", "it", "if", "so", "than",
    "into", "about", "been", "model", "models", "said", "says",
}


def _tokenize(text):
    """抽取候选主题词：英文词元 + 中文 2/3/4 字 n-gram。"""
    toks = []
    for m in re.finditer(r'[A-Za-z][A-Za-z0-9+.\-]{1,}', text or ""):
        toks.append(m.group(0))
    for m in re.finditer(r'[一-鿿]{2,}', text or ""):
        run = m.group(0)
        for n in (4, 3, 2):
            for i in range(len(run) - n + 1):
                toks.append(run[i:i + n])
    return toks


def _auto_keywords(api_data: dict, top_n: int = 8) -> list:
    """轻量 TF 聚类：从本周新闻标题/摘要自动派生 5–8 个高频主题词 + 标签。

    设计：
      - 白名单 `_AUTO_TERM_TAGS`（高精实体）优先保留，确保关键议题不漏；
      - 同时做 TF n-gram 发现，补充白名单未覆盖的新兴主题（消除人工偏斜）；
      - 过滤停用词与「出现在 >55% 新闻中」的过度通用词；
      - note 写「本周被 N 条新闻提及（如《…》）…」——是本周相关，而非通用知识。
    """
    items = format_news_items(api_data) or []
    if not items:
        return []
    n_items = len(items)
    uni = Counter()
    term_items = defaultdict(set)
    seed_set = {c.lower() for c, _ in _AUTO_TERM_TAGS}

    for idx, it in enumerate(items):
        blob = f"{it.get('title', '')} {it.get('summary', '')}"
        low = blob.lower()
        # 1) 白名单精确命中（高精，优先）
        for cand, tag in _AUTO_TERM_TAGS:
            c = low.count(cand.lower())
            if c:
                uni[cand] += c
                term_items[cand].add(idx)
        # 2) TF n-gram 发现（去停用词/短词）
        for tk in _tokenize(blob):
            tl = tk.lower()
            if tl in _KW_STOP or len(tk) < 2:
                continue
            uni[tk] += 1
            term_items[tk].add(idx)

    # 过滤：白名单词保留；TF 发现词去掉过度通用（覆盖 >55% 新闻）与低频（<2）
    cands = {}
    for t, c in uni.items():
        is_seed = t.lower() in seed_set
        if not is_seed:
            if len(term_items.get(t, set())) > 0.55 * n_items:
                continue
            if c < 2:
                continue
        cands[t] = c
    if not cands:
        cands = dict(uni.most_common(top_n))

    # 排序：白名单优先，其次词频；取 top_n
    ranked = sorted(cands.items(),
                    key=lambda x: (x[0].lower() in seed_set, x[1]),
                    reverse=True)[:top_n]

    def _tag_for(term):
        tl = term.lower()
        for cand, tag in _AUTO_TERM_TAGS:
            if cand.lower() in tl:
                return tag
        idxs = term_items.get(term, set())
        tagcnt = Counter()
        for idx in idxs:
            b = (items[idx].get("title", "") + " " + items[idx].get("summary", "")).lower()
            for cand, tag in _AUTO_TERM_TAGS:
                if cand.lower() in b:
                    tagcnt[tag] += 1
        return tagcnt.most_common(1)[0][0] if tagcnt else "话题"

    def _note_for(term, cov):
        idxs = sorted(term_items.get(term, set()))
        sample = ""
        if idxs:
            s = items[idxs[0]].get("title", "")
            if len(s) > 20:
                s = s[:20] + "…"
            sample = s
        base = f"本周被 {cov} 条新闻提及"
        if sample:
            base += f"（如《{sample}》等）"
        base += "，是本期高频议题，建议沿它做资料搜集与交叉验证。"
        return {
            "开发者": base + "重点关注选型 / 成本 / 落地影响。",
            "PM": base + "反映需求与机会窗口，纳入路线图评估。",
            "自媒体": base + "是本周高热叙事，适合做选题与解读。",
        }

    out = []
    for t, c in ranked:
        cov = len(term_items.get(t, set()))
        out.append({
            "term": t,
            "tag": _tag_for(t),
            "tier": "主线" if (cov >= 4 or c >= 9) else "延伸",
            "note": _note_for(t, cov),
        })
    return out


def _normalize_keywords(keywords) -> list:
    """规范化关键词：保证为 dict 列表且尽量带分类 tag。"""
    out = []
    if not isinstance(keywords, list):
        return out
    for kw in keywords:
        if not isinstance(kw, dict) or not kw.get("term"):
            continue
        kw = dict(kw)
        if not kw.get("tag"):
            kw["tag"] = _infer_tag(kw["term"])
        out.append(kw)
    return out


# ── 服务端静态预渲染：把「给本周的你」与关键词标签直接写进 HTML ──────
# 目的：即使浏览器禁用/未执行 JS，这些核心部分也一定出现在静态页面里，
# 不再依赖客户端 renderInsights()。（renderInsights 仍会在 JS 可用时运行并接管交互）
_TAG_COLORS = {
    "安全": "#e74c3c", "模型": "#3498db", "基建": "#f39c12",
    "产品": "#27ae60", "资本": "#9b59b6", "监管": "#16a085",
    "话题": "#7f8c8d",
}


# 命名常量替代散落的魔法字符串（受众默认激活项 / 默认搜索引擎 / note 通用兜底键）
DEFAULT_ACTIVE_AUDIENCE = "开发者"
DEFAULT_SEARCH_ENGINE = "baidu"
GENERIC_AUDIENCE_LABEL = "通用"


def _pick_preferred_key(d: dict, preferred: str):
    """取 preferred 键的值；缺失或为空则取第一个有值键；用于受众 note 的降级。

    避免散落 `next(iter(d), "")` 这类一次性的兜底写法。
    """
    if not isinstance(d, dict):
        return None
    if d.get(preferred):
        return d[preferred]
    for v in d.values():
        if v:
            return v
    return None


def _render_audience_chips_html(audience_summary, active=DEFAULT_ACTIVE_AUDIENCE) -> str:
    """把受众结论渲染成静态 chips HTML（与 JS renderInsights 输出一致）。"""
    if not isinstance(audience_summary, dict) or not audience_summary:
        return ""
    parts = []
    for key in audience_summary:
        cls = "audience-chip active" if key == active else "audience-chip"
        parts.append(
            f'<span class="{cls}" data-audience="{html.escape(key, quote=True)}" '
            f'onclick="switchAudience(\'{html.escape(key, quote=True)}\', this)">'
            f"{html.escape(key, quote=True)}</span>"
        )
    return "\n".join(parts)


def _kw_tag_html(tag: str) -> str:
    """关键词分类彩标 HTML。"""
    if not tag:
        return ""
    color = _TAG_COLORS.get(tag, "#888")
    return (f'<span class="kw-tag" style="background:{color}22;color:{color};">'
            f"{html.escape(tag, quote=True)}</span>")


def _kw_tier_html(tier: str) -> str:
    """关键词层级（主线/延伸）标签 HTML。"""
    if not tier:
        return ""
    tier_cls = "kw-tier-main" if tier == "主线" else "kw-tier-ext"
    return f'<span class="kw-tier {tier_cls}">{html.escape(tier, quote=True)}</span>'


def _kw_note_html(note, active: str) -> str:
    """关键词面向当前受众的注释 HTML。"""
    if not note:
        return ""
    note_obj = note if isinstance(note, dict) else {GENERIC_AUDIENCE_LABEL: note}
    note_text = _pick_preferred_key(note_obj, active)
    if not note_text:
        return ""
    return (f'<div class="kw-note" style="margin-top:6px;font-size:12px;'
            f'line-height:1.5;color:var(--text-secondary);">'
            f'<b style="color:var(--accent);">{html.escape(active, quote=True)}：</b>'
            f"{html.escape(note_text, quote=True)}</div>")


def _kw_search_url(k: dict, active: str, base: str) -> str:
    """关键词点击跳转的网页搜索 URL。"""
    search = k.get("search")
    if isinstance(search, dict):
        q = _pick_preferred_key(search, active) or k.get("term", "")
        q = f"{q} AI"
    else:
        q = f"{k.get('term', '')} AI 行业"
    return base + urllib.parse.quote(q)


def _render_keyword_chips_html(keywords, active=DEFAULT_ACTIVE_AUDIENCE,
                               search_sources=None,
                               search_base="https://www.baidu.com/s?wd=") -> str:
    """把关键词渲染成静态 chips HTML（含彩色分类标签 tag），与 JS 输出一致。"""
    if not keywords:
        return ""
    src = search_sources or {"baidu": "https://www.baidu.com/s?wd="}
    base = src.get(DEFAULT_SEARCH_ENGINE) or search_base
    parts = []
    for k in keywords:
        if not isinstance(k, dict):
            k = {"term": k}
        term = k.get("term") or ""
        if not term:
            continue
        parts.append(
            f'<div class="kw-item" style="margin-bottom:12px;">\n'
            f'  <a class="kw-chip" href="{html.escape(_kw_search_url(k, active, base), quote=True)}" '
            f'target="_blank" rel="noopener" '
            f'title="在网页中搜索「{html.escape(term, quote=True)} AI」" '
            f'style="display:flex;align-items:center;gap:8px;">\n'
            f'    <span class="kw-term" style="font-weight:600;">'
            f'{html.escape(term, quote=True)} <span class="kw-go">↗</span></span>\n'
            f"    {_kw_tag_html(k.get('tag'))}\n    {_kw_tier_html(k.get('tier'))}\n  </a>\n"
            f"  {_kw_note_html(k.get('note'), active)}\n</div>"
        )
    return "\n".join(parts)


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


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="生成 AI 新闻网站 HTML")
    parser.add_argument("--api-json", help="新闻 JSON 文件路径（RSS 抓取结果，AI HOT 兼容 schema）")
    parser.add_argument("--output", "-o", help="输出 HTML 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="仅显示数据摘要，不生成")
    # 可选外部 API 增强：用户自备（如 AI HOT 或其他 AI 行业知识 API），自行承担合规风险
    parser.add_argument("--external-news-json", help="可选：自备外部 API 导出的新闻 JSON（增强报告，如 AI HOT）")
    parser.add_argument("--external-source-name", help="外部数据源名称（页脚署名，如 AI HOT）")
    parser.add_argument("--external-source-url", help="外部数据源主页 URL（页脚链接，可选）")
    parser.add_argument("--ranking-json", help="从本地 JSON 文件读取排行榜数据（覆盖自动获取）")
    parser.add_argument("--profiles-json", help="追加的模型资料卡 profile JSON（按模型名索引）；会与技能目录 canonical 档案合并并写回，实现档案实时累积更新")
    parser.add_argument("--no-live-ranking", action="store_true",
                        help="跳过自动获取排行榜，显示'暂无实时数据'")
    parser.add_argument("--ranking-top", type=int, default=10,
                        help="排行榜获取条数（默认 10）")
    parser.add_argument("--date", default=None,
                        help="固定报告周期截止日 YYYY-MM-DD（如 2026-08-02）；不提供则用当前日期")
    parser.add_argument("--region", default="auto",
                        choices=["auto", "cn", "global"],
                        help="网络环境：auto=探测(默认) / cn=优先国内源 / global=优先国外源")
    parser.add_argument("--proxy", default=None,
                        help="显式指定出站代理（如 http://127.0.0.1:7890），让国外源在受限网络下可达")
    parser.add_argument("--data-snapshot", default=None,
                        help="市场数据快照日期 YYYY-MM-DD（展示在图表注释，标注为静态快照；默认取 --date 或当天）")
    # 图表数据（由 Agent 从 WebSearch 获取真实值后注入；不提供则标注为估算）
    parser.add_argument("--market-data", help="市场规模数据，逗号分隔，如 51,71,103,...")
    parser.add_argument("--market-labels", help="市场规模标签，逗号分隔，如 2020,2021,...")
    parser.add_argument("--funding-data", help="融资额数据，逗号分隔")
    parser.add_argument("--funding-labels", help="融资额标签，逗号分隔")
    parser.add_argument("--market-source", help="市场规模数据来源说明（如 Statista 2026）")
    parser.add_argument("--funding-source", help="融资额数据来源说明（如 Crunchbase 2026）")
    # 中国分轨（国内源）：与全球分轨并列，单位亿元（RMB）
    parser.add_argument("--cn-market-data", help="中国 AI 市场规模数据，逗号分隔，如 9188,12000,17000")
    parser.add_argument("--cn-market-labels", help="中国市场规模标签，逗号分隔，如 2024,2025,2026E")
    parser.add_argument("--cn-funding-data", help="中国 AI 融资额数据，逗号分隔")
    parser.add_argument("--cn-funding-labels", help="中国融资额标签，逗号分隔")
    parser.add_argument("--cn-market-source", help="中国市场规模来源说明（如 中国信通院/中商产业研究院）")
    parser.add_argument("--cn-funding-source", help="中国融资额来源说明（如 新浪创投Plus 2025）")
    parser.add_argument("--ranking-criteria", help="排行榜排名标准说明（覆盖默认 LMMarketCap 综合评分说明）")
    # 英文报道中文总结（本地 Ollama 翻译，可选；零 API 成本、国内友好；best-effort 不阻断）
    parser.add_argument("--translate-en", action="store_true",
                        help="为英文报道生成中文总结（调用本地 Ollama，需本机运行 Ollama；失败/超时保留英文原文）")
    parser.add_argument("--translate-model", default="qwen2.5:7b",
                        help="翻译所用本地 Ollama 模型（默认 qwen2.5:7b，非推理模型更快）")
    parser.add_argument("--translate-workers", type=int, default=6,
                        help="翻译并发线程数（默认 6）")
    parser.add_argument("--translate-timeout", type=int, default=25,
                        help="单条翻译超时秒数（默认 25）")
    # 本周看点（编辑洞察 + 关键词）：由 Agent 基于本周新闻撰写
    parser.add_argument("--insights-json", help="本周看点 JSON 文件（{keywords:[{term,note}], insights:[{kicker,title,analysis,insight,related:[{title,url}]}]}）")
    parser.add_argument("--lead", help="本周看点顶部导语一句话（电梯演讲，可选）")
    parser.add_argument("--keyword-search-base",
                        default="https://www.baidu.com/s?wd=",
                        help="关键词点击跳转的网页搜索基址（默认百度；搜索词将追加「词语 AI 行业」）")
    # 面向目标用户群的「本周看点」优化（Plan A-F）
    parser.add_argument("--audience-summary",
                        help="面向受众的一句话结论，JSON 格式 {开发者:..., PM:..., 媒体:...}；渲染在关键词区上方")
    parser.add_argument("--keyword-search-sources",
                        default='{"baidu":"https://www.baidu.com/s?wd=","google":"https://www.google.com/search?q=","arxiv":"https://arxiv.org/search/?query="}',
                        help="可切换的搜索源 JSON {name:url}；默认百度/谷歌/ arXiv")

    args = parser.parse_args()
    _configure_proxy()  # 应用 HTTPS_PROXY / --proxy（含 SOCKS）到本次运行

    # 获取新闻数据（默认仅 RSS 自治抓取结果；不内置任何第三方 API）
    if args.api_json:
        print(f"📂 读取 {args.api_json} ...")
        api_data = json.loads(Path(args.api_json).read_text(encoding="utf-8"))
    else:
        parser.error("需要 --api-json（请先运行 fetch_ai_news.py 抓取 RSS 新闻）")

    base_items = api_data.get("items", [])

    # 可选：合并用户自备的外部 API 新闻（如 AI HOT），按 url/title 去重
    external_source = None
    if args.external_news_json:
        print(f"🔌 合并外部增强新闻 {args.external_news_json} ...")
        ext = json.loads(Path(args.external_news_json).read_text(encoding="utf-8"))
        if isinstance(ext, dict):
            ext = ext.get("items", [])
        ext_items = [it for it in ext if isinstance(it, dict)]
        merged = merge_external_news(base_items, ext_items)
        api_data["items"] = merged
        api_data["count"] = len(merged)
        external_source = (args.external_source_name or "外部API", args.external_source_url)
        print(f"  ✅ 外部补充 {len(ext_items)} 条，去重后共 {len(merged)} 条"
              + (f"（来源：{args.external_source_name}）" if args.external_source_name else ""))

    count = api_data.get("count", len(api_data.get("items", [])))
    print(f"  获取到 {count} 条新闻")

    if args.dry_run:
        from collections import Counter
        cats = Counter(item["category"] for item in api_data.get("items", []))
        print("\n📊 分类统计：")
        for c, n in sorted(cats.items()):
            print(f"  {c}: {n}")
        print(f"\n📝 前 5 条标题：")
        for item in api_data.get("items", [])[:5]:
            print(f"  [{item['category']}] {item['title'][:60]}...")
        return

    # 获取双排行榜数据（综合榜 + 开源模型榜），每源独立容错
    leaderboard_data = None
    if args.ranking_json:
        print(f"🏆 从 {args.ranking_json} 读取排行榜...")
        try:
            leaderboard_data = json.loads(Path(args.ranking_json).read_text(encoding="utf-8"))
            print(f"  已加载自定义排行榜数据")
        except (json.JSONDecodeError, OSError) as e:  # P0#8 收窄：仅数据/文件错误
            print(f"  ⚠️ 读取排行榜 JSON 失败：{e}")
    elif not args.no_live_ranking:
        print("🏆 抓取双排行榜（按网络环境自适应选择国内外源）...")
        try:
            if args.proxy:
                # P0 拆分后：_PROXY_OVERRIDE 在 aiweekly.utils 模块；直接对其赋值
                _au._PROXY_OVERRIDE = args.proxy
                _configure_proxy()
            leaderboard_data = fetch_all_leaderboards(args.ranking_top, region=args.region)
            lm = leaderboard_data["comprehensive"]["lmarena"]["rows"]
            aa = leaderboard_data["comprehensive"]["aa"]["rows"]
            hf = leaderboard_data["open_source"]["hf"]["rows"]
            print(f"  ✅ 综合榜左 {len(lm)} 条、综合榜右 {len(aa)} 条、开源榜 {len(hf)} 条")
        except Exception as e:  # noqa: BLE001  best-effort 抓取，失败回退缓存/暂无实时数据
            print(f"  ⚠️ 排行榜抓取异常：{e}（将显示「暂无实时数据」）")

    # 模型档案同步：自动加载 canonical 档案 + 合并传入的新档案 + 检测新上榜模型
    model_profiles_data = sync_model_profiles(args.profiles_json, leaderboard_data)

    # 解析图表数据（CLI 注入；未提供则回退估算并标注）
    def _parse_csv(s):
        return [x.strip() for x in s.split(",")] if s else None
    def _parse_num(s):
        try:
            return [float(x) for x in s.split(",")] if s else None
        except ValueError:
            print(f"  ⚠️ 图表数据解析失败(含非数字): {s} — 将回退估算值")
            return None

    # 本周看点（编辑洞察 + 关键词）：由 Agent 基于本周新闻撰写，可选
    insights = None
    keywords = None
    audience_summary_data = None
    if args.insights_json:
        print(f"📌 读取本周看点 {args.insights_json} ...")
        data = json.loads(Path(args.insights_json).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            insights = data.get("insights", [])
            keywords = data.get("keywords", [])
            # 允许在 insights.json 内联 audience_summary（与关键词受众键一致：开发者/PM/自媒体）
            audience_summary_data = data.get("audience_summary")
        else:
            insights = data
        errs = _validate_insights(data)
        if errs:
            print("❌ insights.json 校验失败：")
            for e in errs:
                print("  -", e)
            sys.exit(1)
        print(f"  ✅ 载入 {len(insights or [])} 条看点"
              + (f"、{len(keywords or [])} 个关键词" if keywords else "")
              + (f"、受众结论 {len(audience_summary_data or {})} 类" if audience_summary_data else ""))
        # 受众键一致性检查（非致命）：keywords[].note 的受众键须与 audience_summary 一致，
        # 否则切换「给本周的你」受众卡时，关键词 note 取不到值而显示空白。
        _aud_keys = set((audience_summary_data or _DEFAULT_AUDIENCE_SUMMARY).keys())
        _note_keys = set()
        for kw in (keywords or []):
            if isinstance(kw, dict) and isinstance(kw.get("note"), dict):
                _note_keys |= set(kw["note"].keys())
        if _note_keys and _note_keys != _aud_keys:
            print(f"  ⚠️ 受众键不一致：audience_summary={sorted(_aud_keys)}，"
                  f"keywords[].note={sorted(_note_keys)}")
            if _aud_keys - _note_keys:
                print(f"     切到 {sorted(_aud_keys - _note_keys)} 时部分关键词注释将为空")
            if _note_keys - _aud_keys:
                print(f"     多余受众键（无对应受众卡，永不显示）：{sorted(_note_keys - _aud_keys)}")

    # 读取面向受众的一句话结论（独立文件路径优先；缺失则回退 insights.json 内联或内置默认）
    if args.audience_summary:
        try:
            audience_summary_data = json.loads(Path(args.audience_summary).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:  # P0#8 收窄：仅数据/文件错误
            print(f"  ⚠️ 读取 audience-summary 失败：{e}")

    # 读取可切换搜索源（文件路径 -> JSON 字符串；默认内联百度/谷歌/arXiv）
    search_sources_data = args.keyword_search_sources
    if args.keyword_search_sources and Path(args.keyword_search_sources).exists():
        try:
            search_sources_data = Path(args.keyword_search_sources).read_text(encoding="utf-8").strip()
        except OSError as e:  # P0#8 收窄：仅文件读取错误
            print(f"  ⚠️ 读取 keyword-search-sources 失败：{e}")

    # 生成
    logger.info("开始渲染 HTML（新闻数=%d）", count)
    output = args.output or f"AI_News_{datetime.now().strftime('%Y-%m-%d')}.html"
    html = generate(
        api_data, output_path=output,
        market_data=_parse_num(args.market_data),
        market_labels=_parse_csv(args.market_labels),
        funding_data=_parse_num(args.funding_data),
        funding_labels=_parse_csv(args.funding_labels),
        market_source=args.market_source,
        funding_source=args.funding_source,
        cn_market_data=_parse_num(args.cn_market_data),
        cn_market_labels=_parse_csv(args.cn_market_labels),
        cn_funding_data=_parse_num(args.cn_funding_data),
        cn_funding_labels=_parse_csv(args.cn_funding_labels),
        cn_market_source=args.cn_market_source,
        cn_funding_source=args.cn_funding_source,
        external_source=external_source,
        leaderboard_data=leaderboard_data,
        model_profiles=model_profiles_data,
        insights=insights,
        lead=args.lead,
        keywords=keywords,
        keyword_search_base=args.keyword_search_base,
        audience_summary=audience_summary_data,
        keyword_search_sources=search_sources_data,
        report_date=args.date,
        data_snapshot=args.data_snapshot,
        translate_en=args.translate_en,
        translate_model=args.translate_model,
        translate_workers=args.translate_workers,
        translate_timeout=args.translate_timeout,
    )
    _lb_ok = bool(leaderboard_data and (
        leaderboard_data.get("comprehensive", {}).get("lmarena", {}).get("rows") or
        leaderboard_data.get("comprehensive", {}).get("aa", {}).get("rows") or
        leaderboard_data.get("open_source", {}).get("hf", {}).get("rows")))
    print(f"✅ 已生成 {output}（{len(html.encode('utf-8'))} bytes，{count} 条新闻，"
          f"双排行榜: {'已填充' if _lb_ok else '暂无实时数据'}）")

    # Chart.js 已内联进 HTML(见上方 [CHARTJS_LIB_PLACEHOLDER] 替换),无需附带外部 js 文件


__all__ = [
    "main", "generate", "fetch_all_leaderboards",
]


if __name__ == "__main__":
    main()
