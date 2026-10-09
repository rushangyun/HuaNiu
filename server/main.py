"""组合根（Composition Root）—— 整个后端唯一负责"组装"的地方。

这个文件里不应该有任何业务逻辑，它只做一件事：
    造出所有零件 → 按依赖关系接起来 → 交给 FastAPI

为什么要把组装单独拎出来放到最外层：
    如果每个模块自己 import 自己需要的单例，依赖关系会迅速变成一张网，
    想换掉其中任何一个都得改一堆文件。现在这张网的线头只在这里，
    想换模型 provider、想换检测器、想给工具集加东西，都只改这个文件的几行。

    这也是"主程序只负责模块组装"那条要求的落点。

启动：
    python server/main.py
    # 或
    python -m uvicorn app.main:app --reload   （cwd 为 server/）
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 把 server/ 加进模块搜索路径，这样无论从项目根执行 `python server/main.py`
# 还是从 server/ 执行 `python main.py`，下面的 `from app.xxx import` 都能成立。
# （这两行必须排在 import app.* 之前，所以故意放在这里。）
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.api import chat, health
from app.core.config import settings
from app.core.container import Container
from app.llm.provider import OpenAICompatProvider
from app.vision.detector import Detector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("huaniu")


def build_container() -> Container:
    """把依赖按「从底往上」的顺序造出来。

    顺序是有讲究的：
        provider  （最底层，只依赖配置）
        detector  （延迟加载 torch，构造时不占显存）
        registry  （需要 detector 才能注册视觉工具）
        runtime   （需要 provider + registry）
    """
    provider = OpenAICompatProvider()
    detector = Detector()
    registry = build_registry(detector)
    runtime = AgentRuntime(provider, registry)
    return Container(
        settings=settings,
        provider=provider,
        registry=registry,
        runtime=runtime,
        detector=detector,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：进来时装配，退出时收尾。"""
    container = build_container()
    app.state.container = container
    logger.info(
        "华小牛已启动：模型=%s，工具=%s，视觉=%s",
        settings.llm_model,
        "、".join(container.registry.names),
        "就绪" if container.detector.available else "未就绪",
    )
    try:
        yield
    finally:
        await container.aclose()
        logger.info("已退出")


def create_app() -> FastAPI:
    app = FastAPI(
        title="华小牛 HuaNiu",
        description="本地优先的视觉智能体后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 前端开发服务器在 5173，浏览器跨域必须放开
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # 传 "main:app" 而不是 app 对象，是因为 reload 模式下 uvicorn 要能重新导入它
    # reload 默认开（改代码即时生效），但会多出一个父子进程对，
    # 端口排查时用 HUANIU_RELOAD=0 关掉它
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=os.getenv("HUANIU_RELOAD", "1") == "1",
        app_dir=str(_HERE),
    )
