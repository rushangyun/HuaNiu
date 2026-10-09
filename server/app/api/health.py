"""健康检查与状态探针。

这个接口是排查问题的第一现场：
浏览器打不开页面、模型不说话、摄像头没画面，
先看 /api/health 基本就能定位是哪一环断了。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from ..core.container import Container
from .deps import get_container

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(container: Container = Depends(get_container)) -> dict:
    """返回后端各模块的就绪状态。"""
    # 探测本地模型服务。给 5 秒上限——Ollama 没启动时不能让整个健康检查卡住
    llm_ok = False
    models: list[str] = []
    try:
        models = await asyncio.wait_for(container.provider.list_models(), timeout=5.0)
        llm_ok = bool(models)
    except asyncio.TimeoutError:
        pass
    except Exception:  # noqa: BLE001
        pass

    return {
        "status": "ok" if llm_ok else "degraded",
        "llm": {
            "base_url": container.settings.llm_base_url,
            "model": container.settings.llm_model,
            "reachable": llm_ok,
            "available_models": models[:10],
        },
        "vision": {
            "available": container.detector.available,
            "reason": container.detector.reason,
            "model_path": str(container.detector.model_path),
        },
        "agent": {
            "tools": container.registry.names,
            "max_rounds": container.settings.max_tool_rounds,
        },
    }


@router.get("/tools")
async def list_tools(container: Container = Depends(get_container)) -> dict:
    """列出当前 Agent 具备的全部能力，前端可据此展示功能清单。"""
    return {
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters.get("properties", {}),
            }
            for spec in (container.registry.get(n) for n in container.registry.names)
            if spec is not None
        ]
    }
