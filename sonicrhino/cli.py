#!/usr/bin/env python3
"""声云语音转写命令行工具。

token 优先级：--token 参数 > 环境变量 SONIC_TOKEN。
退出码：0 成功；1 一般错误；2 token 失效。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .client import (
    STATUS_NAMES, Client, SonicrhinoError, TokenExpiredError, probe_duration,
)
from .langs import LANGUAGE_CODES, LANGUAGE_NAMES, resolve_language


def _client(args) -> Client:
    token = args.token or os.environ.get("SONIC_TOKEN", "")
    if not token:
        sys.exit(
            "需要 --token 或环境变量 SONIC_TOKEN"
            "（浏览器 F12 -> Network -> 任意 /api 请求头里的 token）"
        )
    return Client(token)


def _fmt_seconds(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def _save_transcript(segments, audio: Path, out_dir: Path | None = None):
    """把 Segment 列表写成 <stem>.txt + <stem>.segments.json，返回 txt 路径。"""
    out_dir = out_dir or audio.parent
    txt = out_dir / (audio.stem + ".txt")
    js = out_dir / (audio.stem + ".segments.json")
    txt.write_text(
        "\n".join(
            f"[{s.speaker}] {s.text}" if s.speaker else s.text
            for s in segments
        ) + "\n",
        encoding="utf-8",
    )
    js.write_text(
        json.dumps([s.to_dict() for s in segments], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return txt


# ---- 子命令 ----

def cmd_whoami(args):
    c = _client(args)
    d = c.userinfo() or {}
    user = d.get("user") or {}
    left, total = c.quota(d)
    name = user.get("nickname") or user.get("id") or "?"
    vip = user.get("vip_type_name") or ""
    print(f"[token 有效] 用户: {name}{'（' + vip + '）' if vip else ''}")
    print(f"时长额度: 剩余 {left:.1f} 分钟 / 共 {total:.1f} 分钟")
    print("（注：计费口径低于音频时长，长静音段基本不扣）")


def cmd_langs(args):
    print("常用语言（本地代号 -> 声云 type）：")
    for code, t in LANGUAGE_CODES.items():
        print(f"  {code:<8} -> {t:<4} {LANGUAGE_NAMES.get(t, '')}")
    print("\n声云没有 auto 自动检测；auto 一律按中文处理。")
    if args.online:
        c = _client(args)
        print("\n在线 langList（完整 %d 种）：" % len(c.lang_list()))
        for row in c.lang_list():
            print(f"  {row.get('type'):<6} {row.get('name', row.get('title', ''))}")


def cmd_submit(args):
    c = _client(args)
    path = Path(args.file).expanduser()
    title = args.title or path.stem
    lang = resolve_language(args.lang)
    print(f"[预检] {title}  语言 {LANGUAGE_NAMES.get(lang, lang)}")
    c.check(probe_duration(path) if not args.times else args.times)
    print("[上传中]（大文件可能较慢）...")
    t0 = time.time()
    task_id = c.upload(path, language=args.lang, times_sec=args.times,
                       title=title)
    print(f"[已提交] 任务 #{task_id}（上传 {time.time() - t0:.0f}s）")
    if not args.poll:
        print(f"稍后取结果：sonicrhino export {task_id} -o {path.stem}.txt")
        return
    _poll_and_export(c, task_id, path, args)


def _poll_and_export(c: Client, task_id: int, audio: Path, args):
    print(f"[轮询] 每 {c.poll_interval:.0f}s 一次，最长 {args.timeout:.0f}s ...")
    c.wait(task_id, timeout=args.timeout,
           on_poll=lambda st: print(f"  {time.strftime('%H:%M:%S')} "
                                    f"status={st}（{STATUS_NAMES.get(st, st)}）"))
    txt = _save_transcript(c._parse_export(task_id), audio)
    print(f"[完成] 转写已保存: {txt}")


def cmd_transcribe(args):
    c = _client(args)
    path = Path(args.file).expanduser()

    def on_event(ev, **info):
        if ev == "check":
            print(f"[预检] {path.name}  {info['times']}s  "
                  f"语言 {LANGUAGE_NAMES.get(c.language, c.language)}")
        elif ev == "uploaded":
            print(f"[已提交] 任务 #{info['task_id']}（上传 {info['seconds']:.0f}s）")
        elif ev == "poll":
            print(f"  {time.strftime('%H:%M:%S')} status={info['status']}"
                  f"（{STATUS_NAMES.get(info['status'], info['status'])}）")

    c.language = resolve_language(args.lang)
    segments = c.transcribe(path, language=args.lang, on_event=on_event)
    txt = _save_transcript(segments, path)
    total = segments[-1].end if segments else 0
    print(f"[完成] {len(segments)} 个片段，共 {_fmt_seconds(total)} -> {txt}")


def cmd_list(args):
    c = _client(args)
    rows = c.tasks(page=args.page, limit=args.limit)
    if not rows:
        print("（无任务）")
        return
    print(f"{'id':<10} {'状态':<6} {'时长':<10} 标题")
    for r in rows:
        st = int(r.get("status", 0))
        dur = r.get("times") or r.get("time") or ""
        dur = f"{dur}s" if dur else ""
        print(f"{r.get('id', ''):<10} {STATUS_NAMES.get(st, st):<6} "
              f"{dur:<10} {r.get('title', '')}")


def cmd_find(args):
    c = _client(args)
    d = c.find(args.id)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2)[:8000])
        return
    st = int(d.get("status", 0))
    print(f"任务 #{d.get('id')}  {STATUS_NAMES.get(st, st)}  {d.get('title', '')}")
    for seg in c.find_segments(args.id):
        print(f"  [{_fmt_seconds(seg.start)}-{_fmt_seconds(seg.end)}] "
              f"{seg.speaker}: {seg.text}")


def cmd_export(args):
    c = _client(args)
    if args.type == "docx":
        data = c.export_docx(args.id)
        out = Path(args.out) if args.out else Path(f"{args.id}.docx")
        out.write_bytes(data)
    else:
        text = c.export_text(args.id)
        out = Path(args.out) if args.out else Path(f"{args.id}.txt")
        out.write_text(text, encoding="utf-8")
    size = out.stat().st_size
    print(f"[已导出] {out}（{size} 字节）")


def cmd_delete(args):
    c = _client(args)
    c.delete(args.id, hard=args.hard)
    verb = "彻底删除" if args.hard else "移入回收站"
    print(f"[{verb}] 任务 #{args.id}")


# ---- 入口 ----

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sonicrhino",
        description="声云语音转写（sonicrhino.cc）非官方 CLI",
    )
    ap.add_argument("--token", default="", help="登录 token（默认取环境变量 SONIC_TOKEN）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("whoami", help="校验 token 并显示剩余额度")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("langs", help="列出支持的语言")
    p.add_argument("--online", action="store_true", help="拉取在线完整语言列表")
    p.set_defaults(func=cmd_langs)

    p = sub.add_parser("submit", help="上传音频创建任务")
    p.add_argument("file", help="音频文件路径")
    p.add_argument("--lang", default="zh", help="语言代号，默认 zh（见 langs）")
    p.add_argument("--title", default="", help="任务标题，默认取文件名")
    p.add_argument("--times", type=float, help="音频时长秒数（缺省用 ffprobe 探测）")
    p.add_argument("--poll", action="store_true", help="提交后轮询直到完成")
    p.add_argument("--timeout", type=float, default=3600, help="轮询超时秒数")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("transcribe", help="一键：上传+轮询+导出带说话人时间戳的转写稿")
    p.add_argument("file", help="音频文件路径")
    p.add_argument("--lang", default="zh", help="语言代号，默认 zh（见 langs）")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("list", help="任务列表")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("find", help="任务详情与分段内容")
    p.add_argument("id", type=int)
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("export", help="导出转写结果（txt/docx）")
    p.add_argument("id", type=int)
    p.add_argument("--type", choices=["txt", "docx"], default="txt")
    p.add_argument("-o", "--out", help="输出文件路径")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("delete", help="删除任务（默认进回收站）")
    p.add_argument("id", type=int)
    p.add_argument("--hard", action="store_true", help="彻底删除（不可恢复）")
    p.set_defaults(func=cmd_delete)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except TokenExpiredError as e:
        print(f"[token 失效] {e}", file=sys.stderr)
        return 2
    except SonicrhinoError as e:
        print(f"[失败] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
