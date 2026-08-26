# Changelog

本文件记录 ai-weekly（AI 行业周报生成技能）从 1.0.0 到 3.3.0 的全部变更。

> **关于版本说明**：`3.1.1` 是本技能的**首个正式公开发行版**（发布于 SkillHub）。
> 此前的 `1.0.0`–`3.1.0` 为开发迭代历史，仅 `3.0.0`、`3.1.0` 在版本库中留有版本标记；
> `1.0.0`、`2.0.0` 的节点系根据《AI Weekly 优化计划》的"已落地"记录与提交历史推断重建（见各版本注）。
> 所有早期版本的功能均已在 `3.1.1` 中可用。

格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [3.3.0] — 2026-08-27

把「GitHub Pages 自动部署 + 飞书完整周报链接可用」这条核心链路正式封版：新增 gh-pages 部署流水线、修通免交互 PAT 推送认证、加固 CI 与安全正则，并修正文档中与实测不符的描述（Fine-grained→Classic PAT、自动化调度日 周六→周一）。

### Added
- **GitHub Pages 部署接入流水线**：新增 `scripts/deploy_ghpages.py`，用 git worktree 把生成的周报 HTML 推到 `gh-pages` 分支根目录（飞书/钉钉卡片 `view_url` 即指向此地址），并自动累加根 `index.html` 存档页（列出各期、最新高亮）。支持 `--no-push`（离线仅本地提交）、`--switch-pages`（GitHub API 一次性切 Pages 源）、`--dry-run`（只预览不提交）。
- **`run_report.sh deploy` 子命令**：把部署作为流水线一等步骤封装（`bash run_report.sh deploy --html AI_News.html`）。
- **`publish.py --deploy`**：在推送飞书卡片的同时顺带部署到 gh-pages（需配合 `--html`）；透传 `--no-push` / `--switch-pages`。

### Changed
- **停用 `.github/workflows/mirror.yml`**（`if: false`）：原先的 Actions artifact Pages 部署与 gh-pages 分支来源互斥，会破坏分支部署；如需恢复 Actions 部署，需先把仓库 Pages 源切回 "GitHub Actions"。
- README / SKILL.md 的「GitHub Pages」说明改为描述 gh-pages 分支部署模型与首次启用步骤。
- **首次启用文档修正**：Pages 源切换改用 **Classic PAT**（Fine-grained 不被 Pages API 支持，常 403）。

### Fixed
- **部署推送认证修正（deploy_ghpages.py）**：原 `http.extraheader=AUTHORIZATION: Bearer <token>` 在 git smart HTTP 上无效（GitHub 报 `invalid credentials`）。改为用 `url.insteadOf` 把 Classic PAT 嵌进远端 URL（Basic 认证），并清空 `credential.helper` 避免 Windows wincred 在无 tty 环境卡死超时。支持从 `.github_token` 文件（gitignore）或环境变量 `GITHUB_TOKEN`/`GH_TOKEN` 读取。
- **CI 诊断（ci.yml）**：`pip install` 加 `--no-cache-dir`，单测前 `pytest --version` 显式诊断，失败用 `--tb=short` 输出短堆栈。
- **mirror.yml 合规**：顶层 `if: false` 改为 job 级 `if: false`，修复 GitHub Actions `Invalid workflow file`。
- **安全加固（validate_checks/v2.py）**：`<style>`/`<script>` 过滤正则增加单词边界 `\b` 与尾部容错 `[^>]*`，防止误删 `<stylesheet>`/`<scriptx>` 且闭合标签带尾字符时漏过滤（CodeQL CWE-20）。

### Notes
- 首次启用需 `git push origin gh-pages`，并在仓库 **Settings → Pages → Source** 设为 `gh-pages / /root`（或 `run_report.sh deploy --switch-pages`，需带 `pages:write` 的 `GITHUB_TOKEN`）。

---

## [3.2.0] — 2026-08-17

文档与发布层面的对齐版本：正式把**飞书双推送路径**（Webhook + 连接器）写进技能文档，并把版本号对齐到 3.2.0。

> **核实说明（重要）**：飞书连接器代码 `delivery/feishu_connector.py` 其实已于 **v3.1.1**（commit `b636960`）随 GA 一并入库；本版本（3.2.0）的增量是**文档补全**——把此前"代码存在但无说明"的连接器路径正式记录为可选推送方式，而非新增代码功能。另外，`publish.py` 自动管线当前**仅**走 Webhook 路径；连接器为独立 CLI，尚未接入自动编排（见下方 Notes）。

### Added
- 无新增代码（`feishu_connector.py` 已在 3.1.1 提供）。

### Changed
- **SKILL.md §6.1 重写**：从"仅 Webhook 一种"扩展为**双路径对比**——路径 A（Webhook：`scripts/publish.py` + `delivery/feishu_bot.py`）与路径 B（连接器：`delivery/feishu_connector.py`，经 WorkBuddy 飞书连接器 `lark-cli` 发送，密钥由连接器托管、不落配置文件）。附文件职责说明与两种模式的命令、回退 / 目标解析 / 身份。
- **README.md 新增整节「飞书头条卡片推送（可选）」**：含架构树补 `delivery/`、能力分级表补飞书推送行。
- **SKILL.md「文件清单」表**补 `publish.py` / `feishu_bot.py` / `feishu_connector.py` 三行。
- 版本号 `3.1.1 → 3.2.0` 对齐（SKILL.md 双行）。

### Notes / 后续
- 两条路径共用同一张卡片 schema（`feishu_bot.build_headline_card`），产出卡片内容完全一致。
- 若希望自动化周报也能走连接器路径，需在 `publish.py` 增加 `--delivery connector` 开关并复用 `feishu_connector.send_card`——可作为后续小版本（如 3.2.1 / 3.3.0）的增强项。

---

## [3.1.1] — 2026-08-16 🎉 首个正式发行版

首个对外公开发行的稳定版本（SkillHub 发布）。在 3.1.0 基础上补齐了**分发链路、实时榜单回退、合规化与 CI 门禁**。

### Added
- **飞书群机器人 Webhook 推送**：`publish.py` + `delivery/feishu_bot.py`，自动推送周报头条卡片；附"每周一 09:00"自动化模板（P0 北极星：让周报从网页变成被打开的消息）。
- **`--pin-terms` 钉选必读**：按标题子串强制把指定主题（如 `DeepSeek Harness`）钉入"必读"Top-N，避免重要同事件报道被算法稀释漏出。
- **实时榜 cn 源回退**：全局源（LMArena/AA/HF/LLM-Stats）不可达时，回退 OpenCompass 司南 / SuperCLUE / ModelScope 等国内源填充综合榜与开源榜。
- **英文中译默认开启** `--translate-en`（best-effort）：接本地 Ollama（`localhost:11434`）将英文报道译为中文 `cn_summary`/`cn_title`；无本地模型时自动跳过，可用 `--no-translate-en` 关闭（供 CI/fixture）。
- **GitHub Pages 在线 demo 部署**：Jekyll 工作流 + 往周数据源累加索引（周报 HTML/JSON 按周归档，支持历史回溯）。
- **CI 24/24 端到端门禁**：确定性 fixture 离线生成报告并跑全套校验（校验从 19/19 → 24/24），新闻抓取降级不再判致命（仅 `news.json` 为空才终止构建）。

### Changed
- **排行榜优化（L0/L1）**：AI 排行榜渲染增强 + 模态框成本（输入/输出单价）渲染修复。
- **模型卡归一键索引加固**；拆分 `leaderboard_fetch.py` 修复 P0#4（`leaderboard.py` 单文件 ≤800 行硬守护）。
- **仓库优化**：删除冲突的 Jekyll 工作流、抽取 JSON 助手、文档对齐、README 安全加固章节。
- **P2 工程债**：`validate_report.py`（1285 行）拆分为 `validate_checks/` 子包（common/news_v3/news_v2/market/keywords/source），原文件退化为薄入口，逻辑零改动。

### Fixed
- 渲染快照超龄告警分支 `NameError`（缺 `LEADERBOARD_STALE_DAYS` 导入）。
- 合规化：移除内容审核违规措辞（网络管控绕过类表述），代理说明合规化。

---

## [3.1.0] — 2026-08-11

跨平台技能整合与发布就绪。

### Added
- `plugin.json`（Agent Plugins 1.0.0 规范）。
- `SKILL.md` 遵循开放 AgentSkills 规范，成为跨框架（Claude Code / OpenAI Codex / OpenCode / OpenClaw / Coze / WorkBuddy）单一入口。

### Changed
- **M3 整合**：收敛为单一跨平台 `SKILL.md` + 清理死代码。
- 工程债清理：图表标签转义、XSS 守护、工具迁移、ClawHub 独立包、`re-export` 重构。
- 仓库治理：计划/审计类文档移出版本库（`.gitignore` 排除），运行产物移出版本库。

---

## [3.0.0] — 2026-08-10

跨框架兼容落地与工程债收尾（版本库中首次写入 `version: 3.0.0`）。

### Added
- 《调研报告》+《AI Weekly 优化计划》+ 工程债清零收尾文档。

### Changed
- 清理代码 + 跨框架兼容落地 + 工程债收尾。
- README 重写 + 跨框架兼容矩阵表；确认 Agent Plugins 1.0.0 兼容。

---

## [2.0.0] — 2026-08-09 ~ 08-10（节点推断重建）

内容质量大修与工程强化。这一版本把周报从"RSS 原始搬运"提升到"有编辑实质"的产品级形态（优化计划 C0/C1/C2 全部落地，校验 7/7 → 19/19 全绿）。

### Added
- **摘要归一化**：`>120` 字正文搬运压成 `≤80` 字事实摘要（核心事实 + 影响），超长按句号截断保留事实链。
- **重要度评分 + 🔥必读**：`_score_news()` = 来源权威度(S/A/B) × 时效 × 类别权重，Top 8 标 `mustRead`，渲染"🔥 必读"徽章并计入必读 tab。
- **信源名称归一化**：`SOURCE_ALIASES` 映射表，展示短名（InfoQ / TechCrunch / 量子位 / 36氪 / 机器之心），原 feed 全名降级为链接 `title`。
- **本周主线导语** `_auto_lead()`：从全量新闻聚合 Top3 主题合成 2~3 句电梯演讲，服务端预渲染（禁 JS 也可见）。
- **榜单时效标注**：快照距报告日 >3 天显式标"非本周抓取"并告警。
- **看点去注水 + 扩链**：`INSIGHTS_BLOCKLIST` 剔除纯日报聚合类，每条看点挂 2–3 个 related。
- **关键词 TF 自动聚类**：`_auto_keywords()` 混合算法（白名单 + TF n-gram），note 改写为"本周被 N 条新闻提及"式周相关表述（周相关率 100%）。
- **本周数字看板**：聚合总量 / 国内外比 / 模型相关 / 新发布 / 资本&发布事件 / 在榜 Top3。
- **死分类动态隐藏**：空 tab 自动不渲染（如"技巧"）。
- 校验守护：`check_editorial` / `check_editorial_c1` / `check_keyword_clustering` / `check_empty_category_tabs` / `check_keyword_filter`。

### Changed
- 工程债 P1：types / 时区 / snapshot ISO / 运维加固。

---

## [1.0.0] — 2026-08-08 ~ 08-10（节点推断重建，初始版本）

首个可用的自治 AI 行业新闻网站生成器（项目起点）。

### Added
- **自治新闻抓取**：RSS 14 源（国内 7 + 国外 7，国内优先），零第三方商业 API 依赖；如需外部知识类 API 增强由用户以 `--external-news-json` 自行注入。
- **单文件 HTML 网站**：全文搜索、分类筛选、暗色模式。
- **AI 排行榜**：综合榜（LMArena / Artificial Analysis）+ 开源榜（LLM-Stats / HuggingFace）双榜并排。
- **市场/融资图表**：国内 + 国外双源（全球规模/中国规模/全球融资/中国融资），数据由 WebSearch 获取注入，未提供时标注"示例/估算"。
- **工程基座**：工程债治理 P0（日志 / 日期 / 异常 / 源码守护）、时区修正（`GEN_DATE` 用 `astimezone().isoformat()`）、X0 跨框架兼容性文档。

---

## 版本对照速查

| 版本 | 日期 | 性质 | 关键标记 |
|---|---|---|---|
| 1.0.0 | 2026-08 初 | 开发起点（推断） | 首个自治生成器 |
| 2.0.0 | 2026-08-09~10 | 开发迭代（推断） | 内容质量大修 C0/C1/C2 |
| 3.0.0 | 2026-08-10 | VCS 标记 | 跨框架兼容 + 工程债收尾 |
| 3.1.0 | 2026-08-11 | VCS 标记 | 单一跨平台 SKILL.md + plugin.json |
| 3.1.1 | 2026-08-16 | **首个正式发行** | 分发/实时榜/合规/CI 门禁 |

_注：1.0.0 / 2.0.0 的版本号与日期为根据《优化计划》"已落地"记录重建，未在版本库中单独标记；如与实际心智模型不符，可在本文件中直接调整。_
