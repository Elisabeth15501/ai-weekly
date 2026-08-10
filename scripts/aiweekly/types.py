"""共享数据结构 TypedDict（工程债 P1#3 / Phase 2 types 模块）。

纯类型定义，无任何运行时逻辑；供 aiweekly 子包与 generate_site.py
标注函数签名（`-> list[NewsItem]` / `-> LeaderboardSlot`），
提升 IDE 智能提示与可读性（D10 消化）。

约定：
- 所有字段 `total=False`（宽松，兼容历史 JSON 缺字段）；
- 日期字段统一为 **ISO 8601 字符串**（如 `2026-08-10T12:33+08:00`）。
"""
from typing import TypedDict


class NewsItem(TypedDict, total=False):
    """单条新闻（RSS / 外部 API 合并后的统一形态）。"""
    title: str
    summary: str
    url: str
    source: str            # 已归一化的信源短名
    publishedAt: str       # ISO 8601
    category: str          # ai-models / ai-products / industry / paper / tip
    lang: str              # zh / en
    score: float           # 重要度评分（仅排序，不篡改事实）
    mustRead: bool         # 🔥必读标记
    cn_summary: str        # 英文报道的中文总结（本地 Ollama，best-effort）


class LeaderboardRow(TypedDict, total=False):
    """单个模型在某个榜源中的一行。"""
    model: str
    rank: int
    score: float
    org: str               # 机构
    developer: str         # 开发方（兼容历史字段）
    license: str
    context: int
    price_in: float
    price_out: float
    delta: int             # 周变化（WoW）
    cn_access: str         # 国内可直连标注
    open_source: bool


class LeaderboardSlot(TypedDict, total=False):
    """一个榜源的整体槽位（含元信息）。"""
    source: str            # lmarena / aa / ls / hf
    url: str
    snapshot: str          # ISO 8601
    criteria: str          # 排名标准说明
    rows: list[LeaderboardRow]
    source_region: str     # cn / global
    is_cache: bool         # 是否来自缓存/快照兜底


__all__ = ["NewsItem", "LeaderboardRow", "LeaderboardSlot"]
