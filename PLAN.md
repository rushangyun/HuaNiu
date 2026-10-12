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

### Day 3（10-11）— ✅ 已完成

1. ✅ 有声小说 MVP 实现（M1 能听 → M2 会导演 → M3 能批量 → M4 可交付）
   - 端到端验证：本地 Ollama 解析自动识别 4 角色并分配音色；2 章 7 段合成 done=7 failed=0（edge-tts 联网）
   - 详见 [`DEVLOG.md`](DEVLOG.md) 2026-10-11 条目
2. ✅ `AI_USAGE.md` 已补记 edge-tts 合规风险（数据出境）与本地模型解析局限
3. ✅ 演示打磨 + 推送 GitHub（commit `5fcbf3b` → origin/master）
4. ✅ 解析质量与角色声线修复（commit `7c48b62` → origin/master）
   - 修复前端创建后卡「解析中」、解析产出垃圾（碎片段/假角色名）、男角色被配女声、旁白被角色声线替代
   - 解析器重构为「程序切句 + LLM 只标注」；角色性别按 LLM 上下文提示 + 代词归因判定；对白必须带引号
   - 新增 `POST /api/novels/{nid}/reparse` 旧书重解析。详见 [`DEVLOG.md`](DEVLOG.md) 2026-10-11（续）
5. ✅ 二次复核后的根治修复（commit `8c7fc3a` + `4778449` → origin/master，HEAD==origin/master）
   - 用户复核指出「旁白仍被角色声线替代」未解决；量化复核确认属实。根因比首轮更深：
     **跨句引号**（？ 落在引号内）被「先按句切再按引号切」劈成两半，后半段带悬空引号被判成对白；
     而所谓「段落缺失」实为**分块 100 字重叠被解析两次**导致的重复落库（881 字原文拼出 978 字）。
   - 修法：切分改为「先按引号切、再在非引号区按句切」；按片段边界分批（**无重叠**）；
     逐片段标注后只按 kind+speaker 归并（**绝不跨旁白/对白合并**）；章节级段落序号。
   - 验证：文本覆盖率 100%（881=881）、旁白被角色声线读 0/27、声线 林昭/老掌柜/谢无咎=男声 苏晚=女声。

### Day 4（10-12）— ⬜ 待办（10-11 晚只做收尾，行动明天进行）

依据 2026-10-11 晚的**项目完善度审查**（结论见当日 memory 日志）排优先级：

1. ✅ **补 13 个二级子模块 README** — **已完成（13/13）**，命中题目「每个功能文件夹有 README」。
   `server/app/` 下 9 份（app, core, llm, agent, agent/tools, vision, transport, api, audiobook）、
   `web/src/` 下 4 份（src, api, hooks, components）。每份写明「干什么 + 为什么不这么干不行」，
   并记录了本项目真实踩过的坑（延迟加载 torch、SSE `[DONE]` 撞名、进度流不回刷内容等）。
2. ⬜ **加 pytest 最小套件**（约 15~20 分钟）— 覆盖文本归一化、切分保真（覆盖率 100% 检查）、
   事件契约→TS 生成一致性。
3. ⬜ **加 GitHub Actions**（约 5 分钟）— 跑契约校验 + pytest，兑现第三节
   「CI 里跑一次，不一致就报错」的承诺（**目前该承诺未落地**）。
4. ⬜ **YOLO 训练 B 方案续跑**（3 小时 GPU，建议夜间挂机）— 代码就绪，`best.pt` 现停 34 epoch。
5. ⬜ **有声书增强项** — 情绪真正调制语音、piper 离线开箱、整本几十万字压测、角色名册跨块归并。

---

## 六之二、当前阻塞项与待确认（按优先级）

| # | 事项 | 状态 | 需要什么 |
|---|---|---|---|
| 1 | **edge-tts 需联网，与「完全离线」冲突** | ✅ 已落地（双 Provider：edge-tts 联网高质量 + piper 离线兜底，默认 edge-tts） | — |
| 2 | YOLO 训练续跑（B 方案） | 🟡 待定 | 3 小时 GPU；建议夜间挂机 |
| 3 | 有声小说 MVP 实现 | ✅ 已完成（2026-10-11，见 DEVLOG） | — |

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

## 九、模型交接计划（Hy4 preview → Hy3 / 下一个模型）

> 用户提示当前模型额度可能用尽，之后会切到下一个模型继续。
> **无缝接续靠本目录下的日志与 `DEVLOG.md`**：新会话先读下面三个信息源即可还原全部上下文、决策与阻塞项，无需用户复述。

### 9.1 接续入口（按此顺序读）
1. `.workbuddy/memory/` 最新日期日志（最精炼的当日事实）
2. `DEVLOG.md` 顶部最新条目（过去时：做了什么 / 卡在哪 / 实测数据）
3. `PLAN.md` 本文件第六节排期 + 本节（将来时：排期 / 状态 / 待办）

> 📌 本会话（2026-10-11）已实际按此机制接续成功。保持机制有效的关键：**三个信息源要同步**——DEVLOG 记最新事实、本文件排期/阻塞项及时翻牌、memory 每日补记。

### 9.2 当前状态快照（2026-10-11 交接时点）
- **创意作品「AI 有声小说」MVP 已完整落地并两轮修复**，最新 commit `7c48b62` 已推送 `origin/master`。
- 已完成：建书（粘贴/上传 + 版权校验）→ 本地 Ollama `qwen2.5:7b-instruct` 解析（角色/情绪/语速标注）→ edge-tts 联网合成 → 章节/全书合并下载。前端三视图（对话/视觉/有声书）就绪。
- 已修复并通过验证：前端创建后卡「解析中」；解析产出垃圾（碎片段/假角色名）；男角色被配女声；旁白被角色声线替代。
- 运行方式：后端 `HUANIU_RELOAD=0 .../server/main.py`（:8000）、前端 `web/` 下 `npm run dev`（:5173）。本地 LLM 需 Ollama 已 `pull qwen2.5:7b-instruct` 并 `serve`。
- 示例书 `nov_a7aa0e0682b102c7`（《雨夜客栈》）已按修复后解析为正确结果，可直接试听。

### 9.3 下一个模型的优先事项（按建议顺序）
1. **整本几十万字压测**：目前只验过 ~1 千字短篇。用真实长篇测解析耗时、token 预算、合成稳定性。
2. **角色名册跨块归并**：同一角色在不同块可能被识别为不同名（如敲门人被分别叫「门外的人」「敲门人」），需按别名/上下文合并同一实体，避免重复声线条目。
3. **M2 情绪真正调制语音**：当前只标注 emotion 未影响发声（edge-tts 不支持 style/emotion；可换支持情绪的 TTS 或用 SSML）。
4. **piper 离线兜底开箱**：默认打包一个中文模型，实现真正可离线。
5. **前端便捷按钮**：把「重新解析」（已有 `POST /api/novels/{nid}/reparse`）、「单段情绪/语速试听」补到 `AudiobookView`。
6. **YOLO 训练续跑（B 方案）**：代码就绪，需 3 小时 GPU，建议夜间挂机（与本作品无关，独立线）。

### 9.4 关键坑（避免重踩）
- **改了 `server/app/audiobook/parser.py` / `pipeline.py` 等后端代码后必须重启后端进程**才生效（无热重载）。端口杀进程注意 Git Bash 会把 `/PID` 当路径，用 `MSYS_NO_PATHCONV=1 taskkill /PID <pid> /F`。
- 隔离 venv：`C:\Users\19067\.workbuddy\binaries\python\envs\default\Scripts\python.exe`；装包用 `python -m pip install`（别 `pip install --upgrade pip`，会自升级失败）。
- 后端探测/脚本要加 `curl --noproxy '*'`（本机有 http_proxy，否则误判端口被占/502）。
- 推送用 `bash scripts/push.sh master`（自动读代理端口 + 重试）；网络不通时生成 bundle 兜底。
- `storage/`、`*.bundle`、`.huaniu.pids` 是运行产物，**不入库**。

### 9.5 明日（2026-10-12）开工清单 —— 下一个模型的第一个动作

> 10-11 晚已做完全部收尾（两套修复已提交推送、HEAD==origin/master、全套服务在线）。
> **明天/下一个模型直接按本清单执行，不要重新做一遍分析。**

1. **先读三处**：本文件第六节 **Day 4** + 本节，再读 `.workbuddy/memory/2026-10-11.md`
   （里面有完善度审查的**五项缺口**明细，是 Day 4 排期的依据）。
2. **第一件事**：补 13 个二级子模块 README（完整列表见 Day 4 第 1 项）。
   每份 5~15 行，写法对齐现有 `server/README.md` / `web/README.md`：
   「这个文件干什么 + 为什么不这么干不行」。这是题目明确要求，也是最容易被当场发现的一条。
3. **第二件事**：建 `tests/`（pytest），至少覆盖：
   文本归一化、chunking 切分保真（用「段落拼接长度 == 原文长度」这条断言）、
   事件契约→TS 生成一致性。
4. **第三件事**：加 `.github/workflows/ci.yml`，跑契约校验 + pytest，
   兑现第三节「CI 里跑一次，不一致就报错」的承诺。
   （若 `scripts/gen_event_types.py` 没有 `--check` 参数，先给它加一个。）
5. **收尾习惯**：每完成一件就 `git add` + Conventional Commits 提交，
   再 `bash scripts/push.sh master`。**推送可能很慢（走代理），务必后台运行**，不要在前台等。
6. 改 `server/app/**` 下任何代码后**必须重启后端进程**才生效（无热重载）。

---

## 八、我现在不会动的东西

在你回复之前，我只做这几件不影响结构的事：
- ✅ 已删除 5.9GB 冗余文件
- ✅ 已配好 git 身份（`rushangyun` / `1906707288@qq.com`）并确认能连 GitHub
- ⏸ 代码重构、前端、训练 —— 等你确认
