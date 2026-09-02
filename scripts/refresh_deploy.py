#!/usr/bin/env python3
"""refresh_deploy.py — 一键「实时刷新排行榜 + 重新部署」编排器（ai-weekly 实时化核心）。

背景：
  原先周报生成时排行榜走 --ranking-json 静态快照，部署后便不再变化。
  实测本环境（2026-09 起）已可直连 LMArena / Artificial Analysis / LLM-Stats /
  HuggingFace / OpenCompass / SuperCLUE / ModelScope，四榜均可实时抓取
  （fetch_all_leaderboards 默认即 live fetch，无需 --ranking-json）。
  因此「排行榜实时更新」= 周期性用 live fetch 重新生成并部署即可。

本脚本把三步合为一：
  1) generate_site.py  —— 实时抓取四榜（默认 live，不传 --ranking-json）+ 复用固定周次新闻
  2) deploy_ghpages.py --no-push —— 把新 HTML 提交到本地 gh-pages worktree
  3) git push origin gh-pages —— 用 Windows 凭据管理器取 PAT 推送（沙箱无交互凭据时的标准解法）

用法：
  # 手动刷新（默认推 gh-pages）
  python refresh_deploy.py --api-json ../workspace/news.json \
      --output ../workspace/AI_News_2026-08-31.html

  # 仅本地生成+提交、不推送（离线/调试）
  python refresh_deploy.py --api-json news.json --output out.html --no-push

设计要点：
  * 新闻用固定 --api-json（周次不变），只有排行榜随每次 live fetch 刷新 ——
    既保证「实时榜」，又不打乱周刊的新闻内容。
  * 推送复用 git-credential-wincred 取回的 PAT（仅命令内存，不写 config、不落盘）。
  * 推送失败显式非零退出：本地 gh-pages 已提交，但返回非零码并告警，避免自动化误判「实时榜已部署」；多策略回退（$GITHUB_TOKEN / Windows 凭据），凭据经 GIT_CONFIG_* 环境变量注入、不进 argv。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENV_PY = (SKILL_DIR / ".." / ".." / "binaries" / "python" / "envs" / "aiweekly" /
           "Scripts" / "python.exe")
# 回退：若 venv 不存在则用当前解释器
if not VENV_PY.exists():
    VENV_PY = Path(sys.executable)


def _run(cmd: list[str], **kw) -> int:
    print("▶", " ".join(cmd), flush=True)
    return subprocess.call(cmd, **kw)


def _git_push_with_creds(creds: str) -> bool:
    """用 insteadOf + GIT_CONFIG_* 注入凭据推送（凭据在环境变量，不进 argv）。"""
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "url.https://github.com/.insteadOf"
    env["GIT_CONFIG_VALUE_0"] = f"https://{creds}@github.com/"
    rc = subprocess.call(
        ["git", "push", "origin", "gh-pages"],
        env=env, cwd=SKILL_DIR,
    )
    return rc == 0


def git_push_ghpages() -> bool:
    """推送 gh-pages 到远端。多策略回退，凭据不进 argv（用 GIT_CONFIG_* 环境变量）。

    策略1：$GITHUB_TOKEN / $GH_TOKEN（CI/托管环境）
    策略2：本机 Windows 凭据管理器（git-credential-wincred）
    任一成功即返回 True。
    """
    # 策略1：CI/托管环境常用 GITHUB_TOKEN（细粒度或 classic PAT）
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        print("  ▶ 用 $GITHUB_TOKEN 推送 gh-pages", flush=True)
        if _git_push_with_creds(f"x-access-token:{token}"):
            return True
        print("  ⚠️ $GITHUB_TOKEN 推送失败，尝试 Windows 凭据管理器", flush=True)

    # 策略2：本机 Windows 凭据管理器
    try:
        cred = subprocess.run(
            ["git-credential-wincred", "get"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True,
        ).stdout
        user = ""
        t = ""
        for line in cred.splitlines():
            if line.startswith("username="):
                user = line[len("username="):].strip()
            elif line.startswith("password="):
                t = line[len("password="):].strip()
        if t:
            print("  ▶ 用 Windows 凭据管理器推送 gh-pages", flush=True)
            if _git_push_with_creds(f"{user}:{t}"):
                return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 读取 Windows 凭据失败：{exc}", flush=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="实时刷新排行榜并重部署到 gh-pages")
    ap.add_argument("--api-json", required=True, help="固定周次新闻 JSON（--api-json）")
    ap.add_argument("--output", required=True, help="生成的 HTML 输出路径")
    ap.add_argument("--no-push", action="store_true",
                    help="仅本地生成+提交 gh-pages，不推送")
    ap.add_argument("--region", default="auto",
                    help="排行榜抓取区域（auto/cn/global），默认 auto")
    ap.add_argument("--ranking-top", type=int, default=15,
                    help="每榜取前 N 条，默认 15")
    args = ap.parse_args()

    gen = SKILL_DIR / "scripts" / "generate_site.py"
    deploy = SKILL_DIR / "scripts" / "deploy_ghpages.py"

    # 1) 实时生成（默认 live fetch，不传 --ranking-json / --no-live-ranking）
    rc = _run([
        str(VENV_PY), str(gen),
        "--api-json", args.api_json,
        "--output", args.output,
        "--region", args.region,
        "--ranking-top", str(args.ranking_top),
    ])
    if rc != 0:
        print("  ❌ generate_site.py 失败，中止。", flush=True)
        return rc

    # 2) 本地提交到 gh-pages
    rc = _run([
        str(VENV_PY), str(deploy),
        "--no-push",
        "--html", args.output,
    ])
    if rc != 0:
        print("  ❌ deploy_ghpages.py 失败，中止。", flush=True)
        return rc

    # 3) 推送
    if args.no_push:
        print("  ⏭️ --no-push：跳过推送。待网络恢复后手动："
              "git push origin gh-pages", flush=True)
        return 0

    if git_push_ghpages():
        print("  ✅ 已推送 gh-pages（排行榜已实时更新）。", flush=True)
        return 0

    # R4：推送失败必须显式非零退出，避免调度/自动化误以为「实时榜已部署」
    print("  ❌❌ 自动推送失败：本地 gh-pages 已提交，但未能推到远端！", flush=True)
    print(f"     请手动执行： cd {SKILL_DIR} && git push origin gh-pages", flush=True)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
