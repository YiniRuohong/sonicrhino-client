"""解析声云两种转写结果格式为统一的 Segment 列表。"""

from __future__ import annotations

import re
from .client import Segment

# 「说话人1  00:00:01 --> 00:00:04」时间戳行
_TS_LINE = re.compile(
    r"^(说话人\d+)\s+(\d{1,2}:\d{2}:\d{2})\s*-->\s*(\d{1,2}:\d{2}:\d{2})\s*$"
)


def _hms_to_sec(s: str) -> float:
    h, m, sec = (int(x) for x in s.split(":"))
    return h * 3600 + m * 60 + sec


def parse_export_text(raw: str) -> list[Segment]:
    """解析 export 接口 ``role=1&time=1`` 导出的 txt 文本。

    格式（说话人标签行 + 时间戳行 + 正文若干行）::

        说话人1   00:00:01 --> 00:00:04
        今天我们讲第三章。
        说话人2   00:00:05 --> 00:00:09
        Hello everyone.

    返回按时间排序的 Segment 列表；解析结果为空时抛 ValueError
    （通常意味着任务未完成或导出格式变化）。
    """
    segments: list[Segment] = []
    cur: list[str] = []          # 当前分段的正文行
    cur_meta: tuple[float, float, str] | None = None

    def flush() -> None:
        if cur_meta and cur:
            start, end, who = cur_meta
            text = "".join(cur).strip()
            if text:
                segments.append(Segment(start=start, end=end, speaker=who, text=text))

    for line in raw.splitlines():
        m = _TS_LINE.match(line.strip())
        if m:
            flush()
            cur = []
            cur_meta = (
                _hms_to_sec(m.group(2)),
                _hms_to_sec(m.group(3)),
                m.group(1),
            )
        elif cur_meta is not None:
            cur.append(line)
    flush()

    if not segments:
        raise ValueError(
            "导出文本解析为空：任务可能尚未完成，或导出格式已变化"
        )
    return segments


def segments_from_record_list(record_list: list[dict]) -> list[Segment]:
    """解析 find 接口返回的 ``record_list``（带 s/e 毫秒 + role + text）。"""
    segments: list[Segment] = []
    for row in record_list or []:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        role = row.get("role")
        segments.append(
            Segment(
                start=(row.get("s") or 0) / 1000.0,
                end=(row.get("e") or 0) / 1000.0,
                speaker=f"说话人{role}" if role not in (None, "") else "",
                text=text,
            )
        )
    if not segments:
        raise ValueError("record_list 为空：任务可能尚未完成")
    return segments
