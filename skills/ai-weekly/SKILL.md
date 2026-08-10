---
name: ai-weekly
description: >-
  Generates a self-contained, searchable, filterable HTML website of the week's AI industry news (models, products, funding, papers).
  Aggregates from 14 RSS feeds (7 Chinese + 7 global), renders leaderboards from multiple sources with automatic fallback, and
  produces a single-file deliverable with inline CSS/JS/Chart.js. Use when the user asks for an AI weekly report, AI industry
  newsletter, AI news website, or a shareable single-page AI intelligence briefing.
license: MIT
compatibility: AgentSkills, Claude Code, Claude.ai, ChatGPT Plugins, Codex CLI, OpenClaw
metadata:
  author: Elisabeth15501
  version: "3.0.0"
  homepage: https://github.com/Elisabeth15501/ai-weekly
  tags: [ai, news, report, rss, weekly, leaderboard, market-data]
---

# AI Weekly Report

Generates a single-file HTML website that aggregates one week of AI industry intelligence:
news, model releases, product launches, funding rounds, and research papers — all sourced
from RSS feeds with zero hardcoded third-party commercial APIs.

## When to Use

- User says "generate AI weekly report", "AI industry newsletter", "AI news website"
- User wants a shareable, filterable, dark-mode-ready AI intelligence page
- Scheduled task: auto-generate the latest issue every Saturday at 09:00

## When NOT to Use

- Tasks requiring real-time databases, private data APIs, or non-public endpoints
- Pushing news to IM platforms (Feishu/DingTalk) — that's a distribution layer, not this skill's core output
- Interactive multi-turn Q&A — this is a batch tool that produces a static site

## Prerequisites

1. Python >= 3.10 with `pip`
2. Install dependencies: `pip install feedparser requests beautifulsoup4`
3. Network: RSS fetching and live leaderboard sources need internet access;
   Chinese-network environments auto-fallback to domestic sources (OpenCompass, SuperCLUE, ModelScope) and local snapshots
4. (Optional) Local Ollama translation: set `AIWEEKLY_OLLAMA_URL` env var, install a model like `qwen2.5:7b`, then use `--translate-en`

## Commands

All commands use `run_report.sh` as the unified launcher. It auto-detects Python (preferring the `aiweekly` managed venv,
falling back to `python3`/`python`).

### 1. Fetch this week's AI news (RSS → news.json)

```bash
bash run_report.sh scripts/fetch_ai_news.py --output news.json
```

### 2. Generate the single-file news website

```bash
bash run_report.sh scripts/generate_site.py \
  --api-json news.json \
  --insights-json insights.json \
  --date 2026-08-10 \
  --output AI_News_2026-08-10.html
```

Optional flags:
- `--translate-en` — translate English articles to Chinese summaries via local Ollama
- `--no-live-ranking` — skip live leaderboard fetching, use cached snapshots
- `--market-data ...` / `--funding-data ...` — inject real market/funding figures from WebSearch
- `--data-snapshot ...` — label the report with a static data snapshot date
- `--proxy ...` — route traffic through an HTTP/SOCKS proxy
- `--region cn|global` — override auto-detected network region

### 3. Validate the output

```bash
bash run_report.sh scripts/validate_report.py --html AI_News_2026-08-10.html
```

### 4. (Optional) Extract summary for distribution

```bash
bash run_report.sh scripts/deploy_report.py --html AI_News_2026-08-10.html
```

## Scheduling

Standard cron for weekly generation:

```
0 9 * * 6  bash /path/to/ai-weekly/run_report.sh scripts/fetch_ai_news.py --output /tmp/news.json && bash /path/to/ai-weekly/run_report.sh scripts/generate_site.py --api-json /tmp/news.json --insights-json /path/to/ai-weekly/insights.json --date $(date +%Y-%m-%d) --output /path/to/output/AI_News_$(date +%Y-%m-%d).html
```

## Architecture

- **Engine**: Pure Python, 11 modules (`scripts/aiweekly/`), zero Agent SDK dependencies
- **News sources**: 14 RSS feeds (7 Chinese + 7 global), categorized by keyword + source hint
- **Leaderboards**: Multi-source pool (LMArena, Hugging Face, OpenCompass, SuperCLUE, ModelScope) with auto-fallback
- **Market data**: Global + China market size and funding charts (2x2 grid), static data injected via CLI
- **Model profiles**: 26+ curated model profiles (cost, context window, license, currency) as single source of truth
- **Output**: Single-file HTML with inline CSS/JS/Chart.js — no external dependencies, ready to host or share
- **Validation**: Comprehensive validator checking news cards, leaderboard sections, market charts, insights, and keywords

## Notes

- **No fabrication**: Market/funding data must be injected from real WebSearch results; charts are clearly labeled "estimate/sample" when data is unavailable
- **Every news item carries its source**: source name + clickable link at the bottom of each card
- **Framework-agnostic output**: The output is a single-file HTML — no runtime dependency on any Agent SDK
- **Cross-framework reuse**: The core engine can be called directly by LangGraph, Dify, Coze, or any framework via the root `manifest.json`
- **License**: MIT © 2026 Elisabeth15501
