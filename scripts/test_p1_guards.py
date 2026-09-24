"""P1 新增守护与门禁的单元测试（无需外网）。

覆盖：
  - P1-4：check_xss_safe 覆盖属性逃逸（on*=）/ 正文裸 <script> / 危险协议 href
  - P1-1：compliance_check 的 BLOCKER / WARN 叙事 / INFO 白名单静音 /
          check_dep_pinning（依赖钉版）/ --learn 回灌闭环
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_checks.keywords import check_xss_safe  # noqa: E402
import compliance_check as CC  # noqa: E402
from compliance_check import scan_text, check_dep_pinning, learn, load_feedback  # noqa: E402


# ============ P1-4：XSS 守护 ============
def _html_with_news(payload: str) -> str:
    return (
        '<!doctype html><html><body>'
        '<script>const NEWS_DATA = [{"title": ' + json.dumps(payload) + '}];</script>'
        '</body></html>'
    )


def test_xss_benign_passes():
    # 良性：NEWS_DATA 里没有裸 <script / on*= / javascript: href
    html = _html_with_news("普通标题，无注入")
    res = check_xss_safe(html)
    assert res["ok"] is True, res["msg"]
    assert res["raw_breakout"] == []
    assert res["raw_event_handler"] == []
    assert res["danger_href"] == []


def test_xss_script_breakout_detected():
    # 正文裸 <script> 注入必须被捕获
    res = check_xss_safe(_html_with_news("<script>alert(1)</script>"))
    assert res["ok"] is False
    assert "NEWS_DATA" in res["raw_breakout"], res


def test_xss_event_handler_attribute_escape_detected():
    # 属性逃逸：数据里混进 on*= 事件处理器（对应 jsStrInAttr / escapeHtml 回归面）
    res = check_xss_safe(_html_with_news("点击 onclick=alert(1) 触发"))
    assert res["ok"] is False
    assert "NEWS_DATA" in res["raw_event_handler"], res


def test_xss_danger_href_detected():
    html = ('<html><body><a href="javascript:alert(1)">x</a>'
            '<script>const NEWS_DATA = [];</script></body></html>')
    res = check_xss_safe(html)
    assert res["ok"] is False
    assert any("javascript:" in h for h in res["danger_href"]), res


# ============ P1-1：合规门禁 ============
def test_gate_blocker_cjk():
    hits = scan_text("这是一段翻墙教程内容")
    levels = [h[0] for h in hits]
    assert "BLOCKER" in levels, hits


def test_gate_warn_narrative():
    hits = scan_text("我们解决了访问不了的问题，配置了代理即可恢复")
    levels = [h[0] for h in hits]
    assert "WARN" in levels, hits


def test_gate_info_muted_by_default_but_present():
    hits = scan_text("设置 HTTPS_PROXY 环境变量")
    info = [h for h in hits if h[0] == "INFO"]
    assert info, "INFO 命中应存在于 scan_text 结果中（由 main 层默认静音）"


def test_gate_whitelist_suppresses_known_false_positive():
    wl = [re.compile("HTTPS_PROXY", re.I)]
    hits = scan_text("设置 HTTPS_PROXY 环境变量", whitelist_res=wl)
    assert not any(h[0] == "INFO" for h in hits), "白名单应静音已知误报"


def test_gate_dep_pinning_unpinned_flagged(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "feedparser==6.0.13\nrequests\nbeautifulsoup4==4.15.0\n", encoding="utf-8")
    bad = check_dep_pinning(tmp_path)
    assert len(bad) == 1 and bad[0][1] == "requests", bad


def test_gate_dep_pinning_all_pinned_clean(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "feedparser==6.0.13\nrequests==2.34.2\n# comment\n", encoding="utf-8")
    assert check_dep_pinning(tmp_path) == []


def test_gate_learn_roundtrip(monkeypatch, tmp_path):
    fb_path = tmp_path / "gate_feedback.json"
    fb_path.write_text(json.dumps({"whitelist": [], "learned_blockers": []}), encoding="utf-8")
    monkeypatch.setattr(CC, "GATE_FEEDBACK_PATH", fb_path)
    learn({"type": "whitelist", "pattern": "企业内网出站", "reason": "文档已定位"})
    data = load_feedback()
    assert len(data["whitelist"]) == 1
    assert data["whitelist"][0]["pattern"] == "企业内网出站"
    # 回灌的 whitelist 应能静音对应命中
    wl = CC._feedback_res(data, "whitelist")
    hits = scan_text("本服务仅用于企业内网出站场景", whitelist_res=wl)
    assert not any(h[0] == "INFO" for h in hits), hits
