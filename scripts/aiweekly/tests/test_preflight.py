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


# ---------- 缺必需检查项必须 fail（fail-open 回归）----------

def test_missing_checks_is_not_silent_pass():
    """doctor 只返回部分检查项时，**不得**静默判定为通过。

    这条守的是 fail-open：旧实现对缺键用 ``.get(...) or {}`` 兜底，
    ``status`` 取到 None，三条 if 全不进分支 -> evaluate 返回 [] -> exit 0。
    后果是 lark-cli 一旦升级改了字段名，预检就永远绿灯——比没有门禁更危险，
    因为它给出「已预检通过」的虚假安全感。
    """
    doctor = {"checks": [{"name": "identity_ready", "status": "pass",
                          "message": "identities: [pass]"}]}
    checks = preflight.collect_checks(doctor)
    problems = preflight.evaluate(checks)
    assert problems, "缺 bot_identity / app_resolved 却判定为通过（fail-open 回归）"
    # 文案要说清是「输出结构变了」而不是「用户没登录」，否则用户会去反复登录
    joined = " ".join(problems)
    assert "缺少必需检查项" in joined
    assert "lark-cli" in joined


def test_missing_checks_key_is_not_silent_pass():
    """doctor 输出连 ``checks`` 键都没有（结构变了）时同样必须 fail。"""
    problems = preflight.evaluate(preflight.collect_checks({}))
    assert problems, "doctor 无 checks 键却判定为通过（fail-open 回归）"
    assert "缺少必需检查项" in " ".join(problems)


def test_empty_checks_list_is_not_silent_pass():
    """``{"checks": []}`` 是最常见的结构漂移表现，必须 fail 而非通过。"""
    problems = preflight.evaluate(preflight.collect_checks({"checks": []}))
    assert problems, "空 checks 数组却判定为通过（fail-open 回归）"
    # 三个必需键全缺，应一次报全而不是只报一个
    assert len(problems) == 1
    assert "3/3" in problems[0]


def test_missing_app_resolved_is_not_silent_pass():
    """app_resolved 从未被验证 -> 不能算通过（它决定 app_id/secret 能否解析）。"""
    doctor = {"checks": [
        {"name": "identity_ready", "status": "pass", "message": "ok"},
        {"name": "bot_identity", "status": "pass", "message": "ok"},
    ]}
    problems = preflight.evaluate(preflight.collect_checks(doctor))
    assert problems
    assert "app" in " ".join(problems).lower()


def test_renamed_check_is_not_silent_pass():
    """上游把 bot_identity 改名（如 bot_identity_v2）时必须 fail，而非当通过。"""
    doctor = {"checks": [
        {"name": "identity_ready", "status": "pass", "message": "ok"},
        {"name": "bot_identity_v2", "status": "pass", "message": "ok"},
        {"name": "app_resolved", "status": "pass", "message": "ok"},
    ]}
    problems = preflight.evaluate(preflight.collect_checks(doctor))
    assert problems, "检查项被改名却判定为通过"
    assert "bot" in " ".join(problems).lower()


def test_missing_keys_exit_code_is_nonzero(monkeypatch):
    """端到端：缺键时 main() 的退出码必须非 0（真实风险在 exit code 上）。"""
    _patch_doctor(monkeypatch, {"checks": []})
    assert preflight.main([]) == 1, "缺检查项时 exit code 仍为 0"


def test_extra_unknown_checks_do_not_fail():
    """doctor 多返回无关检查项时不应误报（只对**缺**必需键 fail）。"""
    doctor = _doctor_json()
    doctor["checks"].append({"name": "cli_version", "status": "pass", "message": "1.0.97"})
    doctor["checks"].append({"name": "some_new_check", "status": "warn", "message": "x"})
    assert preflight.evaluate(preflight.collect_checks(doctor)) == []


def test_required_checks_constant_matches_labels():
    """_REQUIRED_CHECKS 与 _CHECK_LABELS 的键必须一致，避免两处漂移。"""
    assert set(preflight._REQUIRED_CHECKS) == set(preflight._CHECK_LABELS)


# ---------- --json 不得泄露本机绝对路径 ----------

def test_json_output_has_no_absolute_path(monkeypatch, capsys, tmp_path):
    """--json 的机器可读输出不得含本机绝对路径（会连同用户名粘进 issue / CI 日志）。

    这与 test_market_snapshot.py:71 守的「降级文案避免绝对路径泄进发布产物」
    是同一类问题：输出被粘到别处时，本机目录结构与用户名就跟着泄露了。
    """
    fake_home = tmp_path / "Users" / "someveryuniquename"
    cli = fake_home / ".workbuddy" / "binaries" / "node" / "cli-connector-packages" / "lark-cli.cmd"
    monkeypatch.setattr(preflight, "resolve_lark_cli", lambda: str(cli))
    _patch_doctor_only_doctor(monkeypatch, _doctor_json())

    preflight.main(["--json"])
    out = capsys.readouterr().out
    assert "someveryuniquename" not in out, "--json 输出泄露了本机用户名目录"
    assert str(tmp_path) not in out, "--json 输出泄露了本机绝对路径"
    # 但仍要保留足以定位的信息：文件名在
    payload = json.loads(out)
    assert payload["cli"] == "lark-cli.cmd"


def _patch_doctor_only_doctor(monkeypatch, payload):
    """只打桩 run_doctor 链路（resolve_lark_cli 由用例自己指定）。"""
    monkeypatch.setattr(
        preflight.subprocess, "run",
        lambda *a, **k: _FakeProc(json.dumps(payload)),
    )


def test_cli_missing_error_message_has_no_absolute_path(monkeypatch, capsys, tmp_path):
    """找不到 lark-cli 时，报错文案不得带含用户名的绝对路径。"""
    monkeypatch.setattr(preflight.shutil, "which", lambda _n: None)
    monkeypatch.setattr(preflight, "_CLI_DIR", tmp_path / "Users" / "someveryuniquename" / "cli")

    rc = preflight.main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "someveryuniquename" not in captured.err, "报错文案泄露了本机用户名目录"
    assert str(tmp_path) not in captured.err, "报错文案泄露了本机绝对路径"
    # 仍要给出可操作的定位线索
    assert "~/.workbuddy/binaries/node/cli-connector-packages" in captured.err


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


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows 专属行为：run_doctor 的 System32 补入逻辑在 `os.name == \"nt\"` "
           "分支内，Linux/macOS 上根本不执行，断言无意义",
)
def test_run_doctor_appends_system32_case_insensitively(monkeypatch):
    """回归：拼 System32 时大小写无关（仅 Windows）。

    沙箱/宿主可能是 ``SYSTEMROOT``（大写）。若按 ``SystemRoot`` 取值会拿到
    None，拼出 ``System32`` 这样的相对路径，反而把 PATH 弄坏。

    ⚠️ 这段逻辑在 ``preflight.py:109`` 的 ``os.name == "nt"`` 分支内，
    **非 Windows 平台不会执行**。本测试必须 skipif，否则 CI（Linux runner）
    会因 ``os.pathsep`` 是 ``:`` 而把 ``C:\\only`` 切成 ``['C', '\\\\only']`` 误报。
    这正是「本地 Windows 全绿 → CI Linux 挂」的典型模式。
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
