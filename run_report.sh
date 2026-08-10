#!/usr/bin/env bash
# run_report.sh — ai-weekly 统一启动器
#
# 自动探测「已安装依赖(feedparser/requests/beautifulsoup4)」的 Python:
#   1) 优先复用已存在的 aiweekly 受管 venv
#   2) 否则回退到当前 python / 受管基础 python
# 找不到可用 Python 时,给出明确的 venv 创建 + 安装命令后退出。
#
# 用法(把原本的 `python scripts/xxx.py ...` 换成):
#   bash run_report.sh scripts/fetch_ai_news.py --output news.json
#   bash run_report.sh scripts/generate_site.py --api-json news.json -o AI_News.html
#   bash run_report.sh scripts/validate_report.py --html AI_News.html
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 候选 Python(按优先级);~ 稍后展开
CANDIDATES=(
  "python"
  "python3"
  "$HOME/.workbuddy/binaries/python/envs/aiweekly/Scripts/python.exe"
  "$HOME/.workbuddy/binaries/python/envs/aiweekly/bin/python"
  "$HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe"
)

PY=""
for cand in "${CANDIDATES[@]}"; do
  cand="${cand/#\~/$HOME}"
  [ -z "$cand" ] && continue
  if command -v "$cand" >/dev/null 2>&1 || [ -f "$cand" ]; then
    if "$cand" -c "import feedparser, requests, bs4" >/dev/null 2>&1; then
      PY="$cand"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  echo "❌ 未找到已安装依赖(feedparser/requests/beautifulsoup4)的 Python。"
  echo "请先创建 venv 并安装依赖："
  echo "  $HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe -m venv $HOME/.workbuddy/binaries/python/envs/aiweekly"
  echo "  $HOME/.workbuddy/binaries/python/envs/aiweekly/Scripts/python.exe -m pip install -r $SCRIPT_DIR/requirements.txt"
  exit 1
fi

echo "🐍 使用 Python: $PY"
exec "$PY" "$@"
