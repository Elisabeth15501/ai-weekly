"""aiweekly · AI 周报生成器内部包。

设计原则：
- 按职责垂直切分：utils（日期/网络/区域）/ translate（Ollama）/ news（抓取·归一·评分）
  / market（市场数据·图表）/ leaderboard（多源榜）/ insights（看点·关键词·看板）。
- 公开 API 通过包级 re-export 暴露；外部仍可用 `from generate_site import generate`（兼容垫层）。
- 模块内部私有函数以下划线前缀，模块级 `__all__` 显式声明对外接口。

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
    "_ollama_translate", "translate_en_summaries",
    # news
    "SUMMARY_MAX", "SUMMARY_TARGET", "MUSTREAD_TOP_N", "LEADERBOARD_STALE_DAYS",
    "SOURCE_ALIASES", "SOURCE_AUTHORITY", "CATEGORY_WEIGHT",
    "DEFAULT_SOURCE_AUTHORITY", "DEFAULT_CATEGORY_WEIGHT", "OPEN_SOURCE_PROVIDERS",
    "merge_external_news", "format_news_items",
    "_normalize_source", "_detect_lang", "_normalize_summary",
    "_is_open_source", "_score_news", "get_default_ranking",
]