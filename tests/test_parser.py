"""parser 的离线单测（不访问网络）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sonicrhino import (
    Segment, parse_export_text, resolve_language, segments_from_record_list,
)

SAMPLE = """说话人1   00:00:01 --> 00:00:04
大家好，今天我们开始上课。
说话人2   00:00:05 --> 00:00:09
Hello everyone, let's get started.
说话人1   00:00:10 --> 00:00:15
这节课我们讲第一章，
主要介绍基本概念。
"""


def test_parse_export_text_basic():
    segs = parse_export_text(SAMPLE)
    assert len(segs) == 3
    assert segs[0] == Segment(start=1.0, end=4.0, speaker="说话人1",
                              text="大家好，今天我们开始上课。")
    assert segs[1].speaker == "说话人2"
    assert segs[1].text.startswith("Hello everyone")


def test_parse_export_text_multiline():
    segs = parse_export_text(SAMPLE)
    # 一个说话人段内的多行正文应合并为一条
    assert segs[2].text == "这节课我们讲第一章，主要介绍基本概念。"
    assert segs[2].start == 10.0 and segs[2].end == 15.0


def test_parse_export_text_hours():
    segs = parse_export_text("说话人1   01:02:03 --> 01:02:05\n长录音")
    assert segs[0].start == 3600 + 2 * 60 + 3
    assert segs[0].end == 3600 + 2 * 60 + 5


def test_parse_export_text_empty_raises():
    with pytest.raises(ValueError):
        parse_export_text("")
    with pytest.raises(ValueError):
        parse_export_text("没有时间戳行的普通文本")


def test_segments_from_record_list():
    rows = [
        {"s": 1000, "e": 4000, "role": 1, "text": " 第一句 "},
        {"s": 5000, "e": 9000, "role": 2, "text": "第二句"},
        {"s": 9500, "e": 9800, "role": 1, "text": ""},  # 空行应被跳过
    ]
    segs = segments_from_record_list(rows)
    assert len(segs) == 2
    assert segs[0].start == 1.0 and segs[0].end == 4.0
    assert segs[0].speaker == "说话人1"
    assert segs[0].text == "第一句"
    assert segs[1].speaker == "说话人2"

    with pytest.raises(ValueError):
        segments_from_record_list([])


def test_resolve_language():
    assert resolve_language("zh") == "0"
    assert resolve_language("en") == "1"
    assert resolve_language("fr") == "10"
    assert resolve_language("yue") == "4"
    assert resolve_language("0") == "0"          # 直接传 type 原样返回
    assert resolve_language("100") == "100"
    assert resolve_language(None) == "0"          # 无 auto，按中文
    assert resolve_language("auto") == "0"
    with pytest.raises(ValueError):
        resolve_language("xx")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
