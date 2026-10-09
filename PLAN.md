# 实施计划（待确认）

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

### Day 1（今天 ~ 明天上午）
1. 重构后端为上面的分层结构 + 顶部注释 + 各层 README
2. 生成事件契约与前端 TS 类型（含校验脚本）
3. 前端 Vite + React 骨架，跑通对话流
4. YOLO 数据集准备 + 首轮训练跑起来

### Day 2
1. 实时检测推流接入前端（MJPEG，canvas 叠加检测框）
2. Harness 闭环跑通（目标：至少 3 轮超参搜索）
3. 硬件部分：串口协议层 + Wokwi 仿真（可选，视时间）

### Day 3
1. 文档补齐（含 README 启动命令）
2. git 规范化提交 + 推送 GitHub
3. 演示脚本打磨、录一段演示

---

## 七、需要你拍板的 4 件事

1. **仓库名**用 `HuaNiu` 可以吗？需要你先在 GitHub 上建一个**空仓库**（不要勾 README）
2. **YOLO 数据集**用哪个？
   - (a) 自带小数据集 `coco8`（快，但太玩具）
   - (b) 公开数据集如 VOC/VisDrone 子集（真实，但下载慢）
   - (c) 你自己拍的照片标注（最贴合"自主实验"，但费时间）
   - 我倾向 **(b) 的一个小子集**，既真实又能跑完
3. **前端风格**：浅色简洁 / 深色科技感？（我默认浅色，跟 IDE 一致）
4. **Harness 的实验对象**就用 YOLO 超参搜索，还是你有更贴合专业的想法？

---

## 八、我现在不会动的东西

在你回复之前，我只做这几件不影响结构的事：
- ✅ 已删除 5.9GB 冗余文件
- ✅ 已配好 git 身份（`rushangyun` / `1906707288@qq.com`）并确认能连 GitHub
- ⏸ 代码重构、前端、训练 —— 等你确认
