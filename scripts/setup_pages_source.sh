#!/usr/bin/env bash
# setup_pages_source.sh — 一次性把 GitHub Pages 源切到 gh-pages 分支（/root）。
#
# 用法（推荐：复用 gh CLI 已登录凭据，无需自建 PAT）：
#   gh auth login                       # 仅首次；凭据由 gh 自己保管，不落项目文件
#   bash scripts/setup_pages_source.sh
#
# 备选（显式传令牌，仅内存、不落盘；请用最小权限 + 短有效期）：
#   把令牌临时放进环境变量 GITHUB_TOKEN / GH_TOKEN（仅当前 shell 内存，不落盘）。
#
# 说明：
#   - 只读 GITHUB_TOKEN / GH_TOKEN 环境变量，不写任何文件、不回显 token。
#   - 仅做「切 Pages 源」这一件事；报告部署由 deploy_ghpages.py 负责。
#   - idempotent：已切对也返回成功，可重复跑。
#   - 若遇 403：多为所用凭据对该仓库缺少修改 Pages 设置的权限。优先改用 gh CLI
#     凭据（见上），或直接手动切源（仓库 Settings → Pages → Source），一次性且零凭据。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
# 环境变量都没有时，复用 gh CLI 已登录凭据（凭据由 gh 保管，本脚本不落盘、不回显）
if [ -z "$TOKEN" ] && command -v gh >/dev/null 2>&1; then
  TOKEN="$(gh auth token 2>/dev/null || true)"
fi
if [ -z "$TOKEN" ]; then
  echo "❌ 未取得可用凭据。" >&2
  echo "   推荐（零自建令牌）：先 gh auth login，再重跑本脚本（会自动复用 gh 凭据）。" >&2
  echo "   兼容做法：export GITHUB_TOKEN=<token>（或 GH_TOKEN）——请用最小权限、短有效期的令牌，且不要落盘。" >&2
  echo "   最省事的替代：直接在仓库 Settings → Pages → Source 手动切到 gh-pages / /root（一次性操作，无需任何凭据）。" >&2
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
  echo "✅ Pages 源切源请求已接受（HTTP $HTTP）。正在回查当前实际源..."
  # 回查确认设置真的生效（GitHub API PUT 成功≠边缘立即生效）
  VERIFY="$(curl -s -m 20 \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "$API")"
  CURRENT_BRANCH="$(printf '%s' "$VERIFY" | grep -o '"branch":"[^"]*"' | head -1 | cut -d'"' -f4)"
  CURRENT_PATH="$(printf '%s' "$VERIFY" | grep -o '"path":"[^"]*"' | head -1 | cut -d'"' -f4)"
  echo "   当前 Pages 源：branch=$CURRENT_BRANCH / path=$CURRENT_PATH"
  if [ "$CURRENT_BRANCH" = "gh-pages" ] && [ "$CURRENT_PATH" = "/" ]; then
    echo "✅ 已确认 Pages 源 = gh-pages / /root。约 1 分钟后链接生效；若仍 404，请硬刷新或稍等 CDN 刷新。"
  else
    echo "⚠️ API 回查显示 Pages 源尚未变成 gh-pages / /root（当前：$CURRENT_BRANCH / $CURRENT_PATH）。" >&2
    echo "   请等待 1-2 分钟后重跑本脚本，或到仓库 Settings → Pages 手动确认。" >&2
    exit 1
  fi
  echo "   验证：https://${OWNER}.github.io/${NAME}/AI_News_2026-08-17.html"
else
  echo "❌ 切源失败（HTTP $HTTP）：" >&2
  cat /tmp/_pages_resp.json >&2
  echo "" >&2
  # 常见原因：所用凭据对该仓库缺少修改 Pages 设置的权限（403 Resource not accessible）
  if [ "$HTTP" = "403" ]; then
    echo "💡 若报错含 'Resource not accessible by personal access token'（403）：" >&2
    echo "   说明当前凭据对该仓库不具备修改 Pages 设置的权限。两个方向——" >&2
    echo "   ① 最省事：不走 API，直接在仓库 Settings → Pages → Source 手动选 'Deploy from a branch → gh-pages / /root'（一次性，零凭据）。" >&2
    echo "   ② 仍要自动化：用 gh CLI 凭据（gh auth login 后重跑本脚本），并确认该账号对该仓库有 Pages 管理权限。" >&2
  fi
  if [ "$HTTP" = "404" ]; then
    echo "💡 若报错含 'Not Found'（404）：仓库尚未启用 GitHub Pages。" >&2
    echo "   请先到仓库 Settings → Pages 手动启用一次（选任意分支均可），再重跑本脚本切到 gh-pages。" >&2
  fi
  exit 1
fi
