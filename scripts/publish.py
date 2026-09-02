#!/usr/bin/env python3
"""publish.py — 组装本周头条 report.json 并推送至 IM（P0：飞书群机器人）。

数据来源（均为 generate_site.py 已产出的结构化产物，不重新跑生成器）：
  --news-json       news.json        {count, items[{title,url,summary,source,category,score}]}
  --insights-json   insights.json    {lead, insights[{kicker,title,insight}], keywords[], audience_summary?}
  --audience-json   audience_summary.json  {角色: 摘要}   (可选，缺省回退 insights.audience_summary)

产出：
  --output report.json   本周头条结构化载荷（headlines/insights/audience/keywords/view_url）
  --dry-run              仅构造卡片并打印，不发起网络请求

Webhook 解析（优先级，首个非空生效）：
  1. --webhook CLI 参数
  2. 环境变量 FEISHU_WEBHOOK
  3. delivery/feishu_config.json {"webhook": "..."}
  三者皆空 -> 仅警告、exit 0（不阻断上游生成管线，符合"推送失败不丢报告"原则）。

度量：view_url 自动追加 ?src=feishu&uid=<uid>，uid 默认 auto 生成短 uuid。

合规：仅用 requests 调飞书官方 webhook，不引入任何第三方商业 API / SDK。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 让 repo 根（含 delivery/ 包）可导入
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from delivery.feishu_bot import build_headline_card, push  # noqa: E402

# 关键词保送集（与 aiweekly.insights._PRIORITY_ALIASES 对齐，确保民间绰号等
# 高感知词在飞书卡片 6 槽截断时不被吃掉）。导入失败则回退本地最小集。
try:
    from aiweekly.insights import _PRIORITY_ALIASES as _PRIORITY_KW
except Exception:  # noqa: BLE001
    _PRIORITY_KW = {"牛来"}

logger = logging.getLogger("aiweekly.publish")


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        logger.warning("输入文件不存在，跳过：%s", p)
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("读取失败 %s: %s", p, e)
        return None


def _safe_score(item: dict) -> float:
    """从新闻条目安全解析 score（脏数据如 "N/A"、"high" 兜底为 0，不崩）。"""
    try:
        return float(item.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def build_report(
    news: dict | None,
    insights: dict | None,
    audience: dict | None,
    view_url: str | None,
    uid: str,
    top_n: int = 5,
) -> dict[str, Any]:
    """从结构化产物组装飞书卡片所需的 headline 载荷。"""
    news = news or {}
    insights = insights or {}

    # 头条：按 score 降序取前 top_n（脏数据由 _safe_score 兜底）
    items = news.get("items", []) or []
    ranked = sorted(items, key=_safe_score, reverse=True)
    headlines = []
    for it in ranked[:top_n]:
        score = _safe_score(it)
        headlines.append({
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "summary": it.get("summary", ""),
            "source": it.get("source", ""),
            "category": it.get("category", ""),
            "mustRead": bool(it.get("mustRead") or score >= 8),
        })

    ins_list = insights.get("insights", []) or []
    ins_cards = [
        {"kicker": i.get("kicker", ""), "title": i.get("title", ""), "insight": i.get("insight", "")}
        for i in ins_list[:3]
    ]

    # 受众摘要：audience_json 优先；否则 insights.audience_summary
    aud = audience if isinstance(audience, dict) else None
    if aud is None:
        aud = insights.get("audience_summary")
    if isinstance(aud, dict) and "audience_summary" in aud and len(aud) == 1:
        # 防止嵌套一层
        aud = aud["audience_summary"]
    if not isinstance(aud, dict):
        aud = {}

    # 关键词：保送集（牛来等）优先，再截断到 6 槽，确保高感知词不被吃掉
    raw_kws = [k for k in (insights.get("keywords", []) or []) if k.get("term")]
    raw_kws.sort(key=lambda k: (0 if k.get("term") in _PRIORITY_KW else 1,))
    kws = [
        {"term": k.get("term", ""), "tag": k.get("tag", "")}
        for k in raw_kws[:6]
    ]

    week = news.get("week") or insights.get("week") or "本周"
    lead = insights.get("lead", "")

    final_view = None
    if view_url:
        sep = "&" if "?" in view_url else "?"
        final_view = f"{view_url}{sep}src=feishu&uid={uid}"

    return {
        "week": week,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lead": lead,
        "headlines": headlines,
        "insights": ins_cards,
        "audience": aud,
        "keywords": kws,
        "view_url": final_view,
        "view_label": "查看完整周报",
    }


def resolve_webhook(args: argparse.Namespace) -> str | None:
    if args.webhook:
        return args.webhook
    env = os.environ.get("FEISHU_WEBHOOK")
    if env:
        return env
    cfg = REPO_ROOT / "delivery" / "feishu_config.json"
    if cfg.exists():
        try:
            d = json.load(open(cfg, encoding="utf-8"))
            if d.get("webhook"):
                return d["webhook"]
        except (OSError, ValueError):
            pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="组装本周头条 report.json 并推送飞书卡片（P0）")
    ap.add_argument("--platform", default="feishu", choices=["feishu"],
                    help="目标平台（当前仅 feishu）")
    ap.add_argument("--news-json", required=True, help="news.json 路径")
    ap.add_argument("--insights-json", required=True, help="insights.json 路径")
    ap.add_argument("--audience-json", default=None, help="audience_summary.json（可选，缺省用 insights.audience_summary）")
    ap.add_argument("--report-json", default=None, help="直接复用已生成的 report.json（跳过组装）")
    ap.add_argument("--webhook", default=None, help="飞书自定义机器人 Webhook 地址")
    ap.add_argument("--view-url", default=None, help="完整周报托管链接（自动追加 ?src=feishu&uid=）")
    ap.add_argument("--uid", default="auto", help="度量 uid；'auto' 生成短 uuid")
    ap.add_argument("--output", default=None, help="report.json 写出路径（默认 news 同目录/report.json）")
    ap.add_argument("--top-n", type=int, default=5, help="头条条数（默认 5）")
    ap.add_argument("--dry-run", action="store_true", help="仅构造卡片并打印，不推送")
    ap.add_argument("--html", default=None, help="生成的周报 HTML 路径（配合 --deploy 部署到 gh-pages）")
    ap.add_argument("--deploy", action="store_true", help="生成 report.json 后顺便部署到 gh-pages（需 --html）")
    ap.add_argument("--no-push", action="store_true", help="部署时仅本地提交不推送（透传给 deploy_ghpages）")
    ap.add_argument("--switch-pages", action="store_true", help="部署时一并把 Pages 源切到 gh-pages（需 GITHUB_TOKEN）")
    args = ap.parse_args()

    uid = args.uid if args.uid != "auto" else uuid.uuid4().hex[:8]

    # 复用已生成的 report.json
    if args.report_json and Path(args.report_json).exists():
        report = json.load(open(args.report_json, encoding="utf-8"))
        print(f"♻️ 复用已有 report.json：{args.report_json}")
    else:
        news = _load(args.news_json)
        insights = _load(args.insights_json)
        audience = _load(args.audience_json)
        if not news or not insights:
            print("❌ 缺少 news.json 或 insights.json，无法组装报告。")
            return 1
        report = build_report(news, insights, audience, args.view_url, uid, top_n=args.top_n)

    out = args.output or str(Path(args.news_json).resolve().parent / "report.json")
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ report.json 已写入：{out}")

    card = build_headline_card(report)
    print(f"📦 卡片段落数：{len(card['card']['elements'])} | "
          f"headlines={len(report['headlines'])} insights={len(report['insights'])} "
          f"audience={len(report['audience'])} keywords={len(report['keywords'])}")

    if args.dry_run:
        print("🛑 dry-run：不推送。卡片 JSON 预览（截断 2400 字）：")
        print(json.dumps(card, ensure_ascii=False, indent=2)[:2400])
        return 0

    rc = 0
    webhook = resolve_webhook(args)
    if not webhook:
        print("⚠️ 未配置飞书 Webhook（--webhook / $FEISHU_WEBHOOK / delivery/feishu_config.json 均空），"
              "跳过推送（报告已生成，不阻断）。")
    else:
        try:
            resp = push(webhook, card)
            code = resp.get("code")
            if code in (0, None):
                print(f"✅ 飞书推送成功：{resp}")
            else:
                print(f"❌ 飞书返回业务错误：{resp}")
                rc = 1
        except Exception as e:  # noqa: BLE001  传输层错误，best-effort 上报
            logger.warning("飞书推送传输失败: %s", e)
            print(f"❌ 飞书推送失败：{e}")
            rc = 1

    # 流水线最终分发步骤：把周报部署到 gh-pages（GitHub Pages）
    if args.deploy:
        if not args.html or not Path(args.html).exists():
            print("⚠️ --deploy 需要有效的 --html 路径，跳过 gh-pages 部署。")
        else:
            print("🌐 部署周报到 gh-pages…")
            try:
                import subprocess as _sp
                deploy_cmd = [sys.executable,
                              str(REPO_ROOT / "scripts" / "deploy_ghpages.py"),
                              "--html", args.html]
                if args.no_push:
                    deploy_cmd.append("--no-push")
                if args.switch_pages:
                    deploy_cmd.append("--switch-pages")
                _sp.run(deploy_cmd, cwd=str(REPO_ROOT), check=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("gh-pages 部署异常: %s", exc)
                print(f"❌ gh-pages 部署异常：{exc}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
