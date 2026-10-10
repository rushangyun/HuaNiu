# 实施计划与排期

> 记录**接下来要做什么**：里程碑、当前状态、阻塞项、待确认事项（将来时）。
>
> | 文档 | 时态 | 内容 |
> |---|---|---|
> | **`PLAN.md`**（本文件） | 将来时 | 计划 / 排期 / 状态 / 待确认 |
> | [`DEVLOG.md`](DEVLOG.md) | 过去时 | 做了什么 / 卡在哪 / 实测数据 |
> | [`README.md`](README.md) | 现在时 | 项目是什么 / 怎么启动 |
>
> **分工红线**：本文件只写"打算怎么做"；做完之后的具体过程、证据、踩坑一律写进 DEVLOG。
> 反过来，DEVLOG 不重复解释"为什么这么设计"，只记决策结果与验证数据。
> （原标题为「待确认」，2026-10-10 用户已全部确认，改为正式排期。）

> 这份文档是为了让你先挑毛病。
> **确认之前我不动现有代码结构**，避免白干。

---

## 一、你要的五条要求，我怎么落地

| 你的要求 | 落地方式 |
| --- | --- |
| 代码模块化封装，主程序只负责组装 | `server/main.py` 和 `web/src/main.tsx` 做成**组合根**：只做「读配置 → 造模块 → 接依赖」，一行业务逻辑都不写 |
| 按功能组织文件层级 | 后端按`能力域`分层（llm / agent / vision / transport / api），工具按`用途`再拆文件 |
| 代码顶部写简明注释 | 每个文件顶部统一写：**这个文件干什么 + 为什么不这么干不行**。不是"定义了一个类"这种废话 |
| 前后端高度解耦 | 前后端之间**只有一个耦合点：事件契约**。前端只做 UI 组织 + 订阅；后端只做计算 + 推送 |
| 根 README 带启动命令 / 每个功能文件夹有 README | 根目录 README 顶部就是三条启动命令；每个含代码的目录配一份 5~15 行 README |

---

## 二、新的目录结构

```
HuaNiu/
├── README.md              总览 + 启动命令
├── PLAN.md                本文件（确认后删除或移入 docs/）
├── DEVLOG.md              工程日志
├── AI_USAGE.md            AI 使用情况
│
├── scripts/               【README】一键脚本
│   ├── setup.ps1          装环境
│   ├── dev.ps1            起服务
│   └── fetch_model.ps1    拉模型权重
│
├── server/                【README】后端：只负责计算与推送
│   ├── requirements.txt
│   ├── main.py            ★ 组合根：装配，无业务逻辑
│   └── app/
│       ├── README.md
│       ├── config.py      所有可配项集中在此
│       │
│       ├── core/          【README】契约层 —— 前后端解耦的关键
│       │   ├── events.py      事件数据结构（唯一的跨端契约）
│       │   └── errors.py      统一错误类型
│       │
│       ├── llm/           【README】模型 provider（可替换）
│       │   └── provider.py    只认 OpenAI 兼容协议
│       │
│       ├── agent/         【README】智能体运行时
│       │   ├── runtime.py     主循环
│       │   ├── registry.py    工具注册与 schema 推断
│       │   ├── prompts.py     上下文装配
│       │   └── tools/     【README】工具按用途拆
│       │       ├── base.py
│       │       ├── system.py      时间 / 计算器 / 设备信息
│       │       ├── filesystem.py  列目录 / 读文件
│       │       ├── vision.py      图像检测
│       │       └── lab.py         实验相关（Harness 用）
│       │
│       ├── vision/        【README】视觉：只负责算
│       │   ├── detector.py    YOLO 推理
│       │   └── stream.py      帧采集与推流源
│       │
│       ├── transport/     【README】推送层：只负责发
│       │   └── sse.py         SSE 编码，不含业务
│       │
│       └── api/           【README】HTTP 路由（薄）
│           ├── chat.py
│           ├── vision.py
│           └── health.py
│
├── web/                   【README】前端：只负责 UI 组织与订阅
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── README.md
│       ├── main.tsx       ★ 组合根：挂载 + 注入 client
│       ├── App.tsx        纯 UI 组织
│       ├── types/
│       │   └── events.ts  ★ 与后端 core/events.py 一一对应
│       ├── api/           【README】唯一的后端耦合点
│       │   ├── client.ts      HTTP 客户端
│       │   └── subscribe.ts   事件流订阅
│       ├── hooks/         订阅逻辑，组件不含网络代码
│       │   ├── useChatStream.ts
│       │   └── useVisionStream.ts
│       └── components/    纯展示组件，不含网络代码
│           ├── ChatPanel.tsx
│           ├── MessageList.tsx
│           ├── ToolTrace.tsx
│           └── VisionCanvas.tsx
│
├── training/              【README】YOLO 训练（独立于服务）
│   ├── configs/yolo.yaml
│   ├── prepare_data.py
│   └── train.py
│
├── harness/               【README】自主实验闭环（你的专业方向）
│   ├── main.py            ★ 组合根
│   ├── planner/           读历史 → 提出下一组超参
│   ├── executor/          跑实验（子进程隔离）
│   ├── observer/          读指标
│   ├── memory/            实验记录（JSONL）
│   └── report/            生成对比与结论
│
├── models/                【README】权重（不入库，脚本下载）
├── data/                  数据集（不入库）
├── runs/                  训练产物（不入库）
└── docs/                  【README】分模块详细文档
```

---

## 三、前后端是怎么做到"高度解耦"的

这是这次重构的核心，单独说清楚。

**唯一契约 = 事件。**

```
后端 core/events.py          前端 types/events.ts
    ChatToken      <----------->  chat_token
    ToolCalled     <----------->  tool_called
    ToolResult     <----------->  tool_result
    VisionFrame    <----------->  vision_frame
    ...
```

分工：

| | 后端 | 前端 |
| --- | --- | --- |
| 职责 | 计算 + 推送事件 | 组织 UI + 订阅事件 |
| 知道对方存在吗 | **不知道**。它只管按契约发事件 | **只知道契约类型**，不知道后端怎么写 |
| 能不能单独替换 | 能。换语言/换框架，只要事件一致 | 能。换 React 为 Vue，后端不用改 |

为了保证契约不漂移，我会加一个小脚本：
从 `core/events.py` 自动生成 `web/src/types/events.ts`，
CI 里跑一次，不一致就报错。**跨端契约不靠人肉同步。**

---

## 四、后端依赖方向（单向，无环）

```
main.py  ──►  api  ──►  agent  ──►  llm   ──►  core
                │         │
                │         └──────►  vision ──►  core
                └──► transport ──────────────►  core
```

规则：
- `core` 谁都能依赖，但它不依赖任何人
- 同层之间不互相依赖（agent 不 import vision，需要视觉能力就走工具注册表）
- `api` 层保持**薄**：只做参数校验和转发，不写业务

---

## 五、Harness：自主实验闭环（结合你的专业方向）

> ✅ **已落地**（2026-10-10）：代码在 [`harness/`](harness/README.md)，
> 过程与验证见 [`DEVLOG.md`](DEVLOG.md) 对应日期条目。
> 本节保留**原始计划意图**，实现细节以代码为准。

你说专业方向是**自主实验闭环**。我的想法是——**不要另起炉灶，直接拿 YOLO 训练当实验对象**。

理由：题目里举的例子是「自主设计实验 → 自主比较实验 → 下一轮设计」，
而我们手上正好有一个天然的、可量化、可重复的实验：**训练一个检测模型**。

```
      ┌─────────────────────────────────────────┐
      │                                         │
      ▼                                         │
  planner  ──►  executor  ──►  observer  ──►  memory
  提出超参      跑训练         收指标         记下来
 （LLM）     （子进程）      （读 results.csv）
```

- **实验** = 一组超参：`{epochs, lr, imgsz, batch, 增强策略, 模型规模}`
- **指标** = `mAP50`、`mAP50-95`、训练耗时、显存峰值
- **闭环** = 模型读历史 JSONL → 提出下一组候选 → 执行 → 回收指标 → 再设计

**为什么强调子进程隔离**：训练会吃满显存、偶尔 OOM 崩掉。
如果和主服务同进程，一次崩溃整个应用就挂了。
用子进程跑，崩了记录一次"失败实验"继续下一轮——**失败本身也是实验数据**。

最后一轮结束后，`report/` 输出一张对比表 + 结论，
这就是题目里"自主完成实验并撰写"的最小可用版本。

> 这块是加分项也是风险点。如果时间紧，我会保证它**能跑通 2~3 轮**，
> 而不是做一个漂亮的空壳。

---

## 六、三天排期

> 最后更新：2026-10-10。✅ 已完成 · ⏳ 进行中 · ⬜ 待办

### Day 1（10-09）— ✅ 已完成

1. ✅ 后端分层重构 + 顶部注释 + 各层 README
2. ✅ 事件契约 → 前端 TS 类型自动生成（`scripts/gen_event_types.py`）
3. ✅ 前端 Vite + React 骨架，跑通对话流
4. ✅ YOLO 数据集准备（train 16551 / val 4952，与官方一致）
5. ✅ 摄像头实时检测推流（MJPEG）接入前后端
6. ✅ Harness 自主实验闭环（含 OOM 剪枝）
7. ✅ git 推送 GitHub（`master` 已同步）

### Day 2（10-10）— ⏳ 进行中

1. ⏳ **训练收尾**：方案 A 已执行（导出 34 epoch `best.pt`，mAP@50=0.804）；方案 B（resume）代码就绪待启动
2. ⬜ **创意作品：AI 有声小说生成网页** —— 设计方案已交付（见 `AUDIOBOOK_DESIGN.md`），待确认离线冲突后开工
3. ✅ 更新日程与如实上报问题

### Day 3（计划）

1. ⬜ 有声小说 MVP 实现（M1 能听 → M2 会导演 → M3 能批量 → M4 可交付）
2. ⬜ `AI_USAGE.md` 补记 edge-tts 合规风险与本地模型解析局限
3. ⬜ 演示打磨 + 推送 GitHub

---

## 六之二、当前阻塞项与待确认（按优先级）

| # | 事项 | 状态 | 需要什么 |
|---|---|---|---|
| 1 | **edge-tts 需联网，与「完全离线」冲突** | 🔴 阻塞 | 你选 A 双 Provider / B 纯离线 / C 放弃离线 |
| 2 | YOLO 训练续跑（B 方案） | 🟡 待定 | 3 小时 GPU；建议夜间挂机 |
| 3 | 有声小说 MVP 实现 | 🟡 待定 | 确认 #1 后开工 |

---

## 七、需要你拍板的事 — ✅ 4 项已全部确认（10-10）

1. ✅ **仓库名** = `HuaNiu`（空仓库已建，代码已推送 master）
2. ✅ **数据集** = **VOC**（train 16551 / val 4952，与官方一致）
3. ✅ **前端风格** = **浅色简洁**
4. ✅ **Harness 实验对象** = **YOLO 超参搜索**

### 🔴 新增待确认（10-10，阻塞实现）

**edge-tts 必须联网，与「完全离线」冲突**：

| 环节 | 离线? |
|---|---|
| AI 解析（本地 Ollama qwen2.5） | ✅ |
| TTS 合成（edge-tts） | ❌ 必须联网 |

本轮已确认的其余 5 项决策：TTS=edge-tts；**完全离线**；本机 demo 但预留上线；
主体整本几十万字（单章辅助）；不做音色克隆但需**同角色跨上下文音色一致**；
**真能批量导出整本 MP3**。

**三选一（待你回复）**：
- **A（推荐）双 Provider**：edge-tts 作联网高质量模式 + 本地 `piper` 离线兜底，默认离线
- **B 纯离线高质量**：CosyVoice2-0.5B / GPT-SoVITS（8GB 显存够），要下 1~2GB 模型
- **C 放弃离线**：全程联网用 edge-tts

## 九、模型额度切换说明（Hy4 preview → Hy3）

用户提示当前 Hy4 preview 额度可能用尽，之后会切到 Hy3 继续。
**无缝接续靠本目录下的日志与 `DEVLOG.md`**：新会话应先读
`.workbuddy/memory/` 最新日志 + `DEVLOG.md` 顶部 + `PLAN.md` 第六节，
即可还原全部上下文、决策与阻塞项，无需用户复述。

---

## 八、我现在不会动的东西

在你回复之前，我只做这几件不影响结构的事：
- ✅ 已删除 5.9GB 冗余文件
- ✅ 已配好 git 身份（`rushangyun` / `1906707288@qq.com`）并确认能连 GitHub
- ⏸ 代码重构、前端、训练 —— 等你确认
