"""英文报道 → 中文总结（本地 Ollama，best-effort，零 API 成本、国内友好）。

把「英文新闻中文总结」这一*单一职责*收敛为一个可复用的 **Translator** 服务：

- 既能在生成周报**途中即时**为某个英文条目补中文总结（``Translator.ensure(item)``），
  也能对一批英文条目做并发批量翻译（``Translator.translate_items(items)``）；
- 单条失败 / 超时 / Ollama 未运行 → 静默回退（保留英文原文），**绝不阻断报告生成**；
- 内置**重试 + 受控并发**：CPU 本地推理也能拿到高覆盖率（高并发 + 短超时反而会
  因互相抢资源导致大量超时丢条）；
- 仅依赖本地 Ollama，不引入任何第三方商业 API、不触合规红线。

失败模式（全部静默回退）：
  - Ollama 未运行 / 网络不可达
  - 模型不存在 / 推理超时（会按 retries 重试）
  - 输出几乎无中文（视为翻译失败）
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import urllib.request
from typing import Iterable, Optional

from aiweekly.news import _detect_lang


# ── 常量（可被 CLI 覆盖）─────────────────────────────────────────────
DEFAULT_MODEL = "qwen2.5:7b"
# CPU 本地推理比 GPU 慢很多，单条超时给足；过短会大量超时丢条
DEFAULT_TIMEOUT = 45
# 并发线程；CPU 推理下过高会互相抢资源导致超时丢条（实测 6→3 覆盖率翻倍）
DEFAULT_WORKERS = 3
# 单条失败后的重试次数（总尝试 = retries + 1）
DEFAULT_RETRIES = 2

_EDITOR_PROMPT = (
    "你是一名 AI 行业新闻编辑。把下面这段英文新闻摘要翻译成中文，"
    "要求：事实准确、简洁（不超过原文长度）、不添加原文没有的解释或评论、"
    "不写「以下是翻译」之类的套话。只输出中文译文。\n\n"
)
_CJK_HAN = re.compile(r"[一-鿿]")


def ollama_base_url() -> str:
    """返回 Ollama generate 端点（可用环境变量 AIWEEKLY_OLLAMA_URL 覆盖）。"""
    return os.environ.get("AIWEEKLY_OLLAMA_URL", "http://localhost:11434/api/generate")


def ollama_health(timeout: float = 3.0, model: Optional[str] = None, opener=None):
    """翻译前先 ping ``/api/tags``，判断本地 Ollama 是否可用（P1#14）。

    返回 ``(ok, detail)``。``ok=False`` 时 detail 是可直打印给用户的原因。
    不抛异常——探测失败一律折算为 ``(False, 原因)``，避免逐条空等超时。
    """
    tags_url = ollama_base_url().replace("/api/generate", "/api/tags")
    try:
        req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
        _open = opener.open if opener else urllib.request.urlopen
        with _open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001  健康探测：任何失败都只意味着「不可用」
        return False, f"本地 Ollama 不可达（{tags_url}）：{type(e).__name__}"
    names = [m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict)]
    if not names:
        return False, "Ollama 已启动但未安装任何模型（请先 ollama pull）"
    if model and not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
        return False, f"Ollama 可达但缺少模型 {model}（已装：{', '.join(names[:5])}）"
    return True, f"Ollama 可用（{len(names)} 个模型）"


def _ollama_translate(text, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT, client=None):
    """单次英文→中文，best-effort，失败返回 None。

    Args:
        text    — 英文原文；空串直接返回 None；
        model   — 本地 Ollama 模型标签（须与 ``ollama list`` 完全一致）；
        timeout — 单条推理超时（秒）；
        client  — **依赖注入点**，签名 ``f(url, payload, timeout) -> dict``；
                  None 时走真实 HTTP。单测传 mock 可完全脱离本地 Ollama。
    返回：中文译文 str；失败（不可达 / 超时 / 输出几乎无中文）返回 None。
    """
    if not text or not text.strip():
        return None
    url = ollama_base_url()
    payload = {"model": model, "prompt": _EDITOR_PROMPT + text, "stream": False,
               "options": {"temperature": 0.1, "num_predict": 400}}
    try:
        if client is not None:
            data = client(url, payload, timeout)
        else:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("response") or "").strip()
        # 去掉常见的套话前缀
        out = re.sub(r"^(翻译[：:]\s*|中文译文[：:]\s*|以下是翻译[：:]\s*|译文[：:]\s*)", "", out).strip()
        if len(_CJK_HAN.findall(out)) < 3:   # 几乎无中文 -> 失败
            return None
        return out
    except Exception:  # noqa: BLE001  可选增强：任何失败都回退英文原文
        return None


class OllamaUnavailable(RuntimeError):
    """显式标记「翻译服务不可用」，供调用方选择是否告警（非致命）。"""


class Translator:
    """英文→中文总结服务（可即时、可批量，best-effort）。

    设计目标：把翻译从「生成脚本里的独立后处理块」变成**生成管线内的一等公民服务**——
    生成周报途中遇到英文报道即自动、即时地补上中文总结，无需任何额外的手动步骤。

    典型用法（生成管线内）::

        tr = Translator(enabled=args.translate_en, model=args.translate_model)
        tr.translate_items(items)     # 批量：途中遇英文即并发中译（推荐，最快）
        # 或严格的逐条即时：
        tr.ensure(item)               # 仅当 item 为英文且缺 cn_summary 时即时补

    未开启（``enabled=False``）或 Ollama 不可用 → 所有方法静默 no-op / 回退，
    绝不抛异常阻断报告生成。
    """

    def __init__(self, enabled: bool = False, model: str = DEFAULT_MODEL,
                 timeout: int = DEFAULT_TIMEOUT, max_workers: int = DEFAULT_WORKERS,
                 retries: int = DEFAULT_RETRIES):
        self.enabled = enabled
        self.model = model
        self.timeout = timeout
        self.max_workers = max(1, int(max_workers))
        self.retries = max(0, int(retries))
        self._available: Optional[bool] = None   # 懒探测结果缓存

    # ── 可用性 ──────────────────────────────────────────────────────
    def available(self) -> bool:
        """探测本地 Ollama 是否可用（含模型校验）；结果缓存，不重复 ping。"""
        if self._available is None:
            ok, _ = ollama_health(timeout=3.0, model=self.model)
            self._available = ok
        return self._available

    # ── 单条 ────────────────────────────────────────────────────────
    def translate(self, text: str) -> Optional[str]:
        """翻译单段英文；未启用 / 空串 / 失败均返回 None（按 retries 重试）。"""
        if not self.enabled or not text or not text.strip():
            return None
        for _ in range(self.retries + 1):
            out = _ollama_translate(text, model=self.model, timeout=self.timeout)
            if out:
                return out
        return None

    def ensure(self, item: dict) -> dict:
        """即时为**单个**新闻条目补中文总结（原地写 ``cn_summary``）。

        仅当：启用 + 条目为英文(``lang=en``) + 缺 ``cn_summary`` 时生效；
        否则原样返回（非英文 / 已翻译 / 未启用 / Ollama 不可用）。
        翻译失败静默保留英文原文。
        """
        if not self.enabled:
            return item
        lang = item.get("lang") or _detect_lang(item.get("title", ""), item.get("summary", ""))
        if lang != "en" or item.get("cn_summary"):
            return item
        src = (item.get("summary") or item.get("title") or "").strip()
        cn = self.translate(src)
        if cn:
            item["cn_summary"] = cn
        return item

    # ── 批量（途中遇英文即并发中译）─────────────────────────────────
    def translate_items(self, items: Iterable[dict]) -> int:
        """就地给所有「英文且缺 cn_summary」的条目补中文总结。

        返回成功翻译条数。未启用 / Ollama 不可用 → 立即返回 0（不空等）。
        使用受控线程池并发，单条失败按 retries 重试。
        """
        if not self.enabled:
            return 0
        targets = [it for it in items
                   if (it.get("lang") or _detect_lang(it.get("title", ""), it.get("summary", ""))) == "en"
                   and not it.get("cn_summary")]
        if not targets:
            return 0
        if not self.available():
            ok, detail = ollama_health(timeout=3.0, model=self.model)
            print(f"  ⚠️ 跳过英文中译：{detail}（{len(targets)} 条保留英文原文）")
            return 0
        print(f"  🩺 本地 Ollama 可用，开始翻译 {len(targets)} 条英文报道 …")

        def worker(it):
            src = (it.get("summary") or it.get("title") or "").strip()
            return self.translate(src)

        n_done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {ex.submit(worker, it): it for it in targets}
            for fut in concurrent.futures.as_completed(futs):
                res = fut.result()
                if res:
                    futs[fut]["cn_summary"] = res
                    n_done += 1
        if n_done < len(targets):
            print(f"  ⚠️ 英文中译完成 {n_done}/{len(targets)} 条"
                  f"（其余因超时/失败保留英文原文）")
        return n_done


__all__ = [
    "Translator", "OllamaUnavailable",
    "ollama_base_url", "ollama_health", "_ollama_translate",
    "DEFAULT_MODEL", "DEFAULT_TIMEOUT", "DEFAULT_WORKERS", "DEFAULT_RETRIES",
]
