# app/llm — 大模型接入（只认协议，不认厂商）

| 文件 | 干什么 | 为什么不这么干不行 |
|---|---|---|
| `provider.py` | OpenAI 兼容协议的流式客户端：发请求、解析 SSE 流、把流式 `tool_call` 碎片拼回完整结构 | 抽象边界划在**协议层**而不是"厂商 SDK 层"，所以换 Ollama / vLLM / llama.cpp / 云端 OpenAI **只改一个 `base_url` 环境变量**，业务代码一行不动 |

## 三个必须记住的点

1. **只依赖 `/v1/chat/completions` 这个事实标准** —— 不 import 任何厂商 SDK。
   写死 Ollama 的 SDK，就等于和 Ollama 绑死。

2. **流式返回的 tool_call 是碎片**：函数名和参数一点一点到（`"{"a"`、`'":1}'`），
   必须自己攒起来再 `json.loads`，直接交给上层必然是半个 JSON。

3. **访问本机地址要关掉环境代理**（`trust_env=not is_local`）：
   本机配了 `http_proxy` 时，连 `localhost:11434` 也会被发去代理，
   代理解析不了本机地址直接返回 404，**而且报错完全看不出是代理的锅**。

## 错误要读 body

模型服务（尤其 Ollama）的很多错误藏在响应体里 —— 比如模型名写错返回
`404 + {"error":{"message":"model 'xxx' not found"}}`。只看状态码会完全看不出问题在哪。
