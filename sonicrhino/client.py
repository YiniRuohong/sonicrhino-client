"""声云语音转写（sonicrhino.cc）非官方 Python 客户端。

接口契约逆向自 pc.sonicrhino.cc 前端 v1.3.2（Vue SPA），转写引擎为讯飞听见。
本项目与声云官方无关，仅供个人学习研究、自动化操作自己的已购账户；
请遵守服务条款，接口随时可能变动。

认证方式：HTTP 请求头 ``token: <值>``（不走 cookie）。token 在浏览器登录
pc.sonicrhino.cc 后，F12 -> Network -> 任意 /api 请求的 Request Headers 里
（前端存于 IndexedDB localforage 的 "token" 键）。
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

from .langs import resolve_language

BASE = "https://pc.sonicrhino.cc"
EXPORT_HOST = "https://voice.sonicrhino.cc"

# 任务状态（GET /api/voice/index 的 status 字段）
STATUS_UNPAID = 0    # 未支付
STATUS_RUNNING = 1   # 处理中
STATUS_DONE = 2      # 已完成
STATUS_FAILED = -1   # 失败
STATUS_NAMES = {0: "未支付", 1: "处理中", 2: "已完成", -1: "失败"}

# 平台限制
MAX_FILE_GB = 1.5        # 单文件上限
MAX_DURATION_SEC = 18000  # 单任务时长上限（5 小时）


class SonicrhinoError(Exception):
    """声云客户端错误基类。"""


class TokenExpiredError(SonicrhinoError):
    """token 已失效（code 4001），需要到网页重新抓取。"""


class StorageFullError(SonicrhinoError):
    """云端存储空间已满（code 6001）。"""


class QuotaInsufficientError(SonicrhinoError):
    """剩余转写时长不足（code 6003）。"""


class TaskFailedError(SonicrhinoError):
    """云端转写任务失败（status -1）。"""


class PollTimeoutError(SonicrhinoError):
    """轮询超时（任务仍在处理中，额度已扣，可稍后取结果）。"""


@dataclass
class Segment:
    """一条转写片段。start/end 单位为秒。"""

    start: float
    end: float
    speaker: str  # 如 "说话人1"；无分离信息时为空串
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def probe_duration(path: str | Path) -> float:
    """用 ffprobe 读取音频时长（秒）。未安装 ffprobe 时抛 SonicrhinoError。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError as e:
        raise SonicrhinoError(
            "未找到 ffprobe（brew install ffmpeg / apt install ffmpeg），"
            "或手动传 times_sec 跳过时长探测"
        ) from e
    except subprocess.CalledProcessError as e:
        raise SonicrhinoError(f"ffprobe 无法读取音频时长: {path}\n{e.stderr}") from e
    return float(json.loads(out)["format"]["duration"])


class Client:
    """声云语音转写客户端。

    :param token: 登录 token（浏览器 F12 -> Network -> /api 请求头里的 ``token``）
    :param language: 默认语言，本地代号（``zh``/``en``/``fr``...）或声云 type
    :param poll_interval: ``wait``/``transcribe`` 的轮询间隔秒数
    :param poll_timeout: ``wait``/``transcribe`` 的轮询超时秒数
    :param timeout: 单个 HTTP 请求超时秒数

    最简用法::

        from sonicrhino import Client

        c = Client(token="...")
        segments = c.transcribe("lecture.wav", language="zh")
    """

    def __init__(self, token: str, language: str = "zh",
                 poll_interval: float = 15.0, poll_timeout: float = 3600.0,
                 timeout: float = 120.0, base: str = BASE,
                 export_host: str = EXPORT_HOST):
        if not token:
            raise SonicrhinoError(
                "缺少 token：浏览器登录 pc.sonicrhino.cc 后 F12 -> Network -> "
                "任意 /api 请求的 Request Headers 里的 token"
            )
        self.language = resolve_language(language)
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.timeout = timeout
        self.base = base.rstrip("/")
        self.export_host = export_host.rstrip("/")
        self.s = requests.Session()
        self.s.headers["token"] = token
        self.s.headers["Origin"] = self.base
        self.s.headers["Referer"] = self.base + "/"

    # ---- 基础 ----

    def _unwrap(self, resp_json: dict, step: str):
        """校验 ``{code, msg, time, data}`` 封套：code=1 成功。"""
        code = resp_json.get("code")
        if code == 1:
            return resp_json.get("data")
        msg = resp_json.get("msg", "")
        if code == 4001:
            raise TokenExpiredError(
                f"token 已失效（4001），请到网页 F12 -> Network 重新抓取 token"
            )
        if code == 6001:
            raise StorageFullError(f"{step}: 云端存储空间已满（6001）{msg}")
        if code == 6003:
            raise QuotaInsufficientError(f"{step}: 剩余转写时长不足（6003）{msg}")
        raise SonicrhinoError(f"{step} 失败: code={code} msg={msg}")

    def _get(self, path: str, **kw):
        r = self.s.get(self.base + path, timeout=self.timeout, **kw)
        return self._unwrap(r.json(), path)

    def _post(self, path: str, **kw):
        r = self.s.post(self.base + path, timeout=self.timeout, **kw)
        return self._unwrap(r.json(), path)

    # ---- 账户 / 字典 ----

    def userinfo(self) -> dict:
        """GET /api/passport/userinfo —— 用户信息与时长额度。"""
        return self._get("/api/passport/userinfo")

    def quota(self, userinfo: dict | None = None) -> tuple[float, float]:
        """返回 (剩余分钟, 总分钟)。

        注意：userinfo 里 ``time.time_use`` 字段名有误导，实测实为**剩余**分钟，
        ``time.time_total`` 为总分钟；另一组 ``user.income``/``user.total``
        （单位秒）口径与之对应（income=总额秒数，total=剩余秒数）。
        :param userinfo: 已取到的 userinfo 返回值，传入可省一次请求。
        """
        t = ((userinfo if userinfo is not None else self.userinfo()) or {}).get("time") or {}
        return float(t.get("time_use", 0) or 0), float(t.get("time_total", 0) or 0)

    def lang_list(self) -> list[dict]:
        """GET /api/ajax/langList —— 完整语言列表（公开接口，无需登录）。"""
        r = self.s.get(self.base + "/api/ajax/langList", timeout=self.timeout)
        return self._unwrap(r.json(), "/api/ajax/langList") or []

    # ---- 任务生命周期 ----

    def check(self, times_sec: float) -> None:
        """POST /api/voice/checkBeforeAddTask —— 提交前预检（时长够不够等）。

        可提交时静默返回；存储满 / 时长不足分别抛
        :class:`StorageFullError` / :class:`QuotaInsufficientError`。
        """
        self._post("/api/voice/checkBeforeAddTask", json={"times": times_sec})

    def upload(self, path: str | Path, language: str | None = None,
               times_sec: float | None = None, title: str | None = None,
               is_sync: bool = True) -> int:
        """POST /api/voice/addTask —— 上传音频并创建任务，返回任务 id。

        :param times_sec: 音频时长（秒）；缺省时用 ffprobe 自动探测。
        :param title: 任务标题；缺省取文件名去扩展名。
        """
        path = Path(path)
        if not path.is_file():
            raise SonicrhinoError(f"文件不存在: {path}")
        size_gb = path.stat().st_size / 1024 ** 3
        if size_gb > MAX_FILE_GB:
            raise SonicrhinoError(
                f"文件 {size_gb:.2f}GB 超过声云 {MAX_FILE_GB}GB 上限，请分段或压缩"
            )
        if times_sec is None:
            times_sec = probe_duration(path)
        times_sec = int(round(times_sec))
        if times_sec <= 0:
            raise SonicrhinoError(f"无法读取音频时长: {path}")
        if times_sec > MAX_DURATION_SEC:
            raise SonicrhinoError(f"时长 {times_sec}s 超过声云 5 小时上限")

        lang = resolve_language(self.language if language is None else language)
        with open(path, "rb") as f:
            data = self._post(
                "/api/voice/addTask",
                files={"file": (path.name, f)},
                data={
                    "language": lang,
                    "times": str(times_sec),
                    "is_sync": "true" if is_sync else "false",
                    "title": title or path.stem,
                },
                timeout=max(self.timeout, 1800),  # 大文件上传放宽
            )
        task_id = (data or {}).get("voiceId") or (data or {}).get("id")
        if not task_id:
            raise SonicrhinoError(f"addTask 响应缺少任务 id: {data}")
        return int(task_id)

    def tasks(self, page: int = 1, limit: int = 20) -> list[dict]:
        """GET /api/voice/index —— 任务列表（最新在前）。"""
        rows = self._get("/api/voice/index", params={"page": page, "limit": limit})
        return rows or []

    def task(self, task_id: int) -> dict | None:
        """从任务列表里找指定 id 的任务（找不到返回 None）。"""
        for row in self.tasks(page=1, limit=50):
            if int(row.get("id", 0)) == int(task_id):
                return row
        return None

    def find(self, task_id: int) -> dict:
        """GET /api/voice/find —— 任务详情（转写内容在 ``record_list`` 数组，
        每项含 ``s``/``e`` 毫秒时间戳 + ``role`` 说话人 + ``text``）。"""
        return self._get("/api/voice/find", params={"id": int(task_id)}) or {}

    def find_segments(self, task_id: int) -> list[Segment]:
        """find + 解析 record_list 为 Segment 列表。"""
        from .parser import segments_from_record_list
        return segments_from_record_list(self.find(task_id).get("record_list") or [])

    def wait(self, task_id: int, interval: float | None = None,
             timeout: float | None = None, on_poll=None) -> int:
        """轮询任务直到完成，返回最终 status（2=完成）。

        :param on_poll: 可选回调 ``on_poll(status)``，每轮收到当前状态。
        :raises TaskFailedError: status == -1
        :raises PollTimeoutError: 超时（任务仍处理中，额度已扣，可稍后取结果）
        """
        interval = self.poll_interval if interval is None else interval
        deadline = time.time() + (self.poll_timeout if timeout is None else timeout)
        while time.time() < deadline:
            row = self.task(task_id)
            status = int(row["status"]) if row and row.get("status") is not None else None
            if on_poll and status is not None:
                on_poll(status)
            if status == STATUS_DONE:
                return status
            if status == STATUS_FAILED:
                raise TaskFailedError(f"云端任务 #{task_id} 转写失败")
            time.sleep(interval)
        raise PollTimeoutError(
            f"云端任务 #{task_id} 轮询超时；额度已扣，可稍后用 find/export 取结果"
        )

    # ---- 导出 ----

    def export(self, task_id: int, export_type: str = "txt",
               role: int = 1, time_stamps: int = 1) -> str | bytes:
        """GET {EXPORT_HOST}/api/voice/export —— 导出转写结果。

        :param export_type: ``"txt"`` 返回 str；``"doc"`` 返回 docx 的 bytes；
            （``"srt"`` 实测返回的也是 docx 二进制，未细究）
        :param role: 1=带说话人分离，0=不带
        :param time_stamps: 1=带时间戳，0=不带
        """
        r = self.s.get(
            self.export_host + "/api/voice/export",
            params={
                "id": int(task_id), "type": export_type,
                "textType": "text", "role": role, "time": time_stamps,
                "pa": 1, "tone": 1,
            },
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise SonicrhinoError(f"导出失败: HTTP {r.status_code}")
        return r.text if export_type == "txt" else r.content

    def export_text(self, task_id: int) -> str:
        """导出带说话人 + 时间戳的纯文本（role=1&time=1，可用 parse_export_text 解析）。"""
        text = self.export(task_id, export_type="txt", role=1, time_stamps=1)
        assert isinstance(text, str)
        return text

    def export_docx(self, task_id: int) -> bytes:
        """导出 docx 文件的字节串，自行写入 .docx。"""
        data = self.export(task_id, export_type="doc")
        assert isinstance(data, bytes)
        return data

    # ---- 删除 ----

    def delete(self, task_id: int, hard: bool = False) -> None:
        """删除任务。``hard=False`` 软删除进回收站（POST /api/voice/del），
        ``hard=True`` 彻底删除（POST /api/voice/destroy）。"""
        path = "/api/voice/destroy" if hard else "/api/voice/del"
        self._post(path, json={"id": int(task_id)})

    # ---- 一键流程 ----

    def transcribe(self, path: str | Path, language: str | None = None,
                   title: str | None = None, on_event=None) -> list[Segment]:
        """上传 -> 预检 -> 轮询 -> 导出 -> 解析，返回 Segment 列表。

        :param on_event: 可选进度回调 ``on_event(event: str, **info)``，
            依次收到 ``check`` / ``upload_start`` / ``uploaded`` /
            ``poll`` / ``done``。
        """
        def emit(ev: str, **info):
            if on_event:
                on_event(ev, **info)

        times = probe_duration(path)
        emit("check", times=times)
        self.check(times)

        emit("upload_start", path=str(path))
        t0 = time.time()
        task_id = self.upload(path, language=language, times_sec=times, title=title)
        emit("uploaded", task_id=task_id, seconds=time.time() - t0)

        self.wait(task_id, on_poll=lambda st: emit("poll", status=st))

        segments = self._parse_export(task_id)
        emit("done", task_id=task_id, segments=len(segments))
        return segments

    def _parse_export(self, task_id: int) -> list[Segment]:
        from .parser import parse_export_text
        return parse_export_text(self.export_text(task_id))
