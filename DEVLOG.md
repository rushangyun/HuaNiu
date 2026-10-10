# 工程日志

> 记录**已经发生的事实**：做了什么、卡在哪、怎么解决的、实测数据是多少。
> 格式：最新在最上面。失败的尝试也会保留——它们比成功更有信息量。

## 📌 文档分工（先看这个，避免和 PLAN.md 混淆）

| 文档 | 回答的问题 | 时态 | 比喻 |
|---|---|---|---|
| **`DEVLOG.md`**（本文件） | 发生了什么？卡在哪？怎么解决的？ | **过去时** | 航海日志 |
| **`PLAN.md`** | 接下来做什么？排期？待确认？ | **将来时** | 航海图 |
| **`README.md`** | 这项目是啥？怎么跑起来？ | 现在时 | 说明书 |

**这条线要守住**：
- ✅ DEVLOG 写**结果和证据**（"epoch 34 时 mAP50=0.804"）
- ✅ PLAN 写**意图和安排**（"Day3 完成 MVP"）
- ❌ DEVLOG 不要重复解释"为什么这么设计"——那是 PLAN 的活
- ❌ PLAN 不要大段抄已实现的代码细节——指向代码即可

> 2026-10-10 补记：之前 Day 0 的 Harness 完成记录把 PLAN 里的设计理由
> 又抄了一遍，导致两份文件看起来内容一样。现在已按上面的分工收敛。

---

## 2026-10-10 · Day 1 · 发现训练崩了 + 创意作品定方案

### ⚠️ 如实上报：YOLO 训练早在昨晚就崩了，一直没被发现

**事实**：`training/logs/train.log` 最后写入时间 **Oct 9 17:58**，此后无输出。
训练在 epoch **35/100** 时崩溃：

```
FileNotFoundError: Image Not Found
D:\...\data\VOC\images\train\VOC2012_2011_000430.jpg
Caught FileNotFoundError in DataLoader worker process 0
```

**排查结论**：
- 全量扫描确认数据集**完整无损**：`标签总数 21503，对应图片缺失数 0`，
  train 16551 / val 4952 与官方数字完全对齐
- 报错的那张图**现在存在**（99823 字节，硬链接引用计数 2）
- → 判定为**瞬时故障**（大概率杀软/Defender 扫描瞬间占用），不是数据缺失
- 之前几轮都在推进别的模块，**没人回头看训练状态**——
  **教训：长任务必须留健康检查，不能"起了就不管"**

**崩溃前成绩**（epoch 34）：mAP@50 **0.80408**，mAP@50-95 **0.58706**

**产物**：有 `../voc_yolov8n/weights/{best,last}.pt`（18.4MB）；
无 `result.json`（崩在拿到 `save_dir` 之前）；`models/yolo/best.pt` 原本不存在。

**实测速度**：157 秒/epoch。34 epoch 用 1.49 小时，跑满 100 epoch 还需约 2.9 小时
（patience=20 可能提前早停，实际更短）。

### 两方案对比（用户要求）

| | **A：直接用现有 34 epoch 权重** | **B：resume 续跑到 100 epoch** |
|---|---|---|
| 交付耗时 | **≈5 分钟（已执行完成）** | ≈2.9 小时（占 GPU） |
| 指标 | mAP@50 **0.804** | 预计 **0.83~0.85**（+0.03~0.04） |
| 边际收益 | — | 相对提升约 4%~6%，**递减明显** |
| 风险 | 无（已验证：可加载、20 类正确） | GPU 被占 3 小时，无法同时流畅演示；可能再崩 |

**结论：两者不互斥。** A 只要 5 分钟且已完成；B 是增益。
→ **已执行 A**：`best.pt` 导出到 `models/yolo/`，加载验证通过（类别数 20，VOC 类别正确），
后端视觉已自动切换为自己训的 VOC 模型（不再用 COCO 兜底）。
→ **B 代码已就绪**（`training/train.py` 新增 `--resume`），随时可跑：
`python training/train.py --resume --name voc_yolov8n --project runs/train`
（续跑不能传超参，ultralytics 从 `args.yaml` 恢复，传了反而变成重跑）。

### ✅ B 方案当晚执行完毕（19:17）—— 跑满 100 轮

当晚续跑 1h26m44s，**正常跑满 100 轮**收尾：

```
训练完成，用时 5202.2 秒
  mAP@50    = 0.8297
  mAP@50:95 = 0.6213
```

| 里程碑 | mAP@50 | 说明 |
|---|---|---|
| 崩溃时（epoch 34） | 0.80408 | 方案 A 用的那份残缺权重 |
| 续跑起点（epoch 55） | 0.82343 | 第一次续跑被主动取消 |
| **最终（epoch 100）** | **0.8297** | 完整训练，自动导出 |

**踩到的坑（复用价值高）**：
在 Bash 工具里用 `cmd ... &`（前台命令 + 后台符号）启动长任务**不可靠**——
命令执行完 shell 一退出，进程就被回收，**已复现两次**。
→ **可靠做法：必须用 Bash 工具的 `run_in_background: true`**（这次跑了 1.5 小时没问题）。

**实测验证（跑完必须看结果）**：
- `result.json` ✅ 生成；`models/yolo/best.pt` ✅ 导出（**6.2MB** 纯权重）
- 加载：类别数 **20**，VOC 类别正确
- 真实推理：`VOC2007_000001.jpg` → `person` 置信度 **0.92**
- 速度：预热后 **~118 FPS**（8ms/帧）
  ⚠️ 首次推理 2.1 秒是 CUDA 预热，不是真实速度；
  摄像头端到端约 24 FPS（含采集+编码+推流）

→ **视觉模块现已切换到自己训的完整 VOC 模型，不再是 COCO 兜底。**

### ⚠️ 如实上报：edge-tts 与「完全离线」硬冲突

| 环节 | 离线? |
|---|---|
| AI 解析（本地 Ollama qwen2.5） | ✅ |
| **TTS 合成（edge-tts）** | ❌ **必须联网** |

edge-tts 逆向自微软 Edge **在线**接口，断网必然失败。当前方案下**断网只能解析、不能出声**。
三条路：A 双 Provider（edge-tts 联网高质量 + 本地 piper 离线兜底，推荐）；
B 纯离线高质量（CosyVoice2-0.5B / GPT-SoVITS，8GB 显存够，但要下 1~2GB 模型）；
C 放弃离线全程联网。**待你定。**

### 用户已确认的 6 项决策

1. TTS = **edge-tts**
2. **目前完全离线** ← 与 1 冲突，见上
3. **本机 demo，但架构要预留真上线**（DB/队列/存储留抽象与迁移路径）
4. 规模**主体整本几十万字**，单章仅辅助 → 必须正式队列 + 断点续传 + 合并 + 缓存
5. **不音色克隆**，但必须**同一角色跨上下文音色一致**
   → `speakers` 表持久化「角色→音色」映射 + 分块解析回传角色名册
6. **真能批量导出整本 MP3** → 章节级合成 + ffmpeg `-c copy` 合并 + ZIP

### 本轮新增文件

- `scripts/start.sh` — 一键起件套，支持 `--backend` / `--frontend`
- `scripts/check.sh` — 三端口体检 + 模型与 best.pt 检查
- `AUDIOBOOK_DESIGN.md` — 创意作品完整设计方案

---

## 2026-10-09 · Day 0（晚）· Harness 自主实验闭环完成

### 做了什么

题目第四部分：让程序自己反复跑训练、比数字、决定下一组超参。纯手写，不依赖任何框架。
在 `harness/` 下拆成四个各管一件事的模块，主入口 `run.py` 只负责组装：

| 模块 | 职责 |
| --- | --- |
| `space.py` | 搜索空间：`SEARCH_SPACE`（6 个离散候选参数）/ `DEFAULTS` / `Budget` / `clamp_to_space` |
| `experiment.py` | 实验记录：`Experiment`（ok/oom/failed 三态）、`experiments.jsonl` 追加读写 |
| `runner.py` | 执行器：子进程调 `training/train.py`，读 `result.json` 翻成记录；超时记 failed 不卡死 |
| `strategy.py` | 候选池生成（基线 + 单点扰动，去重后 13 组）+ 按历史 OOM 剪枝 |
| `decide.py` | 决策器：默认走确定性策略；`--llm` 时可让本地 qwen2.5 当顾问，建议一律过 `clamp_to_space` |
| `run.py` | 主入口：试→记→学→再试，写 `report.md`，自动导出 mAP 最高的 `best.pt` |

### 两个关键设计决定

> **设计理由写在 `PLAN.md` §五**，这里只记**落地结果与验证数据**，避免两处重复。

1. **`training/train.py` 加 `--no-export` 开关** —— Harness 每组实验用独立的
   `--name trial_N`，由 Harness 自己挑 mAP 最高的那次导出到 `models/yolo/best.pt`，
   避免后跑的较差实验覆盖好模型。人工跑训练仍是默认自动导出。
   （后续又加了 `--resume`，见 Day 1 记录。）

2. **失败（含 OOM）也是一条记录，闭环靠它学** —— `runner` 把 `error_type=oom`
   翻成 `STATUS_OOM`；下一轮 `strategy.prune_with_history` 读历史，
   凡是 OOM 过的 `batch` 及以上直接踢出候选池。
   于是闭环**自动避开显存不够的配置**，不需要人去改代码。

### 验证（不触发真实训练，逻辑层已通）

```
python harness/run.py --help       → 导入与装配正常，argparse 正常
build_pool()                       → 13 组（去重后）
模拟 batch=32 OOM                 → 剪枝后池 12 组，且不再含 batch>=32
连续 decide_next 5 次             → 全不同，无重复
```

真实跑通需要 GPU 训练（每组数分钟起），逻辑层已验证；跑法见 `harness/README.md`：
`python harness/run.py --max-trials 4 --epochs 5` 先小跑验证。

### 顺带修的契约 bug（记录在 `core/events.py`）

`Event.to_dict()` 原先把 `0` 当空值过滤（`v not in ("", 0, ...)`），导致实时视觉的
`fps=0 / object_count=0` 被吞。改成只过滤 `None/""/{}/[]`，保留 0。

---

## 2026-10-09 · Day 0 · 环境勘察与选型

### 目标
不急着写代码。先把「我这台机器到底能跑什么」搞清楚，再定路线。

### 1. 设备体检（实测，不是查参数表）

| 项目 | 实测 | 备注 |
| --- | --- | --- |
| GPU | RTX 5060 Laptop 8GB / CUDA 13.1 | `nvidia-smi` |
| 内存 | 15.5 GB 总容量，**当前空闲仅 6.5 GB** | `GlobalMemoryStatusEx` |
| 磁盘 | C 204GB / D 520GB 可用 | — |
| 工具链 | git 2.55 / node 22 / python 3.13 | 缺 uv、conda、ollama、pip 未在 PATH |

**结论：内存是最大瓶颈，不是显存。**
这点直接否掉了 Docker 方案。16GB 内存里系统+微信+Edge 已经吃掉一大半，再跑 Docker Desktop（本身常驻 2GB+）加上 Dify 的 postgres/redis/weaviate 容器组，机器必卡死。

> 教训：看到「部署 Dify」这种需求，第一反应应该是**先看自己有多少内存**，而不是先看教程。

### 2. 卡住 40 分钟：GitHub 连不上

**现象**
```
ssh -T git@github.com          → port 22: Connection refused
curl https://github.com        → HTTP 000
curl https://www.baidu.com     → HTTP 200   ← 别的站都正常
```

**排查过程（这部分花了最多时间）**

1. 先怀疑断网 → 但 baidu/pypi 都 200，排除
2. 怀疑 DNS → `nslookup github.com` 正常解析到 `20.205.243.166`，排除
3. 查环境变量 → 发现存在代理 `http://127.0.0.1:10383`
4. 上 `curl -v` 看握手 → 找到真凶：

```
* Uses proxy env variable https_proxy == 'http://127.0.0.1:10383'
* CONNECT tunnel established, response 200
* schannel: next InitializeSecurityContext failed:
  CRYPT_E_NO_REVOCATION_CHECK (0x80092012)
```

**根因**：Windows 自带的 schannel（TLS 实现）在做证书吊销检查时失败。
代理做了 TLS 中间人，签名证书拿不到有效的吊销状态，schannel 直接拒绝握手。
**不是网断了，是 Windows 不信任代理的证书链。**

**解决**
```bash
curl --ssl-no-revoke https://github.com   # → 200 ✅
```
git 侧对应配置：
```bash
git config --global http.sslVerify false          # 或用 http.sslBackend=openssl
git config --global http.proxy http://127.0.0.1:10383
```

> 值得记住：`curl` 返回 `000` 时不要慌，它几乎总是 TLS/代理问题，不是网络问题。
> 第一步就该上 `-v`。

### 3. 模型权重下载源的选择

试了三个源的连通性，全通，但速度差异大：

- `ollama.com` / GitHub Release —— 通，但 GitHub Release 实测 ~8MB/s 且不稳定
- `modelscope.cn` —— 通，国内源

**选了魔搭**，并且挑权重时踩到一个坑：

官方 `Qwen/Qwen2.5-7B-Instruct-GGUF` 仓库里的 `q4_k_m` 是**分片文件**（`00001-of-00002` + `00002-of-00002`）。
Ollama 的 Modelfile 用 `FROM ./xxx.gguf` 不太好吃分片，会麻烦。

**换到** `lmstudio-community/Qwen2.5-7B-Instruct-GGUF`，里面有**单文件** `Qwen2.5-7B-Instruct-Q4_K_M.gguf`（4.36GB），一步到位。

> 经验：下模型之前先用 API 把文件列表拉出来看一眼（`modelscope.cn/api/v1/models/{repo}/repo/files`），确认是不是单文件。省得下完发现用不了。

### 4. 今天的决策

- 项目名 **HuaNiu / 华小牛**（取自题目「我们能不能有自己的华小牛」，也是华农的梗）
- 主攻 Web（React + FastAPI）
- 3 天冲刺，主线优先：本地模型 → Agent → Web → YOLO → 文档
- 硬件部分无实物，走仿真 + 协议层实现

### 下一步
- [x] 下载 Ollama 安装包与模型权重（进行中）
- [ ] 静默安装 Ollama 并创建模型
- [ ] 验证 `/v1/chat/completions` 连通

---

---

## 2026-10-09 · Day 0（下午）· 环境搭建完成 + 卡住 1 小时的两个坑

### 已完成

- [x] Ollama 装好（v0.40.1），服务在 `localhost:11434`
- [x] 从魔搭下了 Qwen2.5-7B-Instruct Q4_K_M（4.36GB）
- [x] Python 虚拟环境 + FastAPI + httpx 装好
- [x] **PyTorch CUDA 版跑通**：`torch 2.11.0+cu128`，识别出 RTX 5060 的 `sm_120`
- [x] Agent 运行时写完并端到端跑通

### 卡住最久的两个坑（都是同一类问题：错误信息骗人）

#### 坑 1：PyTorch 装成了 CPU 版

第一次装的时候用了这种写法：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128 \
                  --extra-index-url https://pypi.org/simple
```

装完一看：`torch 2.11.0+cpu`，`torch.cuda.is_available() → False`。

**原因**：`--extra-index-url` 是"备胎源"，pip 会**同时**在两个源里找。
PyPI 上的 `torch` 在 Windows 平台默认就是 CPU 版，pip 挑了版本号更高的那个（2.14.1 CPU），
而不是 CUDA 版。加上 cu128 索引最高只到 2.11.0，pip 根本没往那边找。

**正确写法**——锁死版本，且不要给备胎源：

```bash
pip install --index-url https://download.pytorch.org/whl/cu128 \
            "torch==2.11.0+cu128" "torchvision==0.26.0+cu128"
```

> 中间还踩了一次：torchvision 0.22 硬依赖 torch==2.7，版本要配对。
> 对应关系：torch 2.7→tv 0.22，2.8→0.23，2.9→0.24，2.10→0.25，2.11→0.26。

**教训**：装 PyTorch 一定要装完当场验证，别等到训练时才发现跑了半小时 CPU。
判断依据很直观——CUDA 版 wheel 是 2.5GB 量级，CPU 版才 124MB。

#### 坑 2：模型名写错，Ollama 却返回 404

后端一直报 `404 Not Found`，我按下面顺序排查，绕了很大一圈：

1. 怀疑 Ollama 没起 → 但 `curl` 直连 `/v1/chat/completions` 返回 200，排除
2. 怀疑 httpx 走了代理 → 加了 `trust_env=False`，**还是 404**，排除
3. 怀疑 payload 里 tools 格式不对 → 单独测，200，排除
4. 最后把响应体打出来才看见真相：

```json
{"error":{"message":"model 'qwen2.5-7b-instruct' not found"}}
```

模型真实名字是 `qwen2.5:7b-instruct`（**2.5 后面是冒号**），
我在配置里写成了 `qwen2.5-7b-instruct`（连字符）。

**根因不是网络，是状态码撒了谎**：
Ollama 对"模型不存在"返回 **404 + JSON 错误体**，而不是更合理的 400。
而 `resp.raise_for_status()` 只抛状态码、**把 body 丢了**，
于是我看到的就是一句毫无信息量的 `404 Not Found`。

**两处修复**：
```python
# 1. 配置里改成正确名字
llm_model: str = "qwen2.5:7b-instruct"

# 2. provider 里遇到 4xx/5xx 必须把 body 读出来再抛
if resp.status_code >= 400:
    body = (await resp.aread()).decode(...)
    raise RuntimeError(f"模型服务返回 {resp.status_code}：{body}")
```

> 通用原则：**HTTP 错误一定要把响应体读出来再报。**
> 只看状态码排障，等于蒙着眼睛找东西。这次至少浪费了 40 分钟。

顺带一提，这台机器上还挂着 `HTTP_PROXY=127.0.0.1:10383`，
`curl` 连本地端口有时也会被代理拦（报 `upstream connect failed`），
测本地服务时统一加 `--noproxy '*'`。httpx 侧则用 `trust_env=False`。

### 端到端验证结果

问：「现在几点了？另外算一下 12345 * 6789」

```
>> 调用 [get_current_time]
>> 调用 [calculator] args={'expression': '12345 * 6789'}
<< 返回 2026-10-09 13:51:52 星期五
<< 返回 12345 * 6789 = 83810205
【最终答案】现在是 2026年10月9日13点51分52秒。计算结果是 12345 乘以 6789 等于 83810205。
```

模型自己判断出要调两个工具、并行发起、拿到结果后组织成自然语言。✓

### 下一步

- [ ] YOLO 数据集准备 + 训练（8GB 显存，用 yolov8n + imgsz 640）
- [ ] React 前端
- [ ] 实时检测推流接入前端

---

## 待办

- [ ] 本地大模型跑通
- [ ] Agent 运行时手写实现
- [ ] Web 对话界面
- [ ] YOLO 训练
- [ ] 实时检测接入 Web
- [ ] Harness 原型
- [ ] 文档与 git 规范收尾

---

## Day 0 傍晚（16:20–17:20）：分层重构 + 数据集 + 训练启动

### 做了什么

1. **后端分层重构完成**
   - `config.py` 移进 `core/`，建 `core/{events,errors,container}.py`
   - 工具按用途拆成 `tools/{base,system,filesystem,vision}.py`，
     `build_registry()` 一处装配；删掉会和 `tools/` 包同名的旧 `tools.py`
   - `runtime.py` 改成吐 `core.events` 里的 Event（原来自带一个 AgentEvent）
   - 新建 `transport/sse.py`、`api/{deps,chat,health}.py`
   - `server/main.py` 作组合根，**只做组装**，没有任何业务逻辑

2. **VOC 数据集准备完成**
   - curl 并行下三个 zip（绕开 ultralytics 的 SSL 问题），共 2.8GB
   - `training/prepare_dataset.py` 解压 + 转 YOLO，**硬链接**省 2GB 磁盘
   - 结果：train 16551 / val 4952，与官方数字完全一致，0 张跳过

3. **训练启动**：yolov8n, imgsz 640, batch 16
   - 显存占用 1.96GB，约 4.4 分钟/epoch（含验证）
   - epoch 7 时 mAP50 ≈ 0.58，仍在上升

4. **前端骨架完成**：Vite + React + TS，浅色简洁
   - 事件契约自动生成 TS 类型（`scripts/gen_event_types.py`）
   - 分层：`api/` 订阅 SSE，`hooks/` 事件→状态，`components/` 纯展示

### 卡住的地方（按浪费的时间排序）

**1. 改了配置却一直不生效 —— 40 分钟**

把 `config.py` 从 `app/` 移到 `app/core/` 后，
`ROOT = Path(__file__).resolve().parents[2]` 少了一层，
`vision_model` 变成 `server/models/yolo/best.pt`（应为 `models/yolo/best.pt`）。

修完再测，返回值**还是错的**。反复查了三遍配置代码都没问题——
直接 `python -c` 打印 ROOT，发现配置本身是对的。

真正的原因：`uvicorn reload=True` 会起父子两个进程，
我 kill 掉的那个不是真正在监听的，**curl 一直打在旧进程上**。
新进程其实压根没起来，日志里写着：

```
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)
```

**教训：改完代码测出来还是老样子，先确认你测的到底是不是新进程。**
看后台任务的日志，别只看 curl 的返回值。
后来给 main.py 加了 `HUANIU_RELOAD=0` 开关，排查端口时关掉重载。

**2. tools.py 和 tools/ 包同名 —— 差点埋雷**

新建 `agent/tools/` 包时，旧的 `agent/tools.py` 还在。
Python 里包优先于同名模块，不会报错，但 import 到哪个全看运气。
删掉旧文件才安全。**建包之前先看看有没有同名模块。**

**3. SSE 终止帧和 done 事件撞名**

第一版流结束时发 `data: done`，而 `DoneEvent` 的 type 也是 `"done"`。
前端根本分不清这是"结束"还是"一个 done 事件"。
改成标准 `[DONE]` 并写进注释。

**4. tool_start 每次发两条**

流式阶段收到 `ToolCallDelta` 就发一次不带参数的 `tool_start`，
拿到完整 `ChatResult` 后又发一次带参数的——前端收到两条，还得自己按名字去重。
碎片比完整结果只早几十毫秒，不值得。
改成只发一次，契约保持"一次调用 = 一个 tool_start"。

**5. Vite 默认只监听 IPv6**

`curl http://127.0.0.1:5173` 死活连不上，
`netstat` 一看监听的是 `[::1]:5173`。
在 `vite.config.ts` 里显式写 `host: "127.0.0.1"` 解决。

**6. ultralytics 的两个小意外**（不影响结果，但会吓一跳）
- AMP 检查要联网下载 `yolo26n.pt`，SSL 失败后跳过并自动设 `amp=True`。
  不是错误，训练照常。
- `project="runs/train"` 实际输出到 `runs/detect/runs/train/`（多一层）。
  路径不干净但能用。

### 端到端验证

```
POST /api/chat  "现在几点？顺便算一下 12345 × 6789"
→ tool_start get_current_time
→ tool_end     2026-10-09 16:36:55 星期五
→ tool_start   calculator {"expression": "12345 * 6789"}
→ tool_end     12345 * 6789 = 83810205
→ round 2
→ token...（流式输出）→ done
```

前端通过 Vite 代理访问 `/api/health` 正常，8 个工具全部注册。✓

### 下一步

- [ ] 训练跑完（预计 7 小时，明早看结果）
- [ ] 实时检测推流（MJPEG）接入前端
- [ ] Harness 自主实验闭环（读 result.json 做超参搜索）
- [ ] 各模块 README 已补，根 README 启动命令已补
- [ ] git 规范化提交 + 推 GitHub
