"""FastAPI 应用入口。

职责只有两件：
1. 在启动时把依赖（provider / registry / runtime）装配好，挂到 app.state
2. 挂路由、开 CORS、提供健康检查

业务逻辑一行都不写在这里。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.registry import ToolRegistry
from .agent.runtime import AgentRuntime
from .agent import tools as builtin_tools  # noqa: F401  导入即注册工具
from .api import chat as chat_api
from .config import settings
from .llm.provider import OpenAICompatProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("huanliu")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动装配 / 关闭清理。"""
    provider = OpenAICompatProvider()
    registry: ToolRegistry = builtin_tools.registry
    app.state.provider = provider
    app.state.registry = registry
    app.state.runtime = AgentRuntime(provider, registry)

    logger.info("模型服务: %s  模型: %s", settings.llm_base_url, settings.llm_model)
    logger.info("已注册工具(%d): %s", len(registry.names), ", ".join(registry.names))

    # 启动时不主动连模型，避免 Ollama 还没起来导致服务起不来。
    # 真正用到时再连，health 接口会做探活。
    yield

    await provider.aclose()


app = FastAPI(
    title="华小牛 HuaNiu",
    description="本地优先的视觉智能体：本地大模型 + 自建 Agent 运行时 + YOLO 实时检测",
    version="0.1.0",
    lifespan=lifespan,
)

# 开发期允许前端（Vite 默认 5173）跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_api.router)


@app.get("/api/health", tags=["system"])
async def health() -> dict[str, Any]:
    """健康检查：顺便把模型服务和视觉模块的状态一起报出来。

    排查问题时第一个该看的接口——一眼就能知道是模型没起还是权重没训。
    """
    provider: OpenAICompatProvider = app.state.provider
    try:
        models = await provider.list_models()
        llm_ok = True
        llm_msg = "已连接"
    except Exception as exc:  # noqa: BLE001
        models = []
        llm_ok = False
        llm_msg = str(exc)

    from .vision.detector import get_detector

    detector = get_detector()

    return {
        "status": "ok",
        "llm": {
            "base_url": settings.llm_base_url,
            "model": settings.llm_model,
            "connected": llm_ok,
            "message": llm_msg,
            "available_models": models,
        },
        "vision": {
            "model_path": str(detector.model_path),
            "available": detector.available,
            "reason": detector.reason,
        },
        "tools": app.state.registry.names,
    }


def main() -> None:
    import uvicorn

    uvicorn.run(
        "server.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
