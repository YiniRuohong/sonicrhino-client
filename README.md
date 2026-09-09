# sonicrhino-client

声云语音转写（[pc.sonicrhino.cc](https://pc.sonicrhino.cc)，转写引擎为讯飞听见）的**非官方** Python 客户端与命令行工具：上传音频 → 轮询进度 → 导出带**说话人分离 + 时间戳**的转写稿，也能直接导出 docx / 分段 JSON，适合把课堂录音、访谈、播客批量接入自己的自动化流程。

> [!WARNING]
> - 本项目与声云 / 讯飞官方无关，接口由前端（v1.3.2）逆向所得，**随时可能变动**。
> - 仅供个人学习研究与自动化操作**自己的已购账户**，请遵守服务条款；商用/滥用后果自负。
> - 需要自行拥有声云账户（新账户有免费体验时长，年费会员 6120 分钟）。

**特别感谢 LINUX DO（ https://linux.do ） 社区提供的交流与推广平台。**


## 安装

需要 Python ≥ 3.9；探测音频时长依赖 `ffprobe`（`brew install ffmpeg` / `apt install ffmpeg`）。

```bash
pip install git+https://github.com/YiniRuohong/sonicrhino-client.git
# 或本地开发
git clone https://github.com/YiniRuohong/sonicrhino-client.git
cd sonicrhino-client && pip install -e ".[dev]"
```

## 获取 token

声云的 API 认证走 **HTTP 请求头 `token`**（不是 cookie）：

1. 浏览器打开 [pc.sonicrhino.cc](https://pc.sonicrhino.cc) 并登录；
2. F12 → Network → 随便点出一个 `/api` 请求 → Request Headers 里的 `token` 值；
3. `export SONIC_TOKEN=<值>`，或之后所有命令传 `--token <值>`。

token 是 36 位十六进制的服务端会话串（非 JWT）：无刷新机制、失效时接口返回 `code=4001`；实测存活超过 39 小时，且浏览器重新登录**不会**挤掉旧 token（多会话共存），失效后重新抓一次即可。

## CLI 快速上手

```bash
# 校验 token、看剩余额度
sonicrhino whoami

# 一键转写：上传 + 轮询 + 导出（生成 lecture.txt 与 lecture.segments.json）
sonicrhino transcribe lecture.wav --lang zh

# 只要提交、稍后自己收结果
sonicrhino submit lecture.wav --lang zh
sonicrhino list
sonicrhino export 372334 -o lecture.txt      # 或 --type docx 导出 Word

# 查看某任务分段内容 / 删除任务
sonicrhino find 372334
sonicrhino delete 372334 [--hard]
```

转写稿格式（`transcribe` 产出的 txt，说话人并入正文，方便喂给 LLM）：

```
[说话人1] 大家好，今天我们开始上课。
[说话人2] Hello everyone.
```

`*.segments.json` 则是结构化分段：`[{"start": 1.0, "end": 4.0, "speaker": "说话人1", "text": "..."}]`。

## Python API

```python
from sonicrhino import Client, parse_export_text

c = Client(token, language="zh")

# 一键流程
segments = c.transcribe("lecture.wav", language="zh")

# 或分步控制（可先批量提交再统一收结果，实测 20 任务并行转写不排队）
task_id = c.upload("lecture.wav", language="zh")
c.wait(task_id)                     # 轮询直到完成/失败/超时
for seg in c.find_segments(task_id):
    print(seg.start, seg.end, seg.speaker, seg.text)

c.export_docx(task_id)              # bytes，写入 .docx 即可
c.delete(task_id)                   # 软删除进回收站；hard=True 彻底删除
```

错误均为 `SonicrhinoError` 子类，可分别捕获：`TokenExpiredError`（4001）、`StorageFullError`（6001）、`QuotaInsufficientError`（6003）、`TaskFailedError`（status=-1）、`PollTimeoutError`（轮询超时，额度已扣、结果仍在，可稍后取）。

## 语言选择（重要）

声云**没有 auto 自动检测**（128 种固定语言，`sonicrhino langs --online` 可查全表），`auto` 一律按中文处理。常用代号：

| 代号 | type | 说明 |
|---|---|---|
| `zh` | 0 | 中文；**中英混说也用它**，中文模式下英文词能正确转出 |
| `zh-Hant` | 100 | 中文繁体 |
| `yue` | 4 | 粤语 |
| `en` / `ja` / `ko` | 1 / 2 / 3 | 英语 / 日语 / 韩语 |
| `ru` / `es` / `it` / `vi` / `fr` / `de` / `ar` | 5–11 | 常见小语种 |

实测教训：中文授课夹英文单词的录音如果误传 `--lang en`，会得到整篇幻觉英文——语言选错是最常见的翻车点。

## 接口契约备忘（逆向自前端 v1.3.2）

统一封套 `{code, msg, time, data}`，`code=1` 成功；`4001` token 失效；`6001` 存储满；`6003` 时长不足。认证：请求头 `token`。

| 步骤 | 接口 | 说明 |
|---|---|---|
| 用户信息 | `GET /api/passport/userinfo` | 额度在 `time` 字段（注意 `time_use` 实为**剩余**分钟，字段名有误导） |
| 语言列表 | `GET /api/ajax/langList` | 公开接口，无需登录 |
| 提交预检 | `POST /api/voice/checkBeforeAddTask` | JSON `{"times": 秒}` |
| 上传任务 | `POST /api/voice/addTask` | multipart：`file` + `language` + `times` + `is_sync:"true"` + `title`，返回 `voiceId` |
| 任务列表 | `GET /api/voice/index?page=&limit=` | `status`: 0 未支付 / 1 处理中 / 2 完成 / -1 失败 |
| 任务详情 | `GET /api/voice/find?id=` | 转写在 `record_list`（`s`/`e` 毫秒 + `role` + `text`） |
| 导出 | `GET voice.sonicrhino.cc/api/voice/export` | 注意是另一个子域；`type=txt`（`role=1&time=1` 带说话人+时间戳）/ `type=doc` docx；`srt` 实测返回的也是 docx 二进制 |
| 软删除 | `POST /api/voice/del` | body `{"id": ...}`，进回收站 |
| 彻底删除 | `POST /api/voice/destroy` | 不可恢复 |

### 平台限制与实测数据（2026-09，Apple Silicon / 家庭宽带）

- 单文件 ≤ **1.5GB**，单任务时长 ≤ **5 小时**（18000s）。
- 上传：94MB 约 18s；转写：常规单任务约 **6x 实时**（34 分钟音频 5–6 分钟出稿）。
- 并发：20 任务同时提交**全部并行处理**不排队（94s 音频 10–56s 完成，>20x 实时），只读接口 50 并发无 429；瓶颈在上传带宽，不在服务端。
- 计费口径低于音频时长（20 × 94s 音频只扣 7.8 分钟，疑似按有效语音计）。
- 引擎为讯飞听见（`api_type=talent`）；中文识别质量好于本地 whisper-large-v3-turbo 一档（专有名词、中文人名更准）。

## 已知限制

- 登录（`/api/passport/emailLogin`）需要邮箱验证码/短信/图形验证码，不做自动化——直接抓浏览器 token 最省事。
- token 无刷新接口，失效（4001）后需手动重抓；库会抛 `TokenExpiredError` 提示。
- 接口非官方公开契约，前端升级后可能失配；欢迎提 issue。

---

## License

[MIT](LICENSE)
