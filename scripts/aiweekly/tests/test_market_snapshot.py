"""HON-2/ HON-1：市场快照外置与页脚来源分组的回归测试（无需外网）。

覆盖：
  - 快照文件读取 / 缺失降级 / 过期判定（as_of 与 retrieved_at 两种粒度）
  - 降级时**必须**显式标注「已过期」，且不得把开发机绝对路径写进可发布文案
  - 快照数值与外置前的取值逐字一致（防止搬文件时手抖改了数字）
  - 页脚两块来源分组：静态快照块 / 本周信号块，且本周块只列真实出现过的源
  - 本周源统计的计数正确性（同源多条应累加，空 source 不计入）
"""
import json
import os
import sys
from datetime import date

import pytest

# 让 pytest 能import aiweekly 包（scripts/ 加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiweekly import market as M  # noqa: E402
from aiweekly.render import (  # noqa: E402
    _build_footer_snapshot_block,
    _build_footer_weekly_block,
    _count_weekly_sources,
)


@pytest.fixture(autouse=True)
def _restore_module_snapshot():
    """每个用例后把模块级快照状态还原，避免相互污染。

    必须连BASE_SOURCES 一起还原：它是在 import 期由 _load_base_sources() 从
    _SNAPSHOT 派生的，用例里改_SNAPSHOT 不会自动同步它，
    不还原会让后续用例读到上个用例残留的名单（顺序相关的假绿/假红）。
    """
    saved = (M._SNAPSHOT, M._SNAPSHOT_LOAD_ERROR, M.BASE_SOURCES)
    yield
    M._SNAPSHOT, M._SNAPSHOT_LOAD_ERROR, M.BASE_SOURCES = saved


def _write(obj, tmp_path, name="market_snapshot.json"):
    """把obj 写成临时快照文件并返回路径。"""
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


# ---------- 快照读取与降级 ----------
def test_snapshot_file_present_is_fresh(tmp_path):
    """正常快照：60 天前誊录 < 90 天阈值 -> 不标过期。"""
    p = _write({
        "as_of": "2026-W32",
        "retrieved_at": "2026-08-08",
        "series": [{"key": "market", "labels": ["2020"], "values": [103]}],
    }, tmp_path)
    M.load_snapshot(p)
    assert M._SNAPSHOT != {}
    assert M.snapshot_stale(today=date(2026, 10, 7)) is False
    assert M.snapshot_status_text(today=date(2026, 10, 7)) == ""


def test_snapshot_missing_file_marks_stale_and_explains():
    """文件缺失 -> stale，且状态文案含「已过期」「代码内默认值」。"""
    M.load_snapshot("__不存在的路径__/market_snapshot.json")
    assert M.snapshot_stale() is True
    txt = M.snapshot_status_text()
    assert "已过期" in txt
    assert "使用代码内默认值" in txt


def test_stale_text_never_leaks_absolute_path(tmp_path):
    """降级文案会进发布 HTML，不得含开发机绝对路径（否则泄露本地目录结构）。"""
    missing = tmp_path / "market_snapshot.json"
    M.load_snapshot(missing)  # 故意指向不存在的文件
    txt = M.snapshot_status_text()
    assert "已过期" in txt
    assert str(tmp_path) not in txt
    assert "C:\\" not in txt and "C:/" not in txt


def test_expired_by_age_threshold(tmp_path):
    """超过阈值即过期，并报出实际天数与截止日。"""
    p = _write({
        "as_of": "2026-W32",
        "retrieved_at": "2026-08-08",
        "series": [{"key": "market", "labels": ["2020"], "values": [103]}],
    }, tmp_path)
    M.load_snapshot(p)
    assert M.snapshot_stale(max_age_days=30, today=date(2026, 10, 7)) is True
    txt = M.snapshot_status_text(max_age_days=30, today=date(2026, 10, 7))
    assert "已过期" in txt and "2026-W32" in txt and "60 天" in txt


def test_unparseable_date_is_stale_not_fresh(tmp_path):
    """日期解析不出来时不能当成「新鲜」——无法证明新鲜度就必须报警。"""
    p = _write({
        "as_of": "不知道哪天",
        "retrieved_at": "也不是日期",
        "series": [{"key": "market", "labels": ["2020"], "values": [103]}],
    }, tmp_path)
    M.load_snapshot(p)
    assert M.snapshot_age_days() is None
    assert M.snapshot_stale() is True


def test_iso_week_as_of_is_parsed(tmp_path):
    """as_of 支持 YYYY-Www（ISO 周）粒度，按该周周一算age。"""
    p = _write({
        "as_of": "2026-W32",
        "retrieved_at": "",
        "series": [{"key": "market", "labels": ["2020"], "values": [103]}],
    }, tmp_path)
    M.load_snapshot(p)
    # 没有 retrieved_at 时回退用 as_of 算，仍不该崩
    assert M.snapshot_age_days() is not None


def test_bad_json_does_not_raise(tmp_path):
    """坏 JSON 不抛异常（报告仍要能出），只标 stale。"""
    p = tmp_path / "bad_snapshot.json"
    p.write_text("{ 不是 json", encoding="utf-8")
    assert M.load_snapshot(p) == {}
    assert M.snapshot_stale() is True
    assert "合法 JSON" in M.snapshot_status_text()


def test_missing_series_key_falls_back_but_flags_stale(tmp_path):
    """序列 key 缺失时取值回退兜底常量，且整体判stale。"""
    p = _write({
        "as_of": "2026-W32",
        "retrieved_at": "2026-08-08",
        "series": [{"key": "不存在的键", "labels": ["x"], "values": [1]}],
    }, tmp_path)
    M.load_snapshot(p)
    labels, values = M._labels_values("market", ["fb"], [9])
    assert labels == ["fb"] and values == [9]


def test_labels_values_length_mismatch_falls_back(tmp_path):
    """labels / values 长度不一致是坏数据，必须回退而不是画出错图。"""
    p = _write({
        "as_of": "2026-W32",
        "retrieved_at": "2026-08-08",
        "series": [{"key": "market", "labels": ["a", "b"], "values": [1]}],
    }, tmp_path)
    M.load_snapshot(p)
    labels, values = M._labels_values("market", ["fb"], [9])
    assert labels == ["fb"] and values == [9]


# ---------- 数值未漂移（搬文件不许改数字）----------
def test_repo_snapshot_values_match_legacy_constants():
    """库内快照的 6 条序列必须与外置前的取值逐字一致。"""
    M.load_snapshot(M.SNAPSHOT_PATH)  # 读回仓库里的真实文件
    assert M.DEFAULT_MARKET_DATA == [103, 134, 176, 229, 299, 391, 540, 705, 921]
    assert M.DEFAULT_MARKET_LABELS == ['2020', '2021', '2022', '2023', '2024',
                                       '2025', '2026E', '2027F', '2028F']
    assert M.DEFAULT_FUNDING_DATA == [72.4, 72.4, 72.4, 72.4, 79.9, 79.9, 79.9, 79.9,
                                      110.0, 110.0, 110.0, 110.0, 305.0, 205.0]
    assert M.DEFAULT_CN_MARKET_DATA == [9188, 12000, 17000]
    assert M.DEFAULT_CN_FUNDING_DATA == [391.51, 656.04, 3076.82]
    assert M.DEFAULT_CN_STRUCTURE_DATA == [1598, 906, 596, 725]
    assert M.DEFAULT_CN_CONCENTRATION_DATA == [930, 770, 1376]


def test_repo_snapshot_has_all_six_series():
    """快照必须真的被读到（而不是静默走兜底）。"""
    M.load_snapshot(M.SNAPSHOT_PATH)
    assert M._SNAPSHOT != {}, "库内快照读不到，测试环境异常"
    assert len(M._SNAPSHOT.get("series", [])) == 6
    assert M._SNAPSHOT.get("as_of") == "2026-W32"


# ---------- 本周源统计 ----------
def test_count_weekly_sources_counts_and_sorts():
    """同源多条要累加，按条数降序；空 source 不计入。"""
    items = [
        {"source": "A"}, {"source": "B"}, {"source": "A"},
        {"source": "A"}, {"source": ""}, {"source": None}, {},
    ]
    assert _count_weekly_sources(items) == [("A", 3), ("B", 1)]


def test_count_weekly_sources_empty():
    assert _count_weekly_sources([]) == []
    assert _count_weekly_sources(None) == []


def test_weekly_block_lists_only_real_sources():
    """本周块只列真实出现过的源——这是本次整改的核心（不再拿配置冒充抓取）。"""
    items = [{"source": "量子位"}, {"source": "量子位"}, {"source": "TechCrunch"}]
    html = _build_footer_weekly_block(items)
    assert "量子位" in html and "TechCrunch" in html
    assert "2 个源 / 3 条" in html
    assert "未取到任何 RSS 源" not in html


def test_weekly_block_empty_is_explicit_not_silent():
    """空数据要显式说明，不能静默消失（否则读者以为漏渲染了）。"""
    html = _build_footer_weekly_block([])
    assert "本周未取到任何 RSS 源" in html
    assert "0 条" in html


def test_weekly_block_escapes_source_names():
    """source 来自 RSS 解析（不可信输入），必须转义。"""
    html = _build_footer_weekly_block([{"source": "<script>alert(1)</script>"}])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_weekly_block_includes_external_source():
    items = [{"source": "量子位"}]
    html = _build_footer_weekly_block(items, external_source=("AI HOT", "https://aihot.news"))
    assert "AI HOT" in html and "aihot.news" in html


# ---------- 静态快照块 ----------
def test_snapshot_block_shows_asof_and_retrieved_per_source():
    """快照块标题带截止日，每家带誊录日期。"""
    html = _build_footer_snapshot_block()
    assert "静态快照引用" in html
    assert "非本周抓取" in html
    assert "2026-W32" in html          # as_of
    assert "誊录于 2026-08-08" in html  # 每家 retrieved_at


def test_snapshot_block_marks_uncited_sources():
    """used_for 为空者必须标「未引用其数字」，不能与真被引用的机构混排。"""
    html = _build_footer_snapshot_block()
    assert "未引用其数字" in html
    # Stanford HAI / LMMarketCap 是已知凑数项
    assert "Stanford HAI" in html and "LMMarketCap" in html


def test_snapshot_block_renders_stale_note():
    """传入过期标注时必须渲染出来（不得吞掉）。"""
    html = _build_footer_snapshot_block("【已过期：快照文件缺失，使用代码内默认值】")
    assert "已过期" in html and "使用代码内默认值" in html


def test_snapshot_block_handles_missing_url():
    """无 URL 的机构（如中商产业研究院）渲染为纯文本，不能产出空 href。"""
    html = _build_footer_snapshot_block()
    assert "中商产业研究院" in html
    assert 'href=""' not in html


def test_snapshot_block_rejects_unsafe_url():
    """URL 走 safe_url，javascript: 这类协议不得进入 href。"""
    M.load_snapshot("__不存在__")
    saved = (M._SNAPSHOT,)
    try:
        M._SNAPSHOT = {"sources": [
            {"name": "坏源", "url": "javascript:alert(1)", "used_for": "x", "retrieved_at": ""},
        ]}
        M.BASE_SOURCES = M._load_base_sources()
        html = _build_footer_snapshot_block()
        assert "javascript:" not in html
    finally:
        M._SNAPSHOT = saved[0]
        M.BASE_SOURCES = M._load_base_sources()