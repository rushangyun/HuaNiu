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
