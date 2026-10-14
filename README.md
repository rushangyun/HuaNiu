# 华小牛 HuaNiu

一个**完全跑在你自己电脑上**的视觉智能体：本地大模型当大脑，自己训练的 YOLO 当眼睛，
手写 Agent 运行时当身体，浏览器当脸。断网也能用，数据不出机器。

> 华南农业大学 · 人工智能协会创智部二面实战题
> 设备：RTX 5060 Laptop 8GB / 16GB 内存 / Windows 11

---

## 快速开始

```bash
# 1. 后端依赖
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/pip install --index-url https://download.pytorch.org/whl/cu128 \
    "torch==2.11.0+cu128" "torchvision==0.26.0+cu128"   # 必须用 CUDA 源，见文件内注释

# 2. 本地模型（Ollama）
ollama pull qwen2.5:7b-instruct
ollama serve

# 3. 起后端  → http://127.0.0.1:8000/docs
python server/main.py

# 4. 起前端  → http://127.0.0.1:5173
cd web && npm install && npm run dev
```

改事件契约后要重新生成前端类型：

```bash
python scripts/gen_event_types.py
```

训练视觉模型（可选，约 7 小时；不训练对话也能用，只是"看不见"）：

```bash
python training/prepare_dataset.py   # 下载已在 data/VOC 时会自动跳过
python training/train.py --epochs 100
```

跑自主实验闭环（题目第四部分，超参搜索；失败/OOM 也算一条记录）：

```bash
python harness/run.py                  # 默认 8 组、每组 8 epoch
python harness/run.py --max-trials 4 --epochs 5   # 先小跑验证闭环
python harness/run.py --reset          # 清空历史重来
```

---

## 架构

```
浏览器 (React)  ──只订阅事件──>  ┌──────────────────────────────┐
                                │  server/                     │
                                │   main.py  组合根（只做组装） │
                                │     ↓ 注入                   │
                                │   agent/   工具调用主循环     │
                                │   llm/     OpenAI 兼容协议    │
                                │   vision/  YOLO 推理          │
                                │   transport/ SSE 推送         │
                                │   api/     薄路由             │
                                │   audiobook/ 有声书解析·合成  │
                                │   core/    契约 · 配置        │
                                └──────────┬───────────────────┘
                                           │ HTTP
                                ┌──────────▼──────────┐
                                │ Ollama  qwen2.5:7b  │
                                └─────────────────────┘
```

**前后端唯一的耦合点**是 `server/app/core/events.py` 里的事件契约，
TypeScript 类型由 `scripts/gen_event_types.py` 自动生成，不手抄、不漂移。

后端只负责计算和推送，前端只负责组织和订阅——
换模型、换框架、换前端，只要契约不变，两边各自独立替换。

---

## 目录

| 目录 | 说明 |
|---|---|
| [`server/`](server/README.md) | 后端：Agent 运行时、模型接入、视觉推理、SSE 推送 |
| [`web/`](web/README.md) | 前端：React + Vite，浅色简洁 |
| [`training/`](training/README.md) | 训练：数据集准备、YOLO 训练、实验产出 |
| [`harness/`](harness/README.md) | 自主实验闭环：超参搜索（试→记→学→再试） |
| [`scripts/`](scripts/README.md) | 脚本：事件契约 → TS 类型生成 |

根目录还有这几份说明文档（分工见下表，避免内容重复）：

| 文档 | 时态 | 内容 |
|---|---|---|
| [`DEVLOG.md`](DEVLOG.md) | 过去时 | 工程日志：做了什么、卡在哪、怎么解决、实测数据 |
| [`PLAN.md`](PLAN.md) | 将来时 | 排期：里程碑、当前状态、阻塞项、待确认事项 |
| [`AI_USAGE.md`](AI_USAGE.md) | — | AI 使用情况如实说明（题目要求） |
| [`AUDIOBOOK_DESIGN.md`](AUDIOBOOK_DESIGN.md) | — | 创意作品：AI 有声小说网页设计方案 |
| [`AUDIO_QUALITY.md`](AUDIO_QUALITY.md) | — | 创意作品：TTS 双 Provider 落地与音质提升方案 |
| [`KNOWLEDGE.md`](KNOWLEDGE.md) | — | 整个项目流程的重要知识点总结 |

> **分工红线**：`DEVLOG.md` 只记录已发生的事实与证据；`PLAN.md` 只写计划与安排。
> 设计理由放在 `PLAN.md`，实现结果与验证数据放在 `DEVLOG.md`，两边不互相抄。

---

## 当前交付状态（2026-10-14 实测验证）

后端在线用的是**自己训的 VOC 模型**，不是 COCO 预训练兜底：

| 项目 | 状态 |
|---|---|
| 在线视觉模型 | **yolov8s（VOC 20 类）**，位于 `models/yolo/best.pt` |
| 精度 | **mAP50 = 0.8615** / mAP50-95 = 0.6643（对比 yolov8n 的 0.7983 / 0.5765） |
| 推理 | CUDA，稳态约 **4.5 ms/图**（首次调用含模型加载约 2s，属冷启动） |

**两条主线都已实测跑通：**

1. **视觉检测**（与 VOC 标注真值对照）
   样本 `data/VOC/VOCdevkit/VOC2007/JPEGImages/000001.jpg`（真值：1 dog + 1 person）
   → 检出 `person conf=0.942`、`dog conf=0.558`，与标注**完全一致**。
2. **对话智能体**（工具调用 + SSE 流式）
   问「现在几点？」→ 流式返回「现在是2026年10月14日19点08分47秒」，时间正确。
3. **全栈联通**（前端 → 后端 → 模型）
   `npm run dev` 起前端 → `http://127.0.0.1:5173`，其 `/api` 已代理到后端 8000；
   经前端访问 `/api/health` 实测返回 `status=ok`、`视觉=就绪`，说明三层串通。

> ⚠️ 已知问题：harness 的超参覆盖当前失效（传入的 `lr0`、数据增强参数未真正作用于训练），
> 修复前超参搜索结果不可用。排查过程与 A/B 证据见 `DEVLOG.md` 的 2026-10-14。

---

## 现在能做什么

对话时模型会自主调用工具，前端能看到它每一步在干什么：

| 工具 | 作用 |
|---|---|
| `get_current_time` | 当前时间 |
| `calculator` | 算数（AST 白名单求值，不是 `eval`） |
| `get_device_info` | 本机硬件与显存 |
| `list_dir` / `read_file` | 看工程结构、读文件（有沙箱，出不了工作区） |
| `project_overview` | 一句话了解本项目 |
| `vision_status` / `vision_detect` | 检测图片或摄像头画面里的物体（需先训练） |
| **有声书**（顶栏切换） | 粘贴/上传小说正文，本地 LLM 解析角色情绪、edge-tts 合成、整本导出 MP3 / ZIP |

试试问：**「现在几点」**、**「算一下 12345 × 6789」**、**「这个项目是干什么的」**。

---

## 为什么没用 Docker / Dify / LangChain

不是不想用，是**这台机器用不起**：

- 内存 16GB，实测空闲只有 6.5GB。Docker Desktop + Dify 一套下去就见底了
- Agent 主循环本身只有几十行，套框架等于给自己加一层黑盒，
  出了问题还得去猜框架内部在干什么

所以全部手写，代价是多写几百行，收益是每一行都讲得清。
详见 [`PLAN.md`](PLAN.md) 的选型理由表。
