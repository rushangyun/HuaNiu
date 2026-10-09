# server/ — 后端

FastAPI 服务。负责计算与推送，**不含任何 UI 逻辑**。

## 启动

```bash
python server/main.py          # 默认 127.0.0.1:8000，改代码自动重载
HUANIU_RELOAD=0 python server/main.py   # 关掉重载（端口排查时用）
```

接口文档：<http://127.0.0.1:8000/docs>

## 分层

```
main.py              组合根：唯一负责"造零件 + 接起来"的地方
app/
  core/
    config.py        所有可配置项（换机器只改这里）
    events.py        ★ 前后端唯一耦合点，改它要重跑生成脚本
    errors.py        统一错误类型
    container.py     依赖清单（只放字段，不放构造逻辑）
  llm/
    provider.py      只认 OpenAI 兼容协议，不认具体推理引擎
  agent/
    runtime.py       工具调用主循环
    prompts.py       系统提示词装配
    tools/
      base.py        注册机制：签名+docstring 自动推断 Schema
      system.py      时间 / 计算 / 设备
      filesystem.py  列目录 / 读文件（带沙箱）
      vision.py      视觉状态 / 目标检测
      __init__.py    build_registry() 统一装配
  vision/
    detector.py      YOLO 封装（延迟加载 torch，线程池推理）
  transport/
    sse.py           Event 流 → SSE 文本流
  api/
    deps.py          依赖注入取件口
    chat.py          对话路由
    health.py        健康检查
```

依赖方向严格单向：`api → transport/agent → core`，不出现反向 import。

## 三条设计约定

1. **路由保持薄**：路由函数只做「收参数 → 交 runtime → 交 transport」，超过十几行就是放错地方了
2. **工具永不抛异常**：返回「文件不存在，目录里有 a/b/c」这种模型看了知道怎么改的话
3. **换引擎只改配置**：`llm.base_url` 指向任何 `/v1/chat/completions` 服务都能直接用

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 各模块就绪状态，排查问题先看它 |
| GET | `/api/tools` | 当前 Agent 的能力清单 |
| POST | `/api/chat` | 对话，返回 SSE 事件流 |

事件类型见 `app/core/events.py`。
