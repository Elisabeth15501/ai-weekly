#!/usr/bin/env bash
# setup_pages_source.sh — 一次性把 GitHub Pages 源切到 gh-pages 分支（/root）。
#
# 用法（需先 export token，不落盘）：
#   export GITHUB_TOKEN=github_pat_xxx   # Fine-grained PAT，需 ai-weekly 仓库 Pages:write
#   bash scripts/setup_pages_source.sh
#
# 说明：
#   - 只读 GITHUB_TOKEN / GH_TOKEN 环境变量，不写任何文件、不回显 token。
#   - 仅做「切 Pages 源」这一件事；报告部署由 deploy_ghpages.py 负责。
#   - idempotent：已切对也返回成功，可重复跑。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "❌ 未设置 GITHUB_TOKEN（或 GH_TOKEN）。" >&2
  echo "   PowerShell 请先：\$env:GITHUB_TOKEN=\"github_pat_xxx\"" >&2
  echo "   Git Bash 请先：export GITHUB_TOKEN=github_pat_xxx" >&2
  echo "   需为 ai-weekly 仓库的 Fine-grained PAT（Pages: write）。" >&2
  exit 1
fi

# 解析 owner/repo（兼容 Git bash 的老版 ERE：不用非贪婪/?、不用\. 转义）
REMOTE="$(git remote get-url origin)"
# 先去掉可能的 .git 后缀与协议前缀，再按 / 切分
CLEAN="${REMOTE%.git}"
CLEAN="${CLEAN##*github.com[/:]}"
OWNER="${CLEAN%%/*}"
NAME="${CLEAN##*/}"
if [ -z "$OWNER" ] || [ -z "$NAME" ]; then
  echo "❌ 无法从 remote 解析 owner/repo：$REMOTE" >&2
  exit 1
fi

API="https://api.github.com/repos/${OWNER}/${NAME}/pages"
echo "🔧 目标：${OWNER}/${NAME} → Pages 源切到 gh-pages / /root"

# 先探测现状
STATUS="$(curl -s -m 20 -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "$API")"

if [ "$STATUS" = "404" ]; then
  echo "⚠️ 该仓库尚未启用 GitHub Pages（API 返回 404）。请先到 Settings → Pages 手动启用一次，" >&2
  echo "   或确认仓库不是私有权限限制。启用后重试本脚本即可。" >&2
  exit 1
fi

# PUT 切源
HTTP="$(curl -s -m 20 -o /tmp/_pages_resp.json -w '%{http_code}' -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d '{"source":{"branch":"gh-pages","path":"/"},"build_type":"legacy"}' \
  "$API")"

if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ] || [ "$HTTP" = "204" ]; then
  echo "✅ Pages 源已切到 gh-pages / /root（HTTP $HTTP）。约 1 分钟后链接生效。"
  echo "   验证：https://${OWNER}.github.io/${NAME}/AI_News_2026-08-17.html"
else
  echo "❌ 切源失败（HTTP $HTTP）：" >&2
  cat /tmp/_pages_resp.json >&2
  echo "" >&2
  # 常见原因：Fine-grained PAT 调 Pages 更新端点常被拒（403 Resource not accessible）
  if [ "$HTTP" = "403" ]; then
    echo "💡 若报错含 'Resource not accessible by personal access token'（403）：" >&2
    echo "   GitHub 的 Pages 更新 API 对 Fine-grained PAT 经常不支持，即使已勾 Pages: Read and write。" >&2
    echo "   解法：改用 Classic PAT ——" >&2
    echo "     GitHub → Settings → Developer settings → PAT → Tokens (classic) → Generate new token (classic)" >&2
    echo "     勾选范围：repo（全选）+ pages:write，生成后重新：$env:GITHUB_TOKEN=\"新token\" 重跑本脚本。" >&2
  fi
  if [ "$HTTP" = "404" ]; then
    echo "💡 若报错含 'Not Found'（404）：仓库尚未启用 GitHub Pages。" >&2
    echo "   请先到仓库 Settings → Pages 手动启用一次（选任意分支均可），再重跑本脚本切到 gh-pages。" >&2
  fi
  exit 1
fi
