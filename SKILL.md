---
name: ai-weekly
slug: ai-weekly
version: 3.6.1
displayName: AI Weekly Report
summary: 生成可搜索/筛选/暗色模式的 AI 行业新闻单文件网站（公开 RSS 取数，无付费 API 依赖）
tags: [ai, news, report, rss, weekly, 人工智能, 周报]
homepage: https://github.com/Elisabeth15501/ai-weekly
license: MIT
compatibility: Claude Code, OpenAI Codex, OpenCode, OpenClaw, Coze, WorkBuddy
description: >
  AI 行业新闻网站生成工具。生成可搜索、可筛选、支持暗色模式的 AI 新闻单文件 HTML。
  直接说人话即可触发（「这周 AI 有什么大事」「给我看个 AI 简报」）。
  新闻默认全部来自公开 RSS 抓取（国内 7 + 国外 7 共 14 个精选源，国内源优先，无单点依赖）；
  默认不调用任何付费/商业 API。可选增强：用户自备 NewsAPI key（--news-api，默认关）或以
  --external-news-json 注入 AI HOT 等来源 JSON（页脚自动署名，是否启用由用户决定）。
  市场/融资图表数据由 WebSearch 获取后注入，未提供时明确标注「示例/估算」。
  触发词：AI周报、AI行业周报、AI新闻、人工智能周报、AI行业动态、生成AI报告、AI新闻网站、
  AI新闻站、这周AI有什么大事、AI圈最近怎么样、给我看个AI简报、AI新闻汇总、做个AI周报、
  AI行业速览、我想看AI动态、weekly AI report、AI news digest。
  分发/运维触发：把周报推送到飞书、部署到 GitHub Pages、重生成某期周报、刷新模型排行榜。
  支持自动化：每周一上午 9 点自动生成最新版网站。
metadata:
  author: Elisabeth15501
  version: "3.6.1"
  homepage: https://github.com/Elisabeth15501/ai-weekly
  tags: [ai, news, report, rss, weekly, leaderboard, market-data]
---

# AI Weekly Report Skill

跨平台 Agent Skill（Claude Code · Codex · OpenCode · OpenClaw · Coze · WorkBuddy 通用）。
单一入口、单一真相源：本文件为技能说明**精简版**；**完整版见 `references/SKILL_full.md`**（同仓库 GitHub，含数据路由全表、网络可达性实测、译文三级取值、声明面/分发面完整清单）。

## 一、能力边界（诚实列出）

- **新闻**：14 个 RSS 源（国内 7 + 国外 7）实测全通；海外源个别不可达时**优雅降级到国内源与离线快照，绝不编造**。
- **数据口径**：市场/融资为**静态快照注入**（经 WebSearch 取真实值），非实时；榜单为实时抓取或**诚实标注日期的快照**，绝不冒充实时。
- **翻译**：三级取值（本地缓存 → 远程译文源 → 本地 Ollama）；断网也有 `translations_offline.json`。无命中显式标注「未翻译·原文保留」。
- **体量**：单文件 HTML，可搜索/筛选/暗色模式；周报条数取决于 RSS 窗口（默认近 7 天），非全量归档。

## 二、快速开始

```
用户：帮我生成一份本周 AI 行业新闻周报
→ RSS 抓取近 7 天 →（建议 WebSearch 注入市场/融资数据）→ 写「本周看点」→ 生成单文件 HTML → 校验 → 展示。

用户：这周的 AI 新闻怎么样？给我看个简报
→ 走「轻量模式」：对话里直接输出 Markdown 分组列表，不生成网站。
```

线上 Demo：https://elisabeth15501.github.io/ai-weekly/AI_News_2026-09-07.html
（历史各期见 GitHub 仓库根目录 `AI_News_<日期>.html` 同名文件。）

## 三、核心设计理念

- **自治优先，增强可选**：新闻默认全部来自 RSS；默认不调用任何付费/商业 API；外部 API 增强一律用户 opt-in。
- **单文件交付**：CSS/JS 内联，Chart.js 内联，无外部文件依赖。
- **高可信度**：每条新闻必带原始报道 URL。
- **零脑补**：市场/融资/榜单数据无可靠来源时标注「示例/估算数据」或「暂无实时数据」，绝不用训练数据虚构。
- **跨平台单源**：本 SKILL.md 同时服务多引擎；兼容性按 AgentSkills 规范声明。

## 四、硬规则（不要做）

1. 不要凭训练数据脑补数字——市场/融资金额须有可追溯来源。
2. 不要丢掉新闻的 source URL——每张卡片必含可点击原始链接。
3. 不要用「this week / 最近」搜索——关键词强制带年份+月份。
4. 不要把旧闻当本周新闻——早于 7 天前的内容标注 `[n天前]`。
5. 图表数据必须来自真实搜索——未提供时图表标注「示例/估算数据」，不得伪装实时。
6. 不要让新闻卡片没有来源——卡底必有来源名+链接。
7. 不要省略任何章节——某类别无数据标注「暂无数据」但不删章节。
8. 不要编造模型榜单——抓取失败显示「暂无实时数据」，绝不用训练数据虚构模型名。

## 五、数据获取路由

| 数据类型 | 获取方式 | 优先级 |
|---------|---------|--------|
| 新闻列表 | `scripts/fetch_ai_news.py`（RSS：国内 7 + 国外 7） | 主 |
| 市场/融资数据 | 口径路由：`--region cn` 时国内源优先（信通院/IDC中国/艾瑞/IT桔子…），国外源作对照；经 WebSearch 取真实值后 `--market-data`/`--funding-data`（及 `--cn-*` 变体）注入 | 主（需搜索） |
| 模型排行榜 | 多源池（国外 LMArena/Artificial Analysis/HF + 国内 OpenCompass/SuperCLUE/ModelScope），按运行环境自动排序；实时全失败回退国内快照/本地缓存，绝不空白 | 主 |
| 外部 API 增强（可选） | 用户自备 JSON 以 `--external-news-json` 注入，页脚自动署名 | 可选 |

依赖：`feedparser`/`requests`/`beautifulsoup4`（`requirements.txt`）。一律用仓库根 `bash run_report.sh scripts/xxx.py ...` 启动（自动复用受管 venv；缺失时按提示建 venv + `pip install -r requirements.txt`）。

## 六、工作流（完整模式）

1. **确定时间范围**：默认过去 7 天；用户指定时遵从。`--date` 是周期截止日，**重生成历史周报必须显式传**（否则会被改写成当期内容）。
2. **抓取新闻**：`bash run_report.sh scripts/fetch_ai_news.py --output news.json`。降级：WebSearch 手动搜集写成同结构 JSON 走 `--api-json`，或以 `--external-news-json` 注入。
3. **补充市场/融资数据**：各 1-2 次 WebSearch 取真实值，经 `--market-data`/`--funding-data` 注入；无结果则不伪造（图表自动标「示例/估算数据」）。
4. **生成 HTML**：读取 `assets/news_site_template.html` 理解结构后生成。必含：搜索栏、分类标签栏、**「本周看点」编辑洞察区（头版导语，必做）**、响应式卡片网格、市场数据区（4 个 Chart.js 图）、模型排行榜区、暗色模式开关、页脚来源说明。
   ```bash
   bash run_report.sh scripts/generate_site.py --api-json news.json \
     --ranking-json ranking.json --profiles-json model_profiles.json \
     --insights-json insights.json --lead "本周主线：……" \
     -o AI_News_YYYY-MM-DD.html
   ```
   （尽量每次传 `--insights-json` 与 `--lead`；漏传时自动从本周新闻派生基线看点，但建议人工撰写覆盖。）
5. **质量检查**：`bash run_report.sh scripts/validate_report.py --html AI_News_YYYY-MM-DD.html`（内置 XSS 守护：脚本 JSON 无裸 `</script>`，全文无 `javascript:`/`data:` href）。
6. **交付**：文件 `AI_News_YYYY-MM-DD.html`，调用 `present_files` 展示，总结 3-5 条核心发现。

### 6.1 部署（可选但推荐）

周报托管地址供飞书卡片 `view_url` 用，**不一定要 GitHub Pages**：`scripts/deploy.py --deploy-to` 选 `github-pages`（默认）/ `tencent-cos` / `vercel` / `netlify` / `cloudflare-pages` / `local`；非 github 后端无需配置 GitHub。

- **GitHub Pages**：`bash run_report.sh deploy --html AI_News_YYYY-MM-DD.html`（`--no-push` 仅本地；`--switch-pages` 经 API 切 Pages 源到 gh-pages）。
- **飞书头条卡片**：`bash run_report.sh scripts/publish.py --news-json news.json --insights-json insights.json --audience-json audience_summary.json --html AI_News_YYYY-MM-DD.html --deploy`（Webhook 或飞书连接器双路径，密钥不落盘）。

### 6.2 自动化（每周一 09:00）

创建 recurring automation：`FREQ=WEEKLY;BYDAY=MO`，prompt 复用上方工作流（抓取 → WebSearch 注入 → 写本周看点 → 生成 → 校验 → present_files → 可选部署）。

## 七、「本周看点」编辑洞察（必做）

需由 Agent 基于本周新闻**亲自撰写**（非罗列），代入「有 AI 产品经理经验的专业科技媒体工作者」人设，去 AI 味、有观点锋芒。

- `keywords`（必做）：3-6 个，每条 `{term, tag, note}`；`tag` 可省略（自动推断），`note` 可为字符串或按受众分述的对象 `{开发者, PM, 自媒体}`。
- `audience_summary`（推荐）：`{开发者, PM, 自媒体}` 各一句，省略时用内置兜底，区块永不隐藏。
- `insights`：3-5 条，每条 `{kicker, title, analysis(客观事实), insight(三段式：重点分析/本周trends/预计未来发展), related?}`。
- `lead`：一句话头版导语。

写入 `insights.json` 以 `--insights-json` 注入。详细 schema 与去 AI 味要求（禁用对仗模板、禁用赋能/闭环/范式等黑话）见 `references/SKILL_full.md` 第七节。

## 八、网络环境自适应与合规

- **源池与探测**：综合榜源带 `region` 标签，`--region auto` 探测国内/国外哨兵排序优先级；亦支持 `--region cn`/`global`。
- **出站代理**：遵循标准 `HTTPS_PROXY` / `--proxy`（企业内网合规场景）。**本技能不提供、不指导、也不支持任何规避网络管理措施的能力**；源不可达时既定行为是**降级到国内源与离线快照**，而非绕行。
- **排行榜兜底**：国内/未知环境实时源全失败 → 回退 `cn_leaderboard_snapshot.json`（标注截止日，徽章「缓存快照」）；国外 → 回退 `leaderboard_cache.json`。来源透明（徽章 + 页脚说明）。
- **模型资料卡**：`model_profiles.json` canonical 档案每次自动加载；缺档写 `model_profiles.pending.json` 告警，运行方 WebSearch 核实后以 `--profiles-json` 合并写回。

## 九、合规与免责（生成/发布必留）

- **AIGC 标识**：生成 HTML 页脚固定展示「本报告由 AI 辅助编制」标识与免责声明（依《生成式人工智能服务管理暂行办法》第十二条），转载勿移除。
- **不构成投资建议**：市场规模/融资/估值/成本为公开来源静态快照或折算估算，仅供信息参考。
- **零编造**：每条新闻附原始链接；榜单为实时或标注日期的快照，不冒充实时；成本外币折算仅供参考。
- **无内置第三方内容**：不打包任何 AI HOT/卡兹克内容；页脚参考来源与报告实际引用 `DEFAULT_*_SOURCE` 一致。
- **发布建议**：附 LICENSE；提示用户使用外部 API 前先取得授权。

## 十、文件清单（关键入口）

| 文件 | 用途 |
|------|------|
| `SKILL.md`（本文件）/ `references/SKILL_full.md`（完整版） | 入口说明 / 完整文档 |
| `scripts/generate_site.py` | v3.0 主入口：从 API 生成新闻站 |
| `scripts/fetch_ai_news.py` | RSS 抓取（备用离线；`--news-api` 可选） |
| `scripts/validate_report.py` | 质量校验（含 XSS 守护） |
| `scripts/deploy.py` / `scripts/publish.py` | 多后端部署 / 飞书卡片推送 |
| `scripts/aiweekly/` | 核心引擎包（news/leaderboard/render/translate/market/insights…） |
| `assets/news_site_template.html` | v3.0 HTML 模板 |
| `model_profiles.json` · `translations_offline.json` | canonical 模型资料档案 / 离线译文包 |

完整随包清单（91 文件）与发布裁剪说明见 `references/SKILL_full.md` 第十节。

## 参考资料

- `references/SKILL_full.md` — 完整版技能说明
- `references/data_sources.md` / `references/report_structure.md` — 备用数据源 / 报告结构
- `manifest.json` — 通用引擎接口（框架级调用）
