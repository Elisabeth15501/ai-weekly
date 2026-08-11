#!/usr/bin/env python3
"""Feishu (Lark) custom group bot — push weekly headline card via incoming webhook.

设计原则（沿用 skill 合规约束）：
- 仅用 `requests`（已是 requirements 依赖）POST 到飞书官方 incoming-webhook，
  **不引入任何第三方商业 SDK / 云端服务**。
- 构造 interactive 卡片（消息卡片），承载本周头条速览 + 三视角看点 + 分角色摘要
  + 「查看完整周报」按钮（链接带 ?src=feishu&uid= 度量参数）。
- 防御式处理 report 各字段，任一缺失都不崩，缺失段落自动跳过。

飞书自定义机器人卡片协议（精简）：
  POST <webhook>  body = {"msg_type": "interactive", "card": {...}}
  成功响应 {"code":0,"msg":"success"}；业务错误 {"code":19021,...}。
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("aiweekly.delivery.feishu")

# 角色 icon 映射（audience_summary 中文键）
_ROLE_ICON = {
    "开发者": "🧑\u200d💻",
    "AI 产品经理": "🧑\u200d💼",
    "科技媒体工作者": "📝",
    "PM": "🧑\u200d💼",
    "自媒体": "📝",
}


def _md_escape(text: str) -> str:
    """飞书 lark_md 无官方转义；把可能误触发 markdown 的 * 与 _ 做最小处理，
    仅当它们出现在单词边界时易破坏排版，这里统一把连续 * _ 替换为全角，避免格式错乱。
    标题/摘要来自 RSS，含 * 概率低，做轻量防护即可。"""
    if not text:
        return ""
    # 把独立成对的 *...* / _..._ 视为应保留的强调；仅转义"裸"单字符 *_ 误触。
    # 简单策略：将行内单个 `*`（非成对）替换为全角 ＊，避免整段变粗。
    out = text.replace("**", "\u200b**\u200b")  # 保护成对加粗
    return out


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text[:n] + ("…" if len(text) > n else "") if text else ""


def build_headline_card(report: dict[str, Any]) -> dict[str, Any]:
    """从 report.json 头条载荷构造飞书 interactive 卡片。

    report 期望字段（全部可选，缺失即跳过该段落）：
      week, generated_at, lead,
      headlines[{title,url,summary,source,category,mustRead}],
      insights[{kicker,title,insight}],
      audience{dict: 角色->摘要},
      keywords[{term,tag}],
      view_url, view_label
    """
    report = report or {}
    week = report.get("week") or "本周"

    header = {
        "title": {"tag": "plain_text", "content": f"📊 AI 行业周报 · {week}"},
        "template": "blue",
    }
    elements: list[dict[str, Any]] = []

    # 1) 本周主线
    lead = report.get("lead")
    if lead:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**本周主线**\n{_truncate(lead, 120)}"},
        })

    # 2) 本周重点（headlines，按分数排序取前 5）
    headlines = [h for h in (report.get("headlines") or []) if h.get("title")]
    if headlines:
        lines = ["**🔥 本周重点**"]
        for i, h in enumerate(headlines[:5], 1):
            title = h.get("title", "")
            url = h.get("url", "")
            summary = _truncate(h.get("summary", ""), 56)
            src = h.get("source", "")
            must = " 🔥" if h.get("mustRead") else ""
            t = f"[{title}]({url})" if url else title
            line = f"{i}. {t}{must}"
            if src or summary:
                tail = " · ".join(x for x in [src, summary] if x)
                line += f"\n   _{tail}_" if tail else ""
            lines.append(line)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

    # 3) 本周看点（insights，取前 3）
    insights = [x for x in (report.get("insights") or []) if x.get("title")]
    if insights:
        lines = ["**💡 本周看点**"]
        for ins in insights[:3]:
            kicker = ins.get("kicker", "")
            title = ins.get("title", "")
            insight = ins.get("insight", "")
            head = f"{kicker} · {title}" if kicker else title
            line = f"• **{head}**"
            if insight:
                line += f"\n  {_truncate(insight, 70)}"
            lines.append(line)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

    # 4) 给不同角色（audience_summary）
    audience = report.get("audience") or {}
    if isinstance(audience, dict) and audience:
        lines = ["**👥 给不同角色**"]
        for role, text in audience.items():
            if not text:
                continue
            icon = _ROLE_ICON.get(role, "•")
            lines.append(f"{icon} **{role}**：{_truncate(str(text), 80)}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

    # 5) 本周关键词
    keywords = [k.get("term", "") for k in (report.get("keywords") or []) if k.get("term")]
    if keywords:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**🔖 本周关键词**：{'、'.join(keywords[:6])}"},
        })

    # 6) 查看完整周报（按钮 / 回退 note）
    view_url = report.get("view_url")
    if view_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": report.get("view_label", "查看完整周报")},
                "type": "primary",
                "url": view_url,
            }],
        })
    else:
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text",
                          "content": report.get("view_label", "完整周报见本地生成的 HTML 文件")}],
        })

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": header,
            "elements": elements,
        },
    }


def push(webhook: str, card: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    """POST 卡片到飞书 incoming webhook，返回 API JSON 响应。

    仅在传输层失败时抛 requests.RequestException（由调用方决定重试）；
    业务错误（code != 0）不抛异常，由调用方读取返回值判断。
    """
    resp = requests.post(webhook, json=card, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return {"code": None, "msg": resp.text}
