---

## start.sh — 一键启动华小牛

把 Ollama 检查、后端、前端按顺序拉起来，并保持常驻。

```bash
./scripts/start.sh            # 起全套（推荐）
./scripts/start.sh --backend  # 只起后端
./scripts/start.sh --frontend # 只起前端
```

服务挂在**当前终端的后台任务**里：**这个终端别关**，关了服务就停；`Ctrl+C` 全部停止。

| 服务 | 地址 |
| --- | --- |
| 前端界面 | http://127.0.0.1:5173 |
| 后端接口文档 | http://127.0.0.1:8000/docs |

日志落在 `server/.run.log`、`web/.run.log`。

> 浏览器请用 `127.0.0.1`，**不要用 `localhost`** —— Vite 只绑了 IPv4，`localhost` 会解析到 `[::1]` 从而连不上。

---

## check.sh — 体检

一眼看清三个服务是否可用，以及模型、权重是否就位。

```bash
./scripts/check.sh
```

输出示例：

```
  ✓ Ollama     200    http://127.0.0.1:11434
  ✗ 后端      000    http://127.0.0.1:8000
             └─ 没起：python server/main.py（日志 server/.run.log）
```

**踩坑提醒**：本机配置了 `http_proxy`，探测本地端口必须加 `--noproxy '*'`。
否则 curl 会走代理、拿到代理返回的错误页，被误判成「端口被占」——
实际上端口是空的（这个坑让人误判过一次）。

---

## train_background.cmd — 夜间挂机训练

脱离终端启动 YOLO 训练（断点续跑 + 崩溃自动重试）。

```bash
cmd.exe //c start "" "D:\workbuddy document\2026-10-09-13-21-03\scripts\train_background.cmd"
```

**为什么是 .cmd 而不是 bash 后台任务**：我的 shell 结束（或模型从 Hy4 切到 Hy3）后，
挂在它下面的后台进程会被回收。Windows 的 `start` 会新开一个窗口，
进程归属于新窗口，因此**你关掉我这个终端、甚至我这边额度用尽，训练都还在跑**。

**为什么带重试**：上次训练崩在 epoch 35（瞬时读图失败），一整夜白跑。
这个脚本最多重试 5 次，每次都 `--resume` 接着训，崩溃不再浪费一晚。

日志：`training/logs/train.log`（`tail -f` 实时看）。
跑完会生成 `result.json` 并自动导出 `best.pt`。

---

## chat_test.sh — 对话一键诊断（绕开前端直测后端）

```bash
./scripts/chat_test.sh "算一下 12345 × 6789"
./scripts/chat_test.sh "看看 server 目录下有哪些文件"
./scripts/chat_test.sh "读一下 C:\Windows\System32\drivers\etc\hosts"   # 测沙箱
```

打印三件事：**① 调了哪些工具 → ② 工具执行结果 → ③ 模型最终回答**。

**为什么需要它**：网页上表现异常时，先直测后端，**一次排除一半可能性**：

| 直测结果 | 说明 |
|---|---|
| 工具结果是对的 | 后端没问题 → 锅在前端，或模型「转述」时抄错了 |
| 工具结果就错了 | 锅在后端 / prompt，去查那边 |
| 压根没调工具 | prompt 引导不够，或模型偷懒自己心算 |

> 不做这一步，很容易在前端代码里白找半天——而前端其实一直是好的。
> 2026-10-10 那次「算数算错」就是靠它三秒定位的：后端算对了 83810205，
> 是模型没调工具自己心算成 83812655。

---

## push.sh — 推送到 GitHub

```bash
./scripts/push.sh            # 推 master
./scripts/push.sh main       # 推指定分支
```

**为什么不能直接用 `git push`**：本机代理端口**每次会话都会变**（实测 10383 / 10783 / 4633），
而 `~/.gitconfig` 里有一条按 URL 匹配的写死配置：

```
http.https://github.com.proxy = http://127.0.0.1:10383
```

它优先级高于通用的 `http.proxy`，所以 `git -c http.proxy=` 清不掉它，
端口一过期就报 `Failed to connect to github.com over proxy 127.0.0.1`。

脚本会**实时读取环境变量 `$https_proxy`/`$http_proxy`**，先走代理，
失败再自动回退直连（把按 URL 的代理置空才是真正的禁用）。两种都不行就如实报错。

> 顺带一提：Windows schannel 会对代理的 MITM 证书做吊销检查并失败
> （`CRYPT_E_NO_REVOCATION_CHECK`），所以脚本里必须关掉 `sslVerify`。

---

## gen_event_types.py

把 Python 的事件契约转成 TypeScript 类型。

```bash
python scripts/gen_event_types.py
```

- 读：`server/app/core/events.py`
- 写：`web/src/types/events.ts`

原理：解析 Python AST，抽出事件类型常量和 dataclass 字段，输出 TS 接口。

**改完 `server/app/core/events.py` 必须重跑一次**，否则前后端会悄悄漂移——
这是解耦架构最常见的翻车方式：两边都觉得自己没错，运行时才发现对不上。
