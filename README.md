# AI Weekly Report Skill

> 生成**可搜索、可筛选、支持暗色模式**的 AI 行业新闻单文件 HTML 网站的 Agent 技能。核心引擎为纯 Python（11 模块），零 Agent SDK 依赖，产物为单文件 HTML——可被任意框架复用。**单一跨平台 `SKILL.md`**（开放 Agent Skill 规范），Claude Code / OpenAI Codex / OpenCode / OpenClaw / Coze / WorkBuddy 通用，无需任何平台专属包装。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-green.svg)](https://www.python.org/)
[![AgentSkills](https://img.shields.io/badge/spec-AgentSkills-8A2BE2)](https://github.com/anthropics/skills)
[![Cross-Platform](https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Codex%20%7C%20OpenClaw%20%7C%20Coze%20%7C%20WorkBuddy-10a37f)](./SKILL.md)

---

## 特性

- **自治优先**：新闻默认全部来自 RSS 抓取（14 个精选源：国内 7 + 国外 7，国内优先），不内置任何第三方商业 API
- **单文件交付**：所有 CSS/JS 内联，Chart.js 也内联进 HTML，无外部文件依赖，可直接托管或分享
- **高可信度**：每条新闻附带原始报道 URL；市场 / 融资数据由 WebSearch 获取真实值后注入，未提供时明确标注「示例 / 估算」
- **排行榜自适应**：多源池（LMArena / Hugging Face / OpenCompass 司南 / SuperCLUE / ModelScope），实时失败自动回退快照 / 缓存，绝不空白
- **本周看点**：自动从新闻聚类生成洞察（关键词彩标 + 本周数字 + 三受众行动建议），服务端预渲染进静态 HTML，禁 JS 也可见
- **市场数据双源**：全球 + 中国市场规模 / 融资 4 图 2×2 布局，含趋势洞察 × 本周印证桥接
- **模型资料卡**：26+ 模型档案（成本 / 上下文 / 许可证 / 币种），以 `model_profiles.json` 为唯一权威源
- **可定时**：支持每周自动生成最新版网站
- **安全加固**：RSS 不可信内容经 `<script>` 上下文 JSON 注入与 URL 属性突破均已防御

---

## 快速开始

```bash
# 1. 安装依赖（仅 3 个纯标准库：feedparser / requests / beautifulsoup4）
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 2. 抓取本周 AI 新闻（RSS）
bash run_report.sh scripts/fetch_ai_news.py --output news.json

# 3. 生成单文件新闻网站
bash run_report.sh scripts/generate_site.py --api-json news.json -o AI_News.html

# 4. 校验产出
bash run_report.sh scripts/validate_report.py --html AI_News.html
```

> **统一启动器 `run_report.sh`**：自动探测已安装依赖的 Python（优先复用 `aiweekly` 受管 venv，回退 `python3`/`python`），无需手动激活环境。支持 `--proxy` 代理、`--region` 区域探测、`--translate-en` 本地翻译、`--health-check` 健康检查等全部 CLI 参数透传。

---

## 架构

核心执行引擎（`scripts/`）为**纯 Python、零 Agent SDK 依赖**，产物为**单文件 HTML**。

```
ai-weekly/
├── SKILL.md                      # 单一跨平台入口（开放 Agent Skill 规范；Claude Code / Codex / OpenCode / OpenClaw / Coze / WorkBuddy 通用）
├── manifest.json                 # 通用框架接口描述（LangGraph / Dify / Coze 等）
├── run_report.sh                 # 统一启动器（自动探测 Python + venv，CLI 参数透传）
├── requirements.txt              # Python 依赖（仅 3 个：feedparser / requests / beautifulsoup4）
├── README.md
├── LICENSE
├── .gitignore
├── .github/workflows/mirror.yml  # 每日 CI：抓取榜源 + 生成周报站，发布到 GitHub Pages
├── scripts/
│   ├── fetch_ai_news.py          # RSS 抓取 → news.json（14 源 + 时间窗口过滤）
│   ├── generate_site.py          # 生成单文件 HTML 网站（含排行榜 / 市场 / 看点 / 翻译）
│   ├── validate_report.py        # 产出校验（结构 / ISO8601 / 体量 / 看点 / 市场 / XSS 守护）
│   ├── deploy_report.py          # 部署辅助（提取摘要 + 框架无关通知文本）
│   ├── build_pages_site.py       # CI 专用：组装 Pages 站点（榜镜像 + 周报 HTML + 往周数据源 JSON）
│   └── aiweekly/                 # 内部 Python 包（11 模块）
│       ├── __init__.py           # 包入口 + 公开 API
│       ├── news.py               # RSS 抓取 / 解析 / 分类 / 去重
│       ├── leaderboard.py        # 排行榜合并 / 资料卡权威覆盖（P0#13）
│       ├── leaderboard_sources.py# 多源池抓取（LMArena / HF / OpenCompass / SuperCLUE / ModelScope）
│       ├── insights.py           # 本周看点 / 关键词聚类 / 受众摘要
│       ├── market.py             # 市场 / 融资图表数据（全球 + 中国双源）
│       ├── render.py             # HTML 渲染 + XSS 安全序列化
│       ├── translate.py          # 英文报道中文总结（本地 Ollama）
│       ├── utils.py              # HTTP 重试退避 / 代理 / 区域探测 / ISO8601 日期
│       ├── model_meta.py         # 模型元数据查找（成本 / 上下文 / 许可证）
│       └── types.py              # TypedDict 类型定义
├── assets/
│   └── news_site_template.html   # 单文件 HTML 模板（含内联 Chart.js + safeUrl 守卫）
├── tools/                        # 独立辅助工具（不进入主生成流程）
│   └── accumulate_data.py        # 历史数据累积器（WoY/YoY 环比，可选工具）
├── references/                   # 数据源与报告结构参考文档
├── docs/
│   └── agent-skill-format-landscape.md  # （本地开发参考，已 gitignore，不随仓库发布）
├── data/                         # 本地运行时数据（feed 健康/历史缓存）；gitignore，不入库
├── model_profiles.json           # 模型档案（排行榜描述字段唯一权威源）
└── models_cost.json              # 模型成本兜底数据
```

> 运行时产物（`news.json` / `insights.json` / `leaderboard_cache.json` / `AI_News_*.html` 等）已被 `.gitignore` 排除，不会入库；仓库只保留可复现的源码与参考配置。

---

## 本地数据与首次使用说明

ai-weekly 的**排行榜、市场分析**等展示「实时数据 / 趋势」的模块，依赖**本地累积的历史快照**（如 `snapshots/` 下的周度榜单快照、`data/` 下的趋势累积数据）。

这些历史数据**只在你运行生成时于本地产生**，且只能捕捉**最近**的数据窗口——它们**不会、也不应**随仓库分发（本就属于个人运行产物，已加入 `.gitignore`）。

**⚠️ 首次安装请注意**：头几周生成的报告里，上述模块的「趋势线 / 环比（WoW）变化」会显示为**空白**，这是正常现象、**并非 Bug**。随着你每周持续运行（本地累积 2 周以上快照后），趋势线会自动填充。

> 若希望首次即可看到历史趋势，可手动放入近期快照文件，或先连续运行几周累积本地数据。

---

## GitHub Pages 公开站点（在线 demo + 往周数据源）

仓库启用 GitHub Pages 后，`.github/workflows/mirror.yml` 每天（UTC 18:17 ≈ 北京 02:17）自动运行，把生成的站点发布到 `https://<owner>.github.io/<repo>/`。它同时承担两个角色：

### 1. 在线 demo（HTML）
- `https://<owner>.github.io/<repo>/` → 最新一期 AI 周报（根路径直达）
- `https://<owner>.github.io/<repo>/reports/<ISO周>/index.html` → 任意历史周次（如 `reports/2026-W33/index.html`）
- 单文件 HTML、Chart.js 已内联，**国内免代理、可离线打开**（与本地生成物一致）

### 2. 往周数据源（结构化 JSON）
- `https://<owner>.github.io/<repo>/reports/index.json` → 所有已发布周次的清单（索引）
- `https://<owner>.github.io/<repo>/reports/<ISO周>/news.json` → 该周结构化新闻（字段与 `news.json` 一致，机器可读）
- `https://<owner>.github.io/<repo>/leaderboard.json` · `model_profiles.json` → 排行榜镜像（供国内前端免代理拉取）

> **为什么能当数据源？** RSS 仅保留约 1 周，无法回抓旧闻；但本工作流**每次运行都会把当周已生成的结构化报告发布到 Pages 并累加入 `reports/index.json`**。未来的周报增强（跨周趋势、WoW 环比对比）即可直接 `fetch` Pages 上的历史 `news.json`，无需重新抓取原始 RSS。注意：它保存的是「已生成的周报快照」，不是原始 RSS 流——要扩充历史，需在该周仍处 RSS 保留期内至少运行一次（每日定时已保证这点）。

### 已知限制
- **中文翻译**：CI 环境无本地 Ollama，故不在工作流中传 `--translate-en`，英文报道以**原文**呈现。若需公开站点也带中文总结，请在**本地**生成（带 `--translate-en`）后另行推送到 Pages 源，或把带译文的 `news.json` 注入工作流。
- **数据新鲜度**：周报新闻窗口为「最近 7 天滚动」；排行榜镜像每日刷新（CI 在境外直连 LMArena/HF 等国际源，比本地 `cn` 环境更全）。

如需手动触发或回填某周：`Actions → Mirror Leaderboard & Weekly Report → Run workflow`，可填 `week=2026-W33`（注意 RSS 保留期限制）。

---

## 跨框架兼容性

核心执行引擎**不依赖任何 Agent SDK**，产物为**单文件 HTML**——可被任意 Agent 框架当作普通脚本 + 普通文件复用。

**单一跨平台 `SKILL.md` 即全部入口。** 本技能遵循 Anthropic 首创、已被 OpenClaw / Coze / OpenAI Codex 等广泛采纳的开放 `SKILL.md` 规范。把技能目录放入支持该规范的任意 Agent 即可加载，无需 `plugin.json` 或任何 per-agent 副本。

| 形态 / 平台 | 入口文件 | 状态 |
|---|---|---|
| **Claude Code / Claude.ai** | `SKILL.md`（根） | ✅ 原生读取 |
| **OpenAI Codex CLI** | `SKILL.md`（根） | ✅ 直接读取 |
| **OpenCode** | `SKILL.md`（根） | ✅ 原生 |
| **OpenClaw / ClawHub / 天禧AI** | `SKILL.md`（根） | ✅ 直接读取 |
| **Coze（字节跳动）** | `SKILL.md`（根） | ✅ 兼容（可手动导入） |
| **GitHub Copilot Skills** | `SKILL.md`（`.github/skills/` 或 `~/.copilot/skills/`） | ✅ 兼容（放入对应目录即可） |
| **WorkBuddy** | `SKILL.md`（根） | ✅ 原生 frontmatter |
| **通用框架（Dify / LangGraph 等）** | `manifest.json` | ✅ 引擎接口描述 |

- **引擎层零耦合（可复核）**：以下 grep 应无任何命中：
  ```bash
  grep -rn "import workbuddy\|from workbuddy\|skill_executor" scripts/ || echo "零耦合 ✅"
  ```
- **依赖白名单**：`requirements.txt` 仅 3 个纯标准第三方库——`feedparser` / `requests` / `beautifulsoup4`；无闭源 SDK、无云端强依赖，任何框架可 `pip install` 后直接运行
- **产物框架无关**：`generate_site.py` 输出**单文件 HTML**（CSS/JS/Chart.js 全部内联），不依赖任何 Agent 运行时，可被任意 Agent 返回给用户或托管到静态站点

### 能力分级：核心（全框架通用）vs 框架增强（依赖具体环境）

| 类别 | 能力 | 入口 | 依赖 |
|---|---|---|---|
| **核心** | RSS 新闻抓取 | `fetch_ai_news.py` | `feedparser` + 外网 |
| **核心** | 单文件 HTML 生成（含排行榜 / 市场 / 看点） | `generate_site.py` | `requests` / `bs4` |
| **核心** | 产出校验（6 项守护） | `validate_report.py` | 无 |
| **框架增强** | 英文报道中文总结 | `generate_site.py --translate-en` | 本机 Ollama（`AIWEEKLY_OLLAMA_URL` + 模型） |
| **框架增强** | 摘要提取 / 通知文本 | `deploy_report.py` | 无（纯文本拼装，推送由调用方实现） |
| **框架增强** | 代理支持 + 区域探测 | `generate_site.py --proxy / --region` | PySocks（SOCKS 代理时可选） |
| **框架增强** | 健康检查 | `generate_site.py --health-check` | 无（聚合所有源可达性 + 退出码） |

> **要点**：核心链路 `fetch_ai_news.py → generate_site.py → validate_report.py` **不依赖任何 Agent SDK**，任何框架直接调用即可。`--translate-en` / `--proxy` / `--health-check` 等增强参数跳过也不影响核心产出。

---

## 校验

`validate_report.py` 对生成的 HTML 运行 6 项守护：

| 守护项 | 检查内容 |
|---|---|
| 结构完整性 | `<script>`, `</script>`, `</html>` 存在 |
| 新闻体量 | ≥ 8 条新闻（数据不足时警告而非失败） |
| ISO 8601 日期 | 所有 `publishedAt` 格式正确 |
| 本周看点 | `.insight-card`, `.kw-tag`, `.audience-card` 均存在 |
| 市场图表 | 6 组 Chart.js canvas（含中国数据图） |
| 合作桥接 | `.trend-evidence` 趋势印证行存在 |

校验器参数可通过环境变量覆盖阈值：`AIWEEKLY_MIN_NEWS`（默认 8）、`AIWEEKLY_MIN_INSIGHT_CARDS`（默认 1）等。

---

## 安全

本技能经过对抗式代码审查（[AI_Weekly_Adversarial_Review.md](./AI_Weekly_Adversarial_Review.md)），修复了 RSS 不可信内容导致的安全缺陷：

- **H1 存储型 XSS（`<script>` 上下文 JSON 注入）**：`render.py` 改用 `_json_script_safe()`，序列化后把 `<` `>` `&` 转义为 `\u003c`/`\u003e`/`\u0026`，阻止 `</script>` 突破脚本块。所有 JSON 占位符（`NEWS_DATA` / `LEADERBOARD_DATA` / `INSIGHTS_DATA` 等）均已覆盖
- **H2 URL 属性突破 + 危险协议**：模板新增 `safeUrl()`，仅放行 `http(s):` / `mailto:`，`javascript:` / `data:` 回退 `#`；新闻卡与外链 `href` 均经 `escapeHtml(safeUrl(...))`
- **M1–M2 外部源 / LEAD / 关键词转义**：CLI 可控文本统一走 `html.escape` 与 `_js_str()`

> 所有修复均通过恶意 payload（`</script><img onerror=...>`、`javascript:alert(1)`）注入回归测试验证。

---

## 可选外部增强（合规说明）

本技能**默认完全自治**，不调用任何第三方商业 API。

若希望用 AI HOT 等「AI 行业知识类」外部 API 增强可信度，请**自行**获取数据并导出 JSON，以 `--external-news-json` 注入；页脚会自动署名。是否启用完全由你决定，并须遵守对应服务条款、自行承担合规风险。使用任何第三方 API 时请保留其署名与授权。

---

## 相关文档

- [对抗式代码审查报告](./AI_Weekly_Adversarial_Review.md) — 安全缺陷修复详情与 payload 验证
- [优化方案文档](./AI_Weekly_Optimization_Plan.md)（如有）— 工程债清单与北极星规划

---

## 许可

[MIT](./LICENSE) © 2026 Elisabeth15501
