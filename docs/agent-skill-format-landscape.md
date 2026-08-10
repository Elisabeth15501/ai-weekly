# Agent 技能格式格局调研报告

> 调研日期：2026-08-10 | 调研目的：判断 ai-weekly 应优先兼容哪几种格式

---

## 一、核心结论

**SKILL.md 正在成为事实标准。** Anthropic 的 Agent Skills 规范已被 OpenClaw、Coze、OpenAI Agent Plugins 三方采纳，形成「一格式三生态」格局。ai-weekly 当前基于 OpenClaw/AgentSkills 的 SKILL.md 格式**已处于最优赛道**，无需大幅调整。

**优先兼容顺序：**
1. **AgentSkills SKILL.md**（已兼容，维持）— 覆盖 OpenClaw / Claude Code / Coze / 天禧AI
2. **OpenAI Agent Plugins**（低成本适配）— 加 `plugin.json` 包装即可
3. **ClawHub / SkillHub 市场协议**（分发渠道）— 上传现有包即可

**不推荐兼容的格式：** Cursor Rules（不同范式）、Dify DSL（不同生态）、Gemini Gems（无封装格式）

---

## 二、各平台技能格式对比

| 维度 | AgentSkills (Anthropic) | OpenClaw | OpenAI Agent Plugins | Coze 技能 | Cursor Rules | Gemini Gems | Dify 插件 | MCP |
|---|---|---|---|---|---|---|---|---|
| **核心文件** | SKILL.md | SKILL.md | plugin.json + skills/SKILL.md | SKILL.md + 元数据 YAML | .cursor/rules/*.mdc | 自定义指令文本 | plugin.yaml + .wasm | mcp.json |
| **元数据格式** | YAML frontmatter | YAML frontmatter | JSON (plugin.json) | YAML frontmatter | YAML frontmatter | 无（纯文本指令） | YAML Schema v3 | JSON |
| **目录结构** | SKILL.md + scripts/ + references/ + assets/ | 同 AgentSkills | plugin.json + skills/ + mcp.json | SKILL.md + scripts/ + references/ + assets/ | .mdc 单文件 | 无目录结构 | 独立项目目录 | 独立服务器 |
| **分发渠道** | skillstore.io / claude.ai | ClawHub (5700+) | OpenAI Plugin Directory | Coze 技能商店 | cursor Directory | Gemini 内置 | Dify Marketplace | MCP Registry |
| **是否可复用** | ✅ 跨 Claude 生态 | ✅ 跨 OpenClaw 生态 | ✅ ChatGPT + Codex CLI | ⚠️ 仅 Coze 平台 | ⚠️ 仅 Cursor | ❌ 仅 Gemini | ⚠️ 仅 Dify | ✅ 跨平台协议 |
| **与 SKILL.md 兼容** | ✅ 本体 | ✅ 完全兼容 | ✅ 技能部分兼容 | ✅ 兼容 | ❌ 不兼容 | ❌ 不兼容 | ❌ 不兼容 | N/A（协议层） |
| **采用者** | Claude Code, Claude.ai | OpenClaw, 天禧AI | ChatGPT, Codex CLI | Coze（字节跳动） | Cursor IDE | Gemini | Dify | 全平台（Anthropic/OpenAI/Google 等） |

---

## 三、关键发现

### 3.1 SKILL.md 正在成为事实标准

- **Anthropic** 定义 AgentSkills 规范（SKILL.md + YAML frontmatter），Claude Code / Claude.ai 原生支持
- **OpenClaw** 完整遵循 AgentSkills 规范，并通过 ClawHub 形成最大的技能分发市场（5700+ 技能）
- **OpenAI** 于 2026-08-07 发布 Agent Plugins v1.0.0，其 skills/ 目录完全遵循 AgentSkills 的 SKILL.md 格式
- **Coze（字节跳动）** 技能包同样使用 SKILL.md 格式，目录结构高度一致

这意味着：**一个符合 AgentSkills 规范的 SKILL.md，可以直接在 Claude Code、OpenClaw、Coze、以及未来的 OpenAI Agent Plugins 中使用。**

### 3.2 天禧AI（联想）已确认使用 OpenClaw

- 联想天禧 Claw 基于 OpenClaw 内核构建
- 内置 19 个预装 Skills（办公/创作/生活/技术）
- 支持从 ClawHub 安装第三方 Skills
- 端云混合部署，7×24 小时在线

### 3.3 OpenAI Agent Plugins 是重要的新变量

2026-08-07 发布的 Agent Plugins 规范统一了「技能 + MCP 服务器」的打包：
```
my-plugin/
├── plugin.json          # 插件清单
├── skills/              # Agent Skills 格式
│   └── summarize/
│       └── SKILL.md
├── mcp.json             # MCP 服务器配置
└── com.example.client/  # 客户端特定扩展
```

对 ai-weekly 的影响：当前 SKILL.md + run_report.sh 的结构，只需在外层加一个 `plugin.json` 即可兼容 OpenAI Agent Plugins。

### 3.4 Cursor Rules / Gemini Gems / Dify 不可兼容

- **Cursor Rules**：`.mdc` 格式，面向 IDE 上下文注入，与技能封装范式完全不同
- **Gemini Gems**：纯文本自定义指令，无文件封装、无目录结构，不可移植
- **Dify**：YAML DSL 工作流 + WASM 插件，独立生态，与 SKILL.md 无法互操作
- **MCP**：底层协议，不是技能格式——它是技能**内部**可以调用的工具标准

---

## 四、ai-weekly 兼容策略建议

### 当前状态
ai-weekly 已完整支持 AgentSkills 规范：
- ✅ SKILL.md（YAML frontmatter + markdown 正文）
- ✅ scripts/ 目录（Python 脚本）
- ✅ references/ 目录（数据文件）
- ✅ 兼容 OpenClaw / Claude Code / WorkBuddy

### 低成本兼容路径（按优先级）

| 优先级 | 目标格式 | 工作量 | 覆盖平台 |
|---|---|---|---|
| P0（已完成） | AgentSkills SKILL.md | 0 | Claude Code, OpenClaw, 天禧AI, WorkBuddy |
| P1（建议） | OpenAI Agent Plugins | 加 `plugin.json` | ChatGPT, Codex CLI |
| P2（建议） | ClawHub 发布 | 上传现有包 | OpenClaw 全部用户（5700+ 技能生态） |
| P3（可选） | Coze 技能商店 | 同上 + 可能的平台适配 | Coze 用户 |

### 具体行动

1. **创建 `plugin.json`**（5 分钟）：在项目根目录添加符合 OpenAI Agent Plugins v1.0.0 规范的清单文件
2. **注册 ClawHub**：将 ai-weekly 发布到 `clawhub.ai`，扩大分发
3. **不做的**：Cursor Rules (.mdc)、Dify DSL、Gemini Gems —— 范式不同，投入产出比低

---

## 五、数据来源

- [OpenClaw Skills 文档](https://docs.openclaw.ai/tools/skills)
- [Anthropic Agent Skills 规范](https://github.com/anthropics/skills)
- [OpenAI Agent Plugins 公告 (2026-08-07)](https://developers.openai.com/apps-sdk)
- [ClawHub 技能市场](https://clawhub.ai/)
- [Coze 技能开发文档](https://www.coze.cn)
- [联想天禧 Claw 体验报告](https://www.itheat.com/index.php/view/60692.html)
- [Cursor Rules 文档](https://cursor.com/docs/context/rules)
- [Dify 插件开发文档](https://docs.dify.ai)
- [SkillsIndex 生态数据](https://skillsindex.dev)
