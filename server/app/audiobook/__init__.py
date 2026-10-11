"""有声书子系统（AI 有声小说生成）。

目录约定（与后端其他模块一致）：
    models.py    SQLAlchemy 模型 + 引擎
    repo.py      数据访问（增删查 / 任务出队 / 重试 / 进度）
    chunking.py  章节 / 段落 / 分块切分
    normalize.py 文本归一化（数字/单位转中文，最影响"像不像人话"）
    parser.py    调本地 LLM 解析 → 结构化 JSON（offset 回填防篡改），带规则兜底
    tts/         TTS Provider 抽象 + edge-tts / piper 双实现 + 工厂
    media.py     ffmpeg 后处理与合并
    bus.py       进度发布订阅（喂给 SSE）
    pipeline.py  解析全流程编排
    worker.py    合成任务消费者（重试 / 缓存 / 断点续跑）
"""
