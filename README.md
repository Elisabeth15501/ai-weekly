# AI Weekly Report Skill

> 一个生成 **可搜索、可筛选、支持暗色模式** 的 AI 行业新闻网站（单文件 HTML）的 WorkBuddy 技能。

## 特性

- **自治优先**：新闻默认全部来自 RSS 抓取（14 个精选源：国内 7 + 国外 7），不内置任何第三方商业 API。
- **单文件交付**：所有 CSS/JS 内联，Chart.js 也内联进 HTML，无外部文件依赖。
- **高可信度**：每条新闻附带原始报道 URL。
- **零脑补**：市场 / 融资数据须由 WebSearch 获取真实值后注入，未提供时明确标注「示例 / 估算」。
- **排行榜自适应**：多源池（LMArena / Hugging Face / OpenCompass 司南 / SuperCLUE / ModelScope），实时失败自动回退快照 / 缓存，绝不空白。
- **可定时**：支持每周自动生成最新版网站。

## 快速开始

```bash
# 1. 安装依赖（feedparser / requests / beautifulsoup4）
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 2. 抓取本周 AI 新闻（RSS）
bash run_report.sh scripts/fetch_ai_news.py --output news.json

# 3. 生成单文件新闻网站
bash run_report.sh scripts/generate_site.py --api-json news.json -o AI_News.html

# 4. 校验产出
bash run_report.sh scripts/validate_report.py --html AI_News.html
```

> 统一启动器 `run_report.sh` 会自动探测已安装依赖的 Python（优先复用 `aiweekly` 受管 venv），无需手动激活环境。

## 目录结构

```
ai-weekly/
├── SKILL.md                 # 技能定义（WorkBuddy 载入入口）
├── run_report.sh            # 统一启动器（自动探测 Python + venv）
├── requirements.txt         # Python 依赖
├── scripts/
│   ├── fetch_ai_news.py     # RSS 抓取 → news.json
│   ├── generate_site.py     # 生成单文件 HTML 网站
│   ├── validate_report.py   # 产出校验
│   ├── deploy_report.py     # 部署辅助
│   ├── accumulate_data.py   # 数据累积
│   └── aiweekly/            # 内部 Python 包（news / translate / utils）
├── assets/                  # 模板与静态资源（Chart.js / HTML 模板）
├── references/              # 数据源与报告结构文档
├── data/                    # 运行时小数据（feed 健康、历史）
├── model_profiles.json      # 模型档案（排行榜描述字段权威源）
└── models_cost.json         # 模型成本兜底数据
```

## 可选外部增强（合规说明）

本技能**默认完全自治**，不调用任何第三方商业 API。

若希望用 AI HOT 等「AI 行业知识类」外部 API 增强可信度，请**自行**获取数据并导出 JSON，以 `--external-news-json` 注入；页脚会自动署名。是否启用完全由你决定，并须遵守对应服务条款、自行承担合规风险。使用任何第三方 API 时请保留其署名与授权。

## 兼容性（跨 Agent / 框架可移植性）

> 核心执行引擎（`scripts/` 下的 Python 脚本）**不依赖任何 WorkBuddy SDK**，产物为**单文件 HTML**——可被任意 Agent 框架（OpenClaw / LangGraph / Dify / Coze 等）当作普通脚本 + 普通文件复用。跨框架复用的唯一障碍在"包装层"（`SKILL.md` frontmatter / 启动器路径 / 调度概念），详见 `AI_Weekly_Optimization_Plan.md` 第十三章。

- **引擎层零耦合（可复核）**：以下 grep 应无任何命中：
  ```bash
  grep -rn "import workbuddy\|from workbuddy\|skill_executor" scripts/ || echo "零耦合 ✅"
  ```
- **依赖白名单**：`requirements.txt` 仅 3 个纯标准第三方库——`feedparser` / `requests` / `beautifulsoup4`；无闭源 SDK、无云端强依赖，任何框架可 `pip install` 后直接运行。
- **产物框架无关**：`generate_site.py` 输出**单文件 HTML**（CSS/JS/Chart.js 全部内联），不依赖 WorkBuddy 运行时，可被任意 Agent 返回给用户或托管到静态站点。
- **可选能力分级**：`--translate-en`（英文报道中文总结，依赖本机 Ollama）与 `deploy_report.py`（部署辅助）为**框架增强**能力，不影响核心抓取→生成→校验链路；核心链路 `fetch_ai_news.py → generate_site.py → validate_report.py` 全框架通用。

## 许可

[MIT](./LICENSE) © 2026 Elisabeth15501
