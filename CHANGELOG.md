# Changelog

本文件记录 ai-weekly（AI 行业周报生成技能）从 1.0.0 到 3.4.0 的全部变更。

> **关于版本说明**：`3.1.1` 是本技能的**首个正式公开发行版**（发布于 SkillHub）。
> 此前的 `1.0.0`–`3.1.0` 为开发迭代历史，仅 `3.0.0`、`3.1.0` 在版本库中留有版本标记；
> `1.0.0`、`2.0.0` 的节点系根据《AI Weekly 优化计划》的"已落地"记录与提交历史推断重建（见各版本注）。
> 所有早期版本的功能均已在 `3.1.1` 中可用。

格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [3.4.3] — 2026-09-09
对标 SkillHub 评测「适用性·触发方式 4.3 / 可信任度·国内适配性 4.3 / 可靠性·异常处理 4.3」三项短板：补齐多轮真实对话示例、修复国内榜源（清除假镜像 + 换真 API）、把专业告警翻译成人话。

### Added
- **真实对话场景（SKILL.md § 1.1）**：5 则多轮对话（时间窗澄清 / 中途改需求 / 抓取失败排障 / 历史周报复现边界 / 参数细化），每条命令均实测可用；FAQ 第一节加对应速查表
- **`aiweekly/diagnostics.py`（新模块）**：告警「人话翻译」展示层，规则表驱动，把专业异常转成「为什么 + 下一步怎么办」；生成结束后追加「💡 给你的提示」段落（无告警时静默）
- **HF 镜像热门开源模型源（hm）**：走 `hf-mirror.com/api/models`，国内可直连，仅收录文本生成/对话类；热度榜非能力基准，报告已注明

### Fixed
- **清除两个「假镜像」（P0 安全）**：`lmarena.org.cn` 实测域名不存在；`aa-cn.mirror.xyz` 返回的是 mirror.xyz 博客平台页面（与 AA 无关，HTTP 200 但内容无关，可能污染榜单）——均已从 `URL_REWRITES` 移除。`hf-mirror.com/datasets-server` 实测 401 亦移除
- **ModelScope 魔搭源 0% 成功率修复**：原抓 `modelscope.cn/models` 页面（SPA，33 次调用 0 次成功），改用官方 `openapi/v1/models`（实测 200 + JSON，含下载量/许可证/参数量）
- **Frontmatter 触发词扩充**：按「生成 / 分发与运维」分类，补口语化触发（「这周 AI 有什么大事」「给我看个 AI 简报」等），并明确「直接说人话就能触发，不需要记命令」

### Changed
- 榜源池 8 → 9 源，实测命中数由 3 提升至 **6**（ModelScope 与 HF 镜像两个国内源均由 0/新增转为 ok）
- SKILL.md 新增 § 8.1「国内用户怎么办」：公开 33 次运行实测的各源成功率表，诚实说明 LMArena / AA 无官方国内镜像（硬边界），并给出「接受降级 / 配置代理 / 自备 JSON 注入」三条出路

## [3.4.2] — 2026-09-08
修复「周次漂移」事故：`refresh_deploy.py` 每日刷新时未给 `generate_site.py` 传 `--date`，报告周期被重置为「当天 −7 ~ 当天」，导致 gh-pages 上历史周报 `AI_News_2026-08-31.html` 被覆盖成 9/1–9/8 的 W37 内容（文件名仍是 8-31）。本次同时回滚了 gh-pages 上的该文件至真实 W36（8/24–8/31，112 条）版本。

### Fixed
- **`refresh_deploy.py` 报告周期漂移（P0）**：新增 `_report_date()`，从新闻 JSON 的 `date_end` 推导周期截止日（兜底取输出文件名中的日期），并显式传给 `generate_site.py --date`；文件名日期与新闻周期不一致时以新闻周期为准改写输出名并告警
- **gh-pages 存档回滚**：`AI_News_2026-08-31.html` 恢复为 2026/8/24–8/31 的 W36 版本；`AI_News_2026-09-07.html` 重新生成为 2026/8/31–9/7 的 W37 版本（115 条，校验 25/25）

## [3.4.1] — 2026-09-07
实时排行榜复盘（优化方案 v2·第十节）R1–R4 修复：来源透明化（R1）+ 国内源诚实化（R2）+ 慢源超时提额（R3）+ 系统级调度兜底（R4）。核心：榜单来源标注与真实数据严格一致；删除永不触发的"国内实时源回退"死代码；LMArena/HF/AA 慢源超时提额并放宽整体墙钟上限；新增 `install_scheduler.py` 把每日刷新注册为操作系统级任务，会话不在线也能刷新。

### Added
- **R4 系统级调度兜底**（`scripts/install_scheduler.py`）：新增注册器，按 OS 自动选 Windows 任务计划 / Linux cron，每日 09:00 调用 `refresh_deploy.py` 刷新排行榜；`--uninstall` / `--dry-run` / `--time` 选项齐全；WorkBuddy automation 仍作即时触发，系统调度仅兜底

### Changed
- **R3 慢源超时提额**（`leaderboard_sources.py` / `leaderboard_fetch.py`）：LMArena 超时 60→75s、Hugging Face 45→60s、Artificial Analysis 45→60s；整体墙钟硬上限 `OVERALL_FETCH_CAP_S` 180→240s，给慢源留足重试墙钟（3×75s=225s < 240s）
- **R4 刷新编排更稳健**（`refresh_deploy.py`）：`--api-json`/`--output` 缺省自动落位（`<skill>/workspace/news.json` / `AI_News_live.html`），便于系统调度无参调用；生成步骤失败自动重试 1 次（网络抖动避免一次性放弃整轮刷新）

### Fixed
- **R1 开源榜来源透明**（`leaderboard.py` / `leaderboard_fetch.py` / `news_site_template.html`）：`ls`(LLM-Stats) 源国内实测 0% 实时率，开源榜左列此前用 `dl`(DataLearner) 数据却标"LLM-Stats"——改为按真实命中源动态选 `label`/`criteria`/`url`，命中 `dl` 即显示 `DataLearner · 开源模型榜`；新增 `LB_CRITERIA["dl"]` 真实评分标准；前端图例与兜底默认值同步诚实化
- **R2 国内源诚实化**（`leaderboard.py` / `leaderboard_sources.py`）：探测确认 OpenCompass/SuperCLUE/ModelScope 均为 SPA、简单 HTTP 抓不到（能力性限制非 bug），原"oc/sv 国内实时源回退"两段 `if` 死代码（实测 0% 永不触发）已删除；cn 综合榜如实依赖 aa/lm 实时源、二者皆失败回退 `cn_snap` 静态快照（已标 `is_cache`）；三源仍留池作 best-effort

### 验证
- R1 单测（mock `ls` 空 + `dl` 有数据）：开源榜左列 `source` 输出 `DataLearner · 开源模型榜`、`is_cache=False`
- R4 `install_scheduler.py --dry-run` 正确拼装 schtasks/cron 命令（未落盘）
- `py_compile` 全部通过；`leaderboard.py` 797 行 < 800 行模块体量守护上限

---

## [3.4.0] — 2026-09-05
SkillHub 评测驱动优化全面落地（P0 阻断级 + P1 体验级 + P2 完善级），响应官方评测报告 4.52/5 指出的 5 类问题。核心目标：飞书推送不再依赖 GitHub Pages、模型数据经得起来源核验、海外源国内稳定可达、新用户学习成本降低。

### Added
- **P0-1 统一部署分发器**（`scripts/deploy.py`）：新增统一入口，支持 6 种后端（github-pages / tencent-cos / vercel / netlify / cloudflare-pages / local）；`publish.py --deploy-to` + `run_report.sh deploy` 改调 `deploy.py`（向后兼容）；飞书卡片 `view_url` 与部署后端解耦，非 github-pages 后端完全不碰 GitHub；附 `delivery/deploy_config.example.json` 配置示例
- **P0-2 模型档案准确性守护**（`scripts/validate_models.py` / `model_profiles.json`）：将 15 条无来源推测条目（`source=榜单自动抓取·未联网核实`）移入 `model_profiles_unverified.json`，主表 72→57 条全部 `verified=true`；`model_meta._apply_profile_as_truth` 跳过 `verified=false`；`validate_report.py` 新增 `check_model_profiles_accuracy`（校验 24/24 → 25/25）
- **P0-3 海外源国内镜像**（`leaderboard_sources.py` / `scripts/aiweekly/utils.py`）：新增 `URL_REWRITES`（HF/LMArena/AA 主源 → hf-mirror.com 等国内镜像）+ `_http_get_fallback` 主源失败自动回退镜像，全失败走快照兜底；`HF_MIRROR` / `AA_MIRROR` / `LM_MIRROR` 环境变量可覆盖；新增 `scripts/leaderboard_diagnose.py` 诊断工具
- **P1-1 SKILL.md 快速开始**（`SKILL.md`）：顶部新增「快速开始」章节（5 个真实对话示例），部署章节更新为多后端写法
- **P1-2 独立 FAQ 文档**（`references/FAQ.md`）：新建九节 + 排错速查表，README / SKILL.md 加 FAQ 入口
- **P1-3 交互式飞书配置**（`scripts/init_feishu_config.py`）：webhook / connector 双模式交互式生成 `feishu_config.json` + 格式校验；`SKILL.md` 补配置指引
- **P1-4 错误提示人性化**（`scripts/aiweekly/errors.py`）：新增 `ERR-*` 错误码注册表 + `UserFacingError` 异常类 + `print_error()`；`deploy.py` / `feishu_connector.py` 关键错误改用含解决步骤的友好提示；日志落盘 `~/.aiweekly/run.log`
- **P2-1 硬约束常量集中声明**（`scripts/aiweekly/const.py`）：新增 `NEWS_MAX_ITEMS=100` / `LEADERBOARD_TOP_N=50` / `HTML_MAX_SIZE_BYTES=5MB` / `CHART_MAX_DATA_POINTS=20` / `LEADERBOARD_MAX_MODELS=50`；`scripts/validate_checks/constraints.py` 新增 `check_constraints()` 事后审计；`validate_report.py` 接入（校验 25/25）
- **P2-2 文档层硬约束**（`SKILL.md` / `README.md`）：SKILL.md 第二节.5 新增「硬约束」小节；README「已知限制」补充约束链接
- **P2-3 SkillHub 元数据**（`manifest.json`）：版本升至 3.4.0，新增 `features` 字段（10 项核心优势）
- `delivery/deploy_config.example.json`：部署配置示例

### Changed
- `run_report.sh deploy` 子命令改调 `deploy.py`（向后兼容）；`publish.py` 新增 `--deploy-to`
- `news.py` 从 `const.py` 重新导出统一常量（行为不变）
- 验证套件：25/25 → 26/25（constraints 为 warn 级非硬门槛）

### Fixed
- **P0-2**：15 条无来源锚点的推测模型移出主表，避免伪造数据污染榜单
- **P1-4**：部署失败不再输出裸 RuntimeError，改为含解决步骤的 ERR-* 错误码

### 验证
- `validate_report.py` 26/25 全过（constraints 为 warn 级）；对抗式审查 verify 31/31 / test 21
- 国内镜像回退经 `leaderboard_diagnose.py` 实测命中；模型档案 57 条全部 `verified=true`

## [3.3.1] — 2026-09-03
对抗式安全/健壮性审查的收尾版本：把审查报告（2026-09-02）标记的剩余项全部闭环，并补齐工程可读性。

### Added
- 无新增功能。

### Changed
- **飞书连接器通道根治（R6）**：`delivery/feishu_connector.py` 的 `send_card` 不再把整卡 JSON 作为 `--content` 命令行参数传给 lark-cli（受 Windows 命令行 ~8191 字符上限约束，满配卡片会静默 spawn 失败），改为经 `lark-cli api POST /open-apis/im/v1/messages --data -` 的 **stdin** 传入，从根本上消除 argv 上限；删除原阈值告警常量。
- **优先别名逻辑抽纯函数（S1）**：`scripts/aiweekly/insights.py` 的 `_auto_keywords` 内联脆弱保送逻辑抽成模块级纯函数 `_apply_priority_alias(ranked, cands, top_n)`，语义等价，可单测。
- **榜源并行整体截止（S2）**：`scripts/aiweekly/leaderboard_fetch.py` 已有并发 + 单源隔离，本版本补整体墙钟硬上限 `OVERALL_FETCH_CAP_S=180`（`wait(timeout=)` + 超时源标记 `timeout` 跳过 + 非阻塞 `shutdown`），杜绝"一个慢源拖垮整份周报"。

### Fixed
- **安全/健壮性审查闭环（C1/R1/R2/R3/R4/R5）**（已在 3.3.0 后续提交落地，本版本随发布封版）：
  - **C1/N1**：`_md_escape` 死代码重写为真转义器（飞书卡片排版）。
  - **R1**：`publish.py` 脏数据 `float(score)` 加 `_safe_score` 兜底。
  - **R2**：关键词截断前按保送集（牛来）优先排序。
  - **R3/R4**：`refresh_deploy.py` PAT 改走 `GIT_CONFIG_*` 环境变量、推送失败返回非零码（不再静默 exit 0）。
  - **R5**：`canon_key` 后缀感知（`glm53~flash`）消除 GLM-5.3 ≡ GLM-5.3-Flash 撞键。
- **N2（可读性）**：`scripts/publish.py` 三处 best-effort `except Exception # noqa: BLE001` 补齐「为何必须吞」注释（导入回退保送集 / 末段分发不中断报告 / deploy 不回滚报告）。

### Notes
- 本次为审查收尾 + 合规发布，无用户可见行为变化；卡片结构、报告 schema、部署链路均与 3.3.0 兼容。

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
| 3.4.0 | 2026-09-05 | **SkillHub 评测驱动** | P0/P1/P2 全部落地

_注：1.0.0 / 2.0.0 的版本号与日期为根据《优化计划》"已落地"记录重建，未在版本库中单独标记；如与实际心智模型不符，可在本文件中直接调整。_
