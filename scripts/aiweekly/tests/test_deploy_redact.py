"""deploy 凭据脱敏回归测试（T09 remediation #5）。

用**假 sentinel token** 跑 vercel / netlify / cloudflare 三条 provider 路径，
断言 sentinel 不出现在四条出口：stdout（verbose 命令行）、stderr、异常文本、
dry-run 渲染命令。

设计要点：
  - ``subprocess.run`` 全部 monkeypatch 掉，绝不真调 npx（测试须离线可跑）。
  - 假 ``run`` 会把 token 故意回显进stderr，模拟真实 CLI 的「下游回显」，
    以此证明``_redact`` 的字面量兜底防线真的生效，而不只是打码了 flag 名。
  - 除四条断言外，另有一条「argv 不含 token」的自证（这是 T09 的根因本身）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import deploy as deploy_mod  # noqa: E402

SENTINEL = "SENTINEL_A1B2C3_SECRET_DO_NOT_LEAK"


@pytest.fixture(autouse=True)
def _clean_secret_registry():
    """每个用例前后清空字面量登记表，避免用例间互相污染。"""
    deploy_mod._SECRET_VALUES.clear()
    yield
    deploy_mod._SECRET_VALUES.clear()


@pytest.fixture
def html(tmp_path) -> Path:
    p = tmp_path / "AI_News_2026-10-06.html"
    p.write_text("<html><body>周报</body></html>", encoding="utf-8")
    return p


@pytest.fixture
def fake_run(monkeypatch):
    """替换 subprocess.run：记录 argv/env，绝不执行真实 npx。

    故意把子进程环境里的 token 回显进 stderr——模拟真实 CLI 认证失败时把凭据
    打回终端的行为，以此验证 ``_redact`` 的字面量兜底防线确实生效。
    退出码恒为 0（成功路径），失败路径由专门的异常用例覆盖。
    """
    calls: list[dict] = []

    def _run(cmd, **kwargs):
        env = kwargs.get("env") or {}
        calls.append({"cmd": list(cmd), "env": dict(env)})
        tok = (env.get("VERCEL_TOKEN") or env.get("NETLIFY_AUTH_TOKEN")
               or env.get("CLOUDFLARE_API_TOKEN") or "")
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="https://example.vercel.app\n",
            stderr=f"debug: using credential {tok}\n",
        )

    monkeypatch.setattr(deploy_mod.subprocess, "run", _run)
    return calls


# ---------------------------------------------------------------------------
# 出口 ①②④：verbose stdout / dry-run 渲染
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "backend,kwargs",
    [
        ("vercel", {"token": SENTINEL}),
        ("netlify", {"token": SENTINEL, "site": "my-site"}),
        ("cloudflare-pages", {"token": SENTINEL, "project": "my-proj"}),
    ],
)
def test_dry_run_output_has_no_token(html, capsys, backend, kwargs):
    """dry-run 渲染的stdout 不得含 sentinel，且应显示符号化凭据来源。"""
    deploy_mod.deploy(html, backend=backend, dry_run=True, verbose=True, **kwargs)
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out, "dry-run stdout 泄漏 token"
    assert SENTINEL not in captured.err, "dry-run stderr 泄漏 token"
    # 只显示符号化来源，不显示实际值
    assert "凭据来源" in captured.out
    assert deploy_mod._MASK in captured.out


@pytest.mark.parametrize(
    "backend,kwargs",
    [
        ("vercel", {"token": SENTINEL}),
        ("netlify", {"token": SENTINEL, "site": "my-site"}),
        ("cloudflare-pages", {"token": SENTINEL, "project": "my-proj"}),
    ],
)
def test_verbose_printed_command_has_no_token(html, capsys, fake_run, backend, kwargs):
    """出口 ①：verbose 打印的命令行（含下游 CLI 回显）不得含 sentinel。"""
    deploy_mod.deploy(html, backend=backend, dry_run=False, verbose=True, **kwargs)
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out, "verbose 打印的命令行泄漏 token"
    assert SENTINEL not in captured.err


# ---------------------------------------------------------------------------
# 出口 ③：异常文本
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "backend,kwargs",
    [
        ("vercel", {"token": SENTINEL}),
        ("netlify", {"token": SENTINEL, "site": "my-site"}),
        ("cloudflare-pages", {"token": SENTINEL, "project": "my-proj"}),
    ],
)
def test_runtime_error_message_has_no_token(html, monkeypatch, backend, kwargs):
    """出口 ③：CLI 失败时RuntimeError 的 message 不得含 sentinel。

    假 CLI 会把 token 回显进 stderr 并以非 0 退出，模拟真实回显场景。
    """

    def _run(cmd, **kw):
        env = kw.get("env") or {}
        tok = (env.get("VERCEL_TOKEN") or env.get("NETLIFY_AUTH_TOKEN")
               or env.get("CLOUDFLARE_API_TOKEN") or "")
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="",
            stderr=f"Error: token {tok} is expired\n")

    monkeypatch.setattr(deploy_mod.subprocess, "run", _run)
    with pytest.raises(RuntimeError) as exc:
        deploy_mod.deploy(html, backend=backend, dry_run=False, verbose=True, **kwargs)
    assert SENTINEL not in str(exc.value), "RuntimeError 文本泄漏 token"


def test_truncated_output_does_not_leak_partial_token(html, monkeypatch):
    """先脱敏再截断：out[-500:] 切在 token 中间也不得漏出半截明文。"""
    padding = "x" * 600

    def _run(cmd, **kw):
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr=f"{padding} token {SENTINEL} bad\n")

    monkeypatch.setattr(deploy_mod.subprocess, "run", _run)
    with pytest.raises(RuntimeError) as exc:
        deploy_mod.deploy(html, backend="vercel", token=SENTINEL, dry_run=False, verbose=False)
    msg = str(exc.value)
    assert SENTINEL not in msg
    # 半截（如前 8 个字符）同样不得出现
    assert SENTINEL[:8] not in msg


# ---------------------------------------------------------------------------
# 根因自证：token 不得进 argv
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "backend,kwargs,env_key",
    [
        ("vercel", {"token": SENTINEL}, "VERCEL_TOKEN"),
        ("netlify", {"token": SENTINEL, "site": "my-site"}, "NETLIFY_AUTH_TOKEN"),
        ("cloudflare-pages", {"token": SENTINEL, "project": "my-proj"}, "CLOUDFLARE_API_TOKEN"),
    ],
)
def test_token_not_in_argv_but_in_child_env(html, fake_run, backend, kwargs, env_key):
    """T09 根因自证：token 既不在 argv，也不在 env 名里，只在子进程 env 的值里。"""
    deploy_mod.deploy(html, backend=backend, dry_run=False, verbose=True, **kwargs)
    assert len(fake_run) == 1
    call = fake_run[0]
    joined = " ".join(call["cmd"])
    assert SENTINEL not in joined, "token 仍在 argv 中（ps 可见）"
    # 连 env 赋值前缀也不该出现在 argv（cloudflare 旧代码的形态）
    assert not any("=" in part and part.split("=", 1)[0].isupper() for part in call["cmd"]), \
        "argv 中仍含 ENV=value 形式的凭据"
    # token 只经子进程环境传递
    assert call["env"].get(env_key) == SENTINEL
    # 且未污染父进程环境（_run_cli 只改副本）
    import os
    assert SENTINEL not in os.environ.values()


# ---------------------------------------------------------------------------
# _redact 单元测试：多种含密形态
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,should_contain",
    [
        # --token=X（等号形态）
        ("vercel --token=SECRET_ABC123 --prod", ["--token=<redacted>", "--prod"]),
        # --token X（空格分隔）
        ("netlify --auth SECRET_ABC123 --site x", ["--auth <redacted>", "--site x"]),
        # 引号包裹的 flag 值
        ('netlify --auth "SECRET_ABC123" --prod', ["--auth <redacted>", "--prod"]),
        ("netlify --auth 'SECRET_ABC123' --prod", ["--auth <redacted>", "--prod"]),
        # env 赋值形态（旧的 cloudflare argv 写法）
        ("CLOUDFLARE_API_TOKEN=SECRET_ABC123 npx wrangler", ["CLOUDFLARE_API_TOKEN=<redacted>", "npx wrangler"]),
        # header 形态
        ("Authorization: Bearer SECRET_ABC123", ["Authorization: <redacted>"]),
        ("authorization=SECRET_ABC123", ["authorization=<redacted>"]),
        # 短横线 flag
        ("--apiKey=SECRET_ABC123", ["--apiKey=<redacted>"]),
        # 应保持不变的非密文本
        ("npx vercel deploy --prod --yes /tmp/stage", ["npx vercel deploy --prod --yes /tmp/stage"]),
        ("--dir /tmp/stage --project-name my-proj", ["--dir /tmp/stage --project-name my-proj"]),
    ],
)
def test_redact_shapes(raw, should_contain):
    out = deploy_mod._redact(raw)
    assert "SECRET_ABC123" not in out, f"未打码：{raw!r} -> {out!r}"
    for frag in should_contain:
        assert frag in out, f"{raw!r} 期望包含 {frag!r}，实际 {out!r}"


def test_redact_bare_literal_token_without_prefix():
    """下游 CLI 原样回显、且不带任何 key 前缀时，靠字面量兜底。"""
    deploy_mod._register_secrets({"VERCEL_TOKEN": SENTINEL})
    out = deploy_mod._redact(f"Error: token {SENTINEL} is expired")
    assert SENTINEL not in out
    assert deploy_mod._MASK in out


def test_redact_keeps_non_secret_env_values():
    """非凭据命名的 env 值不该被打码（避免过度脱敏淹没有用信息）。"""
    out = deploy_mod._redact("VERCEL_PROJECT=my-proj CLOUDFLARE_PAGES_PROJECT=p")
    assert out == "VERCEL_PROJECT=my-proj CLOUDFLARE_PAGES_PROJECT=p"


def test_redact_empty_and_plain_input():
    assert deploy_mod._redact("") == ""
    assert deploy_mod._redact("hello world") == "hello world"