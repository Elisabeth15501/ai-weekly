"""L2#13：ai-weekly 纯函数单元测试（无需外网）。

覆盖：
  - leaderboard_sources._norm_model        （模型名归一）
  - leaderboard._leaderboard_freshness     （快照时效判定）
  - leaderboard._build_selection_notes     （三受众选型结论算法）
  - model_meta._apply_profile_as_truth     （资料卡权威覆盖 / 归一键匹配）
"""
import os
import sys

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
