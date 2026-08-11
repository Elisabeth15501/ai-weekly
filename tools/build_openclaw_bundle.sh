#!/usr/bin/env bash
# build_openclaw_bundle.sh — 把 ai-weekly 核心引擎同步进 openclaw-edition/，
# 生成完全自包含、可独立发布到 ClawHub 的 OpenClaw 技能包。
#
# 运行：
#   bash tools/build_openclaw_bundle.sh
#
# 该脚本只做"复制 + 路径改写"，不修改仓库根的任何源码；
# 同步进 openclaw-edition/ 的文件均已被 .gitignore 排除，不会污染主仓库提交。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/openclaw-edition"

echo "🔧 正在构建独立 OpenClaw 技能包: $DEST"

# 1) Python 引擎：内部包 + 顶层脚本
mkdir -p "$DEST/scripts"
rm -rf "$DEST/scripts"/*
mkdir -p "$DEST/scripts/aiweekly"
cp -r "$ROOT/scripts/aiweekly/." "$DEST/scripts/aiweekly/"
cp "$ROOT"/scripts/*.py "$DEST/scripts/"
# 清理字节码缓存（不进入发布包；优先用 Python 以避开 Windows find 的环境限制）
python3 - <<PY 2>/dev/null || true
import os, shutil
for root, dirs, _ in os.walk(r"$DEST/scripts"):
    for d in dirs:
        if d == "__pycache__":
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
PY

# 2) 模板资源
mkdir -p "$DEST/assets"
cp -r "$ROOT/assets/." "$DEST/assets/"

# 3) 根级运行文件与数据（独立运行所需）
cp "$ROOT/requirements.txt" "$ROOT/run_report.sh" \
   "$ROOT/model_profiles.json" "$ROOT/models_cost.json" "$DEST/"

# 4) 生成本地自包含 SKILL.md（../scripts → ./scripts 等，对已是 ./ 的内容为幂等）
sed -e 's#\.\./scripts/\.\./requirements\.txt#./requirements.txt#g' \
    -e 's#\.\./scripts#./scripts#g' \
    -e 's#\.\./run_report\.sh#./run_report.sh#g' \
    -e 's#\.\./insights\.json#./insights.json#g' \
    -e 's#\.\./requirements\.txt#./requirements.txt#g' \
    "$ROOT/openclaw-edition/SKILL.md" > "$DEST/SKILL.md"

echo "✅ 完成。openclaw-edition/ 现在可独立发布到 ClawHub（无需父目录）。"
echo "   提示：这些同步文件已被 .gitignore 排除，不会进入主仓库提交。"
echo "   验证：bash $DEST/run_report.sh $DEST/scripts/generate_site.py --health-check"
