---
name: ai-weekly
version: 3.0.0
author: Elisabeth15501
description: 生成可搜索/筛选/暗色模式的 AI 行业新闻单文件网站（RSS 自治，零第三方 API 依赖）。当用户要生成 AI 周报 / AI 行业周报 / AI 新闻网站，或需要一份可分享的 AI 情报单页时使用；不适用于需要实时数据库或私域数据的场景。
license: MIT
homepage: https://github.com/Elisabeth15501/ai-weekly
tags: [ai, news, report, rss, weekly, 人工智能, 周报]
triggers:
  - "AI周报"
  - "AI行业周报"
  - "AI新闻"
  - "weekly AI report"
  - "人工智能周报"
  - "AI行业动态"
  - "生成AI报告"
  - "AI新闻网站"
  - "AI新闻站"
metadata:
  openclaw:
    emoji: "🗞️"
    requires:
      bins:
        - python3
        - pip
    envVars:
      - name: AIWEEKLY_OLLAMA_URL
        required: false
        description: "本地 Ollama 翻译后端地址；设置后 --translate-en 可用，默认 http://localhost:11434/api/generate"
---

# AI Weekly Report（OpenClaw 版）

> **这是 `ai-weekly` 的 OpenClaw 包装版**。核心执行引擎（`../scripts/` 下的纯 Python 脚本）与 WorkBuddy 版**完全相同、零改动**——本文件只负责把"包装层"翻译为 OpenClaw 能识别的 `SKILL.md` 格式（frontmatter 字段、`triggers`、调度概念）。整个仓库克隆后，`../scripts/` 就在上一层目录，命令里的 `../scripts/...` 即指向共享引擎。
>
> 若要把它作为**独立**的 OpenClaw 技能发布（不依赖父目录），把 `../scripts/` 整个目录复制进本目录即可，命令中的 `../scripts` 改为 `./scripts`。

## 这个 Skill 能做什么

把一周的 AI 行业信息（新闻 / 模型发布 / 产品 / 融资 / 论文）聚合成一个**单文件 HTML 网站**：可搜索、可按分类筛选、支持暗色模式，每条新闻都带原始报道链接。

- **自治优先**：新闻默认全部来自 RSS 抓取（14 个精选源：国内 7 + 国外 7），不内置任何第三方商业 API；如需用 AI HOT 等外部知识库增强，由你自行取数以 `--external-news-json` 注入（页脚自动署名）。
- **单文件交付**：所有 CSS / JS / Chart.js 全部内联，无外部依赖。
- **排行榜自适应**：LMArena / Hugging Face / OpenCompass 司南 / SuperCLUE / ModelScope 多源池，实时失败自动回退国内快照，绝不空白。
- **中文总结**：英文报道可经本机 Ollama 翻译为中文摘要（`--translate-en`）。

## When to Use

- 用户说"生成 AI 周报 / AI 行业周报 / AI 新闻网站 / AI 新闻站"。
- 用户想要一份可分享、可筛选、可归档的本周 AI 情报单页。
- 定时任务：每周六 09:00 自动生成最新一期（见下方调度）。

## When NOT to Use

- 需要实时数据库 / 私域数据 / 非公开接口的场景。
- 需要把新闻"推送到飞书 / 钉钉"等 IM —— 那是分发层（见可选增强），不是本 Skill 的核心产出。
- 需要交互式多轮对话追问 —— 本 Skill 是"一次性生成静态站点"的批处理工具。

## Prerequisites（运行前确认）

1. Python ≥ 3.10 与 `pip` 可用（`requires.bins` 已声明）。
2. 安装依赖：
   ```bash
   pip install -r ../scripts/../requirements.txt   # 即仓库根 requirements.txt：feedparser / requests / beautifulsoup4
   ```
   > 若已把 `scripts/` 复制到本目录，改为 `pip install -r ./scripts/../requirements.txt` 或直接 `pip install feedparser requests beautifulsoup4`。
3. 网络：RSS 抓取与排行榜实时源需要外网；国内环境会自动回退 OpenCompass / SuperCLUE 等国内源与本地快照。
4. （可选）本地 Ollama 翻译：设置 `AIWEEKLY_OLLAMA_URL` 并安装 `qwen2.5:7b` 等模型后，`--translate-en` 才会生效。

## Commands（模型参照生成实际命令）

> 统一启动器 `../run_report.sh` 会自动探测已安装依赖的 Python（优先 `python3` / `AIWEEKLY_PYTHON` 环境变量，其次 WorkBuddy 受管 venv），无需手动激活环境。下面命令假设你在本目录（`openclaw-edition/`）下执行。

**1. 抓取本周 AI 新闻（RSS → news.json）**
```bash
bash ../run_report.sh ../scripts/fetch_ai_news.py --output news.json
# 指定 ISO 周：--week 2026-W32
```

**2. 生成单文件新闻网站**
```bash
bash ../run_report.sh ../scripts/generate_site.py \
  --api-json news.json \
  --insights-json ../insights.json \
  --date 2026-08-08 \
  --output AI_News_2026-08-08.html
# 英文报道中文总结（需本机 Ollama）：追加 --translate-en
# 离线出榜（不抓实时排行榜，用快照）：追加 --no-live-ranking
# 市场/融资数据由 WebSearch 取真实值后注入：--market-data ... / --funding-data ...
```

**3. 校验产出**
```bash
bash ../run_report.sh ../scripts/validate_report.py --html AI_News_2026-08-08.html
```

**4.（可选增强）提取摘要 / 生成通知文本**
```bash
bash ../run_report.sh ../scripts/deploy_report.py --html AI_News_2026-08-08.html
# 输出 <html>.summary.json + 一段框架无关的通知文本，可粘贴到任意 IM / 推送通道
```

## Scheduling（调度）

OpenClaw 版把 WorkBuddy 的"每周一 09:00 automation"概念转译为**标准 cron**：

```
# 每周六 09:00 自动生成最新一期
0 9 * * 6  bash /path/to/ai-weekly/openclaw-edition/run_generate.sh
```

> 仓库未内置 `run_generate.sh`；请在你的 OpenClaw 调度器 / 系统 cron 里包装上面的第 1+2 步，或把这两步写进一个 shell 脚本后由 cron 调用。这样调度语义与 WorkBuddy automation 等价，但不绑定任何框架专属动词。

## Notes

- **零脑补**：市场 / 融资数据必须由 WebSearch 取真实值后注入；未提供时图表会明确标注「示例 / 估算数据」，绝不编造榜单。
- **每条新闻必带来源**：卡片底部有来源名 + 可点击链接。
- **产物框架无关**：输出是单文件 HTML，不依赖 OpenClaw 运行时，可被任意 Agent 返回或托管到静态站点。
- **跨框架复用**：核心引擎不依赖任何 Agent SDK；LangGraph / Dify / Coze 等框架可经仓库根 `manifest.json` 的最小接口描述直接调用同一套 Python。
- **许可**：MIT © 2026 Elisabeth15501。
