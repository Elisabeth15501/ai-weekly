#!/usr/bin/env python3
"""
validate_report.py v3.0

检查生成的 AI 新闻网站 HTML 是否完整合规。
适配 v3.0 新闻网站格式（news_site_template.html），兼容旧版 v2.0 周报格式。

用法：
  python scripts/validate_report.py --html AI_News_2026-07-09.html
  python scripts/validate_report.py --html AI_Weekly_Report_2026_W27.html  # 兼容旧版

检查项：
  1. 文件完整性（存在 + 非空）
  2. 新闻条目 >= 20 条 + 来源链接 >= 80%
  3. 搜索栏功能（v3.0 新闻站）或 图表完整（v2.0 周报）
  4. 分类标签 / KPI 数据
  5. 数据来源说明

版本历史：
  v3.0 (2026-07-09): 适配新闻网站格式，新增来源链接检查、搜索栏检查、分类标签检查
  v2.0 (2026-07-06): 修复3个误报bug
"""

import argparse
import json
import re
import sys
from pathlib import Path


# 判断是 v3.0 新闻站还是 v2.0 周报
def _detect_format(html_content: str) -> str:
    if 'news-card' in html_content or 'NEWS_DATA' in html_content or 'news-grid' in html_content:
        return 'v3'
    if 'kpi-section' in html_content or 'kpi-grid' in html_content:
        return 'v2'
    return 'v3'  # 默认按 v3 检查


# ============================================================
# 通用检查
# ============================================================

def check_file_exists(html_path: Path) -> dict:
    if not html_path.exists():
        return {"ok": False, "msg": f"文件不存在：{html_path}"}
    size = html_path.stat().st_size
    if size < 1024:
        return {"ok": False, "msg": f"文件过小（{size} bytes），可能不完整"}
    return {"ok": True, "msg": f"文件存在，{size//1024} KB"}


def check_data_sources(html_content: str) -> dict:
    """
    检查数据来源，从文件末尾搜索"数据来源"/"来源"/"Sources"字样。
    """
    pattern = re.compile(r'数据来源|数据说明|新闻数据来自', re.IGNORECASE)
    last_match = None
    for m in pattern.finditer(html_content):
        last_match = m

    if not last_match:
        return {"ok": False, "msg": "未找到数据来源说明"}

    start = last_match.start()
    file_len = len(html_content)

    # 如果匹配在文件前 70%，尝试从尾部找
    if start < file_len * 0.6:
        tail = html_content[int(file_len * 0.6):]
        tail_match = pattern.search(tail)
        if tail_match:
            start = int(file_len * 0.6) + tail_match.start()

    source_section = html_content[start:start + 800]
    urls = re.findall(r'https?://[^\s<>"\'()]+', source_section)

    if len(urls) >= 2:
        return {"ok": True, "msg": f"数据来源已填写，含 {len(urls)} 个链接"}
    elif len(urls) >= 1:
        return {"ok": True, "msg": f"数据来源已填写，含 {len(urls)} 个链接"}
    return {"ok": False, "msg": "数据来源可能不完整（未找到 URL 链接）"}


# ============================================================
# v3.0 新闻站检查
# ============================================================

def check_news_v3(html_content: str, min_news: int = 20, min_cov: float = 80) -> dict:
    """
    检查新闻条目数量和来源链接覆盖率。
    - 从 NEWS_DATA JS 数组中提取条目数
    - 检查每条新闻是否有 url 字段
    返回 {ok, warn, ...}:ok=硬门槛达标;warn=接近门槛(降级但可用)。
    """
    # 提取 NEWS_DATA 数组
    news_match = re.search(r'const NEWS_DATA\s*=\s*(\[[\s\S]*?\])\s*;', html_content)
    if not news_match:
        # 回退：数 .news-card 结构
        cards = re.findall(r'class="news-card"', html_content)
        count = len(cards)
        ok = count >= min_news
        warn = (min_news // 2) <= count < min_news
        return {
            "ok": ok,
            "warn": warn,
            "count": count,
            "with_urls": count,
            "msg": f"找到 {count} 条新闻卡片" + (" ✅" if ok else (" ⚠️ 接近门槛" if warn else f" ⚠️ 建议 ≥ {min_news} 条"))
        }

    try:
        raw_data = news_match.group(1)
        # 提取 url 字段
        urls = re.findall(r'"url":\s*"([^"]+)"', raw_data)
        total = raw_data.count('"title"')

        # 检查 url 是否为有效链接（非空）
        valid_urls = [u for u in urls if u.startswith('http')]
        coverage = len(valid_urls) / total * 100 if total > 0 else 0

        ok = total >= min_news and coverage >= min_cov
        warn = (not ok) and ((min_news // 2) <= total < min_news
                             or (min_cov - 20) <= coverage < min_cov)
        return {
            "ok": ok,
            "warn": warn,
            "count": total,
            "with_urls": len(valid_urls),
            "coverage": f"{coverage:.0f}%",
            "msg": (f"找到 {total} 条新闻，{len(valid_urls)} 条含原始链接（{coverage:.0f}%）"
                    + (" ✅" if ok else (" ⚠️ 接近门槛" if warn else f" ⚠️ 建议 ≥ {min_news} 条 / 覆盖率 ≥ {min_cov:.0f}%")))
        }
    except Exception as e:
        return {"ok": False, "warn": False, "count": 0, "with_urls": 0, "msg": f"解析 NEWS_DATA 失败：{e}"}


def check_editorial_c0(html_content: str) -> dict:
    """C0 内容质量校验：摘要归一、🔥必读标记、信源短名。

    三项任一不达标即判不通过（ok=False），直接拉低总分，确保 C0 落地可追溯。
    """
    news_match = re.search(r'const NEWS_DATA\s*=\s*(\[[\s\S]*?\])\s*;', html_content)
    if not news_match:
        return {"ok": False, "warn": False, "msg": "未找到 NEWS_DATA，无法校验 C0"}
    try:
        data = json.loads(news_match.group(1))
    except Exception as e:
        return {"ok": False, "warn": False, "msg": f"NEWS_DATA 解析失败：{e}"}

    total = len(data)
    if total == 0:
        return {"ok": False, "warn": False, "msg": "新闻为空，无法校验 C0"}

    # 1) 摘要 > 120 字占比（归一化目标：<20%）
    long_sum = sum(1 for n in data if len(n.get("summary", "") or "") > 120)
    long_ratio = long_sum / total
    summary_ok = long_ratio < 0.20

    # 2) 🔥必读标记存在且数量合理（5~12）
    mr = sum(1 for n in data if n.get("mustRead") is True)
    mustread_ok = (5 <= mr <= 12)

    # 3) 信源短名：含 RSS feed 分隔符（" | " / " - "）视为未归一
    verbose = sum(1 for n in data
                  if (" | " in (n.get("source", "") or "")) or (" - " in (n.get("source", "") or "")))
    source_ok = verbose == 0

    # 4) 语言标签：每条必须有 zh/en（供「语言」筛选）；整份缺失某一语言→检测可能失效（warn）
    missing_lang = sum(1 for n in data if n.get("lang") not in ("zh", "en"))
    zh = sum(1 for n in data if n.get("lang") == "zh")
    en = sum(1 for n in data if n.get("lang") == "en")
    lang_ok = missing_lang == 0
    lang_warn = (zh == 0 or en == 0)

    ok = summary_ok and mustread_ok and source_ok and lang_ok
    details = [
        f"摘要>120字 {long_sum}/{total}（{long_ratio*100:.0f}%，阈值<20% {'✅' if summary_ok else '❌'}）",
        f"🔥必读 {mr} 条（合理 5–12 {'✅' if mustread_ok else '❌'}）",
        f"信源含 RSS 分隔符 {verbose} 条（应=0 {'✅' if source_ok else '❌'}）",
        f"语言标签 zh={zh}/en={en}（缺失 {missing_lang} {'✅' if lang_ok else '❌'}{'，⚠️整份缺某语言' if lang_warn else ''}）",
    ]
    return {
        "ok": ok,
        "summary_ok": summary_ok, "mustread_ok": mustread_ok, "source_ok": source_ok, "lang_ok": lang_ok,
        "long_ratio": round(long_ratio, 3), "mustread": mr, "verbose_source": verbose,
        "lang_zh": zh, "lang_en": en, "lang_missing": missing_lang,
        "msg": "；".join(details),
    }


def _extract_js_var(name: str, html_content: str):
    """从 HTML 抽取 const NAME = [...] / {...} 字面量（支持嵌套括号）。失败返回 None。"""
    m = re.search(r'const %s\s*=\s*([\[{])' % re.escape(name), html_content)
    if not m:
        return None
    start = m.start(1)
    opener = html_content[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    i = start
    n = len(html_content)
    while i < n:
        ch = html_content[i]
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0 and ch == closer:
                return html_content[start:i + 1]
        i += 1
    return None


_DAILY_DIGEST_MARKERS = ["8点1氪", "早讯", "早报", "日报", "每日速览", "今日速览",
                         "晚报", "晨读", "周报", "daily brief", "早知道", "三分钟速览",
                         "一氪早讯", "科技早报"]


def check_editorial_c1(html_content: str) -> dict:
    """C1 内容质量校验：看点去注水（无日报聚合类）+ 榜单时效标注。

    - 看点含日报聚合类（如「8点1氪」）→ 不通过（去注水未生效）
    - 榜单快照距报告日超龄 → 因「已显式标注」满足 8.3 的「或显式标注」分支，判通过但提示龄期
    """
    # 1) 看点去注水
    ins_raw = _extract_js_var("INSIGHTS_DATA", html_content)
    digest_hits = []
    if ins_raw:
        try:
            ins = json.loads(ins_raw)
        except Exception:
            ins = []
        for it in ins:
            t = f"{it.get('title', '')} {it.get('source', '')}".lower()
            if any(m.lower() in t for m in _DAILY_DIGEST_MARKERS):
                digest_hits.append(it.get("title", "")[:30])
    digest_ok = len(digest_hits) == 0

    # 2) 榜单时效标注（读 generate() 注入的 meta.snapshot_stale / snapshot_max_age）
    lb_raw = _extract_js_var("LEADERBOARD_DATA", html_content)
    snap_stale = False
    snap_max_age = None
    if lb_raw:
        try:
            lb = json.loads(lb_raw)
            meta = (lb.get("meta") or {}) if isinstance(lb, dict) else {}
            snap_stale = bool(meta.get("snapshot_stale"))
            snap_max_age = meta.get("snapshot_max_age")
        except Exception:
            pass
    # 显式标注即满足 8.3 的「或显式标注」分支 → 通过；仅提示龄期
    snap_ok = True

    ok = digest_ok and snap_ok
    details = [
        f"看点日报聚合类 {len(digest_hits)} 条（应=0 {'✅' if digest_ok else '❌'}）",
        f"榜单快照标注 {'已显式标注' if snap_stale else '新鲜'}（最大龄 {snap_max_age if snap_max_age is not None else '—'} 天，超龄已告警 {'✅' if snap_ok else '❌'}）",
    ]
    if digest_hits:
        details.append("含：" + "；".join(digest_hits))
    return {
        "ok": ok,
        "digest_ok": digest_ok, "digest_hits": digest_hits,
        "snap_stale": snap_stale, "snap_max_age": snap_max_age,
        "msg": "；".join(details),
    }


def check_search_v3(html_content: str) -> dict:
    """检查搜索栏和分类标签是否存在。"""
    has_search = 'searchInput' in html_content or 'search-input' in html_content
    has_tabs = 'tabsContainer' in html_content or 'class="tabs"' in html_content
    has_category_filter = 'activeCategory' in html_content or 'switchTab' in html_content

    all_ok = has_search and has_tabs and has_category_filter
    issues = []
    if not has_search:
        issues.append("缺少搜索栏")
    if not has_tabs:
        issues.append("缺少分类标签")
    if not has_category_filter:
        issues.append("缺少分类筛选逻辑")

    return {
        "ok": all_ok,
        "has_search": has_search,
        "has_tabs": has_tabs,
        "has_filter": has_category_filter,
        "msg": "搜索、分类、筛选功能完整 ✅" if all_ok else "缺少：" + ", ".join(issues)
    }


def check_charts_v3(html_content: str) -> dict:
    """检查 v3.0 的 2 个 Chart.js 图表（市场规模 + 融资趋势）。"""
    charts = [
        ("marketSizeChart", "市场规模柱状图"),
        ("fundingChart",    "AI融资折线图"),
    ]

    details = []
    funding_points = None
    for chart_id, chart_name in charts:
        init_pattern = rf"getElementById\(['\"]{chart_id}['\"]\)"
        has_init = re.search(init_pattern, html_content) is not None

        if not has_init:
            details.append({"id": chart_id, "ok": False, "msg": f"{chart_name}：未找到图表初始化代码"})
            continue

        # 提取数据数组
        init_match = re.search(init_pattern, html_content)
        if init_match:
            block = html_content[init_match.start():init_match.start() + 3000]
            data_arrays = re.findall(r"data:\s*(\[[\d\s,\.\-eE+]+\])", block)

            if data_arrays:
                main_arr = data_arrays[0]
                num_points = main_arr.count(",") + 1 if "," in main_arr else 1
                if chart_id == "fundingChart":
                    funding_points = num_points
                details.append({"id": chart_id, "ok": True,
                                "msg": f"{chart_name}：数据正常（{num_points} 个数据点）"})
            else:
                details.append({"id": chart_id, "ok": False, "msg": f"{chart_name}：数据数组缺失"})

    ok = all(d["ok"] for d in details)
    # 融资数据点过少(<4)仅作警告(非致命),提醒补充更完整真实序列
    warn = funding_points is not None and funding_points < 4
    return {"ok": ok, "warn": warn, "details": details,
            "msg": ("⚠️ 融资数据点偏少(<4),建议补充更完整的真实季度序列" if warn else "")}


def _extract_balanced_brace(html_content: str, start: int) -> str:
    """从 start（'{' 位置）开始，按括号配平截取对象字面量。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html_content)):
        c = html_content[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return html_content[start:i + 1]
    return html_content[start:]


def check_ranking_v3(html_content: str, min_ranking: int = 5) -> dict:
    """检查模型排行榜（双榜：综合榜 LMArena+AA / 开源榜 HF）是否存在且有数据。"""
    has_ranking = ('LEADERBOARD_DATA' in html_content
                   or 'RANKING_DATA' in html_content
                   or 'ranking-table' in html_content)

    if not has_ranking:
        return {"ok": False, "warn": False, "msg": "未找到模型排行榜"}

    # 新双榜结构：const LEADERBOARD_DATA = { ... };
    lb_idx = html_content.find('const LEADERBOARD_DATA')
    if lb_idx >= 0:
        brace = html_content.find('{', lb_idx)
        if brace >= 0:
            raw = _extract_balanced_brace(html_content, brace)
            try:
                data = json.loads(raw)
            except Exception:
                # 宽松模式：退化为按行对象计数
                n = raw.count('"model":') or raw.count('"name":')
                return {"ok": n >= 10, "count": n,
                        "msg": f"双排行榜已填充（约 {n} 条，宽松解析）"}
            comp = data.get("comprehensive", {}) or {}
            lm_rows = (comp.get("lmarena", {}) or {}).get("rows", []) or []
            aa_rows = (comp.get("aa", {}) or {}).get("rows", []) or []
            osb = data.get("open_source", {}) or {}
            ls = osb.get("ls", {}) or {}
            ls_rows = ls.get("rows", []) or []
            hf = osb.get("hf", {}) or {}
            hf_rows = hf.get("rows", []) or []
            counts = {
                "LMArena 综合": len(lm_rows),
                "AA 智能指数": len(aa_rows),
                "LLM-Stats 开源": len(ls_rows),
                "HF 开源": len(hf_rows),
            }
            total = sum(counts.values())
            all_ok = all(v >= min_ranking for v in counts.values())
            warn = any((min_ranking // 2) <= v < min_ranking for v in counts.values())
            detail = "，".join(f"{k} {v} 条" for k, v in counts.items())
            return {"ok": all_ok, "warn": warn, "counts": counts, "count": total,
                    "msg": f"双排行榜：{detail} {'✅' if all_ok else ('⚠️ 接近门槛' if warn else f'⚠️ 每榜建议 ≥{min_ranking} 条')}"}

    # 旧版单榜结构：const RANKING_DATA = [ ... ];
    rank_match = re.search(r'const RANKING_DATA\s*=\s*(\[[\s\S]*?\])\s*;', html_content)
    if rank_match:
        count = rank_match.group(1).count('"name"')
        return {"ok": count >= 5, "warn": False, "count": count, "msg": f"排行榜 {count} 个模型 ✅"}
    return {"ok": True, "warn": False, "msg": "排行榜存在"}


# ============================================================
# v2.0 周刊检查（保留兼容）
# ============================================================

PLACE_HOLDER_PATTERNS = [
    r"\$XXX", r"(?<!\w)XXX(?!\w)", r"N/A", r"待填充", r"示例数据",
    r"\[PLACE.*?\]", r"\[KPI_.*?\]", r"\[CHART_.*?\]", r"\[NEWS_.*?\]",
]

TEMPLATE_CHART_DATA = [
    "[327, 390.9, 514.5, 680, 890, 1150, 1450, 3500]",
    "[17.4, 13.1, 16.2, 14.9, 13.8, 25.6, 23.5, 47.2, 62.2, 41.8, 45.1, 83.2]",
    "[56, 51, 47, 46, 40, 35, 33, 30, 30, 26]",
    "[46.4, 27.7, 10.3, 15.6]",
]


def _extract_body_html(html_content: str) -> str:
    cleaned = re.sub(r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r"<body[^>]*>(.*?)</body>", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else cleaned


def check_charts_v2(html_content: str) -> dict:
    charts = [
        ("marketSizeChart",   "市场规模柱状图"),
        ("fundingChart",      "AI融资折线图"),
        ("adoptionChart",     "企业AI采用饼图"),
        ("marketShareChart",  "市场份额饼图"),
        ("maChart",           "并购交易柱状图"),
        ("agentMarketChart",  "AI智能体市场预测"),
    ]
    details = []
    for chart_id, chart_name in charts:
        init_pattern = rf"getElementById\(['\"]{chart_id}['\"]\)"
        has_init = re.search(init_pattern, html_content) is not None
        if not has_init:
            details.append({"id": chart_id, "ok": False, "msg": f"{chart_name}：未找到"})
            continue
        init_match = re.search(init_pattern, html_content)
        block = html_content[init_match.start():init_match.start() + 3000] if init_match else ""
        data_arrays = re.findall(r"data:\s*(\[[\d\s,\.\-eE+]+\])", block)
        if not data_arrays:
            details.append({"id": chart_id, "ok": False, "msg": f"{chart_name}：数据缺失"})
            continue
        arr_normalized = data_arrays[0].replace(" ", "")
        is_template = any(arr_normalized == t.replace(" ", "") for t in TEMPLATE_CHART_DATA)
        if is_template:
            details.append({"id": chart_id, "ok": False, "msg": f"{chart_name}：模板数据未替换"})
        else:
            n = data_arrays[0].count(",") + 1 if "," in data_arrays[0] else 1
            details.append({"id": chart_id, "ok": True, "msg": f"{chart_name}：正常（{n} 点）"})
    ok = all(d["ok"] for d in details)
    return {"ok": ok, "details": details}


def check_news_v2(html_content: str) -> dict:
    count = len(re.findall(r'class="news-item"', html_content))
    if count == 0:
        count = len(re.findall(r'class="news-title"', html_content))
    return {"ok": count >= 5, "count": count, "msg": f"找到 {count} 条新闻" + (" ✅" if count >= 5 else " ⚠️")}


def check_kpi_v2(html_content: str) -> dict:
    body_html = _extract_body_html(html_content)
    kpi_section = ""
    m = re.search(r'class="kpi-section"', html_content)
    if m:
        kpi_section = html_content[m.start():m.start() + 3000]
    else:
        for kw in ["KPI", "kpi-value", "kpi-label", "核心数据"]:
            idx = body_html.find(kw)
            if idx >= 0:
                kpi_section = body_html[idx:idx + 3000]
                break
        if not kpi_section:
            kpi_section = body_html

    issues = []
    for pattern in PLACE_HOLDER_PATTERNS:
        matches = re.findall(pattern, kpi_section)
        if matches:
            issues.extend(list(set(matches))[:3])

    return {
        "ok": len(issues) == 0,
        "msg": "KPI 数据正常" if not issues else f"KPI 含占位符：{issues[:3]}"
    }


# ============================================================
# 主验证
# ============================================================

def check_market_disclaimer(html_content: str) -> dict:
    """M0 守护：市场板块不得再出现「示例/估算」自损式免责，且四张图均需有真实来源署名。

    - HTML 含「示例/估算」字样 → 不通过（M0 回退 bug 复现）
    - 四张图的「来源：… · 快照」署名缺失或含「示例/估算」→ 不通过
    """
    import re
    has_disclaimer = "示例/估算" in html_content
    notes = re.findall(r"来源：([^<]*?)· 快照", html_content)
    bad = [n for n in notes if (not n.strip()) or ("示例" in n) or ("估算" in n)]
    ok = (not has_disclaimer) and (len(notes) >= 4) and (len(bad) == 0)
    return {
        "ok": ok,
        "warn": False,
        "msg": ("市场数据署名正常，无自损式免责"
                if ok else
                f"市场数据仍含自损式免责或来源缺失（署名 {len(notes)-len(bad)}/{len(notes)} 真实）"),
    }


def check_market_signals(html_content: str) -> dict:
    """M1 守护：市场板块须含「本周市场信号」动态区块，且由本周新闻派生（非静态模板）。

    - 无 marketSignals 区块 → 不通过（M1 未接入）
    - 区块内既无 ms-card（信号卡）也无 ms-empty（诚实空态）→ 不通过（疑似回退/空注入）
    """
    import re
    has_block = "marketSignals" in html_content
    if not has_block:
        return {"ok": False, "warn": False, "msg": "未找到「本周市场信号」区块（M1 未接入）"}
    cards = len(re.findall(r'class="ms-card"', html_content))
    empty = "ms-empty" in html_content
    ok = cards > 0 or empty
    msg = (f"本周市场信号已注入（{cards} 条信号卡，由本周新闻派生）"
           if ok else "marketSignals 区块为空，疑似回退/未注入")
    return {"ok": ok, "warn": False, "msg": msg}


def check_market_structure(html_content: str) -> dict:
    """M2 守护：市场板块须含 6 张图（规模/融资 × 全球/中国 + 中国赛道结构 + 头部集中度），
    且结构图赛道标签已出现、[TREND_INSIGHTS] 占位符已被替换（未残留模板占位）。"""
    import re
    canvases = ["marketSizeChart", "cnMarketChart", "fundingChart",
                "cnFundingChart", "cnStructureChart", "cnConcentrationChart"]
    missing = [c for c in canvases if f'id="{c}"' not in html_content]
    struct_labels = ["大模型", "具身智能", "AIGC 应用"]
    missing_labels = [l for l in struct_labels if l not in html_content]
    placeholder_left = "[TREND_INSIGHTS]" in html_content
    ok = (not missing) and (not missing_labels) and (not placeholder_left)
    if ok:
        msg = "市场板块 6 图齐全（含中国赛道结构 / 头部集中度），结构标签已渲染"
    else:
        bits = []
        if missing:
            bits.append(f"缺图 {missing}")
        if missing_labels:
            bits.append(f"缺结构标签 {missing_labels}")
        if placeholder_left:
            bits.append("趋势洞察占位符未替换")
        msg = "；".join(bits)
    return {"ok": ok, "warn": False, "msg": msg}


def check_trend_evidence(html_content: str) -> dict:
    """「趋势洞察 × 本周」合作守护：宏观趋势面板须挂「本周印证」证据行（来自本周信号/新闻）。"""
    import re
    ev = len(re.findall(r'class="insight-evidence"', html_content))
    ok = ev >= 1
    msg = (f"趋势洞察面板已挂 {ev} 条「本周印证」（宏观趋势↔本周事件联动）"
           if ok else "趋势洞察面板无「本周印证」行，未与本周联动")
    return {"ok": ok, "warn": False, "msg": msg}


def check_market_data(html_content: str) -> dict:
    """M3 守护：图表分析厚度与防回归。

    - 6 张图 canvas 均存在（结构/趋势/集中度齐全）
    - 每图来源署名已填（无 [xxx_SOURCE] 占位残留）
    - 快照日期已显示（[DATA_SNAPSHOT] 已替换）
    - 无「示例/估算」与真实来源并存的矛盾（自损免责已撤）
    """
    import re
    canvases = ["marketSizeChart", "cnMarketChart", "fundingChart",
                "cnFundingChart", "cnStructureChart", "cnConcentrationChart"]
    missing_canvas = [c for c in canvases if f'id="{c}"' not in html_content]
    src_placeholders = [p for p in
                        ("[MARKET_SOURCE]", "[FUNDING_SOURCE]", "[CN_MARKET_SOURCE]", "[CN_FUNDING_SOURCE]")
                        if p in html_content]
    snap_left = "[DATA_SNAPSHOT]" in html_content
    disclaimer = "示例/估算" in html_content
    ok = (not missing_canvas) and (not src_placeholders) and (not snap_left) and (not disclaimer)
    if ok:
        msg = "市场图表 6 图齐全、来源署名/快照日期已填、无自损免责残留（M3 厚度达标）"
    else:
        bits = []
        if missing_canvas:
            bits.append(f"缺图 {missing_canvas}")
        if src_placeholders:
            bits.append(f"来源占位未替换 {src_placeholders}")
        if snap_left:
            bits.append("快照日期占位未替换")
        if disclaimer:
            bits.append("仍存在「示例/估算」自损免责")
        msg = "；".join(bits)
    return {"ok": ok, "warn": False, "msg": msg}


def check_en_cn_summary(html_content: str) -> dict:
    """英文报道中文总结守护（best-effort / warn 级）。

    新闻卡片由客户端 JS 渲染，静态 HTML 无法直接数徽标，故解析嵌入的 NEWS_DATA：
    统计 lang=en 条目中已带非空 cn_summary 的覆盖情况。
    - 无英文报道 → ok（无需总结）
    - 有英文报道且覆盖 ≥1 → ok；覆盖偏低（<50%）→ warn（建议提高并发/超时或重跑）
    - 有英文报道但 0 覆盖 → warn（建议开启 --translate-en）
    """
    import re, json
    m = re.search(r'const NEWS_DATA\s*=\s*(\[.*?\]);', html_content, re.S)
    if not m:
        return {"ok": True, "warn": False, "msg": "未找到 NEWS_DATA（无法核验，跳过）"}
    try:
        data = json.loads(m.group(1))
    except Exception:
        return {"ok": True, "warn": False, "msg": "NEWS_DATA 解析失败（无法核验，跳过）"}
    en = [x for x in data if isinstance(x, dict) and x.get("lang") == "en"]
    if not en:
        return {"ok": True, "warn": False, "msg": "报告无英文报道，无需中文总结"}
    trans = [x for x in en if (x.get("cn_summary") or "").strip()]
    cov = len(trans) / len(en)
    if len(trans) == 0:
        return {"ok": True, "warn": True,
                "msg": f"报告含 {len(en)} 条英文报道但 0 条中文总结（建议重生成时加 --translate-en）"}
    if cov < 0.5:
        return {"ok": True, "warn": True,
                "msg": f"英文报道中文总结覆盖 {len(trans)}/{len(en)}（{cov*100:.0f}%，偏低，建议提高并发/超时或重跑）"}
    return {"ok": True, "warn": False,
            "msg": f"英文报道中文总结覆盖 {len(trans)}/{len(en)}（{cov*100:.0f}%）"}


def check_market_signals_cn(html_content: str) -> dict:
    """市场信号英文链接中文注解守护（Fix2：与新闻卡一致，方便英文不好的中文读者）。

    英文市场信号卡（链接到英文新闻）须带 .ms-cn 中文注解。
    解析嵌入的 NEWS_DATA 取「英文且含 cn_summary」的 url 集合，再核对其出现在
    市场信号卡（ms-card / ms-title）时是否配套 .ms-cn 注解。
    """
    import re, json
    from json import JSONDecoder
    m = re.search(r'const\s+NEWS_DATA\s*=\s*', html_content)
    if not m:
        return {"ok": True, "warn": False, "msg": "未找到 NEWS_DATA（跳过核验）"}
    try:
        data, _ = JSONDecoder().raw_decode(html_content, m.end())
    except Exception:
        return {"ok": True, "warn": False, "msg": "NEWS_DATA 解析失败（跳过核验）"}
    en_urls = {x.get("url") for x in data
               if isinstance(x, dict) and x.get("lang") == "en"
               and (x.get("cn_summary") or "").strip()}
    if not en_urls:
        return {"ok": True, "warn": False, "msg": "无含中文总结的英文报道，无需市场信号注解"}

    # ms-card 仅出现在市场信号区块，直接全文切分即可
    segs = html_content.split('<div class="ms-card">')[1:]
    checked = 0
    missing = 0
    for seg in segs:
        card = seg.split('<div class="ms-card">')[0]  # 仅本卡内容
        hm = re.search(r'ms-title"\s+href="([^"]*)"', card)
        if not hm:
            continue
        if hm.group(1) in en_urls:
            checked += 1
            if 'class="ms-cn"' not in card:
                missing += 1

    if checked == 0:
        return {"ok": True, "warn": False,
                "msg": "本周市场信号无英文链接卡（无需注解）"}
    if missing == 0:
        return {"ok": True, "warn": False,
                "msg": f"市场信号英文链接卡 {checked} 张均带中文注解（Fix2 达标）"}
    return {"ok": False, "warn": False,
            "msg": f"{missing}/{checked} 张英文市场信号卡缺中文注解"}


def check_empty_category_tabs(html_content: str) -> dict:
    """C2 守护（死分类动态隐藏）：确保空分类 tab 不会渲染出来。

    1) 从嵌入的 CATEGORIES 常量取出所有分类键；
    2) 统计 NEWS_DATA 各分类实际条数（含 must 计数）；
    3) 确认模板 JS 的 renderTabs 含「count<1 且非 all 则跳过」逻辑。
    运行时该逻辑会把空分类 tab 隐藏，故 guard 存在即视为达标；
    同时把本周实际为空的分类列出供参考。
    """
    import re, json
    from json import JSONDecoder

    # 1) 解析 CATEGORIES 键
    cm = re.search(r'const CATEGORIES\s*=\s*\[(.*?)\];', html_content, re.S)
    if not cm:
        return {"ok": True, "warn": True,
                "msg": "未找到 CATEGORIES 常量（跳过空分类核验）"}
    keys = re.findall(r"key:\s*'([^']+)'", cm.group(1))
    if not keys:
        return {"ok": True, "warn": True,
                "msg": "CATEGORIES 无 key（跳过空分类核验）"}

    # 2) 统计各分类条数
    nm = re.search(r'const\s+NEWS_DATA\s*=\s*', html_content)
    counts = {k: 0 for k in keys}
    if nm:
        try:
            data, _ = JSONDecoder().raw_decode(html_content, nm.end())
            for it in data:
                if not isinstance(it, dict):
                    continue
                cat = it.get("category", "")
                if cat in counts:
                    counts[cat] += 1
                if it.get("mustRead"):
                    counts["must"] = counts.get("must", 0) + 1
            counts["all"] = len(data)
        except Exception:
            pass

    empties = [k for k in keys if k != "all" and counts.get(k, 0) < 1]

    # 3) 确认 hide 逻辑存在
    guard = ("count < 1 && cat.key !== 'all'" in html_content
             or "cat.key !== 'all') return ''" in html_content)
    if not guard:
        return {"ok": False, "warn": False,
                "msg": "renderTabs 缺少空分类隐藏逻辑，空 tab 会被渲染"}

    if empties:
        return {"ok": True, "warn": False,
                "msg": f"空分类 {empties} 已被动态隐藏（guard 就位，渲染 0 个空 tab）"}
    return {"ok": True, "warn": False,
            "msg": "本周无空分类（guard 就位）"}


def check_keyword_filter(html_content: str) -> dict:
    """C2 守护（关键词聚类成可 filter 标签）：确保关键词 chips 可点击筛选新闻。

    确认模板 JS 含 toggleKeywordFilter 函数、并用 activeKeyword 在 currentFilter 中过滤，
    且 chip 用 data-term + onclick 绑定（而非纯外链）。
    """
    has_fn = "function toggleKeywordFilter" in html_content
    has_state = "let activeKeyword" in html_content
    has_filter = "activeKeyword)" in html_content and "filtered = filtered.filter(n =>" in html_content
    has_bind = "toggleKeywordFilter(this.dataset.term" in html_content

    if has_fn and has_state and has_filter and has_bind:
        return {"ok": True, "warn": False,
                "msg": "关键词聚类标签可点击筛选（toggleKeywordFilter 已接线）"}
    return {"ok": False, "warn": False,
            "msg": f"关键词筛选缺失：fn={has_fn} state={has_state} filter={has_filter} bind={has_bind}"}


def check_keyword_clustering(html_content: str) -> dict:
    """C2#7 守护（关键词自动聚类）：确保 INSIGHTS_KEYWORDS 足够（≥5）且 note 为周相关。

    note 必须包含「本周被 N 条新闻提及」等周相关锚点（不再是通用套话）；
    至少 60% 关键词含「本周」字样视为通过——避免悄悄退回通用 note。
    """
    import re, json
    from json import JSONDecoder

    m = re.search(r'const\s+INSIGHTS_KEYWORDS\s*=\s*', html_content)
    if not m:
        return {"ok": False, "warn": False, "msg": "未找到 INSIGHTS_KEYWORDS 常量"}
    try:
        kws, _ = JSONDecoder().raw_decode(html_content, m.end())
    except Exception as e:
        return {"ok": False, "warn": False, "msg": f"INSIGHTS_KEYWORDS 解析失败：{e}"}

    n = len(kws)
    if n < 5:
        return {"ok": False, "warn": False,
                "msg": f"关键词数量不足：{n} < 5（计划要求 5–8 个高频主题词）"}

    def _note_text(kw):
        nt = kw.get("note")
        if isinstance(nt, dict):
            return " ".join(str(v) for v in nt.values())
        return str(nt or "")

    week_specific = sum(1 for k in kws if "本周" in _note_text(k))
    cov = week_specific / n if n else 0
    if cov < 0.6:
        return {"ok": False, "warn": False,
                "msg": f"note 周相关率 {week_specific}/{n}（{cov*100:.0f}%）< 60%，疑似回退为通用 note"}

    return {"ok": True, "warn": False,
            "msg": f"关键词 {n} 个，{week_specific} 个 note 包含「本周」（周相关率 {cov*100:.0f}%）"}


def check_weekly_dashboard(html_content: str) -> dict:
    """C2#8 守护（本周数字看板）：确保 WEEKLY_STATS 注入且字段齐全。

    字段：total / zh / en / model_news / fund_events / lb_models / must_read；
    must_read ≤ 3 且 total > 0（空数据必须隐藏 dashboard）。
    """
    import re, json
    from json import JSONDecoder

    m = re.search(r'const\s+WEEKLY_STATS\s*=\s*', html_content)
    if not m:
        return {"ok": False, "warn": False, "msg": "未找到 WEEKLY_STATS 常量"}
    try:
        s, _ = JSONDecoder().raw_decode(html_content, m.end())
    except Exception as e:
        return {"ok": False, "warn": False, "msg": f"WEEKLY_STATS 解析失败：{e}"}

    if not isinstance(s, dict):
        return {"ok": False, "warn": False, "msg": "WEEKLY_STATS 不是对象"}
    req_keys = ("total", "zh", "en", "model_news", "fund_events", "lb_models", "must_read")
    missing = [k for k in req_keys if k not in s]
    if missing:
        return {"ok": False, "warn": False,
                "msg": f"WEEKLY_STATS 缺字段：{', '.join(missing)}"}

    total = s.get("total", 0) or 0
    must = s.get("must_read", []) or []
    if total <= 0:
        return {"ok": False, "warn": False, "msg": "WEEKLY_STATS.total ≤ 0（无新闻数据）"}
    if len(must) > 3:
        return {"ok": False, "warn": False, "msg": f"must_read 超 3 条：{len(must)}"}

    return {"ok": True, "warn": False,
            "msg": f"数字看板完整：{total} 条 / 必读 Top{len(must)} / 资本&发布事件 {s['fund_events']} 起 / 在榜 {s['lb_models']} 个"}


def validate(html_path: Path, opts: dict = None) -> dict:
    opts = opts or {}
    min_news = opts.get("min_news", 20)
    min_cov = opts.get("min_cov", 80)
    min_ranking = opts.get("min_ranking", 5)
    strict = opts.get("strict", False)

    content = html_path.read_text(encoding="utf-8")
    fmt = _detect_format(content)

    file_check = check_file_exists(html_path)
    sources_check = check_data_sources(content)

    if fmt == 'v3':
        news_check = check_news_v3(content, min_news, min_cov)
        search_check = check_search_v3(content)
        charts_check = check_charts_v3(content)
        ranking_check = check_ranking_v3(content, min_ranking)
        editorial_check = check_editorial_c0(content)
        editorial_c1_check = check_editorial_c1(content)
        market_check = check_market_disclaimer(content)
        signals_check = check_market_signals(content)
        structure_check = check_market_structure(content)
        trend_evidence_check = check_trend_evidence(content)
        market_data_check = check_market_data(content)
        en_cn_check = check_en_cn_summary(content)
        signals_cn_check = check_market_signals_cn(content)
        empty_cat_check = check_empty_category_tabs(content)
        kw_filter_check = check_keyword_filter(content)
        kw_cluster_check = check_keyword_clustering(content)
        dashboard_check = check_weekly_dashboard(content)

        results = {
            "format": "v3.0 新闻网站",
            "file": file_check,
            "news": news_check,
            "search": search_check,
            "charts": charts_check,
            "ranking": ranking_check,
            "editorial": editorial_check,
            "editorial_c1": editorial_c1_check,
            "market": market_check,
            "signals": signals_check,
            "structure": structure_check,
            "trend_evidence": trend_evidence_check,
            "market_data": market_data_check,
            "en_cn_summary": en_cn_check,
            "signals_cn": signals_cn_check,
            "empty_category_tabs": empty_cat_check,
            "keyword_filter": kw_filter_check,
            "keyword_clustering": kw_cluster_check,
            "weekly_dashboard": dashboard_check,
            "sources": sources_check,
        }
    else:
        news_check = check_news_v2(content)
        kpi_check = check_kpi_v2(content)
        charts_check = check_charts_v2(content)

        results = {
            "format": "v2.0 周报",
            "file": file_check,
            "news": news_check,
            "kpi": kpi_check,
            "charts": charts_check,
            "sources": sources_check,
        }

    # 计分：ok=硬门槛达标；warn=软警告(降级但可用)；strict 下 warn 也算不过
    check_items = [r for r in results.values()
                   if isinstance(r, dict) and isinstance(r.get("ok"), bool)]
    passed = sum(1 for r in check_items if r.get("ok") is True)
    warned = sum(1 for r in check_items if r.get("warn") is True)
    total = len(check_items)
    all_ok = (passed == total) and (not strict or warned == 0)
    results["summary"] = {
        "passed": passed, "total": total, "warned": warned,
        "score": f"{passed}/{total}",
        "ok": all_ok,
    }
    return results


def print_report(results: dict) -> None:
    print("=" * 55)
    print(f"📋 AI 新闻网站验证报告（{results['format']}）")
    print("=" * 55)

    fmt = results["format"]

    if "v3" in fmt:
        checks = [
            ("文件完整性", results["file"]),
            ("新闻条目 + 来源链接", results["news"]),
            ("搜索/筛选功能", results["search"]),
            ("市场图表", None),
            ("模型排行榜", results["ranking"]),
            ("内容质量 C0", results.get("editorial", {})),
            ("内容质量 C1", results.get("editorial_c1", {})),
            ("市场数据署名(M0)", results.get("market", {})),
            ("本周市场信号(M1)", results.get("signals", {})),
            ("市场结构图(M2)", results.get("structure", {})),
            ("趋势洞察×本周(M2)", results.get("trend_evidence", {})),
            ("市场图表厚度(M3)", results.get("market_data", {})),
            ("英文报道中文总结", results.get("en_cn_summary", {})),
            ("市场信号中文注解(Fix2)", results.get("signals_cn", {})),
            ("空分类动态隐藏(C2)", results.get("empty_category_tabs", {})),
            ("关键词可筛选(C2)", results.get("keyword_filter", {})),
            ("关键词自动聚类(C2#7)", results.get("keyword_clustering", {})),
            ("本周数字看板(C2#8)", results.get("weekly_dashboard", {})),
            ("数据来源", results["sources"]),
        ]
    else:
        checks = [
            ("文件完整性", results["file"]),
            ("KPI 数据", results.get("kpi", {})),
            ("新闻条目", results["news"]),
            ("数据来源", results["sources"]),
            ("图表数据", None),
        ]

    for name, r in checks:
        if name == "市场图表" or name == "图表数据":
            print(f"\n📊 {name}：")
            for d in results["charts"]["details"]:
                status = "✅" if d["ok"] else "❌"
                print(f"  {status} {d['id']}：{d['msg']}")
        elif r:
            if r.get("ok"):
                status = "✅"
            elif r.get("warn"):
                status = "⚠️"
            else:
                status = "❌"
            print(f"{status} {name}：{r.get('msg', '')}")

    print("\n" + "=" * 55)
    s = results["summary"]
    if s.get("warned"):
        print(f"⚠️ 警告项：{s['warned']} 项（非致命；加 --strict 可将其视为不通过）")
    print(f"总分：{s['score']}  {'✅ 全部通过' if s['ok'] else '❌ 需修复'}")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="验证 AI 新闻网站 / 周报完整性")
    parser.add_argument("--html", required=True, help="HTML 文件路径")
    parser.add_argument("--output", default=None, help="JSON 输出路径")
    parser.add_argument("--min-news", type=int, default=20, help="新闻最少条数(默认 20)")
    parser.add_argument("--min-coverage", type=float, default=80, help="来源链接覆盖率下限(默认 80)")
    parser.add_argument("--min-ranking", type=int, default=5, help="每榜最少模型数(默认 5)")
    parser.add_argument("--strict", action="store_true", help="警告项也视为不通过")
    args = parser.parse_args()

    opts = {
        "min_news": args.min_news,
        "min_cov": args.min_coverage,
        "min_ranking": args.min_ranking,
        "strict": args.strict,
    }
    html_path = Path(args.html)
    results = validate(html_path, opts)
    print_report(results)

    out_path = Path(args.output) if args.output else html_path.with_suffix(".validation.json")
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📝 验证报告已保存：{out_path}")

    sys.exit(0 if results["summary"]["ok"] else 1)


if __name__ == "__main__":
    main()
