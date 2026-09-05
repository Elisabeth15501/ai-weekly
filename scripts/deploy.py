#!/usr/bin/env python3
"""deploy.py — 统一部署入口（P0-1：飞书推送去 GitHub 化）。

把生成的 AI 周报 HTML 部署到一个**公开可访问**的托管位置，使飞书卡片的
「查看完整周报」按钮能直接打开。支持多种后端，用户无需再折腾 GitHub Pages：

  github-pages      (默认) 沿用 deploy_ghpages.py，零破坏
  tencent-cos       腾讯云 COS 静态网站（国内首选，直连快、无需翻墙）
  vercel            Vercel（一条命令 `vercel --prod`，国内访问稳定）
  netlify           Netlify（netlify-cli）
  cloudflare-pages  Cloudflare Pages（wrangler）
  local             复制到本地目录（适合自有服务器 / 内网反代，需自备 view-base）

设计原则：
  - github-pages 为默认，不传 --deploy-to 时行为与旧版一致（向后兼容）。
  - 每个后端对应一组配置（环境变量或 delivery/<backend>_config.json）；
    配置缺失时给出明确引导，不静默失败。
  - 返回 view_base（公开基址），供 publish.py 拼出 view_url。

用法：
  python deploy.py --html AI_News_2026-09-04.html --deploy-to github-pages
  python deploy.py --html AI_News_2026-09-04.html --deploy-to tencent-cos
  python deploy.py --html AI_News_2026-09-04.html --deploy-to vercel --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DELIVERY = REPO_ROOT / "delivery"

BACKENDS = ["github-pages", "tencent-cos", "vercel", "netlify", "cloudflare-pages", "local"]


# ---------------------------------------------------------------------------
# 配置加载（各后端通用）
# ---------------------------------------------------------------------------
def _load_json_config(name: str) -> dict:
    p = DELIVERY / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _require(cond: bool, msg: str):
    if not cond:
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# github-pages（默认，复用 deploy_ghpages）
# ---------------------------------------------------------------------------
def _github_pages_view_base(repo: Path) -> str | None:
    """从 remote 推导 GitHub Pages 基址：https://<owner>.github.io/<repo>/。"""
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=str(repo),
            capture_output=True, text=True, check=False,
        )
        if res.returncode != 0:
            return None
        url = res.stdout.strip()
        m = __import__("re").search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
        if not m:
            return None
        owner, name = m.group(1), m.group(2)
        return f"https://{owner}.github.io/{name}/"
    except Exception:  # noqa: BLE001
        return None


def _deploy_github_pages(html_path: Path, no_push: bool, dry_run: bool, verbose: bool) -> dict:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from deploy_ghpages import deploy as gh_deploy  # noqa: E402
    res = gh_deploy(html_path, no_push=no_push, dry_run=dry_run, verbose=verbose)
    view_base = _github_pages_view_base(REPO_ROOT) if not dry_run else None
    return {"pushed": res.get("pushed", False), "view_base": view_base,
            "reports": res.get("reports", [])}


# ---------------------------------------------------------------------------
# tencent-cos
# ---------------------------------------------------------------------------
def _deploy_tencent_cos(html_path: Path, dry_run: bool, verbose: bool,
                        bucket=None, region=None, secret_id=None,
                        secret_key=None, base_url=None, prefix="") -> dict:
    cfg = _load_json_config("cos_config.json")
    bucket = bucket or os.environ.get("COS_BUCKET") or cfg.get("bucket")
    region = region or os.environ.get("COS_REGION") or cfg.get("region")
    secret_id = secret_id or os.environ.get("COS_SECRET_ID") or cfg.get("secret_id")
    secret_key = secret_key or os.environ.get("COS_SECRET_KEY") or cfg.get("secret_key")
    base_url = base_url or os.environ.get("COS_BASE_URL") or cfg.get("base_url")
    prefix = prefix or cfg.get("prefix", "")

    _require(bucket and region and secret_id and secret_key,
             "腾讯云 COS 未配置：请在 delivery/cos_config.json 或环境变量设置 "
             "COS_BUCKET / COS_REGION / COS_SECRET_ID / COS_SECRET_KEY"
             "（静态网站托管还需 COS_BASE_URL）。")
    _require(bool(base_url),
             "COS_BASE_URL 未设置：COS 静态网站域名（如 https://<bucket>.cos-website."
             "<region>.myqcloud.com），用于拼装周报访问链接。")

    key = f"{prefix.strip('/')}/{html_path.name}".strip("/")
    if dry_run:
        if verbose:
            print(f"🛑 [dry-run] 将上传 {html_path.name} → cos://{bucket}/{key}")
            print(f"   公开链接：{base_url.rstrip('/')}/{key}")
        return {"pushed": False, "view_base": base_url.rstrip("/") + "/", "reports": [html_path.name]}

    try:
        from qcloud_cos import CosConfig, CosS3Client  # cos-python-sdk-v5
    except ImportError:
        raise RuntimeError("缺少腾讯云 SDK：请运行 `pip install cos-python-sdk-v5`（在 aiweekly venv）。")

    client = CosS3Client(CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key))
    client.upload_file(Bucket=bucket, Key=key, LocalFilePath=str(html_path))
    if verbose:
        print(f"✅ 已上传到 COS：cos://{bucket}/{key}")
    return {"pushed": True, "view_base": base_url.rstrip("/") + "/", "reports": [html_path.name]}


# ---------------------------------------------------------------------------
# vercel / netlify / cloudflare-pages（CLI 驱动；dry-run 仅打印命令）
# ---------------------------------------------------------------------------
def _stage_dir(html_path: Path) -> Path:
    """把单文件 HTML 暂存为 index.html 于临时目录，供 CLI 部署工具认作站点根。"""
    d = Path(tempfile.mkdtemp(prefix="aiw-deploy-"))
    (d / "index.html").write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")
    # 同时保留原名，便于固定链接
    shutil.copyfile(html_path, d / html_path.name)
    return d


def _run_cli(cmd: list[str], verbose: bool) -> str:
    if verbose:
        print("  $ " + " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        raise RuntimeError(f"部署命令失败（exit={res.returncode}）：{out[-500:]}")
    return out


def _deploy_vercel(html_path: Path, dry_run: bool, verbose: bool,
                   token=None, project=None) -> dict:
    token = token or os.environ.get("VERCEL_TOKEN") or _load_json_config("vercel_config.json").get("token")
    project = project or os.environ.get("VERCEL_PROJECT") or _load_json_config("vercel_config.json").get("project")
    _require(bool(token), "Vercel 未配置：设置 VERCEL_TOKEN（及可选 VERCEL_PROJECT）。")
    stage = _stage_dir(html_path)
    cmd = ["npx", "vercel", "deploy", "--prod", "--yes", f"--token={token}"]
    if project:
        cmd += ["--name", project]
    cmd += [str(stage)]
    if dry_run:
        if verbose:
            print(f"🛑 [dry-run] 将执行：{' '.join(cmd)}")
        return {"pushed": False, "view_base": None, "reports": [html_path.name]}
    out = _run_cli(cmd, verbose)
    # Vercel 输出最后一行通常是部署 URL
    url = out.strip().splitlines()[-1].strip() if out.strip() else None
    return {"pushed": True, "view_base": (url.rstrip("/") + "/") if url else None,
            "reports": [html_path.name]}


def _deploy_netlify(html_path: Path, dry_run: bool, verbose: bool,
                    token=None, site=None) -> dict:
    token = token or os.environ.get("NETLIFY_AUTH_TOKEN") or _load_json_config("netlify_config.json").get("token")
    site = site or os.environ.get("NETLIFY_SITE_ID") or _load_json_config("netlify_config.json").get("site_id")
    _require(bool(token) and bool(site), "Netlify 未配置：设置 NETLIFY_AUTH_TOKEN 与 NETLIFY_SITE_ID。")
    stage = _stage_dir(html_path)
    cmd = ["npx", "netlify", "deploy", "--prod", "--dir", str(stage),
           "--auth", token, "--site", site]
    if dry_run:
        if verbose:
            print(f"🛑 [dry-run] 将执行：{' '.join(cmd)}")
        return {"pushed": False, "view_base": None, "reports": [html_path.name]}
    out = _run_cli(cmd, verbose)
    return {"pushed": True, "view_base": None, "reports": [html_path.name]}


def _deploy_cloudflare(html_path: Path, dry_run: bool, verbose: bool,
                       project=None, token=None) -> dict:
    token = token or os.environ.get("CLOUDFLARE_API_TOKEN") or _load_json_config("cf_pages_config.json").get("token")
    project = project or os.environ.get("CLOUDFLARE_PAGES_PROJECT") or _load_json_config("cf_pages_config.json").get("project")
    _require(bool(project), "Cloudflare Pages 未配置：设置 CLOUDFLARE_PAGES_PROJECT（及可选 CLOUDFLARE_API_TOKEN）。")
    stage = _stage_dir(html_path)
    cmd = ["npx", "wrangler", "pages", "deploy", str(stage),
           "--project-name", project, "--commit-dirty=true"]
    if token:
        cmd = ["CLOUDFLARE_API_TOKEN=" + token] + cmd
    if dry_run:
        if verbose:
            print(f"🛑 [dry-run] 将执行：{' '.join(cmd)}")
        return {"pushed": False, "view_base": None, "reports": [html_path.name]}
    out = _run_cli(cmd, verbose)
    return {"pushed": True, "view_base": None, "reports": [html_path.name]}


# ---------------------------------------------------------------------------
# local（复制到本地目录；适合自有服务器）
# ---------------------------------------------------------------------------
def _deploy_local(html_path: Path, dry_run: bool, verbose: bool, dest=None, base_url=None) -> dict:
    cfg = _load_json_config("local_config.json")
    dest = dest or os.environ.get("LOCAL_DEPLOY_DIR") or cfg.get("dest")
    base_url = base_url or os.environ.get("LOCAL_VIEW_BASE") or cfg.get("view_base")
    _require(bool(dest), "local 后端需要目标目录：--dest DIR 或 LOCAL_DEPLOY_DIR / delivery/local_config.json。")
    dest = Path(dest)
    if dry_run:
        if verbose:
            print(f"🛑 [dry-run] 将复制 {html_path.name} → {dest}/")
            if base_url:
                print(f"   公开链接：{base_url.rstrip('/')}/{html_path.name}")
        return {"pushed": False, "view_base": (base_url.rstrip("/") + "/") if base_url else None,
                "reports": [html_path.name]}
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(html_path, dest / html_path.name)
    if verbose:
        print(f"✅ 已复制到本地目录：{dest / html_path.name}")
    return {"pushed": True, "view_base": (base_url.rstrip("/") + "/") if base_url else None,
            "reports": [html_path.name]}


# ---------------------------------------------------------------------------
# 分发
# ---------------------------------------------------------------------------
def deploy(html_path, backend: str = "github-pages", view_base: str | None = None,
          no_push: bool = False, dry_run: bool = False, verbose: bool = True,
          **kwargs) -> dict:
    html_path = Path(html_path)
    if not html_path.exists():
        from aiweekly.errors import err_missing_file  # noqa: PLC0415
        raise err_missing_file(html_path)

    backend = backend or "github-pages"
    if backend == "github-pages":
        res = _deploy_github_pages(html_path, no_push, dry_run, verbose)
    elif backend == "tencent-cos":
        res = _deploy_tencent_cos(html_path, dry_run, verbose, **kwargs)
    elif backend == "vercel":
        res = _deploy_vercel(html_path, dry_run, verbose, **kwargs)
    elif backend == "netlify":
        res = _deploy_netlify(html_path, dry_run, verbose, **kwargs)
    elif backend == "cloudflare-pages":
        res = _deploy_cloudflare(html_path, dry_run, verbose, **kwargs)
    elif backend == "local":
        res = _deploy_local(html_path, dry_run, verbose, **kwargs)
    else:
        raise ValueError(f"未知部署后端：{backend}（可选：{', '.join(BACKENDS)}）")

    # 若调用方显式给了 view_base，优先使用
    if view_base:
        res["view_base"] = view_base.rstrip("/") + "/"
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="统一部署 AI 周报 HTML（P0-1：多后端·去 GitHub 化）")
    ap.add_argument("--html", required=True, help="生成的周报 HTML 路径")
    ap.add_argument("--deploy-to", default="github-pages", choices=BACKENDS,
                    help="部署后端（默认 github-pages，零破坏）")
    ap.add_argument("--view-base", default=None, help="公开基址（覆盖后端推导的 view_base）")
    ap.add_argument("--no-push", action="store_true", help="仅本地提交/更新，不推送（仅 github-pages）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作，不实际部署")
    args = ap.parse_args()
    try:
        res = deploy(args.html, backend=args.deploy_to, view_base=args.view_base,
                     no_push=args.no_push, dry_run=args.dry_run)
        if res.get("view_base"):
            print(f"🌐 周报公开基址：{res['view_base']}")
        print(f"✅ 部署完成（pushed={res.get('pushed')}）")
    except Exception as exc:  # noqa: BLE001
        from aiweekly.errors import UserFacingError, print_error  # noqa: PLC0415
        if isinstance(exc, UserFacingError):
            print_error(exc)
        else:
            print_error(UserFacingError("ERR-UNEXPECTED", "部署过程发生未预期错误",
                                        ["检查上方错误信息", "若问题持续，请提交 issue 到 GitHub"],
                                        verbose=repr(exc), log_extra=traceback.format_exc()))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
