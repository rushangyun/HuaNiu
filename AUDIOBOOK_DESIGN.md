# AI 有声小说生成网页 · 设计方案

> 创意作品（二面实战题第五部分）
> 角色设定：资深全栈开发工程师 + AI 产品经理
> 日期：2026-10-10

---

## 0. 先说结论：默认技术选型 + 需要你拍板的问题

### 0.1 我的默认假设（如果没异议就按这个走）

| 维度 | 默认方案 | 理由 |
| --- | --- | --- |
| 运行环境 | **单机优先**（你的 Windows 本机 / 一台轻量云服务器） | 零运维、易演示，和华小牛"数据不出机器"的价值主张一致 |
| AI 解析 LLM | **复用本地 Ollama `qwen2.5:7b-instruct`**（OpenAI 兼容接口） | 免费用、可离线、和本项目已有的 `llm/provider.py` 抽象完全同构 |
| TTS | **edge-tts（微软 Edge 在线语音）** 为主 Provider | 免费、无需注册、中文音色质量高、支持 SSML 语速/音调/停顿/部分情绪；抽象后可一键切 Azure / CosyVoice |
| 前端 | **React + Vite + TS**（复用华小牛浅色简洁风格） | 你已有这套骨架，最快出效果 |
| 后端 | **FastAPI**（与现有 server 同栈） | 同一套语言/心智模式，面试好讲 |
| 数据库 | **SQLite**（MVP）→ PostgreSQL（生产） | MVP 零外部依赖 |
| 队列 | **SQLite 表 + 进程内线程池 Worker**（MVP）→ Celery + Redis（生产） | MVP 不引入 Redis，降低部署门槛 |
| 文件存储 | **本地文件系统** `storage/`（MVP）→ S3/OSS（生产） | 同上 |
| 音频合并 | **ffmpeg concat 解复用（ `-c copy`，零重编码）** | 秒级合并，音质无损 |

一句话：**AI 解析用本地大模型（免费、隐私），语音合成用 edge-tts（免费、高质量），整套在本地就能跑起来。**

### 0.2 需要你确认的问题（影响架构取舍，请逐条给个方向）

1. **TTS 到底用哪个？**
   - `edge-tts`（推荐起步：免费免注册，但属于逆向的非官方接口，商用有风险）
   - `Azure 认知服务 TTS`（官方授权、情绪表达最完整，免费额度 50 万字符/月，需信用卡注册）
   - `CosyVoice / GPT-SoVITS`（本地开源、可克隆专属音色、质量好，但要占 GPU 显存且部署较重）
   → 决定 Provider 层的第一实现，也决定能否商用。

2. **是否要求「完全离线」？** 若要断网可用，TTS 必须换成本地方案（CosyVoice/GPT-SoVITS），质量与部署复杂度都会上升；AI 解析仍可用本地模型。

3. **目标形态是什么——只做本机 demo，还是要真上线给别人用？** 决定要不要做用户账号、鉴权、配额、付费/任务超时。

4. **文本规模预期？** 单篇几千字（几十个片段）vs 整本几十万字（上百章节、上千片段）。后者必须上正式队列 + 断点续传，前者 MVP 的线程 Worker 就够。

5. **是否需要「音色克隆 / 给角色训练专属声音」？** 这是加分项，但要引入 CosyVoice/GPT-SoVITS 和参考音频采集，工作量和 GPU 占用都翻倍。我建议**二期再做**。

6. **最后要交付什么粒度？** 只要**网页能演示**（生成几十秒音频就够），还是要**真能批量导出整本书 MP3**？这决定我在队列、断点续传、失败重试上投入多少。

> 在未确认之前，下文按 **0.1 的默认假设** + **"单章级可用、可导出 MP3"** 的交付粒度设计，并预留第二阶段升级路径。

---

## 1. 需求拆解和用户使用流程

### 1.1 需求拆解（用户目标 → 系统能力）

| # | 原始需求 | 拆解后的系统能力 | MVP 是否必做 |
| --- | --- | --- | --- |
| 1 | 文本输入 | 粘贴文本 / 上传 `.txt`（`.md`/`.docx` 二期）；**按章节识别**并分段（第X章 / Chapter N / 卷xx 正则 + LLM 辅助标题纠正） | ✅ 必做 |
| 2 | AI 智能解析 | 识别旁白/对话/说话人/情绪/语气/停顿/多音字/语速建议，**输出结构化 JSON** | ✅ 必做（核心） |
| 3 | 音频合成 | 按段落选**音色/语速/情感**，调用 TTS，逐段合成 | ✅ 必做 |
| 4 | 播放与导出 | 在线播放/暂停/进度拖动、下载 MP3、生成记录列表 | ✅ 必做 |
| 5 | 角色配置 | 角色 → 音色映射；旁白单独音色；角色名册自动提取 + 手工修正 | ✅ 必做 |
| 6 | 长文本处理 | 分片、任务队列、合并音频、失败重试、**断点续传** | ✅ 必做（队列+重试） |
| 7 | 版权提示 | 首页/上传处显著提示 + 上传前**强制勾选确认** + 服务条款 | ✅ 必做（合规底线） |

**二期（不在 MVP）：** 多用户账号、音色克隆、背景音乐/音效、导出字幕 SRT、.docx/epub 导入、批量任务调度优先级、付费配额。

### 1.2 用户使用流程（Happy Path）

```
① 进入创作台
   └─ 看到版权提示横幅
② 粘贴小说文本 或 拖入 .txt 文件
   └─ 勾选「我确认拥有该文本的合法使用权」（不勾不能继续）
③ 点击「开始解析」
   └─ 前端 POST /api/novels → 后端落库 → 返回 novel_id
   └─ 后端拆章节 → 逐块调 LLM 解析 → SSE 推送进度
   └─ 右侧实时出现：章节列表 + 自动识别出的角色名册
④ 角色音色配置页
   └─ 角色名册（自动列出：旁白、林晚、沈宴…）
   └─ 每个角色选音色（如 旁白=云扬、林晚=晓晓、沈宴=云希）+ 语速 + 情绪
   └─ 多音字/专有名词发音修正表（自动高亮可疑词，可手工改拼音）
⑤ 点击「生成有声书」
   └─ 后端建 合成任务（每个段落 = 一个 job）→ Worker 线程并发合成
   └─ SSE 推送：第 3/58 段… 失败自动重试（指数退避）
   └─ 完成后 ffmpeg 合并成 章节.mp3 / 全书.mp3
⑥ 播放页
   └─ 章节播放列表、播放器（播放/暂停/进度/上一章节/倍速）
   └─ 「下载本章 MP3」「下载全书 ZIP」
⑦ 生成记录
   └─ 历史任务列表：书名、字数、时长、状态、重试次数、耗时、成本估算
```

### 1.3 关键用户痛点 → 设计对策

| 痛点 | 对策 |
| --- | --- |
| 小说很长，等太久 | **边生成边听**：按段落合成，章节完成即可播；不等全书 |
| 断网/关页面就白跑 | 任务持久化到 DB，**断点续传**：重进页面继续未完成的段 |
| TTS 偶尔失败 | 每段独立 job，**失败重试 + 指数退避 + 错误日志** |
| 对话听不出谁在说 | 角色↔音色映射，说话人和旁白用不同音色 |
| 多音字读错（曾/重/行/血） | 发音词典 + LLM 标注可疑词 + 手工修正 → SSML phoneme 或同音替换 |
| LLM 改写原文篡改作者意思 | **强制约束：只标注不改写**，原文靠 offset 回填（见 §4） |
| 合成费用/时间失控 | 段落级**哈希缓存**，相同文本+音色+参数直接复用，不重复调用 |

---

## 2. 页面结构和 UI 草图说明

### 2.1 页面清单（SPA，单页 + 标签）

| 路由/标签 | 页面 | 主要职责 |
| --- | --- | --- |
| `/` **创作台** | ImportView | 粘贴/上传 → 版权勾选 → 触发解析 → 实时显示解析进度与章节、角色名册 |
| `/voices` **角色音色** | VoiceView | 角色名册 → 分配音色/语速/情绪；发音词典修正 |
| `/play` **试听播放** | PlayerView | 章节列表 + 播放器 + 下载 |
| `/tasks` **生成记录** | TaskView | 历史任务列表与状态 |

顶部固定：**版权提示条**；右上：**健康/服务状态**（本地 LLM 是否在线、当前 TTS Provider）。

### 2.2 UI 草图（文本线框）

**① 创作台 ImportView**

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⚠ 请确保你拥有所输入文本的合法使用权，勿上传他人未授权作品。  [了解]  │  ← 版权横幅
├──────────────────────────────────────────────────────────────────────┤
│  华小牛 · AI 有声书       [创作台] [角色音色] [试听] [记录]   ● LLM 在线│
├──────────────────────────────────────┬───────────────────────────────┤
│ ① 输入小说文本                        │  解析结果                      │
│ ┌──────────────────────────────────┐ │  ┌─────────────────────────┐  │
│ │ [粘贴文本] [上传 .txt]            │ │  │ 共 3 章 / 12,480 字      │  │
│ │                                  │ │  │ ▸ 第1章 夜雨叩窗   42 段 │  │
│ │ 第一章 夜雨叩窗                   │ │  │ ▸ 第2章 旧巷深处   38 段 │  │
│ │ 「你还回来做什么。」               │ │  │ ▸ 第3章 灯火可亲   45 段 │  │
│ │ 林晚没有回头，雨水顺着屋檐…        │ │  └─────────────────────────┘  │
│ │                                  │ │                               │
│ └──────────────────────────────────┘ │  识别到的角色                  │
│                                      │  旁白(narration) · 42 段       │
│ 字数统计：12,480     预计 3 章        │  林晚 · 18 段                  │
│                                      │  沈宴 · 15 段                  │
│ ☑ 我确认拥有该文本的合法使用权        │                               │
│                                      │  解析进度 ███████░░░ 82%       │
│              [开始解析]              │  正在解析第 2 章…              │
└──────────────────────────────────────┴───────────────────────────────┘
```

**② 角色音色 VoiceView**

```
┌──────────────────────────────────────────────────────────────────────┐
│  角色音色配置                [← 返回创作台]        [保存并生成有声书] │
├──────────────────────────────────────────────────────────────────────┤
│ 全局设置   基准语速 [1.0 ▾]   音量 [1.0 ▾]   段间停顿 [400ms ▾]       │
├──────────────────────────────────────────────────────────────────────┤
│ 角色          音色                    语速    情绪       试听         │
│ 旁 白   云扬-YunyangNeural     1.0   平静-叙述   ▶ 试听               │
│ 林 晚   晓晓-XiaoxiaoNeural    1.05  温柔         ▶ 试听   [高级▾]    │
│ 沈 宴   云希-YunxiNeural       0.95  低沉/克制    ▶ 试听   [高级▾]    │
│ 老管家  云野-YunyeNeural       0.9   苍老沙哑     ▶ 试听   [高级▾]    │
├──────────────────────────────────────────────────────────────────────┤
│ 发音修正（多音字/专名）        ⚠ AI 标出 4 处可疑读音                 │
│  重逢       chóng féng    ✎ 编辑        曾相识     zēng     ✎ 编辑   │
│  血泊       xuè pō        ✎ 编辑        行伍       háng wǔ  ✎ 编辑   │
└──────────────────────────────────────────────────────────────────────┘
```

**③ 试听播放 PlayerView**

```
┌──────────────────────────────────────────────────────────────────────┐
│  《夜雨叩窗》有声版                 [下载全书 ZIP ⬇]                 │
├────────────────────┬─────────────────────────────────────────────────┤
│ 章节列表            │  正在播放：第 1 章 夜雨叩窗                      │
│ ●第1章 夜雨叩窗 12:34│                                                 │
│ ○第2章 旧巷深处 11:02│  ━━━━━━━●━━━━━━━━━━━━  04:12 / 12:34   1.0x   │
│ ○第3章 灯火可亲 13:18│  ⏮   ▶/⏸   ⏭       [下载本章 MP3 ⬇]           │
│                    │                                                 │
│ ⓘ 共 125 段 / 合成成功 123 / 重试 2 / 耗时 6m20s / 音频 36.9MB         │
└────────────────────┴─────────────────────────────────────────────────┘
```

### 2.3 前端组件结构（与华小牛一致的"订阅式"分层）

```
src/
  api/            novelApi.ts         # REST + SSE 订阅
  hooks/          useParseProgress.ts # SSE → 状态（和 useChat/useVisionStats 同构）
                  useSynthesis.ts
  components/
    CopyrightBanner.tsx
    TextInputPanel.tsx     UploadZone.tsx
    ChapterTree.tsx        SpeakerRoster.tsx
    VoiceMappingTable.tsx  PronunciationTable.tsx
    AudioPlayer.tsx        ChapterList.tsx   TaskTable.tsx
  views/          ImportView / VoiceView / PlayerView / TaskView
  types/          novel.ts            # 与后端 Pydantic 对齐（必要时也从契约生成）
  styles.css      # 复用现有浅色主题
```

设计原则（沿用你既定的工程要求）：**前端只负责 UI 组织与订阅，所有计算与状态在后端**；解析/合成进度统一走 **SSE 事件**，跟 `server/app/core/events.py` 那套契约体系同构。

---

## 3. 技术架构设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ 浏览器 (React + Vite)                                                │
│   创作台 / 音色配置 / 播放器 / 记录                                  │
│        │ REST(JSON)                    ▲ SSE 进度事件                │
└────────┼───────────────────────────────┼────────────────────────────┘
         ▼                               │
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI 后端                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐  │
│  │ api/     │ │ parser/  │ │ tts/     │ │ media/  │ │ tasks/     │  │
│  │ 薄路由   │ │ 章节切分 │ │ Provider │ │ ffmpeg  │ │ 队列+Worker│  │
│  │ +SSE     │ │ LLM解析  │ │ 抽象     │ │ 合并切片│ │ 重试/断点  │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ └─────┬──────┘  │
│       └────────────┴────────────┴────────────┴────────────┘         │
│                              │                                      │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │ SQLite: novels / chapters / segments / speeches / jobs / lexicon│  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────┬───────────────────────────────┬───────────────────────────┘
           │                               │
           ▼                               ▼
   ┌───────────────────┐          ┌──────────────────────┐
   │ Ollama qwen2.5:7b │          │ TTS Provider         │
   │ (本地/免费/隐私)   │          │ edge-tts → Azure →   │
   │ OpenAI 兼容接口    │          │ CosyVoice(可选切换)  │
   └───────────────────┘          └──────────────────────┘
                                            │
                                            ▼
                              ┌──────────────────────────┐
                              │ storage/audio/{novel}/   │
                              │   seg_0008.mp3 …         │
                              │   chapter_01.mp3(合并)   │
                              └──────────────────────────┘
```

**依赖方向严格单向**（沿用你既定的分层要求）：`api → tasks → parser/tts/media → core`。换 TTS Provider 只需改一个环境变量。

### 3.2 数据模型（SQLite / PostgreSQL 通用）

```sql
-- 书籍
CREATE TABLE novels (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source_type TEXT,            -- paste | file
  raw_path TEXT,               -- 原始文本落盘路径
  charset TEXT DEFAULT 'utf-8',
  status TEXT,                 -- draft | parsing | parsed | failed
  copyright_ack INTEGER,       -- 版权确认勾选（合规必须）
  char_count INTEGER,
  created_at TIMESTAMP
);

-- 章节
CREATE TABLE chapters (
  id TEXT PRIMARY KEY,
  novel_id TEXT REFERENCES novels(id),
  idx INTEGER, title TEXT,
  status TEXT,                 -- pending | done | failed
  audio_path TEXT, duration_sec REAL
);

-- 段落（TTS 的最小合成单位）
CREATE TABLE segments (
  id TEXT PRIMARY KEY,
  chapter_id TEXT REFERENCES chapters(id),
  idx INTEGER,
  kind TEXT,                   -- narration | dialogue | quote | poem
  speaker TEXT,                -- null 表示旁白；否则角色名
  text TEXT NOT NULL,          -- 送给 TTS 的最终文本（已做归一化）
  raw_text TEXT,               -- 原文（用于对照，防 LLM 篡改）
  text_hash TEXT,              -- md5(text+voice+speed) → 缓存键
  emotion TEXT, tone TEXT,
  speed REAL DEFAULT 1.0,
  pause_before_ms INTEGER DEFAULT 0,
  audio_path TEXT, status TEXT,-- pending | running | done | failed
  retry_count INTEGER DEFAULT 0,
  error TEXT
);

-- 角色（发言者）与其音色配置
CREATE TABLE speakers (
  id TEXT PRIMARY KEY,
  novel_id TEXT,
  name TEXT,                   -- '旁白' | '林晚' …
  voice_id TEXT,               -- zh-CN-XiaoxiaoNeural
  speed REAL DEFAULT 1.0,
  pitch TEXT DEFAULT '+0Hz',
  emotion TEXT, style TEXT,
  profile TEXT                 -- LLM 推断的人设摘要（辅助选音色）
);

-- 发音词典（多音字/专名）
CREATE TABLE lexicon (
  novel_id TEXT, word TEXT, pinyin TEXT, note TEXT,
  PRIMARY KEY (novel_id, word)
);

-- 合成作业（队列）
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  novel_id TEXT, segment_id TEXT,
  status TEXT,                 -- queued | running | done | failed
  priority INTEGER DEFAULT 0,
  attempts INTEGER DEFAULT 0,
  scheduled_at TIMESTAMP,
  error TEXT, updated_at TIMESTAMP
);
```

### 3.3 任务队列与状态机（MVP：DB 队列 + 线程池 Worker）

```
segment: pending ──► running ──► done
                       │
                       └─► failed ──(attempts<3, 指数退避 2/4/8s)──► queued 重试
                                 └─(attempts>=3)──► 标记 failed，落 error，前端标红可手工重试
```

- **为什么不上 Redis/Celery**：MVP 目标是"能跑起来"，多一个中间件就多一层部署失败点。SQLite 表 + `ThreadPoolExecutor(4~8)` 足够跑到几千段落。
- **升级路径**：队列接口（`enqueue/dequeue/mark`）写好抽象，换成 Celery 只改实现，不改调用方。
- **幂等**：每段用 `text_hash` 查缓存；job 用唯一键防重复入队。
- **断点续传**：进程重启后，Worker 启动时把 `running` 超过 N 分钟的 job 重置为 `queued`。

### 3.4 文件存储布局

```
storage/
  novels/{novel_id}/raw.txt
  audio/{novel_id}/
      seg/{chapter_idx}/{seg_idx}.mp3        # 单段（可缓存复用）
      silence/200ms.mp3, 400ms.mp3, 800ms.mp3
      chapter_01.mp3                          # 章节合并
      book.mp3                                # 全书（可选）
  export/{novel_id}.zip
```

---

## 4. AI 解析模块的 Prompt 设计

### 4.1 三条铁律（决定成败的设计细节）

1. **只标注，不改写。** LLM 只能"圈出" spans 并打标签，**严禁润色/扩写/翻译**。System Prompt 里反复强调，并用技术手段兜底（见下）。
2. **原文靠 offset 回填，不用 LLM 返回的文本。** 让 LLM 返回 `{start, end}` 字符偏移（外加它读懂所需的 trimmed 上下文），程序用偏移量从原文切片。这样即使模型"手痒"改了字，也拿不到最终的合成文本。
3. **情感与说话人分离。** 情绪是"这一句怎么读"，角色是"这一句谁在说"；混在一起会导致同一角色音色漂移。

### 4.2 System Prompt（可直接用）

```
你是中文小说有声化（audiobook）的语音导演兼文本标注引擎。
你的任务是把一段小说原文切分成"可朗读单元"，并为每个单元标注朗读所需的导演信息。

【最高原则】
1. 严禁改写、润色、扩写、翻译、摘要原文。你只能标注，不能创作。
2. 原文文本请通过 start/end 字符偏移量引用，不要返回被你重写过的句子。
3. 所有文本内容保持与原文完全一致（含标点、引号、省略号）。

【切分规则】
- 一个 segment 通常 = 一个自然段中语义完整的一句/一组句子，长度建议 25~120 字。
- kind:
    narration 叙述/描写/心理活动/诗词歌赋外的陈述部分
    dialogue  带引号的人物对话（含「」""‘’）
    poem      诗词、对联、书信、告示等排版特殊的文本
    quote     旁引、书名/招牌/信件的引用内容
- speaker: dialogue 时必须给出说话人（用原文中出现的名字/称谓，保持一致）；
           narration/poem/quote 一律为 null（由"旁白"音色朗读）。
- emotion ∈ {neutral, happy, sad, angry, fear, surprise, disgust, tender, solemn, sarcastic, excited, calm}
- tone     ∈ {叙述, 对话, 内心独白, 喊叫, 低语, 争吵, 哭泣, 权威, 撒娇, 说书}
- speed    建议 0.8~1.3（1.0 为基准）。紧张/争吵偏快，抒情/悲伤偏慢。
- pause_before_ms: 本段朗读前插入的静音毫秒数（0/200/400/800/1200）。
             场景切换、对话与叙述交替、悬念处给 400~1200；连续叙述给 0~200。
- polyphones: 本段中你认为朗读容易读错的多音字或专有名词读音，
             格式 [{ "word": "重逢", "pinyin": "chóng féng" }]。
             只在有把握时给出；拿不准就返回空数组，不要猜。

【输出格式】
只输出一个 JSON 对象，不要任何解释性文字、不要 markdown 代码块围栏：
{
  "speakers_seen": ["林晚", "沈宴"],
  "segments": [
    {"start": 0, "end": 42, "kind": "narration", "speaker": null,
     "emotion": "solemn", "tone": "叙述", "speed": 1.0, "pause_before_ms": 0,
     "polyphones": []}
  ]
}
```

### 4.3 User Prompt 模板 + 上下文延续（保证角色名一致的关键）

```
【小说全局上下文】
书名：{title}
已出现的角色名册（请沿用同样的叫法，不要新造别名）：{roster_json}

【本次待解析原文】（第 {chapter_idx} 章节选，offset 起点 {block_start}）
{block_text}

请按 System Prompt 要求输出 JSON。注意：start/end 是相对于本块文本起点的字符偏移（0-based，左闭右开）。
```

> **为什么要有 roster**：分块处理时，同一角色在不同块里可能被叫成"林晚/林姑娘/她"。把已识别名册回传，能显著减少别名漂移。每解析完一块就把新出现的名字合并进 roster。

### 4.4 分块策略

```
原文 → 按章节切（正则：^\s*第[一二三四五六七八九十百千零〇0-9]+[章节回卷]|^Chapter\s+\d+）
     → 章内按自然段切
     → 段再合并成 ≤ 800 字 的块（保留 100 字上下文重叠，防止断句断在句子中间）
     → 逐块 LLM 解析（temperature=0, format=json, max_tokens 紧扣）
     → 结果按 (block_start + offset) 映射回全局坐标
```

### 4.5 兜底：LLM 不可用时的规则解析

本地模型没起来时不能整个功能瘫痪。写一条纯规则降级路径：

- 引号内的内容 → `dialogue`，尝试从附近（前后 30 字）用正则抓"XX说/道/问/答"推断 speaker；
- 行首含缩进或明显诗句特征 → `poem`；
- 其余 → `narration`；
- `pause_before_ms` 按句子结尾标点给：`。`→200，`？！`→400，`…`→600，`——`→300。

### 4.6 文本归一化（TTS 前必做，最影响"像不像人话"）

```
阿拉伯数字 → 中文读法：2024年 → 二零二四年；第3章 → 第三章；15.6% → 百分之十五点六
年/月/日/时间：1998-07-15 → 一九九八年七月十五日
单位：km → 千米；5kg → 五千克
英文专名：iPhone → 读作规范（可查自定义词典，或加空格提高发音正确率）
符号转停顿：—— → 破折号停顿；…… → 省略号停顿
括号内舞台提示/注释体（若有） → 可选是否朗读
多音字：查 lexicon 表替换或生成 SSML <phoneme>/<say-as>
```

---

## 5. TTS 服务选型建议和调用示例

### 5.1 选型对比

| 方案 | 音色质量 | 情绪/风格支持 | 成本 | 依赖 | 商用风险 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| **edge-tts** | ★★★★☆（Azure 同模型） | SSML rate/pitch/volume；部分音色支持 style | **免费、免注册** | 需联网 | ⚠ 逆向接口，官方可能变更 | **MVP 首选** |
| **Azure TTS** | ★★★★★ | 官方完整 SSML：`mstts:express-as` style/role/styledegree | 免费额度 50 万字符/月，之后约 ¥15/百万字符 | 需 Key + 联网 | ✅ 合规 | **生产首选** |
| **CosyVoice（阿里开源）** | ★★★★☆ | 支持自然语言控制情绪/风格，**可克隆音色** | 免费（自托管） | **需 GPU**（你 8GB 显存可跑 2.0 小模型） | ✅ 开源协议需核 | **进阶/离线首选** |
| **GPT-SoVITS** | ★★★★☆ | 少样本克隆，情绪靠参考音频 | 免费（自托管） | 需 GPU + 参考音频 | ✅ | 备选 |
| **pyttsx3 / SAPI** | ★★☆☆☆ | 无 | 免费 | 完全离线 | ✅ | 仅作**降级兜底**（机械感重） |

**推荐组合（MVP→生产）**：
1. MVP：`edge-tts`（零成本出效果）——`ZH` 推荐音色：
   - 旁白/男声：`zh-CN-YunyangNeural`（沉稳叙述）、`zh-CN-YunyeNeural`（苍老）、`zh-CN-YunjianNeural`（激昂武侠）
   - 女声：`zh-CN-XiaoxiaoNeural`（温柔通用）、`zh-CN-XiaoyiNeural`（活泼）、`zh-CN-XiaochenNeural`（成熟）
   - 青年男：`zh-CN-YunxiNeural`、`zh-CN-YunxiaNeural`（童声）
2. 生产：切 `Azure TTS`（情绪表达最完整，授权合规）
3. 离线/音色克隆：`CosyVoice`（本地 GPU）

### 5.2 Provider 抽象（与现有 `llm/provider.py` 同构，换实现不影响上层）

```python
# app/tts/base.py
from dataclasses import dataclass
from typing import Protocol

@dataclass
class VoiceSpec:
    voice_id: str          # zh-CN-XiaoxiaoNeural
    speed: float = 1.0     # 0.5~2.0
    pitch: str = "+0Hz"    # SSML pitch
    volume: str = "+0%"
    style: str | None = None        # Azure: cheerful/sad/angry...
    style_degree: float = 1.0
    emotion_hint: str | None = None # 给 Provider 的语义提示

class TTSProvider(Protocol):
    name: str
    def list_voices(self) -> list[dict]: ...
    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str: ...
```

### 5.3 edge-tts 调用示例（含 SSML 语速/音调/停顿）

```python
# app/tts/edge.py  —— pip install edge-tts
import asyncio, edge_tts

class EdgeTTSProvider:
    name = "edge-tts"

    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        # 速率写成百分比：1.0 -> +0%；1.2 -> +20%
        rate = f"{int((spec.speed - 1) * 100):+d}%"
        comm = edge_tts.Communicate(text, spec.voice_id, rate=rate, pitch=spec.pitch, volume=spec.volume)
        # 注意：Communicate 是异步生成器，需要 await save()（新版 API）
        await comm.save(out_path)
        return out_path

# 生成静音片段（用于段间停顿）
# ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t 0.4 -q:a 9 -acodec libmp3lame silence_400ms.mp3
```

> **踩坑提醒**：老版本 `edge-tts` 的 `save()` 是同步用法、新版改为 `await`，版本差异会导致"视频/音频文件为空"的诡异 bug。锁版本并把文件大小校验写进自测。另外高并发请求会触发限流，**并发限制 2~4 + 失败重试**。

### 5.4 Azure TTS 调用示例（生产：完整情绪控制）

```python
# pip install azure-cognitiveservices-speech
import azure.cognitiveservices.speech as speechsdk

class AzureTTSProvider:
    def __init__(self, key: str, region: str):
        self.cfg = speechsdk.SpeechConfig(subscription=key, region=region)
        self.cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)

    def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str:
        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="zh-CN">
          <voice name="{spec.voice_id}">
            <prosody rate="{spec.speed:.2f}" pitch="{spec.pitch}">
              <mstts:express-as style="{spec.style}" styledegree="{spec.style_degree}">
                {text}
              </mstts:express-as>
            </prosody>
          </voice>
        </speak>"""
        out = speechsdk.audio.AudioOutputConfig(filename=out_path)
        syn = speechsdk.SpeechSynthesizer(speech_config=self.cfg, audio_config=out)
        res = syn.speak_ssml(ssml)
        if res.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise RuntimeError(f"Azure TTS 失败: {res.cancellation_details.reason}")
        return out_path
```

> **多音字/专业读法**用 `<phoneme alphabet="sapi" ph="chong2 feng2">重逢</phoneme>` 或 `<say-as>` 处理，放进 `lexicon` 表由归一化层注入。

---

## 6. 前后端核心代码示例

### 6.1 后端：数据契约 + 上传解析（FastAPI）

```python
# api/novels.py —— 薄路由，只做入参校验与编排
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from tasks.queue import enqueue_parse

router = APIRouter(prefix="/api/novels", tags=["novels"])

class CreateNovelIn(BaseModel):
    title: str
    text: str | None = None
    copyright_ack: bool          # 版权确认，合规必备

@router.post("")
async def create_novel(body: CreateNovelIn):
    # 合规底线：没勾选确认，直接拒绝
    if not body.copyright_ack:
        raise HTTPException(400, "请先确认你对输入文本拥有合法使用权")
    novel_id = await repo.create_novel(body.title, body.text)
    await enqueue_parse(novel_id)
    return {"novel_id": novel_id}

@router.post("/upload")
async def upload_txt(file: UploadFile = File(...), copyright_ack: bool = False):
    if not copyright_ack:
        raise HTTPException(400, "请先确认你对输入文本拥有合法使用权")
    if not (file.filename or "").lower().endswith((".txt", ".md")):
        raise HTTPException(415, "目前只支持 .txt / .md")
    text = _detect_and_decode(await file.read())     # utf-8 / gbk 自动识别
    novel_id = await repo.create_novel(file.filename, text)
    await enqueue_parse(novel_id)
    return {"novel_id": novel_id}
```

### 6.2 后端：章节切分 + LLM 解析（offset 回填，防篡改）

```python
# parser/pipeline.py
import json, re, httpx

CHAPTER_RE = re.compile(r"^\s*(第[一二三四五六七八九十百千零〇\d]+[章节回卷节]|Chapter\s+\d+)", re.M)
OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"
MODEL = "qwen2.5:7b-instruct"

def split_chapters(text: str) -> list[tuple[str, str]]:
    hits = [m.start() for m in CHAPTER_RE.finditer(text)] + [len(text)]
    out = []
    for i in range(len(hits) - 1):
        head = text[hits[i]:hits[i] + 40].splitlines()[0].strip() or f"第{i+1}章"
        out.append((head, text[hits[i]:hits[i + 1]]))
    return out or [("全文", text)]

async def parse_block(block: str, roster: list[str], title: str) -> dict:
    payload = {
        "model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TPL.format(title=title, roster_json=json.dumps(roster, ensure_ascii=False), block_text=block)},
        ],
    }
    async with httpx.AsyncClient(trust_env=False, timeout=120) as cli:   # 关键：绕开本机代理
        r = await cli.post(OLLAMA, json=payload)
        r.raise_for_status()
        data = r.json()["choices"][0]["message"]["content"]
    return _extract_json(data)

def materialize(block: str, parsed: dict, base: int):
    """用 offset 从原文切片，绝不使用 LLM 返回的文本"""
    segs = []
    for s in parsed.get("segments", []):
        a, b = int(s["start"]), int(s["end"])
        if not (0 <= a < b <= len(block)):      # 越界直接丢弃，防模型乱出 offset
            continue
        segs.append({
            "kind": s.get("kind", "narration"),
            "speaker": s.get("speaker"),
            "raw_text": block[a:b],             # ← 原文，安全
            "text": normalize_for_tts(block[a:b]),
            "emotion": s.get("emotion", "neutral"),
            "speed": float(s.get("speed", 1.0)),
            "pause_before_ms": int(s.get("pause_before_ms", 0)),
            "polyphones": s.get("polyphones", []),
        })
    return segs
```

> **`httpx.AsyncClient(trust_env=False)`** 这个项目里的老坑：本机有 `http_proxy`，不加这个会请求到本地 11434 失败。

### 6.3 后端：Worker（队列 + 重试 + 缓存 + 断点续传）

```python
# tasks/worker.py
import asyncio, hashlib, os
from concurrent.futures import ThreadPoolExecutor

MAX_ATTEMPTS = 3
POOL = ThreadPoolExecutor(max_workers=4)        # edge-tts 并发别太高，会限流

async def run_worker():
    asyncio.create_task(_reset_stale_jobs())     # 重启时把卡住的 running 复位 → 断点续传
    while True:
        job = repo.claim_next_job()              # SELECT … WHERE status='queued' ORDER BY priority
        if not job:
            await asyncio.sleep(0.5); continue
        asyncio.create_task(_handle(job))

async def _handle(job):
    seg = repo.get_segment(job.segment_id)
    key = hashlib.md5(f"{seg.text}|{job.voice_id}|{seg.speed}".encode()).hexdigest()
    cached = cache.get(key)
    try:
        if cached:                                # 命中→不重复花钱/花时间
            os.replace(cached, seg.audio_path)
        else:
            await POOL.run(tts.synth, seg.text, voice_spec(job), seg.audio_path)
            cache.put(key, seg.audio_path)
        repo.mark_segment_done(seg.id); repo.mark_job_done(job.id)
    except Exception as e:                        # 失败重试（指数退避）
        attempts = job.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            repo.mark_segment_failed(seg.id, str(e)[:300]); repo.mark_job_failed(job.id, str(e)[:300])
        else:
            repo.requeue(job.id, delay=2 ** attempts, attempts=attempts)
    finally:
        bus.publish("synthesis", seg.novel_id, progress(seg.novel_id))   # → SSE
```

### 6.4 后端：音频合并 + SSE 进度推送

```python
# media/merge.py —— 零重编码合并，秒级完成
import subprocess

def concat_mp3(parts: list[str], out: str):
    listfile = out + ".txt"
    with open(listfile, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", listfile, "-c", "copy", out], check=True)
    return out

def silence_clip(ms: int, out: str):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", f"{ms/1000:.3f}", "-acodec", "libmp3lame", out], check=True)
    return out

# api/progress.py —— 与 server/app/transport/sse.py 同套机制
@router.get("/api/novels/{nid}/progress")
async def progress_stream(nid: str):
    async def gen():
        async for snap in bus.subscribe("synthesis", nid):
            yield {"event": "progress", "data": json.dumps(snap)}   # {done, total, failed, pct}
    return sse_response(gen())
```

### 6.5 前端：上传 + 版权勾选 + SSE 订阅

```tsx
// views/ImportView.tsx（节选）
export default function ImportView() {
  const [text, setText] = useState("");
  const [ack, setAck] = useState(false);            // 版权确认
  const [nid, setNid] = useState<string | null>(null);

  const start = async () => {
    if (!ack) return alert("请先确认你对输入文本拥有合法使用权");
    const id = await createNovel({ title: "未命名", text, copyright_ack: true });
    setNid(id);
  };

  useParseProgress(nid);        // SSE → {pct, chapters, speakers}

  return (
    <>
      <CopyrightBanner />
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder="粘贴小说文本…" />
      <UploadZone accept=".txt,.md" />
      <label>
        <input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />
        我确认拥有该文本的合法使用权，不上传他人未授权作品
      </label>
      <button disabled={!text || !ack} onClick={start}>开始解析</button>
      {nid && <><ChapterTree /><SpeakerRoster /><ProgressBar /></>}
    </>
  );
}
```

```ts
// hooks/useParseProgress.ts —— 订阅式，和 useChat 同构
export function useParseProgress(nid: string | null) {
  const [snap, setSnap] = useState<ParseSnapshot | null>(null);
  useEffect(() => {
    if (!nid) return;
    const es = new EventSource(`/api/novels/${nid}/progress`);
    es.addEventListener("progress", e => setSnap(JSON.parse((e as MessageEvent).data)));
    return () => es.close();
  }, [nid]);
  return snap;
}
```

---

## 7. 部署方案、性能优化和注意事项

### 7.1 部署矩阵

| 场景 | 部署方式 | 说明 |
| --- | --- | --- |
| **本机 demo（推荐先这样）** | `uvicorn app:app --reload` + `vite dev` | 零外部依赖，SQLite + 本地文件，5 分钟起来 |
| **单机服务器（给老师/同学演示）** | Docker Compose：`web` + `api` + `worker` 三个容器共享 volume | 一条 `docker compose up` |
| **正式上线** | 前端 Vercel/静态托管；后端 + Worker 部署到 Fly.io / Railway / 轻量云；Postgres + Redis + S3 | 需要队列/多实例的完整形态 |

Docker Compose 示例（生产形态）：

```yaml
services:
  api:    { build: ./server, command: uvicorn app:app --host 0.0.0.0 --port 8000, ports: ["8000:8000"],
            environment: [TTS_PROVIDER=azure, AZURE_KEY=..., DATABASE_URL=postgresql://...], volumes: ["./storage:/app/storage"] }
  worker: { build: ./server, command: python -m tasks.worker, depends_on: [redis], volumes: ["./storage:/app/storage"] }
  redis:  { image: redis:7-alpine }
  db:     { image: postgres:16-alpine, environment: [POSTGRES_PASSWORD=...], volumes: ["./pgdata:/var/lib/postgresql/data"] }
  web:    { build: ./web, ports: ["80:80"] }
```

### 7.2 性能优化清单

| 类别 | 措施 | 收益 |
| --- | --- | --- |
| **避免重复合成** | `text_hash + voice + speed` 做键的段落级缓存 | 相同文本直接复用；改音色重跑、重复段落、失败重做都能省下大量调用 |
| **并发与限流** | edge-tts 并发 2~4 + 令牌桶；失败指数退避 | 避免 429，稳定性显著提升 |
| **尽快可听** | 先合成第 1 段并立刻回传 URL，前端"边生成边听" | 首字延迟从"全书完成"降到 ~2 秒 |
| **合并零重编码** | `ffmpeg -c copy` concat | 千段合并 <1 秒，音质无损（若重编码会数十倍耗时且有损） |
| **长文本流式** | 章节独立成任务，支持只重跑失败章节 | 失败局部化，不用全书重来 |
| **LLM 解析优化** | 块间传 roster；`temperature=0`；规则兜底 | 减少角色别名漂移，模型挂了也能降级出结果 |
| **静态资源** | 音频走 CDN / 支持 Range 请求（HTTP 206） | 播放器拖动进度才不卡 |
| **DB** | SQLite 打开 WAL + `busy_timeout`；批量写 job 状态 | 多线程 Worker 下不锁死 |

### 7.3 注意事项（风险与合规）

1. **版权是硬底线**。页面必须在输入区上方常显提示；上传前强制勾选；服务端也要校验 `copyright_ack`（不校验的话，绕过前端就能传受版权保护的作品）；建议在用户协议里明确"用户自担内容责任"，并对明显侵权内容保留处置权。**这是二面 / 真上线都会被问到的点**。
2. **edge-tts 是非官方逆向接口**，随时可能变更或被限制，且协议上不适合商用。**演示用可以，商用必须换 Azure 或开源自托管**——这一点务必写在 README 和 AI_USAGE 里（你们项目本来就有如实说明 AI 使用的要求）。
3. **本地 LLM 解析能力有限**：7B 模型在长对话情绪识别、古文/诗词断句、方言对话上会出错。**必须做"人工可校正"**：前端允许手工改 speaker/emotion/speed/多音字，否则一旦解析错了用户就没救了。这是产品层面的关键决策——**AI 是辅助，最终决定权交给用户**。
4. **多音字/专名永远修不完**：设计上要让用户能"改一次记住一次"（写入 `lexicon` 表，同书复用，甚至跨书复用）。
5. **成本与配额**：Azure 按字符计费，长篇要预估；建议加"字数上限"和"任务总成本预估"提醒。
6. **ffmpeg 是硬依赖**，部署文档要写清安装方式；Windows 上注意加入 PATH。
7. **隐私**：文本会送到云端 TTS（edge-tts/Azure）。若强调"数据不出机器"，必须换本地 CosyVoice——这是场景限制的取舍，要如实告知用户。
8. **别让 LLM 改写原文**（反复强调）：技术上用 offset 回填 + 前后字数校验兜底，这是"有声书"而不是"AI 改写小说"的分界线。

### 7.4 建议的 MVP 排期（按你 3 天冲刺的节奏做裁剪）

| 阶段 | 产出 | 建议投入 |
| --- | --- | --- |
| M1 能听 | txt 上传 + 规则切分（先不接 LLM）+ edge-tts 单音色合成 + 播放下载 | 半天 |
| M2 会导演 | 接本地 LLM 解析 → 结构化 JSON → 旁白/对话分色 + 语速/停顿 | 半天 |
| M3 能批量 | 队列 + 重试 + 并发 + ffmpeg 合并 + SSE 进度 | 半天 |
| M4 可交付 | 角色音色配置 UI + 发音词典 + 生成记录 + 版权提示 + README | 半天 |
| M5 进阶（可选） | 切 Azure Provider / 本��� TTS / 音色克隆 / 背景音乐 | 视时间 |

---

## 附：这套设计与华小牛主项目的一致性

- **Provider 抽象**：TTS Provider 与现有 `llm/provider.py` 同构——换底层只改一个环境变量，这是你已确立的架构思想的自然延伸（面试很好讲）。
- **事件契约**：合成进度用 SSE，和 `server/app/core/events.py` 同一套机制；前端 `hooks/` 订阅式的写法可以直接复用。
- **分层与组合根**：后端仍是一份组合根 + 分层模块，主程序不做业务逻辑。
- **如实说明 AI 使用**：edge-tts 的合规风险、本地 7B 模型的解析局限，都应写进 `AI_USAGE.md`——正好呼应你们项目的要求。
