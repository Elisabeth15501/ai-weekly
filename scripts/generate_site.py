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
from aiweekly.translate import (
    _ollama_translate, translate_en_summaries, ollama_health, _ollama_base_url,
)
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


# ── P1#1 Phase 2：榜单 / 市场 / 看点 已抽到 aiweekly 子包 ──
# 下方 re-export 保证 `from generate_site import X` 的历史调用点零改动。
from aiweekly.leaderboard import (
    LM_ARENA_URL, AA_URL, HF_DS_API, HF_LEADERBOARD_URL,
    DATALARNER_URL, LLMSTATS_URL, CACHE_PATH, COST_PATH,
    CN_SNAPSHOT_PATH, DEFAULT_PROFILES, PENDING_PROFILES, OC_LLM_URL,
    SV_GENERAL_URL, MS_MODELS_URL, _load_cost_table, _COST_TABLE,
    _match_cost, _enrich_cost, _apply_profile_as_truth, ORG_PREFIXES,
    _clean_model_slug, _SUFFIX_RE, _norm_model, fetch_lmarena_ranking,
    OPEN_SOURCE_MODEL_KEYWORDS, _is_open_source_model, fetch_aa_ranking, fetch_hf_open_ranking,
    _parse_table_rows, _parse_ctx, _parse_money, fetch_llmstats_ranking,
    DL_ORG_SPLIT, _split_dl_org, fetch_datalearner_ranking, _load_cn_snapshot,
    _leaderboard_freshness, fetch_opencompass_ranking, fetch_superclue_ranking, fetch_modelscope_ranking,
    LB_CRITERIA, SOURCES, _load_cache, _save_cache,
    _apply_deltas, fetch_all_leaderboards, _fill_from_cache, _collect_leaderboard_models,
    sync_model_profiles,
)

from aiweekly.market import (
    DEFAULT_MARKET_LABELS, DEFAULT_MARKET_DATA, DEFAULT_FUNDING_LABELS, DEFAULT_FUNDING_DATA,
    DEFAULT_CN_MARKET_LABELS, DEFAULT_CN_MARKET_DATA, DEFAULT_CN_FUNDING_LABELS, DEFAULT_CN_FUNDING_DATA,
    DEFAULT_CN_STRUCTURE_LABELS, DEFAULT_CN_STRUCTURE_DATA, DEFAULT_CN_CONCENTRATION_LABELS, DEFAULT_CN_CONCENTRATION_DATA,
    DEFAULT_MARKET_SOURCE, DEFAULT_FUNDING_SOURCE, DEFAULT_CN_MARKET_SOURCE, DEFAULT_CN_FUNDING_SOURCE,
    ESTIMATE_NOTE, build_charts, BASE_SOURCES, SIGNAL_WEIGHTS,
    MODEL_HINTS, CN_HINTS, AMOUNT_RE, _extract_market_signals,
    _compute_weekly_stats, _lb_name_map, _render_market_signals_html, TREND_INSIGHTS,
    _match_insight_evidence, _signal_theme, _render_trend_insights_html, _render_market_signals_html_with_theme,
)

from aiweekly.insights import (
    _validate_insights, _AUTO_KICKERS, _AUTO_SIGNALS, _DAILY_DIGEST_MARKERS,
    _is_daily_digest, _find_related, _auto_insights, _EDITORIAL_THEMES,
    _lead_truncate, _week_tone, _auto_lead, _DEFAULT_AUDIENCE_SUMMARY,
    _AUTO_TERM_TAGS, _AUTO_KW_NOTE, _infer_tag, _KW_STOP,
    _tokenize, _auto_keywords, _normalize_keywords, _TAG_COLORS,
    DEFAULT_ACTIVE_AUDIENCE, DEFAULT_SEARCH_ENGINE, GENERIC_AUDIENCE_LABEL, _pick_preferred_key,
    _render_audience_chips_html, _kw_tag_html, _kw_tier_html, _kw_note_html,
    _kw_search_url, _render_keyword_chips_html,
)

from aiweekly.render import generate  # P1#1 Phase 3：渲染层已抽出


class _CountingWriter:
    """P1#12：包装 stdout，统计本次运行的 ⚠️/❌ 出现次数（供 run.log 聚合）。"""

    def __init__(self, stream):
        self._stream = stream
        self.warns = 0
        self.errors = 0

    def write(self, s: str) -> int:
        self.warns += s.count("⚠️")
        self.errors += s.count("❌")
        return self._stream.write(s)

    def flush(self):
        return self._stream.flush()


def _parse_csv_arg(s: str):
    """CLI 逗号字符串 -> 列表；空串返回 None。"""
    return [x.strip() for x in s.split(",")] if s else None


def _parse_num_arg(s: str):
    """CLI 逗号字符串 -> float 列表；含非数字告警并回退 None。"""
    if not s:
        return None
    try:
        return [float(x) for x in s.split(",")]
    except ValueError:
        print(f"  ⚠️ 图表数据解析失败(含非数字): {s} — 将回退估算值")
        return None


def _run_health_check(args):
    """P1#13：CLI `--health-check` —— 只探测网络与榜源可达性，不抓取、不生成（CI/定时任务前置）。

    注意：不做真实排行榜抓取（不可达源 + 指数退避会让检查卡数分钟），
    一律用 `_probe`（6s 超时）探测 URL 可达性，秒级返回。
    """
    print("🧪 健康检查（只探测，不生成报告）", flush=True)
    region = _detect_region()
    print(f"  🌐 网络环境判定：{region}", flush=True)
    probes = [
        ("百度（国内哨兵）", "https://www.baidu.com"),
        ("OpenCompass（国内榜源）", "https://rank.opencompass.org.cn/leaderboard-llm"),
        ("LMArena（国外综合榜）", "https://lmarena.ai/leaderboard"),
        ("Hugging Face（国外榜源）", "https://huggingface.co"),
    ]
    for name, url in probes:
        ok = _probe(url, timeout=6)
        print(f"  {'✅' if ok else '❌'} {name}: {'可达' if ok else '不可达'}", flush=True)
    if not args.no_live_ranking:
        for name, url in [
            ("排行榜·LMArena", "https://lmarena.ai/leaderboard"),
            ("排行榜·AA", "https://artificialanalysis.ai/"),
            ("排行榜·LLM-Stats", "https://llm-stats.com/leaderboards/open-llm-leaderboard"),
            ("排行榜·HuggingFace", "https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard"),
        ]:
            ok = _probe(url, timeout=6)
            print(f"  {'✅' if ok else '❌'} {name}: {'可达' if ok else '不可达'}", flush=True)
        print("  ℹ️ 生成时会按多源池自动回退快照/缓存，单项不可达不阻断。", flush=True)
    else:
        print("  ⏭️ 已跳过排行榜探测（--no-live-ranking）", flush=True)

    # P1#14：本地 Ollama 探测（英文中译的前置依赖，3s 超时）
    _ok, _detail = ollama_health(timeout=3.0, model=getattr(args, "translate_model", None))
    print(f"  {'✅' if _ok else '⏭️'} 本地 Ollama（--translate-en 依赖）: {_detail}", flush=True)
    if not _ok:
        print("     ↳ 不影响报告生成：未开启 --translate-en 时无关；开启时英文报道保留原文。",
              flush=True)
    print("🧪 健康检查结束。", flush=True)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="生成 AI 新闻网站 HTML")
    _counter = _CountingWriter(sys.stdout)  # P1#12：聚合本次运行的 ⚠️/❌ 计数
    sys.stdout = _counter
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
    parser.add_argument("--health-check", action="store_true",
                        help="只探测网络/榜源可达性，不生成报告（CI/定时任务前置探测）")

    args = parser.parse_args()

    # P0#17：CLI 层即时校验 ISO 8601 日期输入——非法值立刻 parser.error 退出（exit 2），
    # 不再等到渲染中途抛 ValueError 才中断（此前是「等效拦截」，现在是「即时拦截」）。
    for _flag, _val, _parse in (
        ("--date", args.date, _parse_date_arg),
        ("--data-snapshot", args.data_snapshot, _parse_snapshot_date),
    ):
        if not _val:
            continue
        try:
            if _parse(_val) is None:
                raise ValueError("无法解析为日期")
        except ValueError as _e:
            parser.error(
                f"{_flag} 需为 ISO 8601 日期："
                f"YYYY-MM-DD（如 2026-08-08）或完整形式（如 2026-08-08T00:00:00+08:00）。"
                f"收到 {_val!r} —— {_e}"
            )

    _configure_proxy()  # 应用 HTTPS_PROXY / --proxy（含 SOCKS）到本次运行

    # P1#13：健康检查子命令——只探测，不生成
    if args.health_check:
        _run_health_check(args)
        return

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
        market_data=_parse_num_arg(args.market_data),
        market_labels=_parse_csv_arg(args.market_labels),
        funding_data=_parse_num_arg(args.funding_data),
        funding_labels=_parse_csv_arg(args.funding_labels),
        market_source=args.market_source,
        funding_source=args.funding_source,
        cn_market_data=_parse_num_arg(args.cn_market_data),
        cn_market_labels=_parse_csv_arg(args.cn_market_labels),
        cn_funding_data=_parse_num_arg(args.cn_funding_data),
        cn_funding_labels=_parse_csv_arg(args.cn_funding_labels),
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

    # P1#12：错误聚合报告——把本次运行的 ⚠️/❌ 计数写入 <output>.run.log（供无人值守复盘）
    run_log = Path(output).with_suffix(".run.log")
    run_log.write_text(
        f"ai-weekly generate run @ {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"output: {output}\n"
        f"news: {count}\n"
        f"warnings: {_counter.warns}\n"
        f"errors: {_counter.errors}\n",
        encoding="utf-8",
    )
    print(f"📝 运行日志已保存：{run_log}（warnings={_counter.warns} / errors={_counter.errors}）")

    # Chart.js 已内联进 HTML(见上方 [CHARTJS_LIB_PLACEHOLDER] 替换),无需附带外部 js 文件


__all__ = [
    "main", "generate", "fetch_all_leaderboards",
]


if __name__ == "__main__":
    main()
