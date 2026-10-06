"""SEC-12：preflight.py 飞书凭据预检的单元测试（无需外网、无需真实 lark-cli）。

覆盖：
  - ``resolve_lark_cli`` 的 PATH 探测 + 显式回退（**核心回归点**）
  - ``evaluate`` 在 identity_ready / bot_identity / app_resolved 三种状态下的判定
  - ``run_doctor`` 对doctor JSON 的解析
  - ``main`` 的退出码：0（通过）/ 1（凭据不可用）

背景见scripts/preflight.py 模块 docstring。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# 让 pytest 能 import scripts/preflight.py 与 aiweekly 包（scripts/ 加入 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import preflight  # noqa: E402


# ---------- fixtures ----------

def _doctor_json(*, identity="pass", bot="pass", app="pass"):
    """构造一个doctor 风格的 JSON（三项状态可分别指定）。"""
    return {
        "checks": [
            {"name": "cli_version", "status": "pass", "message": "1.0.97"},
            {"name": "app_resolved", "status": app,
             "message": f"app: cli_test (feishu) [{app}]"},
            {"name": "bot_identity", "status": bot,
             "message": f"Bot identity: [{bot}]"},
            {"name": "identity_ready", "status": identity,
             "message": f"identities: [{identity}]"},
        ],
        "ok": True,
        "workspace": "local",
    }


class _FakeProc:
    """subprocess.run 的最小替身，只提供 preflight 会用到的属性。"""

    def __init__(self, stdout, stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ---------- resolve_lark_cli：核心回归点 ----------

def test_resolve_falls_back_when_which_returns_none(monkeypatch, tmp_path):
    """shutil.which 返回 None 时，仍必须通过显式回退路径找到 lark-cli。

    这是本次修复的核心回归点：该目录实测不在用户 PATH 里，
    PowerShell 下直接敲 lark-cli 会 command not recognized。
    """
    monkeypatch.setattr(preflight.shutil, "which", lambda _n: None)

    fake_dir = tmp_path / "cli-connector-packages"
    fake_dir.mkdir()
    suffix = ".cmd" if os.name == "nt" else ""
    fallback = fake_dir / f"lark-cli{suffix}"
    fallback.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(preflight, "_CLI_DIR", fake_dir)

    resolved = preflight.resolve_lark_cli()
    assert resolved == str(fallback)
    assert resolved is not None


def test_resolve_prefers_path_when_available(monkeypatch, tmp_path):
    """PATH 里能找到时优先用 PATH 里的，不走回退。

    回退目录指向一个不存在的路径：若实现仍去读它，结果就不会是 PATH 命中值。
    """
    monkeypatch.setattr(preflight.shutil, "which", lambda _n: "/usr/local/bin/lark-cli")
    monkeypatch.setattr(preflight, "_CLI_DIR", tmp_path / "no-such-dir")
    assert preflight.resolve_lark_cli() == "/usr/local/bin/lark-cli"


def test_resolve_returns_none_when_nothing_found(monkeypatch, tmp_path):
    """PATH 没有、回退文件也不存在时返回 None（由main 转成人话错误）。"""
    monkeypatch.setattr(preflight.shutil, "which", lambda _n: None)
    monkeypatch.setattr(preflight, "_CLI_DIR", tmp_path / "does-not-exist")
    assert preflight.resolve_lark_cli() is None


# ---------- run_doctor ----------

def test_run_doctor_parses_json(monkeypatch):
    """doctor 输出能被解析成 dict。"""
    payload = json.dumps(_doctor_json())
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *a, **k: _FakeProc(payload),
    )
    parsed, raw = preflight.run_doctor("lark-cli")
    assert parsed["ok"] is True
    assert "identity_ready" in raw


def test_run_doctor_raises_on_garbage(monkeypatch):
    """输出不是合法 JSON 时抛 PreflightError（供 CLI 打印人话提示）。"""
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *a, **k: _FakeProc("not json at all", stderr="some noise"),
    )
    with pytest.raises(preflight.PreflightError) as e:
        preflight.run_doctor("lark-cli")
    assert "JSON" in e.value.title


# ---------- evaluate：三种状态判定 ----------

def test_evaluate_all_pass_gives_no_problems():
    checks = preflight.collect_checks(_doctor_json())
    assert preflight.evaluate(checks) == []


def test_evaluate_identity_fail_flags_problem():
    """identity_ready=fail -> 有问题（推送必失败）。"""
    checks = preflight.collect_checks(_doctor_json(identity="fail"))
    problems = preflight.evaluate(checks)
    assert len(problems) == 1
    assert "身份未就绪" in problems[0]


def test_evaluate_bot_warn_mentions_20140():
    """bot_identity=warn -> 必须点名错误码 20140，这是最常见的失败形态。"""
    checks = preflight.collect_checks(_doctor_json(bot="warn"))
    problems = preflight.evaluate(checks)
    assert len(problems) == 1
    assert "20140" in problems[0]
    assert "推送会失败" in problems[0]


def test_evaluate_bot_fail_also_flagged():
    checks = preflight.collect_checks(_doctor_json(bot="fail"))
    problems = preflight.evaluate(checks)
    assert len(problems) == 1 and "20140" in problems[0]


def test_evaluate_app_fail_flagged():
    """app_resolved=fail -> app_id/app_secret 解析不出来。"""
    checks = preflight.collect_checks(_doctor_json(app="fail"))
    problems = preflight.evaluate(checks)
    assert len(problems) == 1
    assert "凭据无法解析" in problems[0]


def test_evaluate_multiple_problems_all_reported():
    """多项同时不通时全部列出，不只报第一条。"""
    checks = preflight.collect_checks(
        _doctor_json(identity="fail", bot="fail", app="fail")
    )
    assert len(preflight.evaluate(checks)) == 3


# ---------- main 退出码 ----------

def _patch_doctor(monkeypatch, payload):
    """把 main 的两条前置依赖都打桩：cli 解析成功 + doctor 返回给定JSON。"""
    monkeypatch.setattr(preflight, "resolve_lark_cli", lambda: "lark-cli")
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *a, **k: _FakeProc(json.dumps(payload)),
    )


def test_main_exit_0_when_healthy(monkeypatch, capsys):
    _patch_doctor(monkeypatch, _doctor_json())
    assert preflight.main([]) == 0
    assert "预检通过" in capsys.readouterr().out


def test_main_exit_1_when_bot_identity_warn(monkeypatch, capsys):
    """bot 凭据 warn 时退出码必须非0，且 stderr 提到 20140。"""
    _patch_doctor(monkeypatch, _doctor_json(bot="warn"))
    assert preflight.main([]) == 1
    assert "20140" in capsys.readouterr().err


def test_main_exit_1_when_cli_missing(monkeypatch):
    """找不到 lark-cli 时退出码非0，而不是抛裸traceback。"""
    monkeypatch.setattr(preflight, "resolve_lark_cli", lambda: None)
    assert preflight.main([]) == 1


def test_main_quiet_silent_on_success(monkeypatch, capsys):
    """--quiet 且成功时 stdout 静默。"""
    _patch_doctor(monkeypatch, _doctor_json())
    assert preflight.main(["--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_main_json_outputs_machine_readable(monkeypatch, capsys):
    """--json 输出可被 json.loads 解析，且 ok 字段与退出码一致。"""
    _patch_doctor(monkeypatch, _doctor_json(bot="warn"))
    rc = preflight.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["exit_code"] == rc == 1
    assert payload["bot_identity"] == "warn"

def test_run_doctor_passes_env_to_subprocess(monkeypatch):
    """回归：run_doctor 必须显式传 env。

    背景——.cmd 是批处理，要靠 PATH 找 node.exe。若不传 env，父进程 PATH 为空时
    子进程什么都不输出，preflight 会在「本该由它发现的场景」里自己先崩掉。
    """
    captured = {}

    class _Proc:
        stdout = '{"checks": []}'
        stderr = ""
        returncode = 0

    def _fake_run(cmd, **kw):
        captured.update(kw)
        return _Proc()

    monkeypatch.setattr(preflight.subprocess, "run", _fake_run)
    preflight.run_doctor("dummy-lark-cli")
    assert "env" in captured, "subprocess.run 未传 env，PATH 回退场景会失效"
    assert isinstance(captured["env"], dict)
    assert "PATH" in captured["env"] or "Path" in captured["env"]


def test_run_doctor_env_preserves_windows_vars(monkeypatch):
    """传 env 时不能把 Windows 关键变量弄丢（变量名大小写不敏感）。

    背景：Windows 环境变量不区分大小写，不同 shell / 沙箱里同一个变量可能
    呈现为 ``SystemRoot`` 或 ``SYSTEMROOT``。preflight 补 System32 时必须
    大小写无关地取值，否则会拼出空路径。
    """
    captured = {}

    class _Proc:
        stdout = '{"checks": []}'
        stderr = ""
        returncode = 0

    monkeypatch.setattr(preflight.subprocess, "run",
                        lambda cmd, **kw: (captured.update(kw), _Proc())[1])
    preflight.run_doctor("dummy")
    env = captured["env"]
    # 子进程 env 必须是父环境的完整副本（逐键比较，不区分大小写地挑几个关键的）
    upper = {k.upper(): v for k, v in env.items()}
    for key in ("WINDIR", "SYSTEMROOT", "COMSPEC", "TEMP"):
        if key in os.environ:
            assert key in upper, f"{key} 在传入子进程的 env 里丢失了"
    # 且必须是副本而非同一对象，避免污染父进程
    assert env is not os.environ


def test_run_doctor_appends_system32_case_insensitively(monkeypatch):
    """回归：拼 System32 时大小写无关。

    沙箱/宿主可能是 ``SYSTEMROOT``（大写）。若按 ``SystemRoot`` 取值会拿到
    None，拼出 ``System32`` 这样的相对路径，反而把 PATH 弄坏。
    """
    captured = {}

    class _Proc:
        stdout = '{"checks": []}'
        stderr = ""
        returncode = 0

    monkeypatch.setattr(preflight.subprocess, "run",
                        lambda cmd, **kw: (captured.update(kw), _Proc())[1])
    monkeypatch.setattr(preflight.os, "environ",
                        {"SYSTEMROOT": r"C:\WINDOWS", "PATH": r"C:\only"})
    preflight.run_doctor("dummy")
    parts = captured["env"]["PATH"].split(os.pathsep)
    assert any(p.lower() == os.path.join("c:\\windows", "system32").lower() for p in parts), \
        f"System32 未被正确补入，实际 PATH 段：{parts}"
    # 不能出现裸的 "System32"（说明 Windows 根目录取空了）
    assert not any(p == "System32" for p in parts), "Windows 根目录取空，拼出了相对路径"
