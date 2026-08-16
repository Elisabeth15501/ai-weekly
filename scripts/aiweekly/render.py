"""渲染层：把新闻 / 榜单 / 市场 / 看点数据填进单文件 HTML 模板。

从 generate_site.py 抽出（P1#1 Phase 3），`generate()` 是整条管线的装配点。
外部仍可 `from generate_site import generate`（兼容垫层）。

关键约束：看点卡、「给本周的你」、关键词彩标、趋势洞察「本周印证」四块
**全部在此服务端预渲染为静态 HTML**，禁用 JS 时仍可见。
"""
import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from aiweekly.utils import _parse_date_arg, _parse_snapshot_date
from aiweekly.news import (
    MUSTREAD_TOP_N, format_news_items, _score_news, LEADERBOARD_STALE_DAYS,
)
from aiweekly.translate import Translator
from aiweekly.leaderboard import (
    _apply_profile_as_truth, _leaderboard_freshness,
)
from aiweekly.market import (
    build_charts, BASE_SOURCES,
    DEFAULT_MARKET_SOURCE, DEFAULT_FUNDING_SOURCE,
    DEFAULT_CN_MARKET_SOURCE, DEFAULT_CN_FUNDING_SOURCE,
    _extract_market_signals, _compute_weekly_stats, _lb_name_map,
    _render_market_signals_html_with_theme, _render_trend_insights_html,
)
from aiweekly.insights import (
    _DEFAULT_AUDIENCE_SUMMARY, _auto_insights, _auto_lead, _auto_keywords,
    _normalize_keywords, _is_daily_digest,
    _render_audience_chips_html, _render_keyword_chips_html,
    DEFAULT_ACTIVE_AUDIENCE, DEFAULT_SEARCH_ENGINE,
)

SKILL_DIR = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = SKILL_DIR / "assets" / "news_site_template.html"

__all__ = ["generate", "TEMPLATE_PATH", "SKILL_DIR"]


def _json_script_safe(obj) -> str:
    """把对象序列化为可安全嵌入 <script> 的 JSON 字符串。

    关键安全修复：RSS / 外部新闻内容是不可信输入，若其中含 ``</script>``，
    Python 默认的 ``json.dumps`` 不会转义，会被 HTML 解析器识别为脚本块结束，
    从而突破 <script> 上下文执行任意 JS（存储型 XSS）。这里把 < > & 转义为
    Unicode 形式（\\u003c 等），既阻止 ``</script>`` 突破，又保证之后经
    innerHTML + escapeHtml 渲染时按纯文本显示。
    """
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def _js_str(s: str) -> str:
    """转义为 JS 字符串字面量（用于 ``const X = "[...]"`` 上下文）。"""
    if not s:
        return ""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\r", "\\r")
             .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _safe_url(u: str) -> str:
    """仅放行 http(s)/mailto 协议的 URL，其余回退 '#'（防 javascript: 等危险协议）。"""
    from urllib.parse import urlparse
    try:
        scheme = urlparse(u or "").scheme.lower()
    except ValueError:
        return "#"
    return u if scheme in ("http", "https", "mailto") else "#"


def generate(api_data: dict, output_path: str = None,
             date_range: str = None, ranking_source: str = "unavailable",
             market_data: list = None, market_labels: list = None,
             funding_data: list = None, funding_labels: list = None,
             market_source: str = None, funding_source: str = None,
             cn_market_data: list = None, cn_market_labels: list = None,
             cn_funding_data: list = None, cn_funding_labels: list = None,
             cn_market_source: str = None, cn_funding_source: str = None,
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
             pin_terms: list = None,
             translate_en: bool = False,
             translate_model: str = "qwen2.5:7b",
             translate_workers: int = 3,
             translate_timeout: int = 45,
             translate_retries: int = 2,
             translate_num_predict: int = 600,
             translate_title: bool = True,
             translate_cache: str = None) -> str:
    """生成完整的新闻网站 HTML。

    Args:
        api_data: 新闻 JSON（RSS 兼容格式，含 items[]）
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

    # 英文报道中文总结：生成途中遇英文即即时中译（本地 Ollama 服务，best-effort 不阻断）
    if translate_en:
        _tr = Translator(
            enabled=True, model=translate_model,
            timeout=translate_timeout, max_workers=translate_workers,
            retries=translate_retries, num_predict=translate_num_predict,
            translate_title=translate_title, cache_path=translate_cache)
        try:
            n_tr = _tr.translate_items(api_data.get("items", []))
            if n_tr:
                print(f"🌐 英文报道中文总结：本地 Ollama 翻译 {n_tr} 条（模型 {translate_model}）")
        except Exception as e:  # noqa: BLE001  best-effort：任何异常都不阻断报告生成
            print(f"  ⚠️ 英文翻译跳过（Ollama 不可用或异常）：{e}")

    # 格式化新闻数据（含信源/摘要归一化 + cn_summary 透传）
    news_items = format_news_items(api_data)
    # C0：重要度评分 + 🔥必读标记（仅排序/标记，不篡改事实字段）
    _score_news(news_items, report_date=report_date, top_n=MUSTREAD_TOP_N, pin_terms=pin_terms)
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
    final_leaderboard["meta"]["snapshot_per_source_age"] = _lb_fresh["per_source_age"]
    if _lb_fresh["stale"]:
        print(f"  ⚠️ 排行榜快照时效告警：最新快照距本期 {_lb_fresh['worst_age']} 天"
              f"（阈值 {LEADERBOARD_STALE_DAYS} 天），部分榜单为「非本周抓取」——"
              f"建议刷新 cn_leaderboard_snapshot.json 或加 --proxy 实时刷新。")
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
                                _json_script_safe(news_items))
    template = template.replace("[LEADERBOARD_DATA_PLACEHOLDER]",
                                _json_script_safe(final_leaderboard))
    template = template.replace("[CHART_DATA_PLACEHOLDER]", chart_code)

    if not date_range:
        today = (_parse_date_arg(report_date) if report_date
                 else datetime.now().astimezone())
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
                         if report_date else datetime.now().astimezone().strftime("%Y-%m-%d"))
    template = template.replace("[DATA_SNAPSHOT]", data_snapshot)

    # 页脚数据来源：基础列表 + 用户自备的外部 API（仅当用户显式提供）
    # 外部来源名/URL 由用户 CLI 提供，按不可信输入处理：转义 + 仅放行安全协议
    sources = [(html.escape(n), _safe_url(u)) for n, u in BASE_SOURCES]
    news_extra = ""
    if external_source and external_source[0]:
        ext_name, ext_url = external_source[0], (external_source[1] or "")
        safe_url = _safe_url(ext_url) if ext_url else ""
        ext_name_e = html.escape(ext_name)
        if safe_url:
            sources.append((ext_name_e, safe_url))
            news_extra = f' 与 <a href="{html.escape(safe_url, quote=True)}" target="_blank" rel="noopener">{ext_name_e}</a>'
        else:
            news_extra = f' 与 {ext_name_e}'
    all_sources_html = '、'.join(
        f'<a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">{n}</a>' for n, u in sources
    )
    template = template.replace("[ALL_SOURCES]", all_sources_html)
    template = template.replace("[NEWS_SOURCE_EXTRA]", news_extra)
    template = template.replace("[GEN_DATE]", datetime.now().astimezone().isoformat(timespec="minutes"))  # P0#16

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
                                _json_script_safe(_kw or []))
    template = template.replace("[INSIGHTS_DATA_PLACEHOLDER]",
                                _json_script_safe(_insights or []))
    # C2#8：本周数字看板（JSON 注入，模板 JS 渲染；服务端兜底也写入静态 HTML）
    template = template.replace("[WEEKLY_STATS_PLACEHOLDER]",
                                _json_script_safe(weekly_stats or {}))
    template = template.replace("[LEAD]", html.escape(_lead or ""))
    # 受众结论：未传入则回退内置默认三段（开发者/PM/自媒体），确保「给本周的你」始终出现
    template = template.replace("AUDIENCE_SUMMARY_PLACEHOLDER",
                                _json_script_safe(audience_summary or _DEFAULT_AUDIENCE_SUMMARY))
    template = template.replace("KEYWORD_SEARCH_SOURCES_PLACEHOLDER",
                                keyword_search_sources or '{"baidu":"https://www.baidu.com/s?wd=","google":"https://www.google.com/search?q=","arxiv":"https://arxiv.org/search/?query="}')
    # 关键词网页搜索基址（默认百度；搜索词 = 「词语 AI 行业」）
    template = template.replace("[KEYWORD_SEARCH_BASE]", _js_str(keyword_search_base))

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
