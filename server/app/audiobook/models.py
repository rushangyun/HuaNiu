"""有声书数据模型（SQLAlchemy 2.0，SQLite）。

一张表一个类，字段与 AUDIOBOOK_IMPL.md §2 的建表语句一一对应。
时间统一用 UTC；SQLite 不存时区，这里直接由 SQLAlchemy 序列化成 TIMESTAMP。
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str]
    source_type: Mapped[str] = mapped_column(default="paste")  # paste | file
    raw_path: Mapped[str | None]  # 原始文本落盘路径
    status: Mapped[str] = mapped_column(default="draft")
    # draft|parsing|parsed|synthesizing|done|failed
    copyright_ack: Mapped[int] = mapped_column(default=0)  # 合规必须
    char_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(primary_key=True)
    novel_id: Mapped[str] = mapped_column(sa.ForeignKey("novels.id"))
    idx: Mapped[int]
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    # pending|synthesizing|done|failed
    audio_path: Mapped[str | None]
    duration_sec: Mapped[float | None]


class Segment(Base):
    """TTS 最小合成单位：一段。"""

    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(primary_key=True)
    chapter_id: Mapped[str] = mapped_column(sa.ForeignKey("chapters.id"))
    idx: Mapped[int]
    kind: Mapped[str] = mapped_column(default="narration")  # narration|dialogue|poem|quote
    speaker: Mapped[str | None]  # null = 旁白
    text: Mapped[str]  # 送 TTS 的最终文本（已归一化）
    raw_text: Mapped[str | None]  # 原文，防篡改对照
    text_hash: Mapped[str | None]  # md5(text|voice|speed) 缓存键
    emotion: Mapped[str | None]
    tone: Mapped[str | None]
    speed: Mapped[float] = mapped_column(default=1.0)
    pause_before_ms: Mapped[int] = mapped_column(default=0)
    audio_path: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="pending")  # pending|running|done|failed
    retry_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]


class Speaker(Base):
    """角色 → 音色 持久化映射（保证跨章节音色一致的关键）。"""

    __tablename__ = "speakers"

    id: Mapped[str] = mapped_column(primary_key=True)
    novel_id: Mapped[str] = mapped_column(sa.ForeignKey("novels.id"))
    name: Mapped[str]  # 旁白 | 林晚 …
    voice_id: Mapped[str | None]
    speed: Mapped[float] = mapped_column(default=1.0)
    pitch: Mapped[str] = mapped_column(default="+0Hz")
    emotion: Mapped[str | None]
    style: Mapped[str | None]
    profile: Mapped[str | None]  # LLM 推断的人设摘要，辅助选音色


class Lexicon(Base):
    """发音词典：改一次全书记住（多音字 / 专名）。"""

    __tablename__ = "lexicon"

    novel_id: Mapped[str] = mapped_column(sa.ForeignKey("novels.id"), primary_key=True)
    word: Mapped[str] = mapped_column(primary_key=True)
    pinyin: Mapped[str | None]
    note: Mapped[str | None]


class Job(Base):
    """合成作业（队列）。一段 = 一个 job。"""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    novel_id: Mapped[str]
    segment_id: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued")  # queued|running|done|failed
    priority: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    scheduled_at: Mapped[datetime] = mapped_column(default=_utcnow)
    error: Mapped[str | None]
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
