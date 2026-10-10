# 方案 A 落地 + 音质提升方案

> 决策：TTS 用 **edge-tts（联网高质量）** 为主；**本地 piper（离线）** 为兜底。
> 目标：让"整本几十万字"的批量产出听起来像有声书，而不是机器念稿。
> 日期：2026-10-10

---

## 0. 先明确：什么叫"音质好"

有声书不是Hi-Fi，核心是**长时间听不累、听得懂、不出戏**。四个可量化维度：

| 维度 | 目标 | 怎么测 |
|---|---|---|
| **响度一致** | 全书统一 ≈ **-17 LUFS**（±1） | `ffmpeg loudnorm` / `ebur128` |
| **无底噪/齿音** | TTS 常见的电流声、刺耳 "si" 要压掉 | 听感 + 频谱 |
| **节奏自然** | 句间/段间按语义停顿，不是匀速念 | 人工听 30 秒 |
| **角色稳定** | 同一角色全书同一音色，不漂移 | 抽查跨章节 |

---

## 1. 方案 A 落地：双 Provider 怎么摆

### 1.1 抽象接口（换引擎只改一个变量）

```python
# app/tts/base.py
class TTSProvider(Protocol):
    name: str
    async def synth(self, text: str, spec: VoiceSpec, out_path: str) -> str: ...
```

```python
# app/tts/factory.py
def build_tts() -> TTSProvider:
    kind = os.getenv("TTS_PROVIDER", "edge")   # edge | azure | piper
    if kind == "edge":  return EdgeTTSProvider()
    if kind == "piper": return PiperProvider(os.getenv("PIPER_BIN"), os.getenv("PIPER_MODEL"))
    ...
```

### 1.2 两个 Provider 的定位

| | **edge-tts**（默认，联网） | **piper**（离线兜底） |
|---|---|---|
| 音质 | ★★★★☆（Azure 同款神经音色） | ★★★☆☆（清晰但偏机械） |
| 情绪 | rate/pitch + 部分 style | 基本只有 rate |
| 离线 | ❌ | ✅ |
| 成本 | 免费 | 免费 |
| 适用 | 正式合成、导出 | 断网演示、草稿试听 |

**降级策略**：检测 `edge-tts` 不可达（超时/非 200）→ 自动切 piper，并在 UI 顶部挂一条提示条「当前离线，已切换为本地语音，音质与情绪表现下降」。**不让用户一脸懵**。

### 1.3 音色清单（中文推荐）

| 角色类型 | edge-tts voice_id |
|---|---|
| 旁白（稳重男声） | `zh-CN-YunyangNeural` |
| 旁白（激昂/武侠） | `zh-CN-YunjianNeural` |
| 老年男声 | `zh-CN-YunyeNeural` |
| 青年男声 | `zh-CN-YunxiNeural` |
| 温柔女声（通用） | `zh-CN-XiaoxiaoNeural` |
| 活泼少女 | `zh-CN-XiaoyiNeural` |
| 成熟女声 | `zh-CN-XiaochenNeural` |
| 童声 | `zh-CN-YunxiaNeural` |

---

## 2. 音质提升：四层递进（按性价比排序）

### L0 · 文本归一化 —— **最便宜、收益最大**

TTS 读错的绝大多数问题，根源在文本，不在模型。

| 问题 | 处理 |
|---|---|
| 数字/年份 | `2024年`→`二零二四年`、`第3章`→`第三章` |
| 小数/百分比 | `15.6%`→`百分之十五点六` |
| 单位 | `5kg`→`五千克`、`3km`→`三千米` |
| 英文专名 | 查自定义词典，或加空格改善发音 |
| 古文/诗词 | 按韵脚断句，避免一口气读完 |
| 引号/破折号 | 映射为停顿，而不是读出符号名 |

```python
def normalize_for_tts(text: str) -> str:
    text = _numbers_to_chinese(text)     # 数字
    text = _apply_lexicon(text)          # 多音字/专名
    text = _punct_to_pause(text)         # 符号 → 停顿标记
    return text
```

### L1 · TTS 参数层 —— 让声音"有情绪"

```python
@dataclass
class VoiceSpec:
    voice_id: str
    speed: float = 1.0      # 0.8~1.3
    pitch: str = "+0Hz"     # 女声可 +2Hz，老人 -3Hz
    volume: str = "+0%"
    style: str | None = None       # Azure: cheerful/sad/angry/fearful/serious...
    style_degree: float = 1.0
```

经验值（可直接抄）：

| 场景 | speed | pitch | 备注 |
|---|---|---|---|
| 旁白叙述 | 1.0 | +0Hz | 基准 |
| 紧张/打斗 | 1.15 | +1Hz | 稍快 |
| 悲伤/离别 | 0.90 | -2Hz | 慢且低 |
| 愤怒/争吵 | 1.20 | +2Hz | 快且高 |
| 老年角色 | 0.90 | -3Hz | 慢、低沉 |
| 童声角色 | 1.10 | +4Hz | 快、偏高 |
| 内心独白 | 0.95 | -1Hz | 轻、慢 |

**停顿**（比语速更能决定"像不像人"）：

| 位置 | 静音 |
|---|---|
| 普通句末 `。` | 200 ms |
| `？！` | 400 ms |
| 省略号 `……` | 600 ms |
| 破折号 `——` | 300 ms |
| **场景/章节切换** | 800~1200 ms |
| **叙述 ↔ 对话 交替** | 400 ms |

### L2 · 音频后处理 —— ffmpeg 一条流水线（关键）

单段统一处理，保证后面能 `-c copy` 零重编码合并：

```bash
ffmpeg -y -i "$IN" -af "\
afftdn=nf=-30,\
deesser=i=0.4:m=0.5:f=0.5:s=o,\
acompressor=threshold=0.089:ratio=3:attack=20:release=250:makeup=1,\
equalizer=f=150:t=q:w=1:g=2,\
equalizer=f=8000:t=q:w=1:g=-2,\
loudnorm=I=-17:TP=-1.5:LRA=11\
" -ar 24000 -ac 1 -b:a 96k "$OUT"
```

各步作用：

| 滤镜 | 作用 | 注意 |
|---|---|---|
| `afftdn` | 自适应降噪，去 TTS 底噪 | `nf` 别调太低，否则声音发闷（"水下声"） |
| `deesser` | 压制齿音 "s/sh" | 轻度即可 |
| `acompressor` | 动态压缩，缩小轻声/重声差距 | 长时间听不累的关键 |
| `equalizer` f=150 +2dB | 补中低频，声音更"厚"有质感 | 别过量，否则浑浊 |
| `equalizer` f=8000 -2dB | 压高频，减少刺耳 | — |
| `loudnorm` | 响度统一到 -17 LUFS | 有声书标准区间 |

**合并（零重编码，秒级）**：

```bash
printf "file '%s'\n" seg_*.mp3 > list.txt
ffmpeg -y -f concat -safe 0 -i list.txt -c copy chapter_01.mp3
```

> ⚠️ 前提：所有段必须**同编码器/采样率/声道**。`-c copy` 才不会出错——正因为 L2 统一了参数，这里才能无损秒合并。

**静音片段生成**（段间停顿）：

```bash
ffmpeg -y -f lavfi -i anullsrc=r=24000:cl=mono -t 0.4 \
  -acodec libmp3lame -b:a 96k silence_400ms.mp3
```
预生成 200/400/800/1200ms 几种，合并时直接插入。

### L3 · 工程层（整本几十万字才需要）

| 措施 | 作用 |
|---|---|
| **段落哈希缓存** | 相同文本+音色+参数直接复用，省钱省时，且保证一致 |
| **并发限流** | edge-tts 并发 2~4，避免 429 触发重试风暴 |
| **断点续传** | 崩溃/关机后重进页面继续，不从头再来 |
| **章节级任务** | 失败局部化；先合成第 1 段就能立刻试听 |
| **失败重试** | 指数退避（2/4/8s），最多 3 次 |

---

## 3. 角色音色一致性（你的第 6 条要求，重点）

不做音色克隆，但要**保证同一角色全书一个音色**。靠三件事：

1. **持久化映射表**（`speakers` 表）
   ```
   旁白 → zh-CN-YunyangNeural
   林晚 → zh-CN-XiaoxiaoNeural
   沈宴 → zh-CN-YunxiNeural
   ```
   一次配置，全书复用。**绝不每段临场猜**。

2. **角色名册回传**（分块解析时）
   每解析完一块，把新出现的角色名合并进 roster，下一块带上。
   → 解决"林晚 / 林姑娘 / 她"被当成三个人的漂移问题。

3. **兜底规则**：识别不出说话人的对话，归入最近一次有明确说话人的角色；
   再不行归旁白，并标记 `speaker_confidence` 低，前端高亮提醒检查。

**降级到 piper 时**：piper 中文音色少，角色区分度会下降。
→ 策略：piper 只给「旁白 / 男 / 女」三种基础音色，并在 UI 明确提示「离线模式：角色区分度降低」。

---

## 4. 三档音质预设（一键切换）

| 档位 | 语速 | 后处理 | 用途 |
|---|---|---|---|
| **草稿** | 1.15 | 无（只做响度归一） | 快速试听、调角色 |
| **标准** | 1.00 | 降噪 + 压缩 + 响度 | 日常收听 |
| **精品** | 0.95 | 全套（+ EQ + 齿音） | 最终导出/分享 |

---

## 5. 注意事项（别踩）

1. **降噪别过头**：`afftdn` 的 `nf` 调太低（如 -40）会产生明显的"水下声/金属声"。建议 -25~-30，先小样本试听再定。
2. **参数必须统一**：采样率/声道/编码器一乱，`-c copy` 合并就会报错或音画不同步。
3. **多音字修不完**：设计上要支持「改一次、全书记住」（写入 `lexicon` 表）。
4. **edge-tts 是非官方接口**：可能限流或变更；生产换 Azure。演示可保留，但要在 `AI_USAGE.md` 如实写明。
5. **离线 ≠ 高质量**：piper 保证能出声，但情绪表现远不如 edge-tts。两者是「可用性 ↔ 表现力」的取舍，别对离线档期待过高。
6. **版权**：页面常显提示 + 上传前强制勾选 + 服务端校验，缺一不可。
