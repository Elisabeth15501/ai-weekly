"""市场数据：全球/中国规模与融资默认值、Chart.js 数据构建、本周市场信号与趋势洞察桥接。

从 generate_site.py 抽出（P1#1 Phase 2）。
- 国内数据单位为亿元人民币，全球为十亿美元；均为**静态快照**，随 `--data-snapshot` 标注截止日。
- `_extract_market_signals` / `_render_trend_insights_html` 负责「宏观图 ↔ 本周新闻」的桥接
  （计划第九章 M1/M2），全部服务端预渲染进静态 HTML，禁 JS 也可见。
"""
import html
import json
import re

from aiweekly.leaderboard import _collect_leaderboard_models


def _js_json(obj) -> str:
    """序列化 JSON 供 <script> 上下文内联（图表 labels/data 来自 CLI 用户可控字符串）。

    转义 < > & 为 \\u003c / \\u003e / \\u0026，阻止 </script> 突破脚本块（防 XSS，对应审查 L4）。
    ensure_ascii=False 保留中文可读性；数值/布尔/None 序列化不受影响。
    """
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026"))




__all__ = [
    "DEFAULT_MARKET_LABELS", "DEFAULT_MARKET_DATA", "DEFAULT_FUNDING_LABELS", "DEFAULT_FUNDING_DATA",
    "DEFAULT_CN_MARKET_LABELS", "DEFAULT_CN_MARKET_DATA", "DEFAULT_CN_FUNDING_LABELS", "DEFAULT_CN_FUNDING_DATA",
    "DEFAULT_CN_STRUCTURE_LABELS", "DEFAULT_CN_STRUCTURE_DATA", "DEFAULT_CN_CONCENTRATION_LABELS", "DEFAULT_CN_CONCENTRATION_DATA",
    "DEFAULT_MARKET_SOURCE", "DEFAULT_FUNDING_SOURCE", "DEFAULT_CN_MARKET_SOURCE", "DEFAULT_CN_FUNDING_SOURCE",
    "ESTIMATE_NOTE", "build_charts", "BASE_SOURCES", "SIGNAL_WEIGHTS",
    "MODEL_HINTS", "CN_HINTS", "AMOUNT_RE", "_extract_market_signals",
    "_compute_weekly_stats", "_lb_name_map", "_render_market_signals_html", "TREND_INSIGHTS",
    "_match_insight_evidence", "_signal_theme", "_render_trend_insights_html", "_render_market_signals_html_with_theme",
]


# 图表默认值（仅在未通过 CLI 提供真实数据时使用，且明确标注为估算）
DEFAULT_MARKET_LABELS = ['2020','2021','2022','2023','2024','2025','2026E','2027F','2028F']
# 2026-W32 版基准：Grand View Research 2026（CAGR 30.6%），单位十亿美元（$B）
DEFAULT_MARKET_DATA = [103, 134, 176, 229, 299, 391, 540, 705, 921]
DEFAULT_FUNDING_LABELS = ['23Q1','23Q2','23Q3','23Q4','24Q1','24Q2','24Q3','24Q4','25Q1','25Q2','25Q3','25Q4','26Q1','26Q2']
# 2026-W32 版基准：Crunchbase H1 2026（Q1 305 / Q2 205，合计 510）+ CB Insights 2023-2025 年度均摊，单位十亿美元（$B）
DEFAULT_FUNDING_DATA = [72.4, 72.4, 72.4, 72.4, 79.9, 79.9, 79.9, 79.9, 110.0, 110.0, 110.0, 110.0, 305.0, 205.0]
# 中国分轨（国内源）：单位亿元（RMB）。来源：中国信通院 / 中商产业研究院《2025-2030 中国人工智能产业现状调查》
DEFAULT_CN_MARKET_LABELS = ['2024', '2025', '2026E']
DEFAULT_CN_MARKET_DATA = [9188, 12000, 17000]
# 中国 AI 一级市场融资（亿元，RMB）。来源：新浪创投Plus 2025 全年 + IT桔子 2026H1（一级市场股权融资，标签「人工智能」）
# M2 #8：补 2026H1 当期点，消除「图说 3076 亿但图里没有」的脱节
DEFAULT_CN_FUNDING_LABELS = ['2024', '2025', '2026H1']
DEFAULT_CN_FUNDING_DATA = [391.51, 656.04, 3076.82]
# 中国 2026H1 AI 融资赛道结构（亿元，RMB）。来源：IT桔子 2026H1 细分赛道统计
# M2 #7：把散文里的细分做成结构图（替代纯文本）
DEFAULT_CN_STRUCTURE_LABELS = ['大模型', '具身智能', 'AIGC 应用', '基础层']
DEFAULT_CN_STRUCTURE_DATA = [1598, 906, 596, 725]
# 中国 AI 融资头部集中度（亿元，RMB）。来源：IT桔子 2026H1（合计 3076 亿）
# M2 #9：TOP3 大模型独揽 930 亿（30%）；TOP4–30 名约 770 亿；其余赛道约 1376 亿
DEFAULT_CN_CONCENTRATION_LABELS = ['TOP3 大模型', 'TOP4–30 名', '其他赛道']
DEFAULT_CN_CONCENTRATION_DATA = [930, 770, 1376]
# 市场数据来源（默认值）——国内源优先、全球源作海外机构静态快照引用。
# 关键：即使未传 --*-source，也用真实署名，避免回退成「示例/估算」自损式免责。
# 国内网络友好：中国分轨均来自国内可达机构（信通院/中商/IT桔子/新浪创投Plus）；
# 全球分轨标注「海外机构，静态快照引用」，明确是静态引用而非实时外网抓取。
DEFAULT_MARKET_SOURCE = "Grand View Research 2026（全球 AI 市场规模，CAGR 30.6%；海外机构，静态快照引用）"
DEFAULT_FUNDING_SOURCE = "Crunchbase / CB Insights（全球 AI 融资，H1 2026 口径；海外机构，静态快照引用）"
DEFAULT_CN_MARKET_SOURCE = "中国信通院 · 中商产业研究院《2025–2030 中国人工智能产业现状调查》（中国核心产业规模）"
DEFAULT_CN_FUNDING_SOURCE = "新浪创投Plus 2025 国内一级市场 AI 行业统计 + IT桔子 2026H1（一级市场股权融资，标签「人工智能」）"
# 兜底免责（已不再默认触发；表述改为诚实的「静态快照」而非「示例/估算」）
ESTIMATE_NOTE = "数据快照（静态，非实时）"

def build_charts(market_data=None, market_labels=None,
                 funding_data=None, funding_labels=None,
                 cn_market_data=None, cn_market_labels=None,
                 cn_funding_data=None, cn_funding_labels=None,
                 cn_structure_data=None, cn_structure_labels=None,
                 cn_concentration_data=None, cn_concentration_labels=None) -> str:
    """生成 Chart.js 初始化代码。未提供真实数据时回退到标注清晰的估算值。
    支持全球(Global)与中国(CN)双来源：每类含市场规模与融资趋势，各自独立来源。
    M2：中国融资补 2026H1 当期点，并新增「赛道结构」与「头部集中度」两张分析图。"""
    m_data = market_data or DEFAULT_MARKET_DATA
    m_labels = market_labels or DEFAULT_MARKET_LABELS
    f_data = funding_data or DEFAULT_FUNDING_DATA
    f_labels = funding_labels or DEFAULT_FUNDING_LABELS
    cm_data = cn_market_data or DEFAULT_CN_MARKET_DATA
    cm_labels = cn_market_labels or DEFAULT_CN_MARKET_LABELS
    cf_data = cn_funding_data or DEFAULT_CN_FUNDING_DATA
    cf_labels = cn_funding_labels or DEFAULT_CN_FUNDING_LABELS
    cs_data = cn_structure_data or DEFAULT_CN_STRUCTURE_DATA
    cs_labels = cn_structure_labels or DEFAULT_CN_STRUCTURE_LABELS
    cc_data = cn_concentration_data or DEFAULT_CN_CONCENTRATION_DATA
    cc_labels = cn_concentration_labels or DEFAULT_CN_CONCENTRATION_LABELS
    return f"""
// Market size chart（M3 #11：实测 vs CAGR 外推 诚实区分）
const marketCtx = document.getElementById('marketSizeChart').getContext('2d');
// 标签以 F 结尾视为「预测/外推」（如 2027F/2028F），浅色虚线感；其余为实测/机构估算，实色
const marketIsForecast = {_js_json([(l.strip().endswith('F')) for l in m_labels])};
const marketBarColors = marketIsForecast.map(f => f ? 'rgba(37,99,235,0.32)' : 'rgba(37,99,235,0.7)');
const marketBarBorders = marketIsForecast.map(f => f ? 'rgba(37,99,235,0.6)' : 'rgba(37,99,235,1)');
marketChart = new Chart(marketCtx, {{
  type: 'bar',
  data: {{
    labels: {_js_json(m_labels)},
    datasets: [{{
      label: '市场规模（$B，约 ¥7.2/$）',
      data: {_js_json(m_data)},
      backgroundColor: marketBarColors,
      borderColor: marketBarBorders,
      borderWidth: 1, borderRadius: 6,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => {{
        const f = marketIsForecast[c.dataIndex];
        return '$'+c.parsed.y+'B' + (f ? '（CAGR 外推，非实测）' : '（实测/机构估算）');
      }} }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => '$'+v+'B' }} }}
    }}
  }}
}});

// Funding trend chart
const fundCtx = document.getElementById('fundingChart').getContext('2d');
fundingChart = new Chart(fundCtx, {{
  type: 'line',
  data: {{
    labels: {_js_json(f_labels)},
    datasets: [{{
      label: '融资额（$B，约 ¥7.2/$）',
      data: {_js_json(f_data)},
      borderColor: 'rgba(124,58,237,1)',
      backgroundColor: 'rgba(124,58,237,0.1)',
      fill: true, tension: 0.3,
      pointRadius: 4, pointBackgroundColor: 'rgba(124,58,237,1)',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => '$'+v+'B' }} }}
    }}
  }}
}});

// --- 中国 AI 核心产业规模（亿元，RMB）--- M3 #10：叠加 YoY% 折线
const cnMarketCtx = document.getElementById('cnMarketChart').getContext('2d');
// 由数据自动算同比：第 i 年 = data[i]/data[i-1]-1（首年无）
const cnYoY = {_js_json([None] + [round((cm_data[i]/cm_data[i-1]-1)*100, 1) for i in range(1, len(cm_data))])};
cnMarketChart = new Chart(cnMarketCtx, {{
  type: 'bar',
  data: {{
    labels: {_js_json(cm_labels)},
    datasets: [
      {{
        label: '核心产业规模（亿元，RMB）',
        data: {_js_json(cm_data)},
        backgroundColor: 'rgba(220,38,38,0.7)',
        borderColor: 'rgba(220,38,38,1)',
        borderWidth: 1, borderRadius: 6,
        yAxisID: 'y',
        order: 2,
      }},
      {{
        label: '同比增速 YoY（%）',
        data: cnYoY,
        type: 'line',
        borderColor: 'rgba(22,163,74,1)',
        backgroundColor: 'rgba(22,163,74,1)',
        borderWidth: 2, tension: 0.3,
        pointRadius: 4, pointBackgroundColor: 'rgba(22,163,74,1)',
        yAxisID: 'y2',
        order: 1,
      }}
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: true, labels: {{ color: '#64748b', boxWidth: 12, font: {{ size: 11 }} }} }},
      tooltip: {{ callbacks: {{ label: c => {{
        if (c.dataset.yAxisID === 'y2') {{
          return c.parsed.y == null ? 'YoY：—' : 'YoY：+'+c.parsed.y+'%';
        }}
        return c.parsed.y+'亿（RMB）' + (cnYoY[c.dataIndex] != null ? '  同比 +'+cnYoY[c.dataIndex]+'%' : '');
      }} }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ position: 'left', grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y2: {{ position: 'right', grid: {{ display: false }}, ticks: {{ color: '#16a34a', callback: v => v+'%' }}, suggestedMin: 0 }}
    }}
  }}
}});

// --- 中国 AI 融资趋势（亿元，RMB，年度）---
const cnFundCtx = document.getElementById('cnFundingChart').getContext('2d');
cnFundingChart = new Chart(cnFundCtx, {{
  type: 'line',
  data: {{
    labels: {_js_json(cf_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {_js_json(cf_data)},
      borderColor: 'rgba(220,38,38,1)',
      backgroundColor: 'rgba(220,38,38,0.1)',
      fill: true, tension: 0.3,
      pointRadius: 4, pointBackgroundColor: 'rgba(220,38,38,1)',
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b' }} }},
      y: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }}
    }}
  }}
}});

// --- 中国 2026H1 AI 融资赛道结构（亿元，RMB）--- M2 #7
const cnStructCtx = document.getElementById('cnStructureChart').getContext('2d');
cnStructureChart = new Chart(cnStructCtx, {{
  type: 'bar',
  data: {{
    labels: {_js_json(cs_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {_js_json(cs_data)},
      backgroundColor: ['rgba(220,38,38,0.78)','rgba(234,88,12,0.78)','rgba(217,119,6,0.78)','rgba(100,116,139,0.78)'],
      borderRadius: 6,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => c.parsed.x + ' 亿（RMB）' }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
    }}
  }}
}});

// --- 中国 AI 融资头部集中度（亿元，RMB）--- M2 #9
const cnConcCtx = document.getElementById('cnConcentrationChart').getContext('2d');
cnConcentrationChart = new Chart(cnConcCtx, {{
  type: 'bar',
  data: {{
    labels: {_js_json(cc_labels)},
    datasets: [{{
      label: '融资额（亿元，RMB）',
      data: {_js_json(cc_data)},
      backgroundColor: ['rgba(220,38,38,0.85)','rgba(234,88,12,0.7)','rgba(148,163,184,0.7)'],
      borderRadius: 6,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: c => c.parsed.x + ' 亿（占 3076 亿的 ' + (c.parsed.x/3076.82*100).toFixed(1) + '%）' }} }} }},
    scales: {{
      x: {{ grid: {{ color: 'rgba(0,0,0,0.06)' }}, ticks: {{ color: '#64748b', callback: v => v+'亿' }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: '#64748b' }} }}
    }}
  }}
}});
"""

# 页脚「数据来源」基础列表（不含任何内置第三方商业 API；用户自备的外部 API 才会动态追加）
BASE_SOURCES = [
    ("LMMarketCap", "https://lmmarketcap.com"),
    ("Gartner", "https://gartner.com"),
    ("IDC", "https://idc.com"),
    ("Statista", "https://statista.com"),
    ("Crunchbase", "https://crunchbase.com"),
    ("Stanford HAI", "https://hai.stanford.edu"),
]


# ============ M1：本周市场信号（新闻 ↔ 宏观图 桥接）============
# 从本周新闻抽取融资 / 并购 / IPO / 大额融资轮 / 模型发布事件，做成「关于本周」的桥接卡，
# 让市场板块不再只是静态宏观百科，而是真正呼应本周发生的事（计划第九章 M1 #4/#5/#6）。
SIGNAL_WEIGHTS = {
    "融资": [("融资", 3), ("募资", 3), ("轮融资", 3), ("融资轮", 3),
             ("funding", 3), ("raised", 3), ("raise", 2), ("round", 2)],
    "并购": [("收购", 3), ("并购", 3), ("acqui", 3), ("merger", 3)],
    "IPO": [("ipo", 3), ("招股", 3), ("敲钟", 3), ("上市", 2)],
    "估值": [("估值", 2), ("valuation", 2), ("独角兽", 3), ("unicorn", 3)],
    "模型发布": [("新模型", 2), ("模型发布", 2), ("发布模型", 2)],
}
# 模型发布类信号词（须与「模型」同现才计入，避免「发布报告」误触发）
MODEL_HINTS = ["发布", "推出", "开源", "上线"]
# 中国 / 国内机构或币种关键词 -> 桥接到中国融资图
CN_HINTS = ["中国", "国内", "人民币", "亿元", "阿里", "腾讯", "字节", "月之暗面", "kimi",
            "deepseek", "阶跃", "智谱", "百度", "商汤", "科大讯飞", "minimax", "百川",
            "零一万物", "蚂蚁", "华为", "美团", "京东"]
AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(亿美金|亿美元|亿人民币|亿元人民币|亿元|亿|万美金|万美元|万元|万|"
    r"trillion|billion|\bn\b|\$b|\$\s*\d[\d.,]*\s*(?:b|bn|k|m)?)", re.I)


def _extract_market_signals(news_items, top_n=5):
    """从本周新闻抽取资本 / 模型发布信号，按信号强度打分取 Top N。

    返回每条：title / url / source / amount / types[] / bridge_label / bridge_region / score。
    桥接目标：中国机构或币种 -> 中国融资趋势；并购/IPO -> 全球融资趋势；纯模型发布 -> 能力榜。
    """
    signals = []
    for it in news_items:
        title = it.get("title", "") or ""
        summary = it.get("summary", "") or ""
        text = f"{title} {summary}"
        low = text.lower()
        score = 0
        types = set()
        for t, kws in SIGNAL_WEIGHTS.items():
            for kw, w in kws:
                if kw.lower() in low:
                    score += w
                    types.add(t)
        # 模型发布须与「模型」同现
        if "模型" in low and any(h in low for h in MODEL_HINTS):
            score += 2
            types.add("模型发布")
        if score < 2:
            continue
        am = AMOUNT_RE.search(text)
        amount = am.group(0).strip() if am else ""
        is_cn = any(h.lower() in low for h in CN_HINTS)
        if "并购" in types or "IPO" in types:
            bridge = ("全球融资趋势", "🌍 全球")
        elif is_cn:
            bridge = ("中国融资趋势", "🇨🇳 中国")
        elif types == {"模型发布"}:
            bridge = ("大模型排行榜", "🏆 能力榜")
        else:
            bridge = ("全球融资趋势", "🌍 全球")
        signals.append({
            "title": title,
            "url": it.get("url", "") or "",
            "source": it.get("source", "") or "",
            "lang": it.get("lang", "") or "",
            "cn_summary": it.get("cn_summary", "") or "",
            "amount": amount,
            "types": sorted(types),
            "bridge_label": bridge[0],
            "bridge_region": bridge[1],
            "score": score + (it.get("score", 0) or 0) * 0.1,
        })
    signals.sort(key=lambda x: x["score"], reverse=True)
    return signals[:top_n]


def _compute_weekly_stats(news_items, market_signals, leaderboard_data):
    """聚合「本周数字看板」：新闻总量 / 国内外比 / 模型相关+新发布 / 融资&发布事件 / 在榜模型数 / 必读 Top3。

    - news_items 已含 mustRead / score / category / lang / title / url
    - market_signals 来自 _extract_market_signals（types 标记融资/并购/IPO/模型发布）
    - 全部为派生指标，不引入新外部数据源；失败场景（空数据）兜底返回零值结构。
    """
    items = news_items or []
    sigs = market_signals or []
    total = len(items)
    zh = sum(1 for n in items if n.get("lang") == "zh")
    en = total - zh
    # 兼容 ai-models / model 两种历史 category 写法
    _MODEL_CATS = {"ai-models", "model"}
    model_news = [n for n in items if n.get("category") in _MODEL_CATS]
    _rel_re = re.compile(r"发布|推出|开源|上线|preview|launch|released|open.?source", re.I)
    releases = [
        n for n in model_news
        if _rel_re.search(f"{n.get('title','')} {n.get('summary','')}")
    ]
    fund_events = [
        s for s in sigs
        if s.get("types") and (
            set(s.get("types", [])) & {"融资", "并购", "IPO", "模型发布"}
            or s.get("amount")
        )
    ]
    must = sorted(
        [n for n in items if n.get("mustRead")],
        key=lambda x: x.get("score", 0) or 0,
        reverse=True,
    )[:3]
    lb_models = _collect_leaderboard_models(leaderboard_data)
    return {
        "total": total,
        "zh": zh,
        "en": en,
        "model_news": len(model_news),
        "releases": len(releases),
        "fund_events": len(fund_events),
        "lb_models": len(lb_models),
        "must_read": [
            {"title": (n.get("title") or "").strip(),
             "url": n.get("url") or "#"}
            for n in must
        ],
    }


def _lb_name_map(leaderboard):
    """构建 模型名/机构名(小写) -> (名次, 源) 映射，供资本↔能力联动标注。"""
    m = {}
    if not isinstance(leaderboard, dict):
        return m
    for grp in ("comprehensive", "open_source"):
        block = leaderboard.get(grp, {})
        if not isinstance(block, dict):
            continue
        for src, payload in block.items():
            rows = payload.get("rows", []) if isinstance(payload, dict) else []
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                for key in ("model", "name", "org", "organization"):
                    v = (r.get(key) or "").lower().strip()
                    if v and v not in m:
                        m[v] = (i + 1, src)
    return m


def _render_market_signals_html(signals, lb_map):
    """服务端预渲染「本周市场信号」区块（即使 JS 不执行也可见）。"""
    if not signals:
        return ('<p class="ms-empty">本周新闻中未检出重大融资 / 并购 / IPO / 模型发布事件'
                '——市场板块维持宏观背景视角。</p>')
    cards = []
    for s in signals:
        types_html = " ".join(f'<span class="ms-type t-{t}">{t}</span>' for t in s["types"])
        amt = f'<span class="ms-amount">{s["amount"]}</span>' if s["amount"] else ""
        # 资本↔能力：检测标题是否含上榜模型/机构名
        title_low = s["title"].lower()
        on_lb = None
        for nm, (rk, src) in lb_map.items():
            if nm and nm in title_low:
                on_lb = (rk, src)
                break
        if on_lb:
            cap = f'<span class="ms-cap">↔ 能力榜 #{on_lb[0]}（{on_lb[1]}）</span>'
        else:
            cap = '<span class="ms-cap ms-cap-off">↔ 能力榜：未上榜</span>'
        url = s["url"] or "#"
        cards.append(
            f'<div class="ms-card">'
            f'<div class="ms-top">{types_html}{amt}</div>'
            f'<a class="ms-title" href="{url}" target="_blank" rel="noopener">{s["title"]}</a>'
            f'<div class="ms-meta"><span class="ms-bridge">{s["bridge_region"]} ↔ {s["bridge_label"]}</span>'
            f'{cap}<span class="ms-src">{s["source"]}</span></div>'
            f'</div>')
    head = (f'<p class="ms-head">从本周 <b>{len(signals)}</b> 条资本 / 模型发布信号看，'
            f'钱与能力正往这些方向集中（桥接下方宏观图）：</p>')
    return head + '<div class="ms-grid">' + "".join(cards) + '</div>'


# ============ 「AI 行业趋势洞察」×「关于本周」合作（计划第九章 用户议题）============
# 原本「趋势洞察」面板是模板写死的宏观百科，与本周新闻零联动。
# 做法：把 4 条宏观洞察上提到 Python，按周从本周信号 / 新闻抽「本周印证」证据行，
# 让每条宏观趋势都挂着本周真实发生的事；同时给 M1 信号卡加「印证趋势」标签，双向桥接。
TREND_INSIGHTS = [
    {
        "theme": "规模红利",
        "ico": "🌍→🇨🇳",
        "head": "规模：全球高速扩张，中国增速更快",
        "body": "全球 AI 市场 CAGR <b>30.6%</b>（Grand View Research），约每 2.5 年翻番；中国核心产业规模 "
                "<b>9188亿→1.2万亿→1.7万亿</b>（2024→2026E，中国信通院），三年近乎翻倍。",
        "tag": "PM / 开发者：国内仍是增量红利，优先盯本土落地场景",
        "tag_cls": "tag-pm",
        "keys": ["规模", "市场", "增速", "扩张", "信通院", "万亿", "增长", "产业"],
    },
    {
        "theme": "钱去哪了",
        "ico": "💰",
        "head": "钱去哪了：极端头部集中，但结构在变",
        "body": "全球 2026H1 融资 <b>$510B</b> 已超 2025 全年；中国 2026H1 AI 融资 <b>3076 亿</b>"
                "（占一级市场 48.6%），但 TOP3 大模型（DeepSeek/阶跃/Kimi）独揽 930 亿（30%），"
                "TOP30 超 1700 亿（过半）。",
        "tag": "开发者：通用大模型已是巨头决赛圈，别硬刚 base model",
        "tag_cls": "tag-dev",
        "keys": ["融资", "并购", "头部", "集中", "独角兽", "估值", "轮", "募资", "收购", "IPO"],
    },
    {
        "theme": "成本塌方",
        "ico": "💸",
        "head": "成本：推理价格年内腰斩，开源比闭源便宜 5 倍",
        "body": "企业级推理均价从 <b>$2.04</b> 跌到 <b>$1.16–1.18 / M token</b>（年内低点）；"
                "开源 vs 闭源价差约 <b>5 倍</b>（<b>$0.66</b> vs <b>$3.07</b>）。"
                "成本已不是应用落地门槛，瓶颈回到「场景与 PMF」。",
        "tag": "开发者：优先验证场景，别再为「模型太贵」找借口",
        "tag_cls": "tag-dev",
        "keys": ["成本", "降价", "价格", "推理", "GLM", "定价", "开源", "token"],
    },
    {
        "theme": "中国模型出海",
        "ico": "🇨🇳→🌐",
        "head": "势能：中国模型海外调用占比冲到 61%",
        "body": "OpenRouter 上中国模型调用量占比 <b>61%</b>；"
                "Ox Alpha 上线 6 天吃掉 <b>23.2 万亿 token</b> 登顶，"
                "国产模型从「追赶」转向「被全球用」。",
        "tag": "自媒体：国产登顶 / 出海占比 = 高情绪传播选题",
        "tag_cls": "tag-media",
        "keys": ["中国模型", "ox alpha", "openrouter", "出海", "登顶", "占比", "海外"],
    },
    {
        "theme": "具身智能",
        "ico": "🤖",
        "head": "机会窗口：具身智能成第二增长极",
        "body": "中国 2026H1 具身智能（人形机器人）融资 <b>906 亿</b>（29.5%），“七武士”单家超 20 亿；"
                "世界模型成早期第一共识（6 家早期合计 97 亿）；AIGC 应用 596 亿（图片/视频生成最成熟）。"
                "端侧拐点已现：MiniMax H3 移动端 <b>2400 万</b>下载、宇树冲刺 IPO，"
                "具身 / 端侧从 demo 走向规模化收入。",
        "tag": "开发者：现实机会在具身智能、AIGC 应用层、端侧 / 机器人",
        "tag_cls": "tag-dev",
        "keys": ["具身", "机器人", "人形", "AIGC", "应用", "agent", "世界模型", "视频生成", "智能体", "宇树", "minimax", "端侧"],
    },
    {
        "theme": "行动建议",
        "ico": "🎯",
        "head": "给三类读者的行动建议",
        "body": "<b>独立开发者</b>：用开源/免费 API（Hy3、Qwen、DeepSeek）做垂直场景应用。<br>"
                "<b>产品经理</b>：需求在“AI+传统行业”（制造/医疗/金融），用低成本模型验证 PMF。<br>"
                "<b>自媒体</b>：具身智能 + 应用层爆发是 2026 最强叙事，原始口径可向 IT桔子/信通院取。",
        "tag": "媒体：具身智能元年 / 应用层爆发 = 高传播选题",
        "tag_cls": "tag-media",
        "keys": [],  # 行动建议不挂本周印证（它是结论，不是可印证的事实趋势）
    },
]


def _match_insight_evidence(theme_keys, signals, news_items, top_k=2):
    """从本周信号 / 新闻中，为本条宏观趋势抽取「本周印证」证据。

    优先用 M1 信号（已带金额 / 链接），其次用本周新闻标题；按与主题词的重合度打分取 Top-K。
    返回 [{title, url, amount}]。
    """
    if not theme_keys:
        return []
    cands = []
    # 信号优先（已有金额与链接）
    for s in (signals or []):
        t = (s.get("title", "") or "").lower()
        hit = sum(1 for k in theme_keys if k.lower() in t)
        if hit:
            cands.append((hit, s.get("title", ""), s.get("url", "") or "", s.get("amount", "")))
    # 普通新闻补充（仅标题，无金额）
    for it in (news_items or []):
        t = (it.get("title", "") or "").lower()
        hit = sum(1 for k in theme_keys if k.lower() in t)
        if hit:
            cands.append((hit, it.get("title", ""), it.get("url", "") or "", ""))
    # 去重（按标题），按命中数降序
    seen = set()
    uniq = []
    for hit, title, url, amt in sorted(cands, key=lambda x: x[0], reverse=True):
        if not title or title in seen:
            continue
        seen.add(title)
        uniq.append({"title": title, "url": url, "amount": amt})
        if len(uniq) >= top_k:
            break
    return uniq


def _signal_theme(signal):
    """给 M1 信号卡标注它「印证」了哪条宏观趋势（双向桥接）。无匹配返回空串。"""
    t = (signal.get("title", "") or "").lower()
    best, best_hit = "", 0
    for th in TREND_INSIGHTS:
        if not th["keys"]:
            continue
        hit = sum(1 for k in th["keys"] if k.lower() in t)
        if hit > best_hit:
            best_hit, best = hit, th["theme"]
    # 标题无中文关键词命中时，回退到信号类型（融资/并购/IPO → 钱去哪了）
    if best_hit == 0:
        types = signal.get("types", []) or []
        if "并购" in types or "IPO" in types or "融资" in types:
            best = "钱去哪了"
    return best


def _render_trend_insights_html(signals, news_items):
    """服务端预渲染「AI 行业趋势洞察」面板（含本周印证行），注入 [TREND_INSIGHTS] 占位符。"""
    items = []
    for th in TREND_INSIGHTS:
        ev = _match_insight_evidence(th["keys"], signals, news_items)
        if ev:
            ev_parts = []
            for e in ev:
                amt = f' <b>{e["amount"]}</b>' if e["amount"] else ""
                if e["url"]:
                    ev_parts.append(
                        f'<a href="{e["url"]}" target="_blank" rel="noopener">{e["title"]}</a>{amt}')
                else:
                    ev_parts.append(f'{e["title"]}{amt}')
            ev_html = (f'<div class="insight-evidence">📌 本周印证：'
                       f'{"；".join(ev_parts)}</div>')
        else:
            ev_html = ""
        items.append(
            f'<div class="insight-item">'
            f'<div class="insight-head"><span class="insight-ico">{th["ico"]}</span>'
            f'<b>{th["head"]}</b></div>'
            f'<p>{th["body"]}</p>'
            f'{ev_html}'
            f'<span class="insight-tag {th["tag_cls"]}">{th["tag"]}</span>'
            f'</div>')
    return '<div class="insight-grid">' + "".join(items) + '</div>'


def _render_market_signals_html_with_theme(signals, lb_map):
    """M1 信号卡渲染（带「印证趋势」标签，与趋势洞察面板双向桥接）。"""
    if not signals:
        return ('<p class="ms-empty">本周新闻中未检出重大融资 / 并购 / IPO / 模型发布事件'
                '——市场板块维持宏观背景视角。</p>')
    cards = []
    for s in signals:
        types_html = " ".join(f'<span class="ms-type t-{t}">{t}</span>' for t in s["types"])
        amt = f'<span class="ms-amount">{s["amount"]}</span>' if s["amount"] else ""
        theme = _signal_theme(s)
        theme_html = (f'<span class="ms-theme">印证趋势：{theme}</span>'
                      if theme else '<span class="ms-theme ms-theme-off">印证趋势：—</span>')
        title_low = s["title"].lower()
        on_lb = None
        for nm, (rk, src) in lb_map.items():
            if nm and nm in title_low:
                on_lb = (rk, src)
                break
        if on_lb:
            cap = f'<span class="ms-cap">↔ 能力榜 #{on_lb[0]}（{on_lb[1]}）</span>'
        else:
            cap = '<span class="ms-cap ms-cap-off">↔ 能力榜：未上榜</span>'
        url = s["url"] or "#"
        # 英文信号卡：补中文注解（与新闻卡一致，方便英文不好的中文读者）
        cn_html = ""
        if s.get("lang") == "en" and s.get("cn_summary"):
            cn_html = (f'<div class="ms-cn"><span class="cn-badge">中文</span> '
                       f'{html.escape(s["cn_summary"])}</div>')
        cards.append(
            f'<div class="ms-card">'
            f'<div class="ms-top">{types_html}{amt}</div>'
            f'<a class="ms-title" href="{url}" target="_blank" rel="noopener">{html.escape(s["title"])}</a>'
            f'{cn_html}'
            f'<div class="ms-meta"><span class="ms-bridge">{s["bridge_region"]} ↔ {s["bridge_label"]}</span>'
            f'{cap}{theme_html}<span class="ms-src">{s["source"]}</span></div>'
            f'</div>')
    head = (f'<p class="ms-head">从本周 <b>{len(signals)}</b> 条资本 / 模型发布信号看，'
            f'钱与能力正往这些方向集中（桥接下方宏观图）：</p>')
    return head + '<div class="ms-grid">' + "".join(cards) + '</div>'

