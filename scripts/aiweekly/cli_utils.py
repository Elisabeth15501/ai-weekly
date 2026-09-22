# -*- coding: utf-8 -*-
"""构建时通用工具 —— 从 `generate_site.py` 主入口下沉，守住 P0#4「主入口 ≤500 行」硬上限。

内容：
  * ``_CountingWriter``  —— 包裹 stdout，统计本次运行的 ⚠️/❌ 并收集告警原文
  * ``_parse_csv_arg``   —— CLI 逗号串 -> 列表
  * ``_parse_num_arg``   —— CLI 逗号串 -> float 列表（含非数字则告警并回退 None）

设计说明：
  这三个工具与「生成引擎」的业务逻辑无关，属纯 CLI/IO 适配层，故独立成模块。
  命名沿用迁移前的下划线前缀，保持调用点零改动（与 ``leaderboard_fetch`` 迁移
  ``_collect_source_results`` / ``_record_health`` 的做法一致）。
"""
from __future__ import annotations


class _CountingWriter:
    """P1#12：统计 ⚠️/❌ 并收集告警原文，供末尾 print_user_hints() 翻译成人话。"""

    def __init__(self, stream):
        self._stream = stream
        self.warns = 0
        self.errors = 0
        self.messages: list[str] = []

    def write(self, s: str) -> int:
        if "⚠️" in s:
            self.warns += s.count("⚠️")
            self.messages.append(s.strip())
        if "❌" in s:
            self.errors += s.count("❌")
            self.messages.append(s.strip())
        return self._stream.write(s)

    def flush(self):
        return self._stream.flush()


def _parse_csv_arg(s: str):
    """CLI 逗号字符串 -> 列表；空串返回 None。"""
    return [x.strip() for x in s.split(",")] if s else None


def _parse_num_arg(s: str):
    """CLI 逗号字符串 -> float 列表；含非数字告警并回退 None。"""
    if not s:
        return None
    try:
        return [float(x) for x in s.split(",")]
    except ValueError:
        print(f"  ⚠️ 图表数据解析失败(含非数字): {s} — 将回退估算值")
        return None


__all__ = ["_CountingWriter", "_parse_csv_arg", "_parse_num_arg"]
