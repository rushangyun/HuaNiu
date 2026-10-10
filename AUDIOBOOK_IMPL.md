# AI 有声小说生成网页 · 实施方案 C（自研）

> 已确认：不引进第三方项目代码，按 `AUDIOBOOK_DESIGN.md` 自研，
> 沿用华小牛已有的分层架构与事件契约体系。
> TTS 走 **方案 A：双 Provider**（edge-tts 联网优质 + piper 离线兜底）。
> 日期：2026-10-10

---

## 0. 交付目标（两天内可演示 + 可批量导出）

| 目标 | 说明 |
|---|---|
| 能听 | 粘贴/上传 txt → 解析 → 合成 → 播放 |
| 会导演 | 旁白与对话分音色，按情绪调语速/停顿 |
| 能批量 | 整本几十万字分片 + 队列 + 重试 + 合并 MP3 |
| 角色一致 | 同一角色跨章节音色不漂移 |
| 合规 | 版权提示 + 强制勾选 + 服务端校验 |

**明确不做（二期）**：多用户账号、音色克隆、背景音乐、字幕导出、epub/docx 导入。

---

## 1. 目录结构

复用 `server/app/` 的分层，新增 `audiobook/` 子系统：

```
server/app/audiobook/
  __init__.py
  models.py        # SQLAlchemy: Novel/Chapter/Segment/Speaker/Lexicon/Job
  schema.py        # Pydantic 出入参
  chunking.py      # 章节切分 + 段落分片（含重叠）
  parser.py        # 调 LLM 解析 → 结构化 JSON（offset 回填）
  normalize.py     # 文本归一化（数字/单位/英文）+ 多音字
  tts/
    base.py        # TTSProvider 协议 + VoiceSpec
    edge.py         # edge-tts（联网）
    piper.py        # piper（离线）
    factory.py      # 按 TTS_PROVIDER 环境变量装配
  pipeline.py      # 分片→解析→合成→合并 的编排
  worker.py        # 线程池消费 Job，失败指数退避重试
  media.py         # ffmpeg 后处理 + concat 合并 + 静音片段
server/app/api/audiobook.py   # 薄路由 + SSE 进度
storage/audio/{novel_id}/...  # 产物
```

**依赖方向**（严格单向）：
`api/audiobook → audiobook/pipeline → parser/tts/media → core`

---

## 2. 数据库（MVP 用 SQLite，升级路径 PostgreSQL）

```sql
CREATE TABLE novels (
  id TEXT PRIMARY KEY, title TEXT, source_type TEXT,
  raw_path TEXT, status TEXT,          -- draft|parsing|parsed|failed
  copyright_ack INTEGER NOT NULL DEFAULT 0,  -- 合规必须
  char_count INTEGER, created_at TIMESTAMP
);

CREATE TABLE chapters (
  id TEXT PRIMARY KEY, novel_id TEXT, idx INTEGER, title TEXT,
  status TEXT, audio_path TEXT, duration_sec REAL
);

-- 最小合成单位：一段 = 一个 Job
CREATE TABLE segments (
  id TEXT PRIMARY KEY, chapter_id TEXT, idx INTEGER,
  kind TEXT,                  -- narration|dialogue|poem|quote
  speaker TEXT,               -- NULL=旁白
  text TEXT,                  -- 归一化后送 TTS 的最终文本
  raw_text TEXT,              -- 原文（防篡改对照）
  text_hash TEXT,             -- md5(text|voice|speed) → 缓存键
  emotion TEXT, tone TEXT,
  speed REAL DEFAULT 1.0,
  pause_before_ms INTEGER DEFAULT 0,
  audio_path TEXT, status TEXT,   -- pending|running|done|failed
  retry_count INTEGER DEFAULT 0, error TEXT
);

-- 角色 → 音色 持久化映射（保证一致性的关键）
CREATE TABLE speakers (
  id TEXT PRIMARY KEY, novel_id TEXT, name TEXT,
  voice_id TEXT, speed REAL DEFAULT 1.0, pitch TEXT DEFAULT '+0Hz',
  style TEXT, profile TEXT
);

-- 发音词典：改一次，全书记住
CREATE TABLE lexicon (
  novel_id TEXT, word TEXT, pinyin TEXT, note TEXT,
  PRIMARY KEY (novel_id, word)
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY, novel_id TEXT, segment_id TEXT,
  status TEXT, priority INTEGER DEFAULT 0,
  attempts INTEGER DEFAULT 0, scheduled_at TIMESTAMP,
  error TEXT, updated_at TIMESTAMP
);
```

---

## 3. 后端核心代码骨架

### 3.1 TTS Provider 抽象

```python
# app/audiobook/tts/base.py
from dataclasses import dataclass
from typing import Protocol

@dataclass
class VoiceSpec:
    voice_id: str
    speed: float = 1.0
    pitch: str = "+0Hz"
    volume: str = "+0%"
    style: str | None = None
    style_degree: float = 1.0

class TTSProvider(Protocol):
    name: str
    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str: ...
```

### 3.2 edge-tts（联网·默认）

```python
# app/audiobook/tts/edge.py  —— pip install edge-tts
import edge_tts

class EdgeTTSProvider:
    name = "edge-tts"

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        rate = f"{int((spec.speed - 1) * 100):+d}%"
        comm = edge_tts.Communicate(text, spec.voice_id, rate=rate,
                                     pitch=spec.pitch, volume=spec.volume)
        await comm.save(out_path)      # 新版 API 必须 await
        return out_path
```

### 3.3 piper（离线·兜底）

```python
# app/audiobook/tts/piper.py
import asyncio

class PiperProvider:
    """离线兜底：piper 是 CPU 可跑的小模型，音质一般但断网能出声。"""

    name = "piper"

    def __init__(self, bin: str, model: str):
        self.bin, self.model = bin, model

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        cmd = [self.bin, "-m", self.model, "-f", out_path,
               "--length_scale", str(1.0 / max(spec.speed, 0.1))]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate(text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(f"piper 失败：{err.decode(errors='ignore')[:300]}")
        return out_path
```

### 3.4 工厂：切换只改一个环境变量

```python
# app/audiobook/tts/factory.py
import os

def build_tts():
    kind = os.getenv("TTS_PROVIDER", "edge")
    if kind == "edge":
        from .edge import EdgeTTSProvider
        return EdgeTTSProvider()
    if kind == "piper":
        from .piper import PiperProvider
        return PiperProvider(os.environ["PIPER_BIN"], os.environ["PIPER_MODEL"])
    raise ValueError(f"未知 TTS provider：{kind}")
```

### 3.5 文本归一化（音质第一杠杆）

```python
# app/audiobook/normalize.py
def normalize_for_tts(text: str, lexicon: dict[str, str]) -> str:
    text = _numbers_to_chinese(text)   # 2024年 → 二零二四年
    text = _units_to_chinese(text)     # 5kg → 五千克
    text = _apply_lexicon(text, lexicon)  # 多音字/专名
    text = _punct_to_pause(text)         # 符号 → 停顿标记
    return text
```

### 3.6 任务队列 Worker（重试 + 断点续跑）

```python
# app/audiobook/worker.py
MAX_ATTEMPTS = 3

async def run_worker(repo, tts, bus):
    asyncio.create_task(_reset_stale_jobs(repo))  # 重启后把卡住的 running 复位 → 断点续跑
    while True:
        job = repo.claim_next_job()
        if not job:
            await asyncio.sleep(0.5); continue
        asyncio.create_task(_handle(job, repo, tts, bus))

async def _handle(job, repo, tts, bus):
    seg = repo.get_segment(job.segment_id)
    try:
        if (cached := cache.get(seg.text_hash)):
            shutil.copy(cached, seg.audio_path)      # 命中缓存，省钱且保证一致
        else:
            await tts.synth(seg.text, voice_spec(job), seg.audio_path)
            cache.put(seg.text_hash, seg.audio_path)
        repo.mark_done(seg.id, job.id)
    except Exception as e:
        attempts = job.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            repo.mark_failed(seg.id, job.id, str(e)[:300])
        else:
            repo.requeue(job.id, delay=2 ** attempts, attempts=attempts)
    finally:
        bus.publish(seg.novel_id, progress(seg.novel_id))
```

### 3.7 音频后处理 + 合并（零重编码）

```python
# app/audiobook/media.py
FILTERS = (
    "afftdn=nf=-30,"
    "deesser=i=0.4:m=0.5:f=0.5:s=o,"
    "acompressor=threshold=0.089:ratio=3:attack=20:release=250:makeup=1,"
    "equalizer=f=150:t=q:w=1:g=2,"
    "equalizer=f=8000:t=q:w=1:g=-2,"
    "loudnorm=I=-17:TP=-1.5:LRA=11"
)

def process_segment(src: str, dst: str):
    subprocess.run(["ffmpeg", "-y", "-i", src, "-af", FILTERS,
                    "-ar", "24000", "-ac", "1", "-b:a", "96k", dst], check=True)

def concat(parts: list[str], out: str):
    lst = out + ".txt"
    with open(lst, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    # 所有段参数统一 → -c copy 秒级、无损
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", out], check=True)
```

---

## 4. 实施顺序（两天 · 按关键路径排）

| 阶段 | 内容 | 产出 | 预计 |
|---|---|---|---|
| **M1 能听** | 建 `audiobook/` 目录 + DB 表 + `/api/audiobook` 路由；txt 上传/粘贴；规则切章 | 能上传、能看到章节 | 2~3h |
| **M2 会导演** | `parser.py` 接本地 LLM（OpenAI 兼容）+ offset 回填；`normalize.py` | 输出结构化 JSON，旁白/对话分开 | 3~4h |
| **M3 能批量** | `tts/` 双 Provider + `worker.py` 队列重试 + `media.py` 合并 | 整本合成并导出 MP3 | 4~5h |
| **M4 可交付** | 前端：上传页/角色音色页/播放器/记录；SSE 进度；版权提示 | 完整可演示 | 4~5h |

**总计约 13~17 小时** —— 两天内**可以完成能演示、能批量导出整本 MP3 的 MVP**，前提是：
- 砍掉多用户/账号/克隆/字幕等二期功能
- TTS 先接 edge-tts（联网跑通主链路），piper 作为可选后端预留接口
- 不追求 UI 精细动画，先把流程跑通

---

## 5. 关键风险与对策

| 风险 | 对策 |
|---|---|
| **edge-tts 是逆向接口，可能限流/变更** | Provider 抽象隔离；预留 Azure / piper 后端，一处切换 |
| 7B 模型情绪识别不准 | 前端必须可手工改 speaker/emotion/speed；低置信度高亮 |
| 整本合成耗时长 | 章节级任务 + 先合成先听；段落哈希缓存 |
| 长任务崩溃无人知 | 状态持久化 + 自动重试 + 日志（已吸取昨晚教训） |
| 音频参数不一致导致合并失败 | 统一 `-ar/-ac/-b:a` 后才能 `-c copy` |

---

## 6. 验收清单（Definition of Done）

- [ ] 粘贴文本或上传 `.txt`，能自动识别章节
- [ ] 调用本地 LLM 解析出：旁白/对话、说话人、情绪、语速、停顿
- [ ] 旁白与不同角色使用不同音色
- [ ] 同一角色跨章节音色一致
- [ ] 在线播放 / 暂停 / 进度拖动
- [ ] 单章 MP3 下载
- [ ] 整本合并 MP3 + ZIP 打包下载
- [ ] 任务失败自动重试，且崩溃后能续跑
- [ ] 版权提示常显 + 上传前强制勾选（服务端也校验）
