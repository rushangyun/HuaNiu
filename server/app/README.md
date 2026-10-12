# server/app — 后端应用层

按**能力域**分层，依赖严格单向、无环：

```
main.py ──► api ──► agent ──► llm ──► core
              │        │
              │        └─────► vision ──► core
              ├──► transport ──────────► core
              └──► audiobook ──────────► core
```

| 目录 | 职责 |
|---|---|
| [`core/`](core/README.md) | 契约层：事件、配置、容器、错误 |
| [`llm/`](llm/README.md) | 模型接入：只认 OpenAI 兼容协议 |
| [`agent/`](agent/README.md) | 手写 tool-calling 主循环 + 工具 |
| [`vision/`](vision/README.md) | YOLO 推理与 MJPEG 推流 |
| [`transport/`](transport/README.md) | SSE 推送（只编码，不含业务） |
| [`api/`](api/README.md) | HTTP 薄路由 |
| [`audiobook/`](audiobook/README.md) | 有声书：解析 → 合成 → 导出 |

**三条规则**：

1. `core` 谁都能依赖，但它不依赖任何人（这是"单向无环"的底座）。
2. 同层之间不互相依赖 —— `agent` 需要视觉能力就走**工具注册表**，不直接 import `vision`，
   否则依赖关系立刻变成一张网，谁也换不掉谁。
3. `api` 层保持**薄**：只做入参校验和转发，一行业务逻辑都不写。
