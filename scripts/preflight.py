#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py — 流水线启动前的飞书凭据预检（SEC-12）。

背景：2026-10-05 那次周报，飞书推送在流水线第 6 步失败（rc=3）却被上游脚本吞掉，
产物照常生成、校验 25/25 通过、.run.log 写着 errors: 0，用户直到手动追问才发现
没收到消息。根因有两层：脚本不判退出码（已单独修复）+ 凭据问题直到第 6 步才暴露。
本脚本解决第二层：把「凭据是否可用」从流水线第 6 步提前到第 0 步暴露。

做什么：
  调``lark-cli doctor``，解析其 JSON 输出，抽取三项决定推送成败的检查：
    * ``identity_ready`` —— 至少有一种身份可用（fail 则完全推不了）
    * ``bot_identity``   —— bot 身份就绪；warn/fail 时机器人发消息会报20140
    * ``app_resolved``   —— app_id/app_secret 能解析出（fail 则凭据无效）

为什么必须显式回退路径：
  ``lark-cli`` 由宿主连接器安装在 ``~/.workbuddy/binaries/node/cli-connector-packages/``，
  该目录实测**不在用户 PATH 里**，PowerShell 下直接敲 ``lark-cli`` 会
  ``command not recognized``。所以先 ``shutil.which`` 探测，探测不到就回退到
  硬编码的安装位置——这是本次修复的核心回归点，有对应的单测守着。

退出码语义：
  0  预检通过（identity_ready 与 bot_identity 均非 fail/warn）
  1  预检不通过（凭据不可用，stderr 给出可操作修复步骤）
  2  用法错误（argparse 自身）

用法：
  python scripts/preflight.py# 人类可读输出
  python scripts/preflight.py --json     # 机器可读结果，供 automation 消费
  python scripts/preflight.py --quiet    # 只在失败时输出（成功静默，退出码 0）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 复用项目既有的人话错误体系（aiweekly.errors），不另写一套错误码/打印逻辑
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiweekly.errors import UserFacingError, print_error  # noqa: E402

# 宿主连接器安装目录（lark-cli 不在 PATH 时回退到这里）
_CLI_DIR = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"

# 飞书「以机器人身份发消息」失败时的错误码，用于把技术故障翻译成人话
_FEISHU_BOT_CODE = 20140

# doctor 输出里我们关心的三项检查 -> 该项不通时的人话含义
_CHECK_LABELS = {
    "identity_ready": "飞书身份未就绪",
    "bot_identity": "飞书 bot 身份未就绪",
    "app_resolved": "飞书应用凭据无法解析",
}

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


class PreflightError(UserFacingError):
    """预检失败。用项目统一的 ERR-* 码 + 解决步骤，CLI 侧走 print_error 输出。"""


def resolve_lark_cli() -> str | None:
    """定位 ``lark-cli`` 可执行文件，返回命令字符串；找不到返回 ``None``。

    先 ``shutil.which`` 走 PATH，再回退到宿主连接器安装目录。
    Windows 下必须用 ``.cmd`` 后缀——目录里那个无后缀的 ``lark-cli`` 是给
    sh/Git Bash 用的脚本，Windows 上直接执行会失败。
    """
    found = shutil.which("lark-cli")
    if found:
        return found

    if os.name == "nt":
        candidate = _CLI_DIR / "lark-cli.cmd"
    else:
        candidate = _CLI_DIR / "lark-cli"
    if candidate.is_file():
        return str(candidate)
    return None


def run_doctor(cli_cmd: str) -> tuple[dict, str]:
    """执行 ``lark-cli doctor``，返回 ``(解析后的 JSON, 原始 stdout)``。

    Windows 的 ``.cmd`` 批处理会把 Node 的警告打到 stderr（噪音），
    故只取 stdout 解析，stderr 仅在 JSON 解析失败时作为诊断信息回传。
    """
    proc = subprocess.run(
        [cli_cmd, "doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    raw = (proc.stdout or "").strip()
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as e:
        detail = (proc.stderr or "").strip() or raw or "(无输出)"
        raise PreflightError(
            "ERR-FS-CLI-002",
            "lark-cli doctor 输出无法解析为 JSON",
            ["确认 lark-cli 版本：lark-cli --version",
             "手动跑一次看原始输出：lark-cli doctor",
             f"若输出被环境变量污染，可清空 LARK_* 相关变量后重试"],
            verbose=f"JSONDecodeError: {e} / stdout+stderr={detail[:400]}",
        )


def collect_checks(doctor: dict) -> dict:
    """把 doctor 的 ``checks`` 数组转成 ``{name: {status, message, hint}}``。"""
    out = {}
    for item in doctor.get("checks") or []:
        name = item.get("name")
        if name:
            out[name] = item
    return out


def evaluate(checks: dict) -> list[str]:
    """按检查项返回问题列表；空列表表示通过。

    判定规则：
      * ``identity_ready`` 为 fail —— 没有任何可用身份，推送必失败
      * ``bot_identity``为 warn/fail —— bot 凭据不可用，发消息会报 20140
      * ``app_resolved`` 为 fail —— app_id/app_secret 解析不出来
    """
    problems: list[str] = []

    identity = checks.get("identity_ready") or {}
    if identity.get("status") == "fail":
        problems.append(
            f"{_CHECK_LABELS['identity_ready']}："
            f"{identity.get('message', 'no identity available')}"
        )

    bot = checks.get("bot_identity") or {}
    if bot.get("status") in ("warn", "fail"):
        problems.append(
            f"{_CHECK_LABELS['bot_identity']}："
            f"{bot.get('message', 'bot identity not ready')}。"
            f"bot 凭据不可用，消息推送会失败（错误码 {_FEISHU_BOT_CODE}）"
        )

    app = checks.get("app_resolved") or {}
    if app.get("status") == "fail":
        problems.append(
            f"{_CHECK_LABELS['app_resolved']}："
            f"{app.get('message', 'app not resolved')}"
        )

    return problems


def build_exit(problems: list[str]) -> int:
    """把问题列表转成退出码，并打印人话提示。空列表 -> 0。"""
    if not problems:
        return EXIT_OK

    steps = ["按顺序修复以下问题后重跑本脚本："]
    steps += [f"  {i + 1}. {p}" for i, p in enumerate(problems)]
    steps += [
        "",
        "常见修法：",
        "  * 登录 / 重新登录：lark-cli auth login",
        "  * 检查 app_id 与 app_secret 是否在 lark-cli 配置中且未过期",
        "  * 确认机器人的消息发送权限（im:message:send_as_bot）已开通",
    ]
    print_error(PreflightError(
        "ERR-FS-PREFLIGHT-001",
        f"飞书凭据预检未通过（{len(problems)} 项）",
        steps,
        verbose="; ".join(problems),
    ))
    return EXIT_FAIL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="流水线启动前的飞书凭据预检（避免跑完 6 步才在推送步失败）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 结果")
    parser.add_argument("--quiet", action="store_true", help="只在失败时输出")
    args = parser.parse_args(argv)

    cli_cmd = resolve_lark_cli()
    if not cli_cmd:
        err = PreflightError(
            "ERR-FS-CLI-001",
            "找不到 lark-cli",
            [f"确认宿主连接器已安装：ls {_CLI_DIR}",
             "或在 PATH 中提供 lark-cli"],
            verbose="shutil.which('lark-cli') -> None，且回退路径不存在",
        )
        if args.json:
            print(json.dumps({"ok": False, "problems": ["找不到 lark-cli"]},
                             ensure_ascii=False, indent=2))
        if not args.quiet:
            print_error(err)
        return EXIT_FAIL

    try:
        doctor, _raw = run_doctor(cli_cmd)
    except PreflightError as e:
        if args.json:
            print(json.dumps({"ok": False, "problems": [e.title]},
                             ensure_ascii=False, indent=2))
        if not args.quiet:
            print_error(e)
        return EXIT_FAIL

    checks = collect_checks(doctor)
    problems = evaluate(checks)
    rc = build_exit(problems) if problems else EXIT_OK

    if args.json:
        print(json.dumps({
            "ok": not problems,
            "exit_code": rc,
            "cli": cli_cmd,
            "identity_ready": (checks.get("identity_ready") or {}).get("status"),
            "bot_identity": (checks.get("bot_identity") or {}).get("status"),
            "app_resolved": (checks.get("app_resolved") or {}).get("status"),
            "problems": problems,
        }, ensure_ascii=False, indent=2))
    elif not args.quiet and not problems:
        print("✅ 飞书凭据预检通过：identity_ready=pass / bot_identity=pass"
              "（推送可用）")

    return rc


if __name__ == "__main__":
    sys.exit(main())