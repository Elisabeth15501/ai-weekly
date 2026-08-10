# AI Weekly 优化方案

> 最后更新：2026-08-10 | 状态：工程债 P0/P1 已清零，X 系列跨框架兼容已落地

---

## 概述

本文档记录 ai-weekly skill 从 v1.0 到 v3.0 的迭代优化路径，按 P0（阻塞性）→ P1（改善性）→ M（市场/图表）→ C（内容/交互）→ X（跨框架兼容）分层推进。

---

## 一、P0 工程债（已清零）

| 编号 | 项目 | 状态 | 说明 |
|---|---|---|---|
| P0#2 | `__all__` 导出清单 | ✅ | `utils.py` / `__init__.py` 均含明确 `__all__` |
| P0#8 | 收窄裸 `except Exception` | ✅ | 所有裸异常加 `noqa: BLE001` 注释说明业务语义 |
| P0#9 | 结构化日志基建 | ✅ | `utils.py` 统一 HTTP 重试/代理/区域日志格式 |
| P0#10 | 重试退避策略统一 | ✅ | `_retry_fetch(idx) → min(30, 2^i) + jitter`，榜源统一调用 |
| P0#15 | `--date` 参数支持完整 ISO 8601 | ✅ | `_parse_date_arg()` 接受 `YYYY-MM-DD` 与 ISO 8601 |
| P0#16 | `GEN_DATE` 使用 `astimezone().isoformat()` | ✅ | 模板注入日期带时区偏移 |
| P0#17 | 快照日期解析支持完整 ISO 8601 | ✅ | `_parse_snapshot_date()` 兼容 `Z` 后缀与偏移 |

---

## 二、P1 工程债（已清零）

| 编号 | 项目 | 状态 | 说明 |
|---|---|---|---|
| P1#3 | `types.py` TypedDict 模块 | ✅ | `NewsItem` / `LeaderboardRow` / `LeaderboardSlot` |
| P1#6 | 依赖注入点（测试性） | ✅ | `_http_get` / `_probe` / `_detect_region` / `_retry_fetch` 均含 `opener`/`sleeper` 注入参数 |
| P1#20 | 时区统一 | ✅ | 所有 `datetime.now()` → `datetime.now(timezone.utc)` |
| P1#21 | `snapshot_per_source` ISO 8601 | ✅ | 榜源快照日期统一 `fromisoformat` 解析 |

---

## 三、M 系列：市场数据与图表

| 层级 | 项目 | 状态 | 说明 |
|---|---|---|---|
| M0 | 撤免责声明 + 真实署名 | ✅ | 页脚移除「示例数据」免责，替换为数据源署名 |
| M1 | 本周市场信号桥接卡 | ✅ | `.market-signals` 卡片 + `_signal_theme()` 印证趋势标签 |
| M2 | 中国融资当期点 + 赛道结构图 + 头部集中度图 | ✅ | 共 6 组 Chart.js 图表（全球/中国各 3 组） |
| M3 | YoY / 预测诚实度 / AI 占比 | ✅ | `build_charts()` 支持 `cn_market_*` / `cn_funding_*` 参数 |

---

## 四、C 系列：内容与交互

| 层级 | 项目 | 状态 | 说明 |
|---|---|---|---|
| C0 | 「本周看点」三块必现 | ✅ | 看点卡 + 受众摘要 + 关键词彩标均服务端预渲染 |
| C1#5 | 榜单时效标注 | ✅ | 模板 `_leaderboard_freshness()` 显示距今天数 |
| C1#6 | 看点去注水 + 扩链 | ✅ | `_auto_insights()` 过滤低质量信号 |
| C2 | 分类 tab 动态隐藏 + 关键词聚类 + 本周数字看板 | ✅ | 空分类 tab 不渲染、关键词归一化聚类、`.weekly-stats` 数字卡片 |

---

## 五、X 系列：跨框架兼容

| 编号 | 项目 | 状态 | 说明 |
|---|---|---|---|
| X1#4 | `openclaw-edition/SKILL.md` | ✅ | 含 `metadata.openclaw` 门控 + 安装器提示 |
| X1#5 | `run_report.sh` 框架无关 | ✅ | 自动探测 Python + venv，不依赖 WorkBuddy |
| X2#7 | `deploy_report.py` 解耦 WorkBuddy | ✅ | 仅提取摘要 + 纯文本拼装，推送由调用方实现 |
| X2#8 | README 能力分级 | ✅ | 核心链路 vs 框架增强明确分层 |
| X3#9 | `openclaw-edition/SKILL.md` 合规 | ✅ | 所有 AgentSkills 必需字段齐全 |
| X3#10 | `manifest.json` 通用接口描述 | ✅ | 含 `entry` / `args` / `deps` / `runtime` / `compatibility` |

---

## 六、北极星与下一步

- **北极星**：为 AI 从业者提供情报，**定时稳定推送到飞书/钉钉**，让情报在"工作者已在用的地方"被消费
- **四模块路线**：①内容层（结构化 `report.json`）→ ②分发层（飞书 Webhook + 钉钉）→ ③调度层（自动化周更）→ ④受众度量（UTM 打开率）
- **短期（P1）**：补充 `plugin.json`（OpenAI Agent Plugins 兼容，5 分钟工作量）
- **中期（P2）**：ClawHub 发布 + 飞书推送头条卡
- **格式格局**：SKILL.md 已成为 Agent 技能事实标准，ai-weekly 已在最优赛道。详见 `docs/agent-skill-format-landscape.md`
