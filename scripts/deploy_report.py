#!/usr/bin/env python3
"""
deploy_report.py

将生成的 AI 周报 HTML 文件部署到云端，返回可分享的 URL。
由 WorkBuddy Agent 在自动化任务中调用，也可以单独运行测试。

依赖：WorkBuddy 内置的 workbuddy_cloudstudio_deploy 工具（由 Agent 调用，本脚本不直接调用）

本脚本负责：
  1. 读取 HTML 报告文件
  2. 提取报告摘要（前3条新闻标题 + KPI 数据）
  3. 输出摘要 JSON，供 Agent 在通知用户时使用

用法：
  python deploy_report.py --html AI_Weekly_Report_2026_W27.html
  python deploy_report.py --help
"""

import argparse
import json
import re
import sys
from pathlib import Path


def _detect_format(html_content: str) -> str:
    """判断是 v3.0 新闻站还是 v2.0 周报。"""
    if 'news-card' in html_content or 'NEWS_DATA' in html_content:
        return 'v3'
    return 'v2'


def extract_kpi(html_content: str) -> list[dict]:
    """从 HTML 中提取 KPI / 统计摘要。"""
    kpis = []
    fmt = _detect_format(html_content)

    if fmt == 'v3':
        # v3.0: 从 NEWS_DATA 提取总条数和分类分布
        total_match = re.search(r'const NEWS_DATA\s*=\s*(\[)', html_content)
        if total_match:
            title_count = html_content.count('"title"', total_match.start(),
                                             total_match.start() + 50000)
            categories = {
                'ai-models': 0, 'ai-products': 0, 'industry': 0, 'paper': 0, 'tip': 0
            }
            for cat in categories:
                categories[cat] = html_content.count(
                    f'"category": "{cat}"', total_match.start(), total_match.start() + 50000
                )
            kpis.append({"value": f"{title_count} 条新闻", "change": "本周精选"})
            top_cats = sorted(categories.items(), key=lambda x: -x[1])[:3]
            for cat, count in top_cats:
                label = {'ai-models': '模型', 'ai-products': '产品',
                         'industry': '行业', 'paper': '论文', 'tip': '技巧'}.get(cat, cat)
                kpis.append({"value": f"{label} ×{count}", "change": ""})
    else:
        # v2.0: 匹配 KPI 卡片
        pattern = r'class="kpi-value"[^>]*>([^<]+)<.*?class="kpi-change"[^>]*>([^<]+)'
        matches = re.findall(pattern, html_content, re.DOTALL)
        for val, change in matches:
            kpis.append({"value": val.strip(), "change": change.strip()})

    return kpis


def extract_news_titles(html_content: str, max_items: int = 3) -> list[str]:
    """从 HTML 中提取新闻标题。"""
    fmt = _detect_format(html_content)

    if fmt == 'v3':
        # v3.0: 从 NEWS_DATA JS 数组中提取前几条标题
        news_match = re.search(r'const NEWS_DATA\s*=\s*(\[)', html_content)
        if news_match:
            # 提取 JSON 数组中的 title 字段
            titles = re.findall(r'"title":\s*"([^"]+)"', html_content[news_match.start():])
            return titles[:max_items]

    # v2.0: 匹配新闻条目中的标题
    pattern = r'class="news-title"[^>]*>([^<]+)<'
    matches = re.findall(pattern, html_content)
    return matches[:max_items]


def extract_summary(html_path: Path) -> dict:
    """从 HTML 报告中提取核心摘要。"""
    content = html_path.read_text(encoding="utf-8")
    kpis = extract_kpi(content)
    news_titles = extract_news_titles(content)

    # 从文件名提取信息
    stem = html_path.stem
    # v2: AI_Weekly_Report_2026_W27
    week_match = re.search(r'(\d{4})_W(\d+)', stem)
    if week_match:
        year, week = week_match.groups()
        week_label = f"{year}年第{week}周"
    else:
        # v3: AI_News_2026-07-18
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', stem)
        if date_match:
            y, m, d = date_match.groups()
            week_label = f"{y}/{m}/{d} AI 新闻站"
        else:
            week_label = stem.replace("AI_Weekly_Report_", "").replace("AI_News_", "").replace("_", "-")

    return {
        "week_label": week_label,
        "kpi_summary": [f"{k['value']} ({k['change']})" for k in kpis if k['value']],
        "top_news": news_titles,
        "report_file": html_path.name,
    }


def generate_workbuddy_notification(summary: dict) -> str:
    """生成 WorkBuddy 通知消息文本。"""
    lines = [
        f"📊 AI行业周报 · {summary['week_label']}",
        "",
        "本周核心数据：",
    ]
    for kpi in summary["kpi_summary"]:
        lines.append(f"  • {kpi}")
    if summary["top_news"]:
        lines.append("")
        lines.append("本周重点：")
        for title in summary["top_news"]:
            lines.append(f"  • {title}")
    lines.append("")
    lines.append(f"完整报告：{summary['report_file']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="提取 AI 周报摘要，生成通知消息体"
    )
    parser.add_argument("--html", required=True, help="HTML 报告文件路径")
    parser.add_argument("--output", default=None, help="摘要输出路径（JSON）")
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"❌ HTML 文件不存在：{html_path}")
        sys.exit(1)

    print(f"📖 正在读取报告：{html_path.name}")

    summary = extract_summary(html_path)
    notification = generate_workbuddy_notification(summary)

    # 输出摘要 JSON
    out_path = Path(args.output) if args.output else html_path.with_suffix(".summary.json")
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ 摘要已保存：{out_path}")

    # 输出通知文本
    print("\n📱 WorkBuddy 通知内容：")
    print("─" * 40)
    print(notification)
    print("─" * 40)

    return 0


if __name__ == "__main__":
    sys.exit(main())
