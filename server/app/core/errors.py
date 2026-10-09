"""统一错误类型。

为什么不用裸 Exception：
    后端出错时要能区分"该告诉用户什么"和"该记进日志什么"。
    用户看到的是人话，日志里的是完整堆栈。

约定：
    - 能被用户理解的失败 → AppError，message 直接展示
    - 外部依赖挂了（模型服务、摄像头）→ 具体的子类，附带排查提示
"""

from __future__ import annotations


class AppError(Exception):
    """应用级错误基类。message 会原样展示给终端用户，务必写人话。"""

    #: 给用户看的排查建议，会拼在 message 后面
    hint: str = ""

    def user_message(self) -> str:
        text = str(self)
        if self.hint:
            text = f"{text}\n\n{self.hint}"
        return text


class ModelServiceUnavailable(AppError):
    """连不上模型服务（Ollama 没启动、模型名写错等）。"""

    hint = "先确认 Ollama 在跑：ollama serve；再用 ollama list 核对模型名。"


class VisionNotReady(AppError):
    """视觉模块不可用（权重没训、摄像头被占用等）。"""

    hint = "先跑 training/train.py 完成一次训练，权重会落到 models/yolo/best.pt。"
