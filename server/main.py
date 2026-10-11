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

import asyncio
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
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.agent.runtime import AgentRuntime
from app.agent.tools import build_registry
from app.api import audiobook as audiobook_api
from app.api import chat, health, vision
from app.audiobook.bus import ProgressBus
from app.audiobook.repo import Repo
from app.audiobook.worker import SynthWorker
from app.core.config import settings
from app.core.container import AudiobookParts, Container
from app.llm.provider import OpenAICompatProvider
from app.vision.detector import Detector
from app.vision.stream import DetectionStream

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
        stream    （需要 detector；构造时不开摄像头，有人看才开）
    """
    provider = OpenAICompatProvider()
    detector = Detector()
    registry = build_registry(detector)
    runtime = AgentRuntime(provider, registry)
    stream = DetectionStream(detector)

    # 有声书子系统：复用同一个 LLM provider 做文本解析
    # repo / bus / worker 共享同一实例，进度推送才不会各发各的
    ab_repo = Repo(settings.audiobook_db, settings.audiobook_storage)
    ab_bus = ProgressBus()
    ab_worker = SynthWorker(ab_repo, ab_bus, settings.audiobook_storage)
    audiobook = AudiobookParts(
        repo=ab_repo,
        bus=ab_bus,
        worker=ab_worker,
        provider=provider,
    )

    return Container(
        settings=settings,
        provider=provider,
        registry=registry,
        runtime=runtime,
        detector=detector,
        stream=stream,
        audiobook=audiobook,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：进来时装配，退出时收尾。"""
    container = build_container()
    app.state.container = container
    # 常驻合成 Worker（消费有声书任务队列）
    worker_task = None
    if container.audiobook is not None:
        worker_task = asyncio.create_task(container.audiobook.worker.run_forever())
    logger.info(
        "华小牛已启动：模型=%s，工具=%s，视觉=%s，有声书=%s",
        settings.llm_model,
        "、".join(container.registry.names),
        "就绪" if container.detector.available else "未就绪",
        "已挂载" if container.audiobook else "未挂载",
    )
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
        if container.audiobook is not None:
            container.audiobook.worker.stop()
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
    app.include_router(vision.router, prefix="/api")
    # 有声书路由自身已带 /api/novels 前缀，不再叠加
    app.include_router(audiobook_api.router)

    # 音频产物静态服务：/audio/{novel_id}/chapter_01.mp3 等
    import os

    audio_dir = settings.audiobook_storage
    os.makedirs(audio_dir, exist_ok=True)
    app.mount("/audio", StaticFiles(directory=audio_dir), name="audio")
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
