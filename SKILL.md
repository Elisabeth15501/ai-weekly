---
name: ai-weekly
slug: ai-weekly
version: 3.3.1
displayName: AI Weekly Report
summary: 生成可搜索/筛选/暗色模式的 AI 行业新闻单文件网站（RSS 自治，零第三方 API 依赖）
tags: [ai, news, report, rss, weekly, 人工智能, 周报]
homepage: https://github.com/Elisabeth15501/ai-weekly
license: MIT
compatibility: Claude Code, OpenAI Codex, OpenCode, OpenClaw, Coze, WorkBuddy
description: >
  AI 行业新闻网站生成工具。生成一个可搜索、可筛选、支持暗色模式的 AI 新闻网站（单文件 HTML）。
  新闻默认全部来自 RSS 抓取（14 个精选源：国内 7 + 国外 7，国内源优先，自治无单点依赖）；技能**不内置任何第三方商业 API**。
  如需用 AI HOT 或其他「AI 行业知识类」外部 API 增强可信度，由用户自行获取数据并以
  --external-news-json 注入，是否启用完全由用户决定。每条新闻含原始来源链接。
  市场/融资图表数据由 WebSearch 获取后注入，未提供时明确标注「示例/估算」。
  触发词：AI周报、AI行业周报、AI新闻、weekly AI report、人工智能周报、AI行业动态、
  生成AI报告、AI新闻网站、AI新闻站。支持自动化：每周一上午 9 点自动生成最新版网站。
metadata:
  author: Elisabeth15501
  version: "3.3.1"
  homepage: https://github.com/Elisabeth15501/ai-weekly
  tags: [ai, news, report, rss, weekly, leaderboard, market-data]
---

# AI Weekly Report Skill

> **Cross-platform Agent Skill** — Claude Code · OpenAI Codex · OpenCode · OpenClaw · Coze · WorkBuddy 通用。
> 跨平台 `SKILL.md`，遵循开放 Agent Skill 规范（Anthropic AgentSkills / OpenClaw / Coze 共用的 `SKILL.md` 标准）。
> 单一入口、单一真相源：本文件即为技能的全部说明，无需任何平台专属包装。

## 快速开始（一句话怎么用）

不知道说什么话才能让本技能干活？下面 5 个真实对话直接复制即可触发全链路，**无需先读下文**：

```
用户：帮我生成一份本周 AI 行业新闻周报
→ 技能自动激活：RSS 抓取近 7 天新闻 →（建议用 WebSearch 注入市场/融资数据）
  → 撰写「本周看点」→ 生成单文件 HTML → 校验 → 展示。

用户：这周的 AI 新闻怎么样？给我看个简报就行
→ 技能激活，走「轻量模式」：直接在对话里输出 Markdown 分组列表，不生成网站。

用户：帮我把上周的周报推送到飞书
→ 技能激活，读取已生成的 report.json，调飞书 Webhook / 连接器推头条卡片
  （部署托管可用 deploy.py --deploy-to 选腾讯云 COS / Vercel 等，不必依赖 GitHub Pages）。

用户：生成 8 月最后一周的 AI 周报，时间范围 2026-08-25 到 2026-08-31
→ 技能遵从你指定的时间窗，其余同完整模式。

用户：用我导出的 AI HOT 数据增强这期周报
→ 技能把你的 JSON 以 --external-news-json 注入（页脚自动署名），是否启用完全由你决定。
```

> 卡片文案 + 更多对话示例见 [references/FAQ.md](references/FAQ.md)。飞书配置一步到位见 [scripts/init_feishu_config.py](scripts/init_feishu_config.py)。

生成一个**可搜索、可筛选、响应式**的 AI 行业新闻网站（单文件 HTML）。
每条新闻附带原始报道链接，支持按分类 / 关键词筛选，桌面端和移动端均可使用。

## 一、为什么这件事重要

在 AI 协作工作流里，行业情报往往散落在十几个 RSS、公众号和付费简报里，且**大量"AI 周报"内容是模型生成的空话摘要**。
本技能的价值是把分散信号聚合成**可溯源、有编辑判断、可交叉验证**的单文件情报页，并让它在任意支持 `SKILL.md` 的 Agent 里都能跑——
不绑定任何商业 API、不依赖特定 Agent SDK，输出就是一份能被托管、被转发、被检索的静态 HTML。

## 二、核心设计理念

- **自治优先，增强可选**：新闻内容**默认全部来自 RSS 抓取**（`scripts/fetch_ai_news.py`，14 个精选源：国内 7 个优先 + 国外 7 个），不内置任何第三方商业 API；若用户希望用 AI HOT 等「AI 行业知识类」外部 API 增强可信度，由用户自行获取数据并以 `--external-news-json` 注入（含来源署名），是否启用完全由用户决定、风险自担
- **单文件交付**：所有 CSS/JS 内联，Chart.js 也内联进 HTML，无需任何外部文件
- **高可信度**：每条新闻必须附带原始报道 URL
- **零脑补**：市场/融资图表数据必须由 Agent 从 WebSearch 获取真实值后注入；未提供时明确标注「示例/估算数据」，绝不编造模型榜单
- **零运维**：生成后直接可用的静态 HTML
- **跨平台单源**：本 `SKILL.md` 同时服务 Claude Code / Codex / OpenCode / OpenClaw / Coze / WorkBuddy；引擎接口另见 `manifest.json`（LangGraph / Dify / Coze 等框架的最小接口描述）。兼容性按 AgentSkills 规范声明；**已实测 WorkBuddy，其余平台尚未逐一回归**，如遇加载问题请反馈。

## 三、不要做（硬规则）

1. **不要凭训练数据脑补数字**——所有市场数据、融资金额必须有可追溯来源
2. **不要丢掉新闻的 source URL**——每条新闻卡片必须包含可点击的原始链接
3. **不要用 "this week" / "最近" 搜索**——搜索关键词强制带年份 + 月份
4. **不要把旧闻当本周新闻**——检查发布日期，早于 7 天前的内容标注 `[n天前]`
5. **图表数据必须来自真实搜索**——市场规模/融资额由 WebSearch 获取后通过 `--market-data` / `--funding-data` 注入；**未提供时图表必须标注「示例/估算数据」**，不得伪装成实时数据
6. **不要让新闻卡片没有来源**——每张卡片底部必须有来源名称 + 链接
7. **不要省略任何章节**——某类别无数据时标注"暂无数据"但不删除章节
8. **不要编造模型榜单**——排行榜抓取失败时显示「暂无实时数据」，绝不用训练数据虚构模型名

## 四、数据获取路由表

| 数据类型 | 获取方式 | 优先级 |
|---------|---------|--------|
| 新闻列表 | `scripts/fetch_ai_news.py`（RSS：国内 量子位/36氪/机器之心/智东西/极客公园/InfoQ 中国/钛媒体 + 国外 TechCrunch/MIT TR/HF Blog/TechMeme/MIT News/VentureBeat/Google AI；国内源优先，国外源全挂也有中文地板） | **主** |
| 模型发布 | RSS（HF Blog / 关键词分类） | 主 |
| 产品发布 | RSS（关键词分类） | 主 |
| 行业动态 | RSS + WebSearch（政策/融资补充） | 主 |
| 学术论文 | RSS（arXiv/MIT News 类源）+ WebSearch | 主 |
| 市场数据（规模/采用率/份额） | **WebSearch → Statista / Gartner / IDC**，结果通过 `--market-data` / `--cn-market-data` 注入 | 主（需搜索） |
| 融资并购金额 | **WebSearch → Crunchbase / 烯牛数据 / IT桔子**，结果通过 `--funding-data` / `--cn-funding-data` 注入 | 主（需搜索） |
| 模型排行榜 | **网络环境自适应多源池**（国外源 LMArena/Artificial Analysis/Hugging Face + 国内源 OpenCompass 司南/SuperCLUE/ModelScope）；按运行环境（国内/国外）自动排序优先级，实时源全失败则回退国内快照或本地缓存，绝不空白 | 主 |
| 政策监管 | RSS + WebSearch | 主 |
| **外部 API 增强（可选）** | 用户自备 AI 行业知识类 API（如 AI HOT）导出 JSON，以 `--external-news-json` 注入，页脚自动署名；是否启用由用户决定 | 可选增强 |

> **依赖说明**：`scripts/fetch_ai_news.py` 需要 `feedparser`、`requests`、`beautifulsoup4`（随技能提供 `requirements.txt`）。
> 运行：一律用仓库根目录的 `bash run_report.sh scripts/xxx.py ...` 启动，启动器会自动探测并复用 `aiweekly` 受管 venv；若 venv 缺失，按提示 `python -m venv` + `pip install -r requirements.txt` 即可。
> 若这些包不可用，可手动用 WebSearch 搜集新闻后写成同样结构的 JSON，再走 `--api-json` 消费；
> 也可用你自己的外部 API（如 AI HOT）导出 JSON 后以 `--external-news-json` 注入——**注意：使用任何第三方 API 须遵守其服务条款，并自行承担合规风险**。

## 五、轻量模式与完整模式

根据用户意图选择模式：

| 用户说的 | 模式 | 输出 |
|---------|------|------|
| "快速看看" / "简单总结" / "不用图表" | **轻量** | Markdown 分组列表，直接在对话中展示 |
| 默认（无特别说明） | **完整** | 生成完整新闻网站 HTML |
| "生成报告" / "生成网站" / "周报" | **完整** | 生成完整新闻网站 HTML |

## 六、工作流（完整模式）

### 1. 确定时间范围

默认：过去 7 天。用户指定时遵从用户。

### 2. 抓取新闻（主路径：RSS）

```bash
# 用统一启动器运行（自动探测并复用 aiweekly venv，无需手动选解释器）
bash run_report.sh scripts/fetch_ai_news.py --output news.json
```

返回 `{"count": N, "items": [{title, summary, url, source, publishedAt, category, score}]}`，
分类已由脚本完成（`ai-models` / `ai-products` / `industry` / `paper` / `tip`）。

**降级**：若 RSS 抓取不可用（缺依赖/无网络），可手动用 WebSearch 搜集后写成同样结构的 JSON，
再走 `--api-json` 消费；也可用你自己的外部 API（如 AI HOT）导出 JSON 后以 `--external-news-json` 注入。

### 3. 补充市场/融资数据（必需搜索，结果注入图表）

各做 1-2 次 WebSearch，拿到真实数值后用 `--market-data` / `--funding-data` 注入：

| 数据类型 | 搜索关键词示例 | 注入参数 |
|---------|--------------|---------|
| 融资并购 | `AI funding Q2 2026`, `AI融资 2026年` | `--funding-data 17.4,13.1,... --funding-labels 23Q1,23Q2,... --funding-source "Crunchbase 2026"` |
| 市场数据 | `AI market size 2026 statistics`, `AI市场规模 2026` | `--market-data 51,71,103,... --market-labels 2020,2021,... --market-source "Statista 2026"` |

**若搜索无结果**：不伪造，直接省略参数——图表会显示「示例/估算数据」标注，由读者知悉非实时。

### 4. 生成新闻网站 HTML

读取 `assets/news_site_template.html` 理解结构，然后用 `Write` 生成完整网站。

**新闻网站必须包含：**
- 顶部搜索栏（实时过滤）
- 分类标签栏（全部 / 模型 / 产品 / 行业 / 论文 / 技巧）
- **「本周看点」编辑洞察区（头版导语，必做）**——见下方第七节
- 新闻卡片网格（响应式：3列 → 2列 → 1列）
- 每张卡片：类别色块缩略图、标题、摘要（2行截断）、来源名 + 原始链接、发布时间
- 市场数据区（2×2 四个 Chart.js 图表：全球/中国市场规模 + 全球/中国融资趋势）
- 模型排行榜区（表格式 Top 10，标注数据来源与排名标准）
- 暗色模式切换按钮
- 页脚：数据来源说明

```bash
bash run_report.sh scripts/generate_site.py --api-json news.json \
  --ranking-json ranking.json --profiles-json model_profiles.json \
  --insights-json insights.json --lead "本周主线：……" \
  -o AI_News_YYYY-MM-DD.html
```

> **推荐（强）**：尽量每次都传 `--insights-json` 与 `--lead`，这是头版核心、产品力所在。若**漏传**，`generate_site.py` 会自动从本周新闻派生基线「本周看点」（标题+摘要+分类+原文链接），**整段不再静默消失**——但自动版只是摘要级，缺少人工「编辑洞察」深度，故仍建议撰写 curated 版本覆盖。

> **「本周看点」三块内容的必现保证（无需任何参数）**：
> | 内容块 | 兜底机制 | 相关函数 |
> |--------|---------|---------|
> | 看点卡片 | 无 `--insights-json` 时从本周新闻按信号词打分派生 Top6 | `_auto_insights()` / `_auto_lead()` |
> | 「给本周的你」三张受众卡 | 无 `audience_summary` 时用内置三段文案 | `_DEFAULT_AUDIENCE_SUMMARY` |
> | 关键词的彩色分类标签 | 缺 `tag` 自动推断分类；完全无关键词时从新闻派生带标签关键词 | `_normalize_keywords()` / `_auto_keywords()` / `_infer_tag()` |
>
> 这三块均在**生成阶段服务端预渲染进静态 HTML**（`_render_audience_chips_html()` / `_render_keyword_chips_html()`），JS 只负责后续交互切换。因此**即使浏览器禁用 JS 或脚本报错，这些内容依然可见**——不会再出现「区块静默消失」。
>
> ⚠️ **排错提醒**：若重新生成后仍看不到某块内容，先确认 ① 输出路径是否就是你打开的那个文件（不要输出到 `-fixed`/`-static` 之类旁路文件名）；② 浏览器是否硬刷新（Ctrl/Shift+R）。用 `grep -c 'class="kw-tag"'` 判断**不可靠**——CSS 里有同名类定义，恒返回 ≥1；应改查 `grep -o 'class="kw-tag"[^>]*>[^<]*'` 看实际渲染内容。

### 5. 质量检查

生成后运行验证：

```bash
bash run_report.sh scripts/validate_report.py --html AI_News_YYYY-MM-DD.html
```

校验器检查新闻卡片、排行榜章节、市场图表、洞察与关键词；并内置 XSS 守护（脚本上下文 JSON 无原始 `</script>`、全文无 `javascript:`/`data:` href）。

### 6. 交付

- 文件名：`AI_News_YYYY-MM-DD.html`（如 `AI_News_2026-07-09.html`）
- 调用 `present_files` 展示
- 总结核心发现（3-5 条）

### 6.1 部署到网页托管（多后端，可选但推荐）

飞书/钉钉卡片里的「查看完整周报」按钮 `view_url` 需要一个可公开访问的地址。**不一定要用 GitHub Pages**——`scripts/deploy.py` 统一入口按 `--deploy-to` 选后端：

| `--deploy-to` | 适合 | GitHub 依赖 |
|------|------|------|
| `github-pages`（默认） | 已用 GitHub、熟悉 Pages | 需要（PAT + push + 切 Pages 源） |
| `tencent-cos` | 国内最稳、免翻墙后台 | **不需要**（需 COS 桶 + 密钥） |
| `vercel` / `netlify` / `cloudflare-pages` | 海外免备案、一条命令 | **不需要**（需对应平台 token） |
| `local` | 自托管 / 内网文件服务 | **不需要** |

非 github-pages 后端无需配置 GitHub，飞书卡片 `view_url` 由后端自动推导（可用 `--view-base` 覆盖）。配置示例见 `delivery/deploy_config.example.json`。

默认（GitHub Pages）路径：`view_url` 指向 `https://<owner>.github.io/<repo>/AI_News_<date>.html`——该地址由 **`gh-pages` 分支**提供（仓库 Pages 源 = `Deploy from a branch: gh-pages / /root`）。用 `run_report.sh deploy` 即可把当期周报推到该分支：

```bash
# 流水线封装：底层调用 scripts/deploy_ghpages.py
bash run_report.sh deploy --html AI_News_YYYY-MM-DD.html
#   --no-push       仅本地提交不推送（离线可跑；待网络恢复后 git push origin gh-pages）
#   --switch-pages  部署后通过 GitHub API 把 Pages 源切到 gh-pages / /root（需 GITHUB_TOKEN）
#   --dry-run       只做 worktree+复制+index 预览，不提交不推送
```

`deploy_ghpages.py` 用 **git worktree** 操作 `gh-pages`（不污染 `main`、不进 SkillHub 包），并把所有 `AI_News_*.html` 累加进根目录 `index.html` 存档页（最新高亮）。脚本自动清理 worktree，本地 `gh-pages` 提交始终保留。

**一步到位**：`publish.py` 在推送飞书卡片的同时可顺带部署周报（需传 `--html`）：

```bash
bash run_report.sh scripts/publish.py \
  --news-json news.json --insights-json insights.json \
  --audience-json audience_summary.json \
  --html AI_News_YYYY-MM-DD.html --deploy
#   --deploy           生成 report.json 后顺带部署（默认 github-pages）
#   --deploy-to tencent-cos   改用腾讯云 COS（国内最稳，无需 GitHub）
#   --deploy-to vercel        改用 Vercel（海外免备案，无需 GitHub）
#   --no-push          部署时仅本地提交不推送
#   --switch-pages     部署时一并把 Pages 源切到 gh-pages
```

**首次启用（一次性）**：`git push origin gh-pages` → 仓库 Settings → Pages → Source 选 `gh-pages / /root`（或 `run_report.sh deploy --switch-pages`）。注意：GitHub Pages 只允许单一来源，原先的 `.github/workflows/mirror.yml`（Actions artifact 部署）因此已停用（`if: false`），以免两种来源互斥导致部署失败。

### 6.2 分发：飞书头条卡片推送（P0，可选但推荐）

生成报告后，可把**本周头条速览**推到飞书（群机器人 / 连接器），让情报在"工作者已在用的地方"被消费。两种推送路径**共用同一张卡片 schema**（由 `delivery/feishu_bot.build_headline_card` 构造），区别只在"怎么发出去"：

| 路径 | 发送方式 | 凭据 | 依赖 | 适合 |
|------|---------|------|------|------|
| **A. Webhook 自定义机器人** | `feishu_bot.push()` POST 到飞书 incoming webhook | webhook URL（token 内嵌在 URL） | `requests` | 任意环境，已建好自定义机器人 |
| **B. 飞书连接器直推（推荐）** | `delivery/feishu_connector.py` 经 `lark-cli im +messages-send` 发送 | 连接器托管，**绝不落配置文件** | 标准库 + 已连接的飞书连接器（lark-cli + node） | WorkBuddy 用户，密钥不想写进仓库 |

> **文件职责**：`delivery/feishu_bot.py` 是共用的卡片构造库（`build_headline_card` + webhook 发送的 `push`）；`delivery/feishu_connector.py` 是独立 CLI，import 前者的卡片构造、改用 lark-cli 发送。两者产出的卡片内容完全一致。

**模式 A — Webhook（由 `publish.py` 一步完成）**

```bash
# 组装 report.json 并直接推送到 webhook（三级回退：--webhook > $FEISHU_WEBHOOK > delivery/feishu_config.json）
bash run_report.sh scripts/publish.py \
  --news-json news.json \
  --insights-json insights.json \
  --audience-json audience_summary.json \
  --view-url "https://<你的托管地址>/AI_News_YYYY-MM-DD.html" \
  --output report.json

# 仅构造卡片预览、不推送：
bash run_report.sh scripts/publish.py --news-json news.json --insights-json insights.json --audience-json audience_summary.json --dry-run

# 直接指定 webhook（也可写入 delivery/feishu_config.json，已被 .gitignore 忽略）：
bash run_report.sh scripts/publish.py ... --webhook "https://open.feishu.cn/open-apis/bot/v2/hook/XXXX"
```
webhook 三级皆空 → 自动跳过推送（exit 0，不阻断报告生成）；推送返回业务错误时 exit 1。

**模式 B — 飞书连接器直推（密钥不落盘，推荐）**

先让 `publish.py` 产出 `report.json`（可加 `--dry-run` 只组装不推），再用连接器 CLI 发送：

```bash
# 1) 组装 report.json（此步不推送）
bash run_report.sh scripts/publish.py \
  --news-json news.json --insights-json insights.json \
  --audience-json audience_summary.json --output report.json

# 2) 经飞书连接器推送到群（bot 身份，需先把「WorkBuddy-Feishu CLI」机器人加进群）
python delivery/feishu_connector.py --report report.json --chat-id oc_xxxx

# 推给自己（user 身份 → 私聊，首次冒烟测试最省事，无需加机器人）
python delivery/feishu_connector.py --report report.json --user-id ou_xxxx --as user

# 预览（不实际发送）
python delivery/feishu_connector.py --report report.json --chat-id oc_xxxx --dry-run
```

- **目标解析优先级**：`--chat-id/--user-id` > 环境变量 `FEISHU_CHAT_ID/FEISHU_USER_ID` > `delivery/feishu_target.json`（`{"chat_id":"oc_xxx"}` 或 `{"user_id":"ou_xxx"}`）。
- **发送身份**：`--as bot`（默认，应用机器人，需机器人已入群）/ `--as user`（以你本人身份，需你对该会话有发消息权限）。
- 依赖：仅标准库 + 已连接的飞书连接器；**无需 `requests`**，卡片构建路径不会因缺 `requests` 而失败。

**卡片内容（两种模式一致）**：本周主线 + 🔥本周重点（按 score 取 Top5，带链接/来源）+ 💡本周看点（Top3）+ 👥分角色摘要（开发者/PM/自媒体）+ 🔖关键词 + 「查看完整周报」按钮（链接自动追加 `?src=feishu&uid=<uid>` 度量参数）。

### 7. 自动化设置

当用户要求"每周自动生成"时，创建 recurring automation：

| 参数 | 值 |
|------|-----|
| name | `AI新闻网站自动更新` |
| scheduleType | `recurring` |
| rrule | `FREQ=WEEKLY;BYDAY=MO` |
| status | `ACTIVE` |
| prompt | 见下方自动化 Prompt 模板 |

```
你是 AI 行业新闻编辑。请生成一个 AI 新闻网站（默认 RSS 自治，不内置任何第三方商业 API）：

1. 运行 RSS 抓取获取近 7 天新闻：
   bash run_report.sh scripts/fetch_ai_news.py --output news.json
   （若依赖缺失/失败，改为 WebSearch 手动搜集，写成相同 JSON 结构再往下走）
2. 用 WebSearch 获取市场/融资真实数据（2-3 次搜索），记录数值与来源
3. 读取 assets/news_site_template.html 理解结构
4. 代入「有 AI 产品经理经验的专业科技媒体工作者」人设，基于 news.json 撰写「本周看点」：
   - 顶部写 3-6 个 keywords（{term, tag, note}；tag 为分类彩色标签可省略——省略时生成器自动推断，note 可为字符串或按受众分述的对象 {开发者, PM, 自媒体}），渲染在「本周看点」开头、带网页搜索链接；
   - 写 3-5 条 insight（每条覆盖：AI 产品/开发角度重点分析 + 本周 trends + 预计未来发展），务必去 AI 味、有观点锋芒；
   - 写顶层 audience_summary（{开发者, PM, 自媒体} 各一句），渲染为「给本周的你」三张受众卡；可省略（用内置 _DEFAULT_AUDIENCE_SUMMARY 兜底，区块永不隐藏）——注意键必须与 keywords[].note 的受众键一致；
   - 拟一句头版导语 lead。
   写入 insights.json（schema 见第七节），insight 字段承载「编辑洞察」栏。
5. 运行生成脚本（注入第 2 步真实图表数据 + 第 4 步洞察）：
   bash run_report.sh scripts/generate_site.py --api-json news.json \
     --market-data <数值> --market-source "<来源>" --funding-data <数值> --funding-source "<来源>" \
     --insights-json insights.json --lead "<本周主线一句话>" \
     -o AI_News_[日期].html
6. 运行 validate_report.py 检查质量
7. 调用 present_files 展示结果
8. （可选）部署到 GitHub Pages，让飞书卡片的「查看完整周报」可点击访问：
   bash run_report.sh deploy --html AI_News_[日期].html
   若沙箱网络/凭据不可用导致推送失败，跳过此步也不影响报告生成（本地 gh-pages 提交已就绪）。

注意：默认流程不含任何外部商业 API。若用户明确要求用 AI HOT 等外部 API 增强可信度，
     请提示用户自行从官方渠道导出 JSON，并以 --external-news-json 注入（含 --external-source-name/url 署名）。
```

## 七、「本周看点」编辑洞察（头版导语，必做）

这是本技能从「新闻聚合器」升级为「科技情报产品」的关键一步。**必须由你（Agent）基于本周新闻亲自撰写**，而非简单罗列。

**人设（务必代入）**：你是一个**有 AI 产品经理经验的专业科技媒体工作者**。你既懂怎么把 AI 能力做成产品、踩过工程与商业化的坑，又能像专栏编辑一样把行业信号讲清楚。

撰写要求：
- **顶部 `keywords`（必做）**：3-6 个本周 AI 行业最值得追踪的**关键词**，每条 `{term, tag, note}`。
  - `tag`：分类标签，取值建议 `模型 / 资本 / 产品 / 安全 / 基建 / 监管`，渲染为词条上的彩色小标签。**可省略**——省略时生成器会用 `_infer_tag()` 按词义自动推断，但显式指定更准。
  - `note`：可以是一句话字符串，也可以是**按受众分述的对象** `{"开发者": "...", "PM": "...", "自媒体": "..."}`（推荐），点击「给本周的你」的受众卡时，所有词条的 note 会联动切换成该受众视角。
  - 每个关键词渲染为**网页搜索链接**（点击在新标签打开搜索引擎，搜索词固定为「词语 AI」；搜索基址默认百度，可用 `--keyword-search-base` 覆盖）。整段下方固定一句引导：**"以上为本周 AI 行业最值得追踪的信号，建议你顺着这些词去做更多资料搜集与交叉验证。"**——目的是鼓励读者深挖，而非替他们下结论。
- **`audience_summary`（推荐）**：顶层字段，给三类读者各写一句本周结论 `{"开发者": "...", "PM": "...", "自媒体": "..."}`，渲染为「给本周的你」三张受众卡。**可省略**——省略时用内置 `_DEFAULT_AUDIENCE_SUMMARY` 兜底，该区块永不隐藏。注意：这里的键必须与 `keywords[].note` 的受众键**保持一致**，否则切换受众时 note 取不到值。
- **数量**：3-5 条，挑本周最影响「AI 产品方向」与「应用开发决策」的动向，不要面面俱到。
- **每条结构**：`kicker`（栏目标签）+ `title`（判断句，不是新闻标题复述）+ `analysis`（发生了什么、为什么重要，2-3 句的事实陈述，不用第一人称）+ `insight`（**编辑洞察栏**，见下）+ 可选 `related`（1-3 条指向原文的新闻链接）。
- **`insight` 三段式（核心）**：以"有 AI 产品经理经验的专业科技媒体工作者"口吻写，必须覆盖：
  1. **重点分析**：循着 AI 产品 / 应用开发的发展角度，拆解这条新闻对"做产品、做开发"到底意味着什么；
  2. **本周 trends**：点明本周正在发生的趋势（用"本周趋势是……"自然带出）；
  3. **预计未来发展**：给出未来判断（用"往后看 / 我判断 / 我倾向于认为"等带观点的口吻，要有具体指向，不要空泛）。
- **开头一条 `lead`**（电梯演讲）：一句话概括本周主线，作为头版导语。
- **语气（务必去 AI 味）**：写成一个有十年经验的科技专栏编辑的手笔，而不是模型生成的摘要。具体要求：
  - 有**明确观点与锋芒**，敢于下判断（"是该重新翻一遍账单了""别高兴太早""没人再犹豫了"这类口吻），不要全程中立。
  - **禁止**工整对仗的「对 AI 产品开发：…… 对应用开发：……」分述模板；把产品/开发的影响自然揉进一段连贯的散文里。
  - **禁用** AI 套话：避免「信号很明确／意义重大／不容忽视／值得关注／总的来说／综上所述」这类空泛收束；少用「赋能／抓手／闭环／范式」等黑话堆叠。
  - 用具体、口语化、带行业质感的表达（"翻一遍调用账单""把宝押在单一云""demo 更炸"），句子长短错落，像人在说话。
  - `analysis` 保持客观陈述事实，`insight` 才是编辑的主观判断——两者分工清晰，不要混成同一段。

写入 JSON（schema 与下方一致）后，用 `--insights-json` 注入；`--lead` 传导语：

```json
{
  "audience_summary": {
    "开发者": "旗舰模型单价下探，先把上季度调用账单重算一遍再决定要不要换栈。",
    "PM": "能力过剩、成本骤降，产品差异化重心从「用哪个模型」挪到「场景与数据」。",
    "自媒体": "「单位智能降价」是本周传播力最强的选题，配上账单对比图最好用。"
  },
  "keywords": [
    {
      "term": "单位智能降价",
      "tag": "资本",
      "note": {
        "开发者": "价格锚松动，重算模型调用预算",
        "PM": "定价模型要跟着推理成本重做",
        "自媒体": "降价幅度对比是天然爆款素材"
      }
    },
    {"term": "智能复利", "tag": "产品", "note": "曾鸣提出，Agent 进业务流程、算得清 ROI"}
  ],
  "insights": [
    {
      "kicker": "模型格局",
      "title": "旗舰模型密集上新，单位智能的定价开始松动",
      "analysis": "本周 Claude Opus 5 正式发布……（客观事实陈述）",
      "insight": "做 AI 产品的团队最纠结的……（重点分析）这一周的趋势是……（本周 trends）往后看半年，我判断……（预计未来发展）",
      "related": [{"title": "原标题", "url": "https://..."}]
    }
  ]
}
```

## 八、网络环境自适应（国内 / 国外差异）

不同运行环境对国内外网站的连通性差异很大，本技能对此做了显式处理：

- **源池与 region 标签**：综合榜源池 `[Artificial Analysis(国外), LMArena(国外), OpenCompass 司南(国内), SuperCLUE(国内)]`；开源榜源池 `[Hugging Face(国外), ModelScope 魔搭(国内)]`。每个源带 `region` 标签。
- **自动探测**：`--region auto` 同时探测一个国内哨兵与一个国外哨兵，判定 `cn` / `global` / `unknown`，并据此排序源优先级（国内环境优先国内源，反之亦然）。也可显式 `--region cn` / `--region global`。
- **代理支持**：部分海外源在受限网络（如企业内网）下可能超时；可通过 `HTTPS_PROXY` 环境变量或 `--proxy` 参数指定出站代理以提升可达性。
- **国内可直连榜的局限（重要）**：OpenCompass 司南、SuperCLUE、ModelScope 官网均为 **JS 渲染 SPA**，其数据 API 无法用简单 HTTP 稳定抓取（返回 SPA 兜底页 / 需鉴权）。因此这些"live"解析器按**尽力而为**实现——连不上或解析不到结构化数据就返回 None，由多源池优雅降级。
- **兜底不空白**：国内环境且实时源全失败 → 自动回退到随技能附带的 `cn_leaderboard_snapshot.json`（OpenCompass 司南 LLM 综合榜 + 开源榜快照，标注数据截止日，徽章显示「缓存快照」）；国外/未知环境且实时源失败 → 回退本地 `leaderboard_cache.json`。
- **来源透明**：排行榜每个子榜头部用徽章标注「实时·国内源 / 实时·国外源 / 缓存快照」，页脚注明探测到的网络环境与选用策略，用户始终知道数据从哪来。

排行榜来源优先级：`--ranking-json` > 多源池实时（按 region 排序）> 国内快照 / 本地缓存 > 显示「暂无实时数据」。
图表数据未注入时，图表注释自动标注「示例/估算数据」，不伪装为实时。

### 配置代理（可选，提升受限网络下海外源可达性）

部分海外源在受限网络（如企业内网、无外网出口的环境）下可能超时。技能内置代理支持（`_http_get` / `_probe` 经 `ProxyHandler` 或 SOCKS 全局生效），可通过标准 HTTP 代理端点提升可达性：

- **通过环境变量**
  ```bash
  HTTPS_PROXY=http://<proxy-host>:<port> bash run_report.sh scripts/generate_site.py --api-json news.json -o AI_News.html
  ```
- **通过参数**
  ```bash
  bash run_report.sh scripts/generate_site.py --api-json news.json --proxy http://<proxy-host>:<port> -o AI_News.html
  ```
- **降级行为**：代理不可达时，海外源优雅降级到国内快照 / 本地缓存，不会崩溃。

### 模型资料卡档案同步（real-time archive update）

排行榜资料卡所需的「机构 / 许可证 / 成本 / 上下文 / 多模态 / 适用场景 / 信息源」等字段，来自一个**联网核实的 canonical 档案**，随技能一起维护、随每次运行累积更新：

- **canonical 档案**：`model_profiles.json`（技能目录内）按模型名索引，存放逐模型核实过的资料；无需每次手动传入，`generate_site.py` 每次生成**自动加载**并注入资料卡。
- **新模型实时建档**：生成时会比对排行榜全部上榜模型与档案。若有模型缺档案，脚本写入 `model_profiles.pending.json` 并告警。运行方（Agent）应据此闭环：
  1. 读取 `model_profiles.pending.json` 中的模型名；
  2. 用 WebSearch 逐模型联网核实（官方公告 / 模型卡 / Artificial Analysis / Hugging Face）；
  3. 产出 `{模型名: {org, license, commercial, intel_index, hf_avg, cost_in, cost_out, context, multimodal, use_case, source}}` 的 JSON；
  4. 以 `--profiles-json 该JSON` 重新生成——脚本会将其**合并写回** `model_profiles.json`（canonical 实时更新），并自动清除 pending 清单。
- **写入优先级**：`--profiles-json` 合并 > canonical 档案 > 资料卡留空（绝不编造字段）。

## 九、发布与第三方依赖说明（合规）

本技能**默认零第三方商业 API 依赖**，可安全开源发布（GitHub / Gitee）：

- 新闻默认全部来自 14 个公开 RSS 源（国内 7 + 国外 7）；市场/融资图表由运行方通过 WebSearch 注入；排行榜从公开网页（LMArena / Artificial Analysis / Hugging Face / OpenCompass / SuperCLUE / ModelScope 等）自适应抓取，国内兜底快照随技能附带。
- **不内置、不打包任何 AI HOT / 卡兹克的内容**。页脚仅保留基础参考来源链接（LMArena / Artificial Analysis / Hugging Face / OpenCompass / Gartner / IDC / Statista / Crunchbase / Stanford HAI）。
- **外部 API 增强是用户 opt-in 的**：技能不主动调用 AI HOT 等任何外部商业 API；只有当用户自备 JSON 并以 `--external-news-json` 注入时才会参与，且页脚自动署名该来源。是否启用、遵守其服务条款均由用户自行决定。
- **发布建议**：① 附带 `LICENSE` 文件（如 MIT / Apache-2.0）；② 如需大范围传播，建议提示用户使用外部 API 前先取得授权。
- **跨平台分发**：本技能以单一 `SKILL.md`（开放 Agent Skill 规范）为唯一入口，直接放入支持该规范的任意 Agent 目录即可加载；框架级调用（LangGraph / Dify / Coze）参考 `manifest.json` 的引擎接口描述。无需任何平台专属包装（无 `plugin.json`、无 per-agent 副本）。

## 十、文件清单

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 本文件（单一跨平台入口） |
| `manifest.json` | 通用引擎接口描述（框架级调用参考） |
| `assets/news_site_template.html` | v3.0 新闻网站 HTML 模板 |
| `assets/report_template.html` | v2.0 周报模板（保留兼容） |
| `assets/sample_chart_data.json` | Chart.js 示例数据 |
| `scripts/generate_site.py` | **v3.0** 一键从 API 生成新闻站 |
| `scripts/validate_report.py` | v3.0 质量检查（含 XSS 守护，自动识别 v2/v3 格式） |
| `scripts/fetch_ai_news.py` | 离线 RSS 抓取（备用） |
| `scripts/deploy_report.py` | 部署摘要提取（框架无关通知文本） |
| `scripts/deploy_ghpages.py` | **部署到 GitHub Pages**：git worktree 操作 `gh-pages` 分支，累加根 `index.html` 存档页并推送（底层被 `deploy.py` 调用） |
| `scripts/deploy.py` | **统一部署入口（P0-1）**：按 `--deploy-to` 选后端（github-pages/tencent-cos/vercel/netlify/cloudflare-pages/local），非 GitHub 后端无需配置 GitHub |
| `scripts/validate_models.py` | **模型档案守护（P0-2）**：`--check` 扫描 `model_profiles.json` 有无未核实条目；`--fix` 将无来源推测条目移入 `model_profiles_unverified.json` |
| `scripts/leaderboard_diagnose.py` | **排行榜源诊断（P0-3）**：逐个源探测可达性 + 统计国内镜像回退命中 |
| `scripts/publish.py` | 组装本周头条 `report.json` 并推送飞书卡片（支持 webhook 与连接器两种路径；`--deploy`/`--deploy-to` 顺带部署） |
| `delivery/feishu_bot.py` | 飞书卡片构造（`build_headline_card`）+ Webhook 发送（`push`），两路径共用的卡片 schema |
| `delivery/feishu_connector.py` | 飞书连接器直推 CLI（lark-cli，密钥不落盘），复用前者的卡片构造 |
| `scripts/init_feishu_config.py` | **飞书配置向导（P1-3）**：交互式生成 `feishu_config.json`（Webhook）或 `feishu_target.json`（连接器），免去手动建文件 |
| `tools/accumulate_data.py` | 历史数据累积（独立辅助工具，不在主流程） |
| `model_profiles.json` | **canonical 模型资料档案**（按模型名索引，逐条 `verified=true` + 真实来源），每次生成自动加载、新模型研究后合并写回 |
| `model_profiles.pending.json` | 新上榜但档案缺失的模型清单（检测为空自动删除；运行方据此联网补档） |
| `model_profiles_unverified.json` | **隔离存放（P0-2）**：被 `validate_models.py` 移出的无来源推测条目，不参与排行榜，待联网核实后回填 |
| `cn_leaderboard_snapshot.json` | 国内排行榜快照（实时不可达时回退） |
| `delivery/deploy_config.example.json` | 部署配置示例（COS/Vercel 等后端参数） |
| `delivery/feishu_config.example.json` | 飞书 Webhook 配置示例（`feishu_config.json` 模板） |
| `references/data_sources.md` | 备用数据源参考 |
| `references/report_structure.md` | v2.0 报告结构参考 |
| `references/FAQ.md` | **常见问题集中解答（P1-2）**：安装配置 / 首次使用 / 飞书推送 / GitHub Pages / 网络 / 模型数据 |
| `data/history.csv` | 历史指标数据 |

## 参考资料

- **[references/data_sources.md](references/data_sources.md)** — 备用 / 候选数据源清单
- **[references/report_structure.md](references/report_structure.md)** — v2.0 报告结构参考
- **[manifest.json](manifest.json)** — 通用引擎接口（框架级调用）
- **[docs/agent-skill-format-landscape.md](docs/agent-skill-format-landscape.md)** — Agent 技能格式格局调研（为何采用单一开放 `SKILL.md`）
