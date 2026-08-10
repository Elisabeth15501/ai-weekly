"""Ollama 本地翻译：英文报道补中文总结（best-effort）。

失败模式（全部静默回退，不影响报告生成）：
  - Ollama 未运行 / 网络不可达
  - 模型不存在 / 推理超时
  - 输出几乎无中文（视为翻译失败）
"""
import concurrent.futures
import json
import os
import re
import urllib.request

from aiweekly.news import _detect_lang


def _ollama_base_url() -> str:
    """返回 Ollama generate 端点（可用 AIWEEKLY_OLLAMA_URL 覆盖）。"""
    return os.environ.get("AIWEEKLY_OLLAMA_URL", "http://localhost:11434/api/generate")


def ollama_health(timeout: float = 3.0, model: str = None, opener=None):
    """P1#14：翻译前先 ping `/api/tags`，判断本地 Ollama 是否可用。

    输入：
        timeout — 探测超时（秒，默认 3；健康检查必须秒级返回，不能拖慢管线）；
        model   — 可选，若给出则额外校验该模型是否已 `ollama pull`；
        opener  — 依赖注入点（P1#6），需实现 `.open(req, timeout=)`；None 走真实网络。
    输出：`(ok: bool, detail: str)`。ok=False 时 detail 是可直接打印给用户的原因。
    异常：不抛——探测失败一律折算为 `(False, 原因)`，绝不阻断报告生成。
    示例：
        >>> ok, msg = ollama_health(timeout=1)                    # doctest: +SKIP
        >>> ok, msg = ollama_health(model="qwen2.5:7b")           # doctest: +SKIP
    """
    tags_url = _ollama_base_url().replace("/api/generate", "/api/tags")
    try:
        req = urllib.request.Request(tags_url, headers={"Accept": "application/json"})
        _open = opener.open if opener else urllib.request.urlopen
        with _open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 健康探测：任何失败都只意味着「不可用」
        return False, f"本地 Ollama 不可达（{tags_url}）：{type(e).__name__}"
    names = [m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict)]
    if not names:
        return False, "Ollama 已启动但未安装任何模型（请先 ollama pull）"
    if model and not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
        return False, f"Ollama 可达但缺少模型 {model}（已装：{', '.join(names[:5])}）"
    return True, f"Ollama 可用（{len(names)} 个模型）"


def _ollama_translate(text, model="qwen2.5:7b", timeout=25, client=None):
    """本地 Ollama 英文→中文，best-effort，失败返回 None。

    输入：
        text    — 英文原文；空串直接返回 None；
        model   — 本地 Ollama 模型标签（须与 `ollama list` 完全一致）；
        timeout — 单条推理超时（秒）；
        client  — **依赖注入点（P1#6）**，签名 `f(url, payload: dict, timeout) -> dict`；
                  None 时走真实 HTTP。单测传 mock 可完全脱离本地 Ollama。
    输出：中文译文 str；失败（不可达 / 超时 / 输出几乎无中文）返回 None。
    异常：不抛——翻译是可选增强，任何失败都保留英文原文。
    示例：
        >>> _ollama_translate("Hello", client=lambda u, p, t: {"response": "你好世界"})
        '你好世界'
    """
    if not text or not text.strip():
        return None
    url = _ollama_base_url()
    prompt = ("你是一名 AI 行业新闻编辑。把下面这段英文新闻摘要翻译成中文，"
              "要求：事实准确、简洁（不超过原文长度）、不添加原文没有的解释或评论、"
              "不写「以下是翻译」之类的套话。只输出中文译文。\n\n" + text)
    payload = {"model": model, "prompt": prompt, "stream": False,
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
        out = re.sub(r'^(翻译[：:]\s*|中文译文[：:]\s*|以下是翻译[：:]\s*|译文[：:]\s*)', '', out).strip()
        if len(re.findall(r'[一-鿿]', out)) < 3:   # 几乎无中文 -> 失败
            return None
        return out
    except Exception:  # noqa: BLE001 可选增强：任何失败都回退英文原文
        return None


def translate_en_summaries(items, enabled=False, model="qwen2.5:7b",
                           max_workers=6, timeout=25, client=None,
                           health_check=True):
    """就地给 lang=en 且缺 cn_summary 的条目补中文总结。

    输入：
        items        — 新闻条目列表（就地写入 `cn_summary`）；
        enabled      — 未开启 `--translate-en` 时直接返回 0；
        model/timeout/max_workers — 本地 Ollama 推理参数；
        client       — 依赖注入点（P1#6），透传给 `_ollama_translate`；
        health_check — **P1#14**：True 时先 ping `/api/tags`，不可用则立即放弃，
                       避免 N 条 × timeout 秒的空等（最坏 102 条 × 25s ≈ 42 分钟）。
    输出：成功翻译条数（int）。
    异常：不抛——翻译失败保留英文原文，绝不阻断报告生成。
    示例：
        >>> translate_en_summaries([], enabled=True)
        0
    """
    if not enabled:
        return 0
    targets = []
    for it in items:
        lang = it.get("lang") or _detect_lang(it.get("title", ""), it.get("summary", ""))
        if lang == "en" and not it.get("cn_summary"):
            targets.append(it)
    if not targets:
        return 0

    # P1#14：先探测本地 Ollama，避免不可用时逐条空等超时
    if health_check and client is None:
        ok, detail = ollama_health(timeout=3.0, model=model)
        if not ok:
            print(f"  ⚠️ 跳过英文中译：{detail}（{len(targets)} 条保留英文原文）")
            return 0
        print(f"  🩺 {detail}，开始翻译 {len(targets)} 条英文报道 …")

    def worker(it):
        src = (it.get("summary") or it.get("title") or "").strip()
        return _ollama_translate(src, model=model, timeout=timeout, client=client)

    n_done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(worker, it): it for it in targets}
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            if res:
                futs[fut]["cn_summary"] = res
                n_done += 1
    return n_done


__all__ = ["_ollama_translate", "translate_en_summaries", "ollama_health", "_ollama_base_url"]