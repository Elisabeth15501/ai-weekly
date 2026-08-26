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

# 5. 部署到 GitHub Pages（gh-pages 分支；飞书/钉钉卡片的 view_url 即此地址）
bash run_report.sh deploy --html AI_News.html
#   离线仅本地提交：加 --no-push
#   部署后顺手把 Pages 源切到 gh-pages：加 --switch-pages（需 GITHUB_TOKEN）
```

> **完整分发一步到位**：`publish.py` 在推送飞书卡片的同时可顺带部署周报——
> `bash run_report.sh scripts/publish.py --news-json news.json --insights-json insights.json --html AI_News.html --deploy`。

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
├── delivery/                    # 飞书推送（周报分发，P0）
│   ├── feishu_bot.py            # 卡片构造（build_headline_card）+ Webhook 发送（push）；两路径共用卡片 schema
│   ├── feishu_connector.py      # 飞书连接器直推 CLI（lark-cli，密钥不落盘，复用前者卡片构造）
│   ├── feishu_config.json       # webhook 配置（gitignore，不入库）
│   └── feishu_target.json       # 连接器推送目标（gitignore，不入库）
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

## GitHub Pages 公开站点（在线 demo）

周报通过 `scripts/deploy_ghpages.py` 部署到 **`gh-pages` 分支根目录**，飞书/钉钉卡片里的 `view_url`（`https://<owner>.github.io/<repo>/AI_News_<date>.html`）即指向这里。部署是**本地流水线的一步**（不是 CI），结构如下：

```
gh-pages 分支（Pages 源 = Deploy from a branch: gh-pages / /root）
├── AI_News_2026-08-17.html   # 当期周报（根路径直达）
├── AI_News_<更早日期>.html   # 历史周报（累加保留）
└── index.html                # 自动生成的存档页（列出所有期，最新高亮）
```

发布方式（`run_report.sh deploy` 即封装此脚本）：
```bash
bash run_report.sh deploy --html AI_News.html
#   --no-push        仅本地提交，不推送（离线可跑，待网络恢复后 git push origin gh-pages）
#   --switch-pages   部署后通过 GitHub API 把 Pages 源切到 gh-pages / /root（需 GITHUB_TOKEN）
#   --dry-run        只做 worktree+复制+index 预览，不提交不推送
```

### 首次启用（一次性）
1. 把 `gh-pages` 分支推送到远端：`git push origin gh-pages`（已推过可跳过）。
2. 把 GitHub Pages **源**切到 `gh-pages / /root`（二选一）：
   - **手动**：仓库 **Settings → Pages → Source** 选 **Deploy from a branch → `gh-pages` / `/root`** → Save。
   - **自动（方案 B，推荐）**：建一个 **Classic PAT**（Fine-grained 不被 Pages API 支持，会 403），再跑脚本：
     1. GitHub → 头像 → **Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token**。
     2. 勾选 **`repo`**（含 `public_repo`）与 **`pages:write`**；设较长过期（如 1 年）。
     3. 生成后复制 token（只显示一次），在本机设环境变量并跑：
        ```bash
        export GITHUB_TOKEN=ghp_xxx   # Classic PAT，仅当前 shell 会话有效，不落盘
        bash scripts/setup_pages_source.sh
        ```
        脚本只读环境变量、不回显、不写文件，切源成功后链接约 1 分钟生效。
     > 之后每周自动化带这个 token 跑 `run_report.sh deploy --switch-pages` 即全自动（首次切源后该步骤幂等，可重复跑不影响）。
     > **注意**：`setup_pages_source.sh` 切源走 GitHub REST API，只认 Classic PAT；而 `deploy_ghpages.py` 部署推送走 git smart HTTP，用 `.github_token` 文件（Classic PAT）经 `url.insteadOf` 免交互推送。两处都用 Classic PAT 即可，不要混用 Fine-grained。
3. 等待约 1 分钟，访问 `https://<owner>.github.io/<repo>/AI_News_<date>.html` 验证不再 404。

> **为什么是 gh-pages 分支而非 CI artifact？** 飞书卡片的 `view_url` 直接指向分支根目录的 `AI_News_*.html`，与「Deploy from a branch」模型天然契合；GitHub Pages 只允许单一来源，故原先的 `.github/workflows/mirror.yml`（Actions artifact 部署）已停用（`if: false`），以免两种来源互斥导致部署失败。

### 已知限制
- **中文翻译**：若需公开站点也带中文总结，请在**本地**生成时加 `--translate-en`（依赖本机 Ollama），再 `run_report.sh deploy` 推上去。
- **数据新鲜度**：周报新闻窗口为「最近 7 天滚动」（RSS 仅保留约 1 周），要保留某周需在该周仍处保留期内至少部署一次。

### 排错：gh-pages 部署 / 推送常见坑

- **飞书 `view_url` 打开 404**：先确认 Pages **源**已切到 `gh-pages / /root`（Settings → Pages → Source）。若已切源仍 404，多半是 `deploy_ghpages.py` 的 `git push` 没推上云——本地已 commit 但远端还是旧版本。用 `curl -I https://<owner>.github.io/<repo>/AI_News_<date>.html` 验证 HTTP 状态。
- **`git push` 报 `invalid credentials` / 卡死超时**：这是**认证方式**问题，**不等于 token 无效**（可用 `curl -H "Authorization: Bearer <token>" https://api.github.com/user` 验证 token 本身有效）。
  - ❌ 不要走 `http.extraheader=AUTHORIZATION: Bearer <token>`：`Bearer` 只对 GitHub **REST API** 有效；git 推送走 **git smart HTTP** 协议，只认 **Basic** 认证，会被拒。
  - ❌ 不要依赖 Windows `wincred` 凭据助手：无交互 tty 的环境（CI / 沙箱 / 定时自动化）会卡在用户名提示导致超时。
  - ✅ 正确做法（已内置）：把 **Classic PAT** 写入本地 `ai-weekly/.github_token`（已 gitignore，不入库），`deploy_ghpages.py` 会用 `url.insteadOf` 把 token 嵌进远端 URL + 清空 `credential.helper`，自动走 Basic 认证完成免交互推送。也可通过环境变量 `GITHUB_TOKEN` / `GH_TOKEN` 传入。
- **`setup_pages_source.sh` 切源报 403 / 404**：Pages 源切换的 GitHub API **不支持 Fine-grained PAT**（常 403）。改用 **Classic PAT**（`repo` + `pages:write`）即可。

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
| **框架增强** | 飞书头条卡片推送 | `publish.py` + `delivery/feishu_bot.py`（webhook）/ `delivery/feishu_connector.py`（连接器） | 飞书 webhook URL 或已连接的飞书连接器（lark-cli） |
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

## 飞书头条卡片推送（可选）

生成报告后，可把**本周头条速览**以飞书消息卡片推送到群 / 私聊，让情报在"工作者已在用的地方"被消费。两种路径**共用同一张卡片 schema**（由 `delivery/feishu_bot.build_headline_card` 构造）：

| 路径 | 发送方式 | 凭据 | 适合 |
|------|---------|------|------|
| **A. Webhook 自定义机器人** | `feishu_bot.push()` POST 到飞书 incoming webhook | webhook URL（token 内嵌在 URL） | 任意环境，已建好自定义机器人 |
| **B. 飞书连接器直推（推荐）** | `delivery/feishu_connector.py` 经 `lark-cli im +messages-send` | 连接器托管，绝不落配置文件 | WorkBuddy 用户，密钥不想写进仓库 |

**模式 A — Webhook（一步完成）**

```bash
bash run_report.sh scripts/publish.py \
  --news-json news.json --insights-json insights.json \
  --audience-json audience_summary.json \
  --view-url "https://<托管地址>/AI_News_YYYY-MM-DD.html" \
  --output report.json --webhook "https://open.feishu.cn/open-apis/bot/v2/hook/XXXX"
```

webhook 三级回退（`--webhook` > `$FEISHU_WEBHOOK` > `delivery/feishu_config.json`）皆空时跳过推送（exit 0，不阻断生成）。

**模式 B — 飞书连接器直推（密钥不落盘，推荐）**

```bash
# 先组装 report.json（此步不推送）
bash run_report.sh scripts/publish.py \
  --news-json news.json --insights-json insights.json \
  --audience-json audience_summary.json --output report.json

# 经飞书连接器推送到群（bot 身份，需先把「WorkBuddy-Feishu CLI」机器人加进群）
python delivery/feishu_connector.py --report report.json --chat-id oc_xxxx

# 推给自己（user 身份 → 私聊，首次冒烟测试最省事）
python delivery/feishu_connector.py --report report.json --user-id ou_xxxx --as user
```

目标解析优先级：`--chat-id/--user-id` > 环境变量 `FEISHU_CHAT_ID/FEISHU_USER_ID` > `delivery/feishu_target.json`。依赖仅为标准库 + 已连接的飞书连接器，无需 `requests`。

> 卡片内容（两种模式一致）：本周主线 + 🔥本周重点（Top5）+ 💡本周看点（Top3）+ 👥分角色摘要 + 🔖关键词 + 「查看完整周报」按钮（链接自动追加 `?src=feishu&uid=<uid>` 度量参数）。

---

## 相关文档

- [对抗式代码审查报告](./AI_Weekly_Adversarial_Review.md) — 安全缺陷修复详情与 payload 验证
- [优化方案文档](./AI_Weekly_Optimization_Plan.md)（如有）— 工程债清单与北极星规划

---

## 许可

[MIT](./LICENSE) © 2026 Elisabeth15501
