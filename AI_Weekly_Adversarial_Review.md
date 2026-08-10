# ai-weekly 对抗式代码审查报告

- **审查对象**：`~/.workbuddy/skills/ai-weekly`（含 `scripts/` 引擎 + `openclaw-edition/` + `manifest.json`）
- **审查日期**：2026-08-10
- **方法**：红队视角逐模块读码 + 恶意 payload 注入回归测试（不依赖既有 import 冒烟，而是跑完整 `generate` 管线）
- **结论一句话**：核心引擎工程质量高（依赖注入 / 窄异常 / ISO8601 / 模块拆分 / 校验守护齐备）；**唯一严重缺陷是 RSS 不可信内容经 `<script>` 上下文 JSON 注入的存储型 XSS，本次已修复并加回归用例**。

---

## 🔴 严重（High）—— 已修复

### H1. 存储型 XSS：`<script>` 上下文 JSON 注入
- **位置**：`aiweekly/render.py` 把 `NEWS_DATA` / `LEADERBOARD_DATA` / `INSIGHTS_DATA` / `INSIGHTS_KEYWORDS` / `WEEKLY_STATS` / `AUDIENCE_SUMMARY` 等 JSON 直接用 `json.dumps(..., ensure_ascii=False)` 替换进模板占位符；模板在 `<script>` 块内消费（`const NEWS_DATA = [NEWS_DATA_PLACEHOLDER];`）。
- **根因**：Python 的 `json.dumps` **不转义 `<` `>` `&`**，因此新闻标题若含 `</script><img src=x onerror=...>`，HTML 解析器会在脚本中途看到 `</script>` 而结束脚本块，后续内容被当作 HTML 执行。
- **攻击面**：新闻来自 14 个公开 RSS 源（不可信），任一源被劫持/投毒即可在**所有打开该报告的人**浏览器执行 JS（报告被设计为可分享/托管）。
- **利用**：`title = "</script><img src=x onerror=alert(document.cookie)>"` → 脚本突破 → XSS。
- **修复**：新增 `_json_script_safe()`，序列化后把 `<` `>` `&` 转义为 `\u003c`/`\u003e`/`\u0026`（阻止 `</script>` 突破，且经 JS `innerHTML`+`escapeHtml` 后仍按纯文本显示）。所有 JSON 占位符改用该函数。
- **验证**：构造含 `</script><img onerror=...>` 的 news.json 跑完整 generate，确认生成的 HTML 中**不再出现原始 `</script>`**，且 JSON blob 内为 `\u003c/script\u003e`。✅

### H2. 新闻卡 / 看点外链 URL 未转义（属性突破 + 危险协议）
- **位置**：模板 `news card` 的 `href="${n.url}"`（原未用 `escapeHtml`）；`renderInsights` 中 `related` 链接 `href="${escapeHtml(r.url)}"`（已转义属性引号，但**未校验协议**）。
- **风险**：`n.url` 来自 RSS（不可信）。① `"` 可突破 `href` 属性；② `javascript:alert(1)` 类 URL 点击即执行。
- **修复**：模板新增 `safeUrl()`，仅放行 `http(s):`/`mailto:`，其余回退 `#`；新闻卡与外链均改为 `href="${escapeHtml(safeUrl(url))}"`。
- **验证**：`url="javascript:alert(1)"` 经 generate 后不会以 `href="javascript:..."` 形式出现（渲染期被 `safeUrl` 转 `#`）。✅

---

## 🟠 中危（Medium）—— 已修复 / 已加固

### M1. 外部数据源名/URL 直接拼 HTML
- **位置**：`render.py` 构建 `[ALL_SOURCES]` / `[NEWS_SOURCE_EXTRA]` 时，`external_source` 的 name/url（来自 `--external-source-name`/`--external-source-url` CLI）未转义、未校验协议。
- **修复**：构建时 `html.escape` 名称与 URL，并用 `_safe_url()` 仅放行 `http(s):`/`mailto:`；基础源 `BASE_SOURCES` 也统一走转义。
- **影响面**：用户显式提供的 CLI 参数（非 RSS），风险低于 H1/H2，但仍是正确性问题。✅

### M2. `[LEAD]` / `[KEYWORD_SEARCH_BASE]` 原始插入
- **位置**：`[LEAD]` 在 HTML 上下文直接 `template.replace("[LEAD]", _lead or "")` 未转义；`[KEYWORD_SEARCH_BASE]` 在 JS 字符串字面量 `const KEYWORD_SEARCH_BASE = "[...]"` 中未做 JS 转义（含 `"` 会破坏字符串）。
- **修复**：`[LEAD]` 改 `html.escape`；`[KEYWORD_SEARCH_BASE]` 改 `_js_str()`（转义 `\"`/`\\`/换行/`<>&`）。
- **影响面**：均来自 `--lead` / `--keyword-search-base`（用户/智能体可控），非 RSS；中危。✅

### M3. ClawHub 分发路径断裂（格式合规相关）
- **问题**：`openclaw-edition/SKILL.md` 通过 `../scripts/...` 引用父目录引擎。若 ClawHub/OpenClaw 仅安装该子目录，相对路径失效，技能无法运行。
- **状态**：**格式本身合规**（frontmatter 含 `metadata.openclaw`）；此为**打包/分发**缺口，非格式错误。
- **建议（未自动改，待你确认）**：发布到 ClawHub 前用 `cp -r scripts openclaw-edition/scripts` 把引擎打进子目录，或将仓库根整体作为 OpenClaw 技能入口。已在 README 注明。

---

## 🟡 低危 / 代码质量（Low）—— 部分已修

- **L1（已修）**：`render.py` 移除未使用的 `leaderboard` 导入（`fetch_all_leaderboards`/`sync_model_profiles`/`DEFAULT_PROFILES`）；早期会话已移除 `get_default_ranking` 导入。
- **L2（已修）**：`.gitignore` 补充 `model_profiles.pending.json` 与 `*.run.log`，避免运行时产物入库。
- **L3（建议）**：`generate_site.py` 106–142 行的 re-export 兼容垫层较大，依赖 `leaderboard.py` 命名空间暴露符号；当前导入测试通过，但脆弱。建议后续改为显式 `import aiweekly.leaderboard as LB` 并调用 `LB.xxx`。
- **L4（建议）**：`[CHART_DATA_PLACEHOLDER]` 注入的是 **JS 代码**（非数据），市场图表 `labels` 来自 CLI 用户可控字符串，未做 `</script>` 转义。属用户自输入、风险低，建议后续对 chart labels 做白名单/转义。
- **L5（建议）**：`accumulate_data.py`（314 行）与 `references/` 未在主流程调用，疑似遗留/可选工具，建议明确标注用途或移出主包。

---

## ✅ 审查中确认安全（疑点已驳回）

| 疑点 | 结论 |
|---|---|
| `run_report.sh` shell 注入 | `exec "$PY" "$@"` 参数经引号传递，无 shell 重解析 → 安全 |
| `fetch_ai_news.py` 请求挂死 | 已有 `socket.setdefaulttimeout(20)` + `requests timeout=15` → 安全 |
| 新闻文本字段（title/summary/source） | JS 端统一经 `escapeHtml` 渲染 → 安全（除 H1 的 JSON blob 突破已修） |
| 模块体量 / 无裸 except / ISO8601 | `validate_report.py` 21/22 守护全过（唯一警告为 C2#7 数据类，与代码无关） |
| `.gitignore` 覆盖构建产物 | `.skill` / `*.log` / `*-health-check*.md` / 运行时数据均已忽略 |

---

## 修复清单（本次已落地）

1. `aiweekly/render.py`：新增 `_json_script_safe` / `_js_str` / `_safe_url`；全部 JSON 占位符改用安全序列化；`[LEAD]`/`[KEYWORD_SEARCH_BASE]`/外部源转义；精简未用导入。
2. `assets/news_site_template.html`：新增 `safeUrl()`；新闻卡与外链 `href` 经 `escapeHtml(safeUrl(...))`。
3. `.gitignore`：补充 `model_profiles.pending.json`、`*.run.log`。

## 后续建议（待你拍板）

- 补 chart labels 转义（L4）。
- ClawHub 发布时把 `scripts/` 打进 `openclaw-edition/`（M3）。
- 清理 `accumulate_data.py` 等遗留文件（L5）。
- 给 `validate_report.py` 增加"XSS 注入回归"用例（把 H1/H2 payload 固化进测试集）。
