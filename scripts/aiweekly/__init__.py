"""aiweekly · AI 周报生成器内部包。

设计原则：
- 按职责垂直切分（P1#1 已全部落地，10 模块）：
    types              — TypedDict 数据契约（NewsItem / LeaderboardRow / LeaderboardSlot）
    utils              — 日期解析 / 网络 IO / 代理 / 区域探测 / 重试退避
    translate          — 本地 Ollama 英文中译 + 健康探测
    news               — 外部合并 / 信源归一 / 摘要压缩 / 语言判定 / 重要度评分
    leaderboard_sources — 多源池抓取（LMArena / HF / OpenCompass / SuperCLUE / ModelScope）
    leaderboard        — 多源榜合并 / 快照兜底 / 成本与档案富化 / 选型结论
    market             — 市场规模与融资数据 / Chart.js 构建 / 本周信号 × 趋势洞察桥接
    insights           — 看点卡 / 导语 / 关键词彩标 / 受众 chips（全部服务端预渲染）
    model_meta         — 模型元数据查找（成本 / 上下文 / 许可证 / 币种）
    render             — HTML 渲染 + XSS 安全序列化
- 公开 API 通过包级 re-export 暴露；外部仍可用 `from generate_site import generate`（兼容垫层）。
  体量较大的 leaderboard / market / insights 不在包级 re-export，按需
  `from aiweekly.leaderboard import fetch_all_leaderboards` 或经 generate_site 垫层取用。
- 模块内部私有函数以下划线前缀，模块级 `__all__` 显式声明对外接口。
- 可测试性（P1#6）：`_http_get` / `_probe` / `_detect_region` / `_retry_fetch` /
  `_ollama_translate` 均接受注入参数（opener / probe / sleeper / client），单测可脱网。

变更请同步更新 AI_Weekly_Optimization_Plan.md 第十二章。
"""
from aiweekly.utils import (
    _UA,
    _PROXY_OVERRIDE,
    _SOCKS_ACTIVE,
    _resolved_proxy,
    _configure_proxy,
    _build_opener,
    _http_get,
    _probe,
    _detect_region,
    _retry_fetch,
    _parse_date_arg,
    _parse_snapshot_date,
)
from aiweekly.translate import (
    _ollama_translate,
    translate_en_summaries,
    ollama_health,
    _ollama_base_url,
)
from aiweekly.news import (
    SUMMARY_MAX,
    SUMMARY_TARGET,
    MUSTREAD_TOP_N,
    LEADERBOARD_STALE_DAYS,
    SOURCE_ALIASES,
    SOURCE_AUTHORITY,
    CATEGORY_WEIGHT,
    DEFAULT_SOURCE_AUTHORITY,
    DEFAULT_CATEGORY_WEIGHT,
    OPEN_SOURCE_PROVIDERS,
    merge_external_news,
    format_news_items,
    _normalize_source,
    _detect_lang,
    _normalize_summary,
    _is_open_source,
    _score_news,
    get_default_ranking,
)

__all__ = [
    # utils
    "_UA", "_PROXY_OVERRIDE", "_SOCKS_ACTIVE",
    "_resolved_proxy", "_configure_proxy", "_build_opener",
    "_http_get", "_probe", "_detect_region", "_retry_fetch",
    "_parse_date_arg", "_parse_snapshot_date",
    # translate
    "_ollama_translate", "translate_en_summaries", "ollama_health", "_ollama_base_url",
    # news
    "SUMMARY_MAX", "SUMMARY_TARGET", "MUSTREAD_TOP_N", "LEADERBOARD_STALE_DAYS",
    "SOURCE_ALIASES", "SOURCE_AUTHORITY", "CATEGORY_WEIGHT",
    "DEFAULT_SOURCE_AUTHORITY", "DEFAULT_CATEGORY_WEIGHT", "OPEN_SOURCE_PROVIDERS",
    "merge_external_news", "format_news_items",
    "_normalize_source", "_detect_lang", "_normalize_summary",
    "_is_open_source", "_score_news", "get_default_ranking",
]