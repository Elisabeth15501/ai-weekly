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


def _ollama_translate(text, model="qwen2.5:7b", timeout=25):
    """本地 Ollama 英文→中文，best-effort，失败返回 None。"""
    if not text or not text.strip():
        return None
    url = os.environ.get("AIWEEKLY_OLLAMA_URL", "http://localhost:11434/api/generate")
    prompt = ("你是一名 AI 行业新闻编辑。把下面这段英文新闻摘要翻译成中文，"
              "要求：事实准确、简洁（不超过原文长度）、不添加原文没有的解释或评论、"
              "不写「以下是翻译」之类的套话。只输出中文译文。\n\n" + text)
    payload = {"model": model, "prompt": prompt, "stream": False,
               "options": {"temperature": 0.1, "num_predict": 400}}
    try:
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
    except Exception:
        return None


def translate_en_summaries(items, enabled=False, model="qwen2.5:7b",
                           max_workers=6, timeout=25):
    """就地给 lang=en 且缺 cn_summary 的条目补中文总结。返回成功翻译条数。"""
    if not enabled:
        return 0
    targets = []
    for it in items:
        lang = it.get("lang") or _detect_lang(it.get("title", ""), it.get("summary", ""))
        if lang == "en" and not it.get("cn_summary"):
            targets.append(it)
    if not targets:
        return 0

    def worker(it):
        src = (it.get("summary") or it.get("title") or "").strip()
        return _ollama_translate(src, model=model, timeout=timeout)

    n_done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(worker, it): it for it in targets}
        for fut in concurrent.futures.as_completed(futs):
            res = fut.result()
            if res:
                futs[fut]["cn_summary"] = res
                n_done += 1
    return n_done


__all__ = ["_ollama_translate", "translate_en_summaries"]