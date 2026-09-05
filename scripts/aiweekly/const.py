"""aiweekly.const — 硬约束常量集中声明（P2-1：边界条件集中声明）。

所有影响输出大小、性能、质量的限制都定义在此处，便于维护和调整。

变更时同步更新 SKILL.md 第二节「硬约束」小节和 README「已知限制」。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 新闻抓取限制
# ---------------------------------------------------------------------------
NEWS_MAX_ITEMS: int = 100         # 单次抓取上限，超过截取前 N 条
NEWS_MIN_SCORE: float = 0.0       # 新闻最低重要度评分（低于此值被过滤）
NEWS_DATE_CUTOFF_DAYS: int = 7    # 超过 N 天前的新闻标注 [n天前]
NEWS_SUMMARY_MAX_CHARS: int = 120  # 摘要最大字符数（触发归一化）

# ---------------------------------------------------------------------------
# 排行榜限制
# ---------------------------------------------------------------------------
LEADERBOARD_TOP_N: int = 50       # 每榜最多显示条数（超过截取 top N）
LEADERBOARD_MAX_MODELS: int = 50  # 单榜最大模型数（防止 HTML 过大）
LEADERBOARD_STALE_DAYS: int = 14  # 超过 N 天未更新的模型标注为「旧」

# ---------------------------------------------------------------------------
# 图表数据限制
# ---------------------------------------------------------------------------
CHART_MAX_DATA_POINTS: int = 20   # 单条趋势线最大数据点数（超出处以平均值）
MARKET_DATA_SOURCE_REQUIRED: bool = True  # 市场数据是否强制要求来源（True=必须搜索）

# ---------------------------------------------------------------------------
# HTML 输出限制
# ---------------------------------------------------------------------------
HTML_MAX_SIZE_BYTES: int = 5 * 1024 * 1024  # 建议 ≤5MB（超过会自动压缩 Chart.js 数据）
CHART_JS_COMPRESS_THRESHOLD: int = 3 * 1024 * 1024  # 超过此大小触发压缩

# ---------------------------------------------------------------------------
# 内容生成限制
# ---------------------------------------------------------------------------
SUMMARY_TARGET_CHARS: int = 600   # 摘要目标长度（避免截断）
MUSTREAD_TOP_N: int = 8           # 评分最高的前 N 条标记为必读
SELECTION_NOTES_MAX_LENGTH: int = 200  # 选型结论最大字符数

# ---------------------------------------------------------------------------
# 部署限制
# ---------------------------------------------------------------------------
DEPLOY_TIMEOUT_SECONDS: int = 120  # 单次部署超时（秒）
DEPLOY_MAX_RETRIES: int = 2       # 部署失败重试次数

# ---------------------------------------------------------------------------
# 网络限制
# ---------------------------------------------------------------------------
HTTP_TIMEOUT_SECONDS: int = 30    # 单次 HTTP 请求超时
HTTP_MAX_RETRIES: int = 3         # 失败重试次数
HTTP_RETRY_DELAY_SECONDS: float = 1.0  # 重试间隔

__all__ = [
    "NEWS_MAX_ITEMS", "NEWS_MIN_SCORE", "NEWS_DATE_CUTOFF_DAYS", "NEWS_SUMMARY_MAX_CHARS",
    "LEADERBOARD_TOP_N", "LEADERBOARD_MAX_MODELS", "LEADERBOARD_STALE_DAYS",
    "CHART_MAX_DATA_POINTS", "MARKET_DATA_SOURCE_REQUIRED",
    "HTML_MAX_SIZE_BYTES", "CHART_JS_COMPRESS_THRESHOLD",
    "SUMMARY_TARGET_CHARS", "MUSTREAD_TOP_N", "SELECTION_NOTES_MAX_LENGTH",
    "DEPLOY_TIMEOUT_SECONDS", "DEPLOY_MAX_RETRIES",
    "HTTP_TIMEOUT_SECONDS", "HTTP_MAX_RETRIES", "HTTP_RETRY_DELAY_SECONDS",
]
