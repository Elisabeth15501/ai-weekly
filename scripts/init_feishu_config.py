#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书配置向导（P1-3）：交互式生成飞书推送所需的配置文件，免去手动建文件。

两种推送路径对应两个文件：
  - Webhook 自定义机器人  -> delivery/feishu_config.json  {"webhook": "..."}
  - 飞书连接器直推（密钥不落盘）-> delivery/feishu_target.json  {"chat_id": "oc_xxx"} 或 {"user_id": "ou_xxx"}

两个文件均被 .gitignore 忽略，不入库。

支持两种用法：
  1) 交互式（默认）：   python scripts/init_feishu_config.py
  2) 一键（CI / 脚本）： python scripts/init_feishu_config.py --method webhook --webhook "https://open.feishu.cn/.../hook/TOKEN"
                      python scripts/init_feishu_config.py --method connector --chat-id oc_xxxx
                      python scripts/init_feishu_config.py --method connector --user-id ou_xxxx --as user

校验：仅做 JSON 合法 + URL / ID 格式基础检查，不实际发请求（连通性在推送时用 --dry-run 验证）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DELIVERY = REPO_ROOT / "delivery"
CONFIG_JSON = DELIVERY / "feishu_config.json"
TARGET_JSON = DELIVERY / "feishu_target.json"

WEBHOOK_PREFIX = "https://open.feishu.cn/open-apis/bot/v2/hook/"


def _ask(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
    except EOFError:
        val = ""
    return val or default


def _confirm(prompt: str) -> bool:
    ans = _ask(prompt + " [y/N] ", "n").lower()
    return ans in ("y", "yes")


def validate_webhook(url: str) -> tuple[bool, str]:
    if not url:
        return False, "Webhook 不能为空"
    if not url.startswith(WEBHOOK_PREFIX):
        return False, f"Webhook 应以 {WEBHOOK_PREFIX} 开头（你在飞书群→智能群助手→自定义机器人里复制的完整 URL）"
    if "REPLACE_WITH_YOUR_TOKEN" in url or "XXXX" in url:
        return False, "Webhook 里还含占位符，请填入真实 token"
    return True, ""


def validate_target_id(flag: str, vid: str) -> tuple[bool, str]:
    if not vid:
        return False, f"{flag} 不能为空"
    if flag == "--chat-id" and not vid.startswith("oc_"):
        return False, "chat_id 应以 oc_ 开头（飞书群设置→群机器人/群信息里获取）"
    if flag == "--user-id" and not vid.startswith("ou_"):
        return False, "user_id 应以 ou_ 开头（飞书用户 open_id）"
    return True, ""


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)  # 原子替换，避免写到一半被读


def do_webhook(webhook: str) -> int:
    ok, msg = validate_webhook(webhook)
    if not ok:
        print(f"❌ {msg}")
        return 1
    write_json(CONFIG_JSON, {"webhook": webhook})
    print(f"✅ 已写入 {CONFIG_JSON}")
    print("\n下一步（Webhook 推送）：")
    print('  bash run_report.sh scripts/publish.py \\')
    print('    --news-json news.json --insights-json insights.json \\')
    print('    --audience-json audience_summary.json \\')
    print(f'    --view-url "https://你的托管地址/AI_News_YYYY-MM-DD.html" --output report.json')
    print("\n  仅预览卡片不推送：在末尾加 --dry-run")
    return 0


def do_connector(chat_id: str, user_id: str, identity: str) -> int:
    if chat_id and user_id:
        print("❌ 只能填其一：--chat-id（群）或 --user-id（私聊），不要同时给")
        return 1
    if chat_id:
        flag, vid = "--chat-id", chat_id
    elif user_id:
        flag, vid = "--user-id", user_id
    else:
        print("❌ 连接器模式需填 --chat-id 或 --user-id")
        return 1
    ok, msg = validate_target_id(flag, vid)
    if not ok:
        print(f"❌ {msg}")
        return 1
    write_json(TARGET_JSON, {flag.lstrip("-").replace("-", "_"): vid})
    print(f"✅ 已写入 {TARGET_JSON}（{flag} = {vid}）")
    print("\n下一步（连接器直推，密钥不落盘）：")
    print(f"  python delivery/feishu_connector.py --report report.json {flag} {vid} --as {identity}")
    print(f"  python delivery/feishu_connector.py --report report.json {flag} {vid} --dry-run   # 仅预览不发送")
    return 0


def interactive() -> int:
    print("=== 飞书配置向导 ===")
    print("选推送方式：")
    print("  1) Webhook 自定义机器人（一个 URL 搞定，最省事）")
    print("  2) 飞书连接器直推（密钥不落盘，推荐 WorkBuddy 用户）")
    choice = _ask("输入 1 或 2：", "1")
    if choice == "1":
        webhook = _ask(f"粘贴飞书 Webhook URL（以 {WEBHOOK_PREFIX} 开头）：\n> ")
        return do_webhook(webhook)
    elif choice == "2":
        print("目标类型：")
        print("  a) 群（chat_id，机器人需已入群）")
        print("  b) 私聊（user_id，以你本人身份发，首次测试最省事）")
        t = _ask("输入 a 或 b：", "a")
        if t == "b":
            vid = _ask("粘贴你的 user_id（ou_ 开头）：\n> ")
            return do_connector("", vid, "user")
        else:
            vid = _ask("粘贴群 chat_id（oc_ 开头）：\n> ")
            return do_connector(vid, "", "bot")
    else:
        print("❌ 无效选择")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="飞书配置向导（P1-3）：交互式生成 feishu_config.json / feishu_target.json")
    ap.add_argument("--method", choices=["webhook", "connector"], help="非交互模式：指定推送方式")
    ap.add_argument("--webhook", help="Webhook 模式：完整 webhook URL")
    ap.add_argument("--chat-id", help="连接器模式：目标群 chat_id（oc_xxx）")
    ap.add_argument("--user-id", help="连接器模式：目标用户 open_id（ou_xxx），用于私聊")
    ap.add_argument("--as", dest="identity", default="bot", choices=["bot", "user"], help="连接器发送身份（默认 bot）")
    args = ap.parse_args()

    # 非交互模式
    if args.method == "webhook":
        if not args.webhook:
            print("❌ --method webhook 需配合 --webhook")
            return 1
        return do_webhook(args.webhook)
    if args.method == "connector":
        return do_connector(args.chat_id or "", args.user_id or "", args.identity)

    # 交互模式
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
