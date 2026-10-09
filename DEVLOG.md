# 工程日志

> 记录进度、卡点，以及**当时为什么这么想**。
> 格式：最新在最上面。失败的尝试也会保留——它们比成功更有信息量。

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
