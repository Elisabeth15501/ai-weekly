#!/usr/bin/env python3
"""把 AI 周报头条卡片推送到飞书 —— 走 WorkBuddy 飞书连接器（lark-cli），不落 webhook token。

设计原则（沿用 skill 合规约束）：
- 复用 ``delivery/feishu_bot.build_headline_card`` 构造消息卡片（Card 1.0，飞书仍支持），
  通过 ``lark-cli im +messages-send`` 发送，密钥由连接器托管，绝不写进任何配置文件。
- 仅依赖标准库 + 已连接的飞书连接器（lark-cli）。

目标会话解析（优先级从高到低，命中即停）：
  1. CLI 参数 ``--chat-id`` / ``--user-id``
  2. 环境变量 ``FEISHU_CHAT_ID`` / ``FEISHU_USER_ID``
  3. ``delivery/feishu_target.json``：``{"chat_id": "oc_xxx"}`` 或 ``{"user_id": "ou_xxx"}``

发送身份：``--as bot``（默认，应用机器人）或 ``--as user``（以你本人身份）。
  注意：bot 身份发送前，需先把「WorkBuddy-Feishu CLI」这个应用机器人拉进目标群；
  user 身份发送则不需要，但需你本人对该会话有发消息权限。

用法：
  # 预览请求（不发）
  python feishu_connector.py --report report.json --chat-id oc_xxx --dry-run

  # 真实发送（bot 身份 → 群）
  python feishu_connector.py --report report.json --chat-id oc_xxx

  # 发给自己（user 身份 → 私聊），适合首次冒烟测试
  python feishu_connector.py --report report.json --user-id ou_xxx --as user

  # 也可把目标写进 delivery/feishu_target.json，省去每次传参
  python feishu_connector.py --report report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger("aiweekly.delivery.feishu_connector")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from feishu_bot import build_headline_card  # noqa: E402

_TARGET_JSON = os.path.join(_HERE, "feishu_target.json")

# R6：lark-cli v1.0.92 的 +messages-send 仅接受内联 --content（不支持 @file / stdin），
# 而 Windows CreateProcess 命令行上限约 8191 字符。卡片通常 2–4KB，远低于此；
# 但满配卡片逼近上限时会 spawn 失败且无提示。这里在临近阈值时显式告警，
# 把「静默 spawn 失败」转为可见信号。彻底修复需 lark-cli 支持 --content @file（上游能力）。
_MAX_CONTENT_CHARS = 6000


def load_report(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_card(report: dict) -> dict:
    """从 feishu_bot 的 {msg_type, card} 信封里取出内层 card（lark-cli --content 需要卡片本体）。"""
    built = build_headline_card(report)
    return built.get("card", built)


def resolve_lark() -> tuple[str, str]:
    """定位 lark-cli 的真实启动方式（node + run.js）。

    ``lark-cli`` 在 Windows 上是个无扩展名 shim / ``lark-cli.cmd``，Python 的
    ``subprocess.CreateProcess`` 无法直接启动；而经 ``cmd /c`` 又会被 JSON 里的引号坑。
    最稳的做法是直接拿 ``node`` 调它的 ``run.js`` 入口（与 shim 内部行为一致）。
    """
    cli = shutil.which("lark-cli.cmd") or shutil.which("lark-cli")
    pkg_dir = os.path.dirname(os.path.abspath(cli)) if cli else None
    if not pkg_dir:
        cand = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries",
                            "node", "cli-connector-packages")
        if os.path.isdir(cand):
            pkg_dir = cand
    if not pkg_dir:
        raise RuntimeError("找不到 lark-cli 安装目录，请确认飞书连接器已安装")
    run_js = os.path.join(pkg_dir, "node_modules", "@larksuite", "cli",
                          "scripts", "run.js")
    if not os.path.exists(run_js):
        raise RuntimeError(f"找不到 lark-cli 入口脚本：{run_js}")

    node = shutil.which("node")
    if not node:
        for ver in ("22.22.2", "24.14.1"):
            c = os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries",
                             "node", "versions", ver, "node.exe")
            if os.path.exists(c):
                node = c
                break
    if not node:
        raise RuntimeError("找不到 node 可执行文件，请确认 Node 可用")
    return node, run_js


def resolve_target(args: argparse.Namespace):
    """返回 (flag, value)，如 ('--chat-id', 'oc_xxx') 或 ('--user-id', 'ou_xxx')；解析失败返回 (None, None)。"""
    if args.chat_id:
        return "--chat-id", args.chat_id
    if args.user_id:
        return "--user-id", args.user_id
    if os.environ.get("FEISHU_CHAT_ID"):
        return "--chat-id", os.environ["FEISHU_CHAT_ID"]
    if os.environ.get("FEISHU_USER_ID"):
        return "--user-id", os.environ["FEISHU_USER_ID"]
    if os.path.exists(_TARGET_JSON):
        try:
            with open(_TARGET_JSON, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("chat_id"):
                return "--chat-id", d["chat_id"]
            if d.get("user_id"):
                return "--user-id", d["user_id"]
        except (ValueError, OSError) as e:
            logger.warning("读取 %s 失败：%s", _TARGET_JSON, e)
    return None, None


def send_card(card: dict, target_flag: str, target_value: str,
              identity: str = "bot", dry_run: bool = False) -> subprocess.CompletedProcess:
    """调用 lark-cli 发送 interactive 卡片。返回 CompletedProcess 供调用方判断 ok。

    注：lark-cli 的 --content 仅接受内联 JSON（不支持 @file / stdin），故卡片整体
    走命令行参数。接近 Windows 8191 字符上限时显式告警（见 _MAX_CONTENT_CHARS）。
    """
    card_json = json.dumps(card, ensure_ascii=False)
    if len(card_json) > _MAX_CONTENT_CHARS:
        logger.warning("卡片 JSON 已达 %d 字符（阈值 %d），逼近 Windows 命令行 8191 上限，"
                       "发送可能静默失败；建议削减摘要长度或等 lark-cli 支持 --content @file。",
                       len(card_json), _MAX_CONTENT_CHARS)
    node, run_js = resolve_lark()
    cmd = [
        node, run_js, "im", "+messages-send",
        target_flag, target_value,
        "--msg-type", "interactive",
        "--content", card_json,
    ]
    if identity:
        cmd += ["--as", identity]
    if dry_run:
        cmd += ["--dry-run"]
    logger.info("执行：node lark-cli im +messages-send %s %s --msg-type interactive --content '<card %d chars>'%s",
                target_flag, target_value, len(card_json), " --dry-run" if dry_run else "")
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="通过飞书连接器推送 AI 周报头条卡片")
    ap.add_argument("--report", required=True, help="report.json 路径（publish.py 产物或样例）")
    ap.add_argument("--chat-id", help="目标群 chat_id（oc_xxx）")
    ap.add_argument("--user-id", help="目标用户 open_id（ou_xxx），用于私聊")
    ap.add_argument("--as", dest="identity", default="bot", choices=["bot", "user"])
    ap.add_argument("--dry-run", action="store_true", help="只打印请求，不实际发送")
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print(f"ERROR: 找不到 report 文件：{args.report}", file=sys.stderr)
        return 2

    report = load_report(args.report)
    card = extract_card(report)

    flag, val = resolve_target(args)
    if not flag:
        print("ERROR: 未指定推送目标。请传 --chat-id/--user-id，或设置环境变量 "
              "FEISHU_CHAT_ID/FEISHU_USER_ID，或在 delivery/feishu_target.json 写入目标。",
              file=sys.stderr)
        return 2

    res = send_card(card, flag, val, args.identity, args.dry_run)
    sys.stdout.write(res.stdout)
    if res.stderr:
        sys.stderr.write(res.stderr)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
