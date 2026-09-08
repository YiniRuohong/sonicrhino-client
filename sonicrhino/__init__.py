"""声云语音转写（sonicrhino.cc）非官方 Python 客户端。"""

from .client import (  # noqa: F401
    BASE,
    EXPORT_HOST,
    STATUS_NAMES,
    Client,
    PollTimeoutError,
    QuotaInsufficientError,
    Segment,
    SonicrhinoError,
    StorageFullError,
    TaskFailedError,
    TokenExpiredError,
    probe_duration,
)
from .langs import LANGUAGE_CODES, LANGUAGE_NAMES, resolve_language  # noqa: F401
from .parser import parse_export_text, segments_from_record_list  # noqa: F401

__version__ = "0.1.0"
__all__ = [
    "Client", "Segment", "SonicrhinoError", "TokenExpiredError",
    "StorageFullError", "QuotaInsufficientError", "TaskFailedError",
    "PollTimeoutError", "probe_duration", "parse_export_text",
    "segments_from_record_list", "resolve_language", "LANGUAGE_CODES",
    "LANGUAGE_NAMES", "STATUS_NAMES", "BASE", "EXPORT_HOST",
]
