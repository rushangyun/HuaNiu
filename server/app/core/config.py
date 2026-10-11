"""全局配置集中在这里。

设计意图：所有「换台机器就需要改」的东西都必须出现在这个文件里，
不允许散落在业务代码中。换模型、换端口、换显存策略，只改这里。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：server/app/core/config.py -> core/app/server/根，所以是 parents[3]
# 这个文件一旦搬家，这个数字必须跟着改，否则所有路径会静默错位。
# （踩过一次：从 app/ 移到 app/core/ 忘改，视觉权重路径变成 server/models/...）
ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """从环境变量 / .env 文件读取，读不到就用默认值。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 本地模型服务 ----------------
    # Ollama 暴露的是标准 OpenAI 兼容协议，所以这里就是一个 base_url。
    # 换成 vLLM / llama.cpp server / 云端 OpenAI，只改这一个变量，业务代码不动。
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"  # Ollama 不校验密钥，但协议要求非空
    # 注意是 qwen2.5:7b-instruct（冒号），不是连字符。
    # Ollama 对「模型不存在」返回的是 404 + JSON 错误体，不是 400，
    # 写错了会看到莫名其妙的 404。可用 ollama list 确认准确名字。
    llm_model: str = "qwen2.5:7b-instruct"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_timeout: float = 180.0

    # ---------------- Agent ----------------
    max_tool_rounds: int = 6  # 工具调用最多几轮，防止模型陷入死循环把显存烧光
    max_history_turns: int = 12  # 带进上下文的历史轮数。本地小模型上下文有限，不能全塞

    # ---------------- 视觉 ----------------
    # 首选：自己训的 VOC 权重。训好后 train.py 会自动复制到这里
    vision_model: str = str(ROOT / "models" / "yolo" / "best.pt")
    # 兜底：COCO 预训练权重。best.pt 还不存在时用它，
    # 这样训练跑着的几小时里实时检测也能演示（类别变成 COCO 80 类）
    vision_fallback_model: str = str(ROOT / "models" / "yolo" / "yolov8n.pt")
    vision_conf: float = 0.25
    vision_imgsz: int = 640
    vision_device: str = "cuda"  # 显存不足时改成 cpu
    camera_index: int = 0

    # ---------------- 服务 ----------------
    host: str = "127.0.0.1"
    port: int = 8000

    # ---------------- 安全边界 ----------------
    # read_file 工具只允许读这个目录里的东西，越界直接拒绝。
    workspace_dir: str = str(ROOT)

    # ---------------- 有声书（AI 有声小说生成） ----------------
    # TTS 双 Provider：edge-tts（联网优质，默认）/ piper（离线兜底）。
    # 切换只改这一个变量，业务代码不动。
    tts_provider: str = "edge"
    # piper 离线兜底所需的二进制与模型（仅 TTS_PROVIDER=piper 时需要）
    piper_bin: str = "piper"
    piper_model: str = ""
    # 默认音色：旁白/女声/男声。解析出的角色先用它们兜底，用户在 UI 可改。
    voice_narrator: str = "zh-CN-YunyangNeural"  # 沉稳叙述
    voice_female: str = "zh-CN-XiaoxiaoNeural"   # 温柔通用
    voice_male: str = "zh-CN-YunxiNeural"        # 青年男声
    # TTS 并发：edge-tts 是逆向接口，并发太高会触发限流，4 以内稳。
    audiobook_concurrency: int = 4
    # ffmpeg 二进制路径。默认走 PATH 上的 ffmpeg；找不到时自动用
    # imageio-ffmpeg 自带的二进制（pip install imageio-ffmpeg 即可，免系统安装）。
    ffmpeg_bin: str = "ffmpeg"
    # 产物落盘：音频片段 / 章节合并 / 全书 / 原始文本
    audiobook_storage: str = str(ROOT / "storage" / "audio")
    audiobook_db: str = str(ROOT / "storage" / "audiobook.db")


settings = Settings()
