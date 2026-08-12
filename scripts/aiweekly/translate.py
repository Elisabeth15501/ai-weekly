"""英文报道 → 中文总结（本地 Ollama，best-effort，零 API 成本、国内友好）。

把「英文新闻中文总结」这一*单一职责*收敛为一个可复用的 **Translator** 服务：

- 既能在生成周报**途中即时**为某个英文条目补中文总结（``Translator.ensure(item)``），
  也能对一批英文条目做并发批量翻译（``Translator.translate_items(items)``）；
- 单条失败 / 超时 / Ollama 未运行 → 静默回退（保留英文原文），**绝不阻断报告生成**；
- 内置**重试 + 受控并发**：CPU 本地推理也能拿到高覆盖率（高并发 + 短超时反而会
  因互相抢资源导致大量超时丢条）；
- **本地译文缓存**：按 URL / 标题 哈希落盘，命中即复用、带原文 hash 防脏，
  避免每周重抓重译（提速 + 离线鲁棒）；
- **一并译中文标题**：``cn_title`` 让卡片标题不再全是英文（中文读者第一眼友好）；
- **编辑口吻 + 质量守护**：prompt 走自然中文科技编辑风格（去 AI 味、保留专有名词），
  输出做套话清理与长度合理性校验；
- 仅依赖本地 Ollama，不引入任何第三方商业 API、不触合规红线。

失败模式（全部静默回退）：
  - Ollama 未运行 / 网络不可达
  - 模型不存在 / 推理超时（会按 retries 重试）
  - 输出几乎无中文 / 明显跑题（长度异常）→ 视为失败重试
"""
from __future__ import annotations

import concurrent.futures
import hashlib
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
# 译文 token 上限；摘要偏长，400 易截断，提到 600 更稳
DEFAULT_NUM_PREDICT = 600

# 编辑口吻 prompt：自然中文科技报道、去机翻套话、保留专有名词、只输出译文
_EDITOR_PROMPT = (
    "你是一名资深中文科技媒体编辑，负责把英文 AI 行业新闻摘要译成流畅中文。\n"
    "要求：用自然、地道的中文科技报道口吻，避免生硬机翻和「据悉/此外/值得注意的是」等套话；"
    "事实与数字必须准确，不增删原文信息，不添加任何评论或解释；"
    "OpenAI、GPT、Google、Meta 等公司/产品专有名词保留英文原样；"
    "只输出中文译文本身，不要写「以下是翻译」之类的说明。\n\n"
)
# 标题 prompt：更短、更克制，同样保留专有名词
_TITLE_PROMPT = (
    "你是一名资深中文科技媒体编辑。把下面这段英文新闻标题译成中文，\n"
    "要求：简洁、准确，保留专有名词（OpenAI/GPT/Google 等）英文原样，"
    "不增删信息、不添加修饰；只输出中文标题本身。\n\n"
)
_CJK_HAN = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]{2,}")
# 常见英文专有名词（用于软校验提示，不强制失败）
_PROPNOUN = re.compile(
    r"\b(OpenAI|GPT|Google|Meta|Microsoft|Anthropic|Claude|Gemini|Llama|"
    r"Mistral|DeepSeek|Qwen|Nvidia|NVDA|Apple|Amazon|IBM|Intel|AMD|Tesla|"
    r"xAI|Hugging Face|Stability AI|Perplexity|Cohere|Cursor|GitHub|"
    r"Sam Altman|Elon Musk)\b"
)


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


def _clean_translation(out: str) -> str:
    """清理模型偶尔带出的套话前缀/说明性包装。"""
    out = re.sub(
        r"^(翻译[：:]\s*|中文译文[：:]\s*|以下是翻译[：:]\s*|译文[：:]\s*|"
        r"【翻译】\s*|\[译文\]\s*)", "", out
    ).strip()
    # 去掉包裹引号（模型有时用 「」"" 包住整段）
    if len(out) >= 2 and out[0] in "「\"'（“" and out[-1] in "」\"'）”":
        out = out[1:-1].strip()
    return out


def _ollama_translate(text, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT,
                      num_predict=DEFAULT_NUM_PREDICT, prompt=_EDITOR_PROMPT,
                      client=None):
    """单次英文→中文，best-effort，失败返回 None。

    Args:
        text       — 英文原文；空串直接返回 None；
        model      — 本地 Ollama 模型标签（须与 ``ollama list`` 完全一致）；
        timeout    — 单条推理超时（秒）；
        num_predict— 译文 token 上限；
        prompt     — 系统/角色提示（摘要用 _EDITOR_PROMPT，标题用 _TITLE_PROMPT）；
        client     — **依赖注入点**，签名 ``f(url, payload, timeout) -> dict``；
                     None 时走真实 HTTP。单测传 mock 可完全脱离本地 Ollama。
    返回：中文译文 str；失败（不可达 / 超时 / 输出几乎无中文 / 明显跑题）返回 None。
    """
    if not text or not text.strip():
        return None
    url = ollama_base_url()
    payload = {"model": model, "prompt": prompt + text, "stream": False,
               "options": {"temperature": 0.1, "num_predict": num_predict}}
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
        out = _clean_translation(out)
        # 几乎无中文 -> 失败
        if len(_CJK_HAN.findall(out)) < 3:
            return None
        # 长度合理性：输入较长时译文不应过度膨胀（跑题/复读循环）
        if len(text) > 80 and len(out) > len(text) * 4:
            return None
        return out
    except Exception:  # noqa: BLE001  可选增强：任何失败都回退英文原文
        return None


# ── 本地译文缓存 ────────────────────────────────────────────────────
class _TranslateCache:
    """按 URL / 标题哈希落盘的译文缓存，避免每周重抓重译。

    键：优先用 article URL（稳定且唯一），缺 URL 时退化为 标题+信源 哈希。
    值：``{src_hash, cn_summary, cn_title}``；``src_hash`` 为原文哈希，
        内容变化时自动失效，避免脏缓存。
    """

    def __init__(self, path: Optional[str]):
        self.path = path
        self.data: dict = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f) or {}
            except Exception:
                self.data = {}

    @staticmethod
    def _key(item: dict) -> str:
        url = (item.get("url") or "").strip()
        if url:
            return "u:" + hashlib.sha1(url.encode("utf-8")).hexdigest()
        basis = (item.get("title", "") + "|" + item.get("source", ""))
        return "t:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()

    @staticmethod
    def _src_hash(src: str) -> str:
        return hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]

    def get(self, item: dict, src: str):
        if not self.path:
            return None
        v = self.data.get(self._key(item))
        if v and v.get("src_hash") == self._src_hash(src):
            return v
        return None

    def put(self, item: dict, src: str, cn_summary: str, cn_title: Optional[str]):
        if not self.path:
            return
        self.data[self._key(item)] = {
            "src_hash": self._src_hash(src),
            "cn_summary": cn_summary,
            "cn_title": cn_title or "",
        }

    def save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass  # 缓存写失败不阻断主流程


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
                 retries: int = DEFAULT_RETRIES, num_predict: int = DEFAULT_NUM_PREDICT,
                 translate_title: bool = True, cache_path: Optional[str] = None):
        self.enabled = enabled
        self.model = model
        self.timeout = timeout
        self.max_workers = max(1, int(max_workers))
        self.retries = max(0, int(retries))
        self.num_predict = max(50, int(num_predict))
        self.translate_title = translate_title
        self._cache = _TranslateCache(cache_path) if cache_path else None
        self._available: Optional[bool] = None   # 懒探测结果缓存
        # 可观测统计
        self.stats = {"translated": 0, "failed": 0, "cache_hit": 0, "skipped": 0}

    # ── 可用性 ──────────────────────────────────────────────────────
    def available(self) -> bool:
        """探测本地 Ollama 是否可用（含模型校验）；结果缓存，不重复 ping。"""
        if self._available is None:
            ok, _ = ollama_health(timeout=3.0, model=self.model)
            self._available = ok
        return self._available

    # ── 单条 ────────────────────────────────────────────────────────
    def translate(self, text: str, prompt: str = _EDITOR_PROMPT) -> Optional[str]:
        """翻译单段英文；未启用 / 空串 / 失败均返回 None（按 retries 重试）。"""
        if not self.enabled or not text or not text.strip():
            return None
        for _ in range(self.retries + 1):
            out = _ollama_translate(
                text, model=self.model, timeout=self.timeout,
                num_predict=self.num_predict, prompt=prompt)
            if out:
                return out
        return None

    def ensure(self, item: dict) -> dict:
        """即时为**单个**新闻条目补中文总结（原地写 ``cn_summary`` / ``cn_title``）。

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
            if self.translate_title and (item.get("title") or "").strip():
                t = self.translate(item["title"], prompt=_TITLE_PROMPT)
                if t:
                    item["cn_title"] = t
        return item

    # ── 批量（途中遇英文即并发中译）─────────────────────────────────
    def translate_items(self, items: Iterable[dict]) -> int:
        """就地给所有「英文且缺 cn_summary」的条目补中文总结（含中文标题）。

        返回成功翻译条数。未启用 / Ollama 不可用 → 立即返回 0（不空等）。
        使用受控线程池并发，单条失败按 retries 重试；命中本地缓存则零推理开销。
        """
        if not self.enabled:
            return 0
        targets = [it for it in items
                   if (it.get("lang") or _detect_lang(it.get("title", ""), it.get("summary", ""))) == "en"
                   and not it.get("cn_summary")]
        if not targets:
            return 0

        # 先查本地缓存（不依赖 Ollama）：命中即复用，即使 Ollama 离线也能用历史译文
        todo = []
        for it in targets:
            src = (it.get("summary") or it.get("title") or "").strip()
            cached = self._cache.get(it, src) if self._cache else None
            if cached:
                it["cn_summary"] = cached.get("cn_summary", "")
                if cached.get("cn_title"):
                    it["cn_title"] = cached["cn_title"]
                self.stats["cache_hit"] += 1
            else:
                todo.append((it, src))

        if not todo:
            print(f"  ♻️ 本地缓存命中 {self.stats['cache_hit']}/{len(targets)} 条"
                  f"（无需调用 Ollama）")
            return 0

        # 仍有未命中缓存的条目，才需要 Ollama；不可达则保留英文原文
        if not self.available():
            ok, detail = ollama_health(timeout=3.0, model=self.model)
            print(f"  ⚠️ 跳过英文中译（{len(todo)} 条未命中缓存且 Ollama 不可用："
                  f"{detail}）；已命中缓存 {self.stats['cache_hit']} 条仍复用")
            return 0
        print(f"  🩺 本地 Ollama 可用，新译 {len(todo)} 条英文报道"
              f"（缓存命中 {self.stats['cache_hit']} 条）")

        def worker(pair):
            it, src = pair
            cn = self.translate(src)
            cn_title = None
            if cn and self.translate_title:
                t = (it.get("title") or "").strip()
                if t:
                    cn_title = self.translate(t, prompt=_TITLE_PROMPT)
            return cn, cn_title

        n_done = 0
        if todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futs = {ex.submit(worker, p): p for p in todo}
                for fut in concurrent.futures.as_completed(futs):
                    cn, cn_title = fut.result()
                    if cn:
                        it = futs[fut][0]
                        it["cn_summary"] = cn
                        if cn_title:
                            it["cn_title"] = cn_title
                        if self._cache:
                            self._cache.put(it, futs[fut][1], cn, cn_title)
                        n_done += 1
                    else:
                        self.stats["failed"] += 1
            if self._cache:
                self._cache.save()

        done_total = n_done + self.stats["cache_hit"]
        print(f"  🌐 翻译统计：新译 {n_done} / 缓存命中 {self.stats['cache_hit']} "
              f"/ 失败 {self.stats['failed']}（共 {len(targets)} 条英文待译）")
        if done_total < len(targets):
            print(f"  ⚠️ 英文中译完成 {done_total}/{len(targets)} 条"
                  f"（其余因超时/失败保留英文原文）")
        return n_done


__all__ = [
    "Translator", "OllamaUnavailable",
    "ollama_base_url", "ollama_health", "_ollama_translate",
    "DEFAULT_MODEL", "DEFAULT_TIMEOUT", "DEFAULT_WORKERS", "DEFAULT_RETRIES",
    "DEFAULT_NUM_PREDICT",
]
