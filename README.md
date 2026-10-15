# 华小牛 HuaNiu

一句话：**这是个装在你自己电脑里的视觉智能体**。

本地大模型当脑子，自己训的 YOLO 当眼睛，手写的 Agent 循环当身体，浏览器就是它的脸。
断网也能跑，数据不出机器。

> 华南农业大学 · 人工智能协会创智部二面实战题
> 开发机：RTX 5060 Laptop **8GB 显存** / 16GB 内存 / Windows 11。
> 显存只有 8G，后面很多取舍都是被它逼出来的。

---

## 先跑起来

按顺序四步：

```bash
# 1. 装后端依赖
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/pip install --index-url https://download.pytorch.org/whl/cu128 \
    "torch==2.11.0+cu128" "torchvision==0.26.0+cu128"   # 必须走 CUDA 源，否则只能 CPU 推理

# 2. 拉本地大模型（Ollama）
ollama pull qwen2.5:7b-instruct
ollama serve

# 3. 起后端 → http://127.0.0.1:8000/docs （有 Swagger，可以直接点着试接口）
python server/main.py

# 4. 起前端 → http://127.0.0.1:5173
cd web && npm install && npm run dev
```

**改了事件契约之后**，记得重新生成前端类型：

```bash
python scripts/gen_event_types.py
```

**训视觉模型**（可选）：不训也能正常聊天，只是它"看不见"。

```bash
python training/prepare_dataset.py        # data/VOC 已存在时会自动跳过
python training/train.py --epochs 100     # n 约 1 小时，s 约 4 小时
```

**跑自主实验闭环**（超参搜索，失败和 OOM 也算一条记录）：

```bash
python harness/run.py                            # 默认 8 组、每组 8 轮
python harness/run.py --max-trials 4 --epochs 5  # 先小跑一次，确认闭环是通的
python harness/run.py --reset                    # 清空历史重来
```

---

## 它能干什么

打开前端，顶栏三个页：**对话 / 视觉 / 有声书**。

### 对话

你说一句，它自己决定要不要用工具。工具什么时候开始、返回了什么、最后怎么回答，
界面上一步一步都看得见，不是黑盒。

试试问：**「现在几点」**、**「算一下 12345 × 6789」**、**「这个项目是干什么的」**。

| 工具 | 干什么 |
|---|---|
| `get_current_time` | 现在几点 |
| `calculator` | 算数（AST 白名单求值，**不是** `eval`，所以塞不进恶意代码） |
| `get_device_info` | 看看这台机器的硬件和显存 |
| `list_dir` / `read_file` | 看目录、读文件（有沙箱，出不了工作区） |
| `project_overview` | 一句话说清这个项目 |
| `vision_status` / `vision_detect` | 检测图片或摄像头画面里的东西（要先训模型） |

### 视觉

摄像头实时检测，画面上直接画框 + 报数量。用的是**自己训的模型**，认得 VOC 的 20 类
（人、狗、车、猫、椅子……）。

### 有声书

粘一段小说正文进去，本地 LLM 会分角色、标情绪语速，再合成语音。
能一段一段试听，也能整本导出 MP3 / ZIP。

---

## 到什么程度了

不吹，下面是**实际跑出来的数字**（2026-10-15）：

| 项 | 数字 |
|---|---|
| 在线用的模型 | **yolov8s（VOC 20 类）**，`models/yolo/best.pt` |
| 精度 | **mAP50 = 0.8615** / mAP50-95 = 0.6643 |
| 对比 yolov8n | 0.7983 / 0.5765 —— 换个更大的模型，涨了 **0.063** |
| 推理速度 | CUDA 稳态 **4.5 ms/图**（第一次调用约 2 秒，那是在加载模型） |

怎么验的：

1. **视觉**：拿 VOC 里一张图（标注真值是 1 只狗 + 1 个人），
   模型检出 `person 0.942`、`dog 0.558`，跟标注**完全一致**。
2. **对话**：问「算一下 12345 × 6789」→ 它调了 `calculator` → 回答「结果是 83810205」，正确。
3. **三层串通**：前端 `/api` 代理到后端 8000，实测经前端能拿到后端的健康状态。

顺带说一个自己挖出来的坑：自主实验闭环**曾经是假跑**——8 组实验结果一模一样。
查下去发现是 ultralytics 默认 `optimizer='auto'`，会把我们传的 `lr0` 和 `momentum` 悄悄吞掉。
修好之后才搜出真结论（`lr0=0.001` 比 `0.01` 高了 0.045）。过程写在 `DEVLOG.md` 的 2026-10-14。

---

## 架构，一句话版

**后端只管算和推，前端只管订阅和展示**，两边唯一的约定是事件契约（`server/app/core/events.py`）。
契约一改，前端的 TypeScript 类型由脚本自动生成——不手抄，所以不会悄悄漂移。
于是换模型、换前端，只要契约不动，两边各换各的。

```
浏览器 (React) ──只订阅事件──> ┌──────────────────────────────┐
                              │  server/                     │
                              │   main.py   组合根（只做组装）│
                              │     ↓ 注入                   │
                              │   agent/    工具调用主循环    │
                              │   llm/      OpenAI 兼容协议   │
                              │   vision/   YOLO 推理         │
                              │   transport/ SSE 推送         │
                              │   api/      薄路由            │
                              │   audiobook/ 有声书解析·合成  │
                              │   core/     契约 · 配置       │
                              └──────────┬───────────────────┘
                                         │ HTTP
                              ┌──────────▼──────────┐
                              │ Ollama  qwen2.5:7b  │
                              └─────────────────────┘
```

---

## 目录

| 目录 | 里面是啥 |
|---|---|
| [`server/`](server/README.md) | 后端：Agent 循环、模型接入、视觉推理、SSE 推送、有声书 |
| [`web/`](web/README.md) | 前端：React + Vite，浅色简洁 |
| [`training/`](training/README.md) | 训练：数据集准备、YOLO 训练、实验产出 |
| [`harness/`](harness/README.md) | 自主实验闭环：超参搜索（试 → 记 → 学 → 再试） |
| [`scripts/`](scripts/README.md) | 脚本：事件契约 → TS 类型生成 |

根目录还有几份文档，各管一段，不重复写：

| 文档 | 时态 | 内容 |
|---|---|---|
| [`DEVLOG.md`](DEVLOG.md) | 过去时 | 工程日志：做了什么、卡在哪、怎么解决的、实测数据 |
| [`PLAN.md`](PLAN.md) | 将来时 | 排期：里程碑、当前状态、待办 |
| [`AI_USAGE.md`](AI_USAGE.md) | — | AI 使用情况的如实说明（题目要求） |
| [`AUDIOBOOK_DESIGN.md`](AUDIOBOOK_DESIGN.md) | — | 创意作品：AI 有声小说的设计方案 |
| [`AUDIO_QUALITY.md`](AUDIO_QUALITY.md) | — | 创意作品：TTS 双 Provider 与音质方案 |
| [`KNOWLEDGE.md`](KNOWLEDGE.md) | — | 整个项目流程的知识点总结 |

> 分工红线：`DEVLOG.md` 只记已经发生的事实和证据，`PLAN.md` 只写计划和安排，两边不互相抄。

---

## 已知的坑，不藏着

- **有声书要联网**：默认走 edge-tts，音色好但要联网；piper 是离线兜底，不过没默认打包中文模型。
  所以"完全离线"这块还差一步。
- **演示时别点错书**：库里只有**《测试书-夜雨》**的两章是真合成好的，
  另外几本还没跑合成，点开播放器是空的。
- **只认得 20 类**：训练用的是 VOC 数据集，20 类之外的东西它认不出来。
  这是数据集决定的，不是 bug。
- **摄像头**：实时检测依赖本机摄像头可用。没摄像头也能正常对话，只是视觉页没画面。

---

## 为什么没上 Docker / Dify / LangChain

不是不想用，是这台机器真扛不住：

- 内存 16G，实测空闲就 6.5G 左右，Docker Desktop + Dify 一套下去直接见底；
- Agent 主循环自己写也就几十行，套个框架等于给自己加一层黑盒，
  出了问题还得去猜框架内部在干什么。

所以全部手写。代价是多写几百行，好处是每一行都讲得清。
选型对比表在 [`PLAN.md`](PLAN.md)。
