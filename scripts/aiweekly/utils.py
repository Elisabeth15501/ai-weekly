"""底层工具：日期解析、网络 IO、区域/代理探测。

所有函数无业务依赖，供其它子模块引用。
外部使用仍可通过 `from generate_site import _http_get`（兼容垫层）。
"""
import os
import random
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

# Chrome UA：绕过部分站点的反爬默认 UA 限制
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 代理：允许通过 HTTPS_PROXY / HTTP_PROXY 环境变量或 --proxy 参数显式指定，
# 让「国外源」在受限网络（如国内需走代理）下也能抓取。
_PROXY_OVERRIDE = None  # 由 CLI 通过 --proxy 设置

_SOCKS_ACTIVE = False  # 由 _configure_proxy() 在启用 SOCKS 时置位


def _resolved_proxy() -> str:
    return _PROXY_OVERRIDE or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") \
        or os.environ.get("http_proxy") or ""


def _configure_proxy():
    """根据 _resolved_proxy() 配置代理（在抓取前调用一次）。

    - http/https 代理：由各 _build_opener() 按请求挂载，无需全局状态；
    - socks5/socks4 代理：需要 PySocks，通过 socks.wrapmodule(urllib.request)
      全局生效，并置 _SOCKS_ACTIVE 以免重复挂载 http ProxyHandler。
    """
    global _SOCKS_ACTIVE
    _SOCKS_ACTIVE = False
    proxy = _resolved_proxy()
    if not proxy:
        return
    if proxy.startswith("socks"):
        try:
            import socks  # PySocks
            scheme, _, rest = proxy.partition("://")
            auth_hostport = rest
            username = password = None
            if "@" in rest:
                auth, auth_hostport = rest.rsplit("@", 1)
                if ":" in auth:
                    username, password = auth.split(":", 1)
            host, _, port = auth_hostport.rpartition(":")
            stype = socks.SOCKS5 if scheme in ("socks5", "socks5h") else socks.SOCKS4
            socks.set_default_proxy(stype, host, int(port), rdns=(scheme == "socks5h"),
                                    username=username, password=password)
            socks.wrapmodule(urllib.request)
            _SOCKS_ACTIVE = True
            print(f"  🔌 已启用 SOCKS 代理：{host}:{port}（PySocks）")
        except ImportError:
            print("  ⚠️ 检测到 SOCKS 代理但未安装 PySocks，无法使用。"
                  " 请运行：pip install PySocks（在 aiweekly venv 中），或改用 HTTP 代理（如 Clash 7890）。")
        except Exception as e:
            print(f"  ⚠️ SOCKS 代理配置失败：{e}")


def _build_opener():
    """构造带代理 + 不校验证书的 opener（与历史行为一致，仅叠加代理能力）。"""
    handlers = []
    proxy = _resolved_proxy()
    if proxy and not _SOCKS_ACTIVE:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _http_get(url: str, timeout: int = 45, opener=None) -> str:
    """抓取 URL 文本内容。

    输入：
        url     — 目标地址；
        timeout — 单次请求超时（秒，默认 45）；
        opener  — **依赖注入点（P1#6）**：任意实现 `.open(req, timeout=)` 的对象。
                  为 None 时用 `_build_opener()` 真实网络；单测传 mock 即可脱网。
    输出：解码后的响应正文（utf-8，非法字节 replace）。
    异常：向上抛 `urllib.error.URLError` / `TimeoutError` 等，由调用方的
          `_retry_fetch` 或 best-effort 容错块处理。
    示例：
        >>> _http_get("https://example.com", timeout=5)          # doctest: +SKIP
        >>> _http_get("x", opener=FakeOpener("<html/>"))         # doctest: +SKIP
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    opener = opener or _build_opener()
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _probe(url: str, timeout: int = 8, opener=None) -> bool:
    """轻量连通性探测：能拿到响应即视为可达（不解析内容）。

    输入：url / timeout（秒）/ opener（依赖注入点，同 `_http_get`）。
    输出：bool，可达为 True。
    异常：不抛——任何异常都被视为「不可达」返回 False（探测语义要求永不中断上层）。
    示例：
        >>> _probe("https://www.baidu.com", 6)                   # doctest: +SKIP
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with (opener or _build_opener()).open(req, timeout=timeout) as r:
            r.read(256)
        return True
    except Exception:  # noqa: BLE001 探测语义：任何失败都只意味着「不可达」
        return False


def _detect_region(probe=None) -> str:
    """探测当前运行环境是 cn / global / unknown。

    输入：probe — 依赖注入点（P1#6），签名同 `_probe(url, timeout)`；None 用真实探测。
    输出：`"cn"` / `"global"` / `"unknown"`。双通时返回 global（榜源更丰富）。
    异常：不抛（内部全部走 `_probe` 的静默语义）。
    示例：
        >>> _detect_region(probe=lambda u, t=6: "baidu" in u)
        'cn'

    国内哨兵：baidu（必通）+ OpenCompass（学术榜）
    国外哨兵：lmarena + huggingface
    """
    _p = probe or _probe
    cn_ok = _p("https://www.baidu.com", 6) or _p("https://rank.opencompass.org.cn/leaderboard-llm", 6)
    foreign_ok = _p("https://lmarena.ai/leaderboard", 8) or _p("https://huggingface.co", 6)
    if cn_ok and not foreign_ok:
        return "cn"
    if foreign_ok and not cn_ok:
        return "global"
    if cn_ok and foreign_ok:
        return "global"  # 双通时按国外优先级（榜源更丰富）
    return "unknown"


def _retry_fetch(fn, attempts: int = 3, base: float = 1.0, cap: float = 30.0, sleeper=None):
    """指数退避 + 随机抖动重试（P0#10）：best-effort，不向上层抛异常。

    输入：
        fn       — 无参可调用；返回任意值即视为成功；
        attempts — 最大尝试次数（默认 3）；
        base/cap — 退避基数与上限（秒）；
        sleeper  — **依赖注入点（P1#6）**，签名 `f(seconds)`；单测传 `lambda s: None`
                   可让重试路径瞬时跑完，不再真 sleep。
    输出：`fn()` 的返回值；全部失败返回 None，由调用方兜底（缓存快照 / 标注「暂无实时数据」）。
    异常：不抛——通用重试包装必须吞掉所有异常（已加 noqa 说明）。
    示例：
        >>> _retry_fetch(lambda: 1)
        1
        >>> _retry_fetch(lambda: (_ for _ in ()).throw(OSError), attempts=2,
        ...              sleeper=lambda s: None) is None            # doctest: +SKIP
        True

    - 第 i 次失败后等待 `min(cap, base * 2**i) + 随机抖动` 秒，避免与上游限流同步重试。
    """
    _sleep = sleeper or time.sleep
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 通用重试包装，必须吞掉所有异常
            last_err = e
            if i < attempts - 1:
                sleep_s = min(cap, base * (2 ** i)) + random.uniform(0, 1.0)
                _sleep(sleep_s)
    print(f"  ⚠️ 重试 {attempts} 次后仍失败：{last_err}")
    return None


def _parse_iso_datetime(s) -> "datetime | None":
    """解析 ISO 8601 字符串为 datetime（兼容尾随 Z / 时区偏移）。

    失败（含空值）返回 None，由调用方决定回退策略，不抛。
    内部集中处理 `...Z` → `...+00:00` 的兼容转换，避免散落各处重复。
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date_arg(token: str):
    """日期参数 -> datetime（P0#15/16：完整 ISO 8601 或 YYYY-MM-DD）。

    用于 --date 固定报告周期（便于复现）。非法输入显式抛 ValueError，
    不再把解析失败静默吞掉。
    """
    s = str(token).strip()
    dt = _parse_iso_datetime(s)
    if dt is not None:
        return dt
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"无法解析 --date 参数（需 YYYY-MM-DD 或 ISO 8601）：{token!r}")


def _parse_snapshot_date(snap: str):
    """快照日期字符串 -> date；解析失败回退 None（P0#17：已支持完整 ISO 8601）。

    返回 `datetime.date`（非 datetime）以兼容 `_leaderboard_freshness` 的
    `report_date.date() - d` 算术；改返回 datetime 需同步下游 `.date()` 调用。
    """
    if not snap:
        return None
    dt = _parse_iso_datetime(snap)
    if dt is not None:
        return dt.date()
    try:
        return datetime.strptime(str(snap).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


__all__ = [
    "_UA", "_PROXY_OVERRIDE", "_SOCKS_ACTIVE",
    "_resolved_proxy", "_configure_proxy", "_build_opener",
    "_http_get", "_probe", "_detect_region", "_retry_fetch",
    "_parse_iso_datetime", "_parse_date_arg", "_parse_snapshot_date",
]