"""最小示例：一键转写 + 拿到带说话人/时间戳的分段结果。

运行前：export SONIC_TOKEN=你的token（F12 -> Network -> /api 请求头）
"""

import os

from sonicrhino import Client, parse_export_text

token = os.environ["SONIC_TOKEN"]
c = Client(token, language="zh")  # 中英混说课程也用 zh

# 方式一：一键流程（上传 -> 轮询 -> 导出 -> 解析）
segments = c.transcribe("lecture.wav", language="zh")
for seg in segments[:10]:
    print(f"[{seg.start:7.1f} -> {seg.end:7.1f}] {seg.speaker}: {seg.text[:40]}")

# 方式二：分步控制（比如批量提交后再统一收结果）
task_id = c.upload("interview.mp3", language="zh")
print("已提交:", task_id)
# ... 做别的事，或提交更多任务（实测 20 个任务会并行转写）...
c.wait(task_id)
text = c.export_text(task_id)          # 带说话人 + 时间戳的原始文本
segments = parse_export_text(text)     # 同样可解析为结构化分段
print(segments[-1].text)
