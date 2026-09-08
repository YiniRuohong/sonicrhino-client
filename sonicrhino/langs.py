"""语言代码表：本地习惯写法 <-> 声云 language type。

声云的 language 参数取自 GET /api/ajax/langList 返回的 ``type`` 字符串
（约 128 种固定语言，**没有 auto 自动检测**）。下表只收录常用项，
完整列表可用 ``Client.lang_list()`` 或 ``sonicrhino langs`` 在线查询。
"""

from __future__ import annotations

# 本地语言代号 -> 声云 language type
LANGUAGE_CODES = {
    "zh": "0",        # 中文（中英混说课程建议用中文模式）
    "zh-Hant": "100",  # 中文繁体
    "yue": "4",       # 粤语
    "en": "1",
    "ja": "2",
    "ko": "3",
    "ru": "5",
    "ar": "6",
    "es": "7",
    "it": "8",
    "vi": "9",
    "fr": "10",
    "de": "11",
}

# type -> 展示名（与 sonicrhino langs 输出保持一致）
LANGUAGE_NAMES = {
    "0": "中文",
    "100": "中文繁体",
    "4": "粤语",
    "1": "English",
    "2": "日本語",
    "3": "한국어",
    "5": "Русский",
    "6": "العربية",
    "7": "Español",
    "8": "Italiano",
    "9": "Tiếng Việt",
    "10": "Français",
    "11": "Deutsch",
}


def resolve_language(language: str | None) -> str:
    """把 ``zh`` / ``en`` / ``"0"`` 之类的输入解析为声云的 language type 字符串。

    - 直接传 type（如 ``"0"``、``"100"``）原样返回；
    - 传本地代号（如 ``zh``、``fr``）映射为对应 type；
    - ``None`` / ``"auto"`` 返回 ``"0"``（中文）：声云没有 auto，
      实测中文模式下讯飞引擎也能正确转出夹带的英文词，
      反过来用英语模式转中文课只会得到幻觉文本。
    - 未知代号抛 :class:`ValueError`。
    """
    if language in (None, "", "auto"):
        return LANGUAGE_CODES["zh"]
    if language in LANGUAGE_CODES.values():
        return language
    if language in LANGUAGE_CODES:
        return LANGUAGE_CODES[language]
    raise ValueError(
        f"未知语言代号 {language!r}；支持：{', '.join(LANGUAGE_CODES)}"
        "（或直接传声云 type，完整列表见 sonicrhino langs）"
    )
