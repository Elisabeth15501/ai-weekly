"""L2#13：ai-weekly 纯函数单元测试（无需外网）。

覆盖：
  - leaderboard_sources._norm_model        （模型名归一）
  - leaderboard._leaderboard_freshness     （快照时效判定）
  - leaderboard._build_selection_notes     （三受众选型结论算法）
  - model_meta._apply_profile_as_truth     （资料卡权威覆盖 / 归一键匹配）
  - 输出转义不变量                          （外部可控字段进 HTML 前必须按上下文转义）
"""
import os
import sys
import time

import pytest

# 让 pytest 能 import aiweekly 包（scripts/ 加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiweekly.leaderboard_sources import _norm_model  # noqa: E402
from aiweekly.leaderboard import (  # noqa: E402
    _leaderboard_freshness,
    _build_selection_notes,
    canon_key,
)
from aiweekly.model_meta import _apply_profile_as_truth  # noqa: E402
from aiweekly import insights as INS  # noqa: E402
from aiweekly import leaderboard_fetch as LB  # noqa: E402


# ---------- _norm_model ----------
def test_norm_model_empty():
    assert _norm_model("") == ""
    assert _norm_model(None) == ""


def test_norm_model_format_invariance():
    # 同一模型的不同写法应归一为同一字符串（大小写/空格/连字符/括号）
    a = _norm_model("DeepSeek V4 Pro")
    b = _norm_model("deepseek-v4-pro")
    c = _norm_model("DeepSeek-V4-Pro")
    d = _norm_model("DEEPSEEK V4 PRO")
    assert a == b == c == d


def test_norm_model_strips_variant_suffix():
    # "(max)/(high)" 等变体后缀应被剥离，变体双胞胎归一一致
    assert _norm_model("GPT-5.4 (high)") == _norm_model("GPT-5.4")


# ---------- _leaderboard_freshness ----------
def _lb_with_snapshots(lm, aa, ls, hf):
    return {
        "comprehensive": {
            "lmarena": {"snapshot": lm},
            "aa": {"snapshot": aa},
        },
        "open_source": {
            "ls": {"snapshot": ls},
            "hf": {"snapshot": hf},
        },
    }


def test_freshness_stale_detected():
    lb = _lb_with_snapshots("2026-08-01", "2026-08-10", "2026-08-09", "2026-07-20")
    res = _leaderboard_freshness(lb, "2026-08-11")
    assert res["stale"] is True
    assert res["max_age"] == 22
    assert res["worst_source"] == "open_source.hf"
    assert res["worst_age"] == 22


def test_freshness_all_fresh():
    lb = _lb_with_snapshots("2026-08-11", "2026-08-11", "2026-08-11", "2026-08-11")
    res = _leaderboard_freshness(lb, "2026-08-11")
    assert res["stale"] is False
    assert res["max_age"] == 0


def test_freshness_missing_snapshot_is_none():
    lb = {"comprehensive": {"lmarena": {}, "aa": {}},
          "open_source": {"ls": {}, "hf": {}}}
    res = _leaderboard_freshness(lb, "2026-08-11")
    assert res["per_source"]["comprehensive.lmarena"] is None
    assert res["per_source_age"]["comprehensive.lmarena"] is None


# ---------- _build_selection_notes ----------
def test_selection_notes_no_cheap():
    note, notes = _build_selection_notes("GPT-5.6", None, [], [])
    assert "GPT-5.6" in notes["开发者"]
    assert "GPT-5.6" in notes["PM"]
    assert "GPT-5.6" in notes["自媒体"]
    assert "本期源数据缺失" not in note


def test_selection_notes_with_cheap():
    cheap = {"model": "Qwen3.6-Max", "price_out": 1.2}
    note, notes = _build_selection_notes("GPT-5.6", cheap, [], [])
    assert "Qwen3.6-Max" in notes["开发者"]
    assert "1.2" in notes["开发者"]


def test_selection_notes_risers_and_new():
    cheap = None
    note, notes = _build_selection_notes(
        "GPT-5.6", cheap, new_entries=["ModelA", "ModelB"], risers=["ModelC"])
    assert "ModelC" in notes["PM"]
    assert "ModelA" in notes["自媒体"]
    assert "ModelC" in notes["自媒体"]


def test_selection_notes_no_top():
    note, notes = _build_selection_notes(None, None, [], [])
    assert "本期源数据缺失" in note


# ---------- _apply_profile_as_truth（归一键匹配 Bug B 回归）----------
def _make_profiles():
    return {
        "DeepSeek-V4-Pro": {
            "org": "DeepSeek", "license": "MIT", "commercial": "可商用",
            "cost_in": 0.435, "cost_out": 0.87, "context": 1000000,
            "multimodal": "文本", "currency": "USD",
        },
        "Kimi K3 (max)": {
            "org": "Moonshot", "license": "Modified MIT", "commercial": "可商用",
            "cost_in": 3.0, "cost_out": 15.0, "context": 1000000,
            "multimodal": "文本+视觉", "currency": "USD",
        },
    }


def test_apply_profile_matches_canonical_key():
    profiles = _make_profiles()
    lb = {"comprehensive": {"lmarena": {"rows": [
        {"model": "DeepSeek V4 Pro", "rank": 1, "org": "?", "license": None,
         "price_out": None, "context": None},
    ]}}, "open_source": {"ls": {"rows": []}}}
    _apply_profile_as_truth(lb, profiles)
    r = lb["comprehensive"]["lmarena"]["rows"][0]
    # _MAP 覆盖的字段：license / cost / context 应被档案回填
    assert r["license"] == "MIT"
    assert r["price_out"] == 0.87
    assert r["context"] == 1000000
    # org 不在 _MAP 覆盖内（由排行榜抓取或 modal 的 profile 对象提供），行原值保留、不被清成 None
    assert r["org"] == "?"


def test_apply_profile_matches_variant_key():
    # 榜单名 "Kimi K3"（无 max）应命中档案键 "Kimi K3 (max)"（归一键匹配）
    profiles = _make_profiles()
    lb = {"comprehensive": {"lmarena": {"rows": [
        {"model": "Kimi K3", "rank": 2, "org": "?", "license": None,
         "price_out": None, "context": None},
    ]}}, "open_source": {"ls": {"rows": []}}}
    _apply_profile_as_truth(lb, profiles)
    r = lb["comprehensive"]["lmarena"]["rows"][0]
    assert r["license"] == "Modified MIT"
    assert r["price_out"] == 15.0
    assert r["context"] == 1000000


def test_apply_profile_no_match_leaves_row():
    profiles = _make_profiles()
    lb = {"comprehensive": {"lmarena": {"rows": [
        {"model": "Brand New Model X", "rank": 3, "org": "ACME",
         "license": "Apache 2.0", "price_out": 2.0, "context": 8000},
    ]}}, "open_source": {"ls": {"rows": []}}}
    _apply_profile_as_truth(lb, profiles)
    r = lb["comprehensive"]["lmarena"]["rows"][0]
    # 未命中档案：保留榜单原值，不被覆盖为 None
    assert r["org"] == "ACME"
    assert r["price_out"] == 2.0


# ---------- canon_key（R5：后缀感知归一，避免 Base/Base-Suffix 撞键）----------
def test_canon_key_suffix_distinguishes_aliased():
    # 已知别名族：GLM-5.3 与 GLM-5.3-Flash 必须不同键
    assert canon_key("GLM-5.3") != canon_key("GLM-5.3-Flash")


def test_canon_key_suffix_distinguishes_unaliased():
    # 无别名时，后缀感知逻辑区分 Base 与 Base-Suffix（不靠手改别名）
    assert canon_key("ZetaModel") != canon_key("ZetaModel-Turbo")
    assert canon_key("ZetaModel") != canon_key("ZetaModel-Preview")


def test_canon_key_suffix_token_appended():
    # 未命中别名：后缀以 ~<token> 形式保留在归一键上
    assert canon_key("ZetaModel-Turbo").endswith("~turbo")
    assert canon_key("ZetaModel-Preview").endswith("~preview")


def test_canon_key_variant_normalization_still_merges():
    # 纯变体写法（大小写/空格/连字符）仍应归一合并
    assert canon_key("GLM-5.3") == canon_key("GLM 5.3")
    assert canon_key("GLM-5.3") == canon_key("glm-5.3")


# ---------- _apply_priority_alias（S1：优先别名保送，可读性 + 可测）----------
def test_apply_priority_alias_promotes_outside_top_n(monkeypatch):
    # 保送词未进 top_n 时应强制挤进列表（末位替换保底）
    monkeypatch.setattr(INS, "_PRIORITY_ALIASES", {"保送词"})
    cands = {"A": 9, "B": 8, "C": 7, "保送词": 2}
    ranked = [("A", 9), ("B", 8), ("C", 7)]  # top_n=3，保送词被词频挤出
    out = INS._apply_priority_alias(ranked, cands, 3)
    assert len(out) == 3
    assert out[-1][0] == "保送词"


def test_apply_priority_alias_no_duplicate_when_already_present(monkeypatch):
    # 已入选的保送词不应被重复插入
    monkeypatch.setattr(INS, "_PRIORITY_ALIASES", {"保送词"})
    cands = {"A": 9, "保送词": 5}
    ranked = [("A", 9), ("保送词", 5), ("C", 3)]
    out = INS._apply_priority_alias(ranked, cands, 3)
    assert len(out) == 3
    assert sum(1 for t, _ in out if t == "保送词") == 1


def test_apply_priority_alias_absent_from_cands_not_inserted(monkeypatch):
    # 本周新闻未出现的保送词不应被硬塞进列表
    monkeypatch.setattr(INS, "_PRIORITY_ALIASES", {"保送词"})
    cands = {"A": 9, "B": 8}
    ranked = [("A", 9), ("B", 8)]
    out = INS._apply_priority_alias(ranked, cands, 3)
    assert out == [("A", 9), ("B", 8)]


# ---------- _collect_source_results（S2：并发 + 整体截止，避免慢源拖垮）----------
def test_collect_source_results_bounded_deadline(monkeypatch):
    # 快源正常返回、慢源（远超整体上限）必须被标记 timeout 且函数快速返回，
    # 证明「一个慢源拖垮整份周报生成」已被硬上限切断。
    def fast(n):
        return [{"model": "x", "rank": 1}]
    def slow(n):
        time.sleep(5)
        return [{"model": "y", "rank": 1}]

    fake = {
        "fast": {"region": "global", "board": "comprehensive", "key": "fast",
                 "fn": fast, "label": "Fast", "url": "http://x", "criteria": ("", "")},
        "slow": {"region": "global", "board": "comprehensive", "key": "slow",
                 "fn": slow, "label": "Slow", "url": "http://y", "criteria": ("", "")},
    }
    monkeypatch.setattr(LB, "SOURCES", fake)
    monkeypatch.setattr(LB, "OVERALL_FETCH_CAP_S", 1)
    t0 = time.monotonic()
    res = LB._collect_source_results(15, "global", None)
    dt = time.monotonic() - t0
    assert dt < 3.0, f"应在整体上限内返回，实际耗时 {dt:.1f}s"
    assert res["fast"]["rows"], "快源应有数据"
    assert res["slow"]["status"] == "timeout", res["slow"]
    # 单源失败隔离：慢源超时不应污染快源结果
    assert res["fast"]["status"] == "ok"


# ========== 输出转义（XSS 防护 · 回归守护）==========
# 守护的不变量：**来自 RSS / CLI 的外部可控字段，进入 HTML 前必须按上下文转义。**
# 背景（均为真实历史缺陷）：
#   - market.py 三处 href/title 直接插值（字段来自 RSS）
#   - render.py 的 KEYWORD_SEARCH_SOURCES 曾是 <script> 内的裸 JSON 注入点
#   - insights.py 的 onclick 曾只用 html.escape 处理「属性内的 JS 字符串」（无效）
from aiweekly import market as MKT  # noqa: E402
from aiweekly.utils import js_str_in_attr, safe_href, safe_url  # noqa: E402

PAYLOAD_TAG = "<img src=x onerror=alert(1)>"
PAYLOAD_JS = "javascript:alert(1)"


def test_safe_url_scheme_whitelist():
    assert safe_url("https://a.example/x") == "https://a.example/x"
    assert safe_url("http://a.example") == "http://a.example"
    assert safe_url("mailto:a@b.com") == "mailto:a@b.com"
    for bad in (PAYLOAD_JS, "JavaScript:alert(1)", " javascript:alert(1)",
                "data:text/html,x", "vbscript:msgbox(1)", "//evil.example", "", None):
        assert safe_url(bad) == "#", bad


def test_safe_href_escapes_attribute_context():
    assert safe_href("https://ok.example/a?x=1&y=2") == "https://ok.example/a?x=1&amp;y=2"
    assert '"' not in safe_href('https://ok.example/a?q="x"')


def test_js_str_in_attr_two_layer_escaping():
    out = js_str_in_attr("x');alert(1);//")
    assert "');alert" not in out, out        # 裸 ' 不得残留，否则闭合 JS 字符串
    assert "\\&#x27;" in out, out            # JS 层 \  +  HTML 层 &#x27;，两层都在
    assert '"' not in js_str_in_attr('a"b')
    assert js_str_in_attr("") == ""


def _signal(**over):
    s = {"title": PAYLOAD_TAG, "url": PAYLOAD_JS, "types": ["融资"], "amount": "$1B",
         "bridge_region": "全球", "bridge_label": "中国", "source": "S",
         "lang": "en", "cn_summary": PAYLOAD_TAG, "keys": []}
    s.update(over)
    return s


def test_market_signals_html_escapes_text_and_href():
    html = MKT._render_market_signals_html([_signal()], {})
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert 'href="#"' in html
    assert PAYLOAD_JS not in html


def test_market_signals_with_theme_escapes_cn_summary_and_href():
    html = MKT._render_market_signals_html_with_theme([_signal()], {})
    assert "<img src=x" not in html and "&lt;img" in html
    assert 'href="#"' in html


def test_market_trend_insights_evidence_escaped():
    # 主题词须出现在标题里，_match_insight_evidence 才会抽出「本周印证」行
    html = MKT._render_trend_insights_html([_signal(title="融资 " + PAYLOAD_TAG)], [])
    assert 'class="insight-evidence"' in html     # 非空断言：确保真的走到拼接分支
    assert "<img src=x" not in html
    assert 'href="#"' in html


def test_market_e_handles_none_without_crashing():
    assert MKT._e(None) == ""
    assert MKT._e(None, quote=True) == ""
    assert '"' not in MKT._e('a"b', quote=True)


def test_market_static_body_keeps_intentional_markup():
    # TREND_INSIGHTS.body 是开发者静态常量且含故意的 <b>，不得被过度转义
    html = MKT._render_trend_insights_html([], [])
    assert "&lt;b&gt;" not in html
    assert "<b>" in html


def test_insights_keyword_chips_rejects_javascript_base():
    html = INS._render_keyword_chips_html([{"term": "测试词"}],
                                          search_sources={"baidu": PAYLOAD_JS})
    import re as _re
    assert _re.findall(r'class="kw-chip" href="([^"]*)"', html) == ["#"]


def test_insights_keyword_chips_keeps_legit_base():
    html = INS._render_keyword_chips_html(
        [{"term": "测试词"}], search_sources={"baidu": "https://www.baidu.com/s?wd="})
    assert 'href="https://www.baidu.com/s?wd=' in html


def test_insights_audience_chip_onclick_two_layer():
    html = INS._render_audience_chips_html({"开发者": {}, "x');alert(1);//": {}})
    assert "');alert(1)" not in html
    assert "\\&#x27;" in html


def test_json_text_script_safe_blocks_breakout_and_keeps_format():
    from aiweekly.render import _json_text_script_safe
    out = _json_text_script_safe('{"a": "</script><img src=x>"}')
    assert "</script>" not in out
    assert "\\u003c/script\\u003e" in out
    # 格式保留：已是 JSON 文本时不得重排（紧凑分隔符须原样保留）
    assert _json_text_script_safe('{"a":"b"}') == '{"a":"b"}'
