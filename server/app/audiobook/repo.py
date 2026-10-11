"""数据访问层（Repository）。

把"怎么存"和"业务怎么用"隔开：pipeline / worker / api 只调用这里的方法，
不直接碰 SQLAlchemy。这样以后换数据库（PostgreSQL）只改这一个文件。

线程安全：SQLite 用 StaticPool + check_same_thread=False + busy_timeout，
Worker 多线程并发读写不会锁死。
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Base,
    Chapter,
    Job,
    Lexicon,
    Novel,
    Segment,
    Speaker,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Repo:
    """有声书所有读写都走这里。"""

    def __init__(self, db_path: str, storage_root: str) -> None:
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        # SQLite 多线程：StaticPool 复用一个连接，配 busy_timeout 防写锁
        self._engine = sa.create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=sa.pool.StaticPool,
        )
        sa.event.listen(self._engine, "connect", self._on_connect)
        Base.metadata.create_all(self._engine)
        self._maker = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._lock = threading.Lock()  # 串行化写，进一步避免 WAL 写冲突

    @staticmethod
    def _on_connect(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    # ------------------------------------------------------------------ #
    # 书籍
    # ------------------------------------------------------------------ #
    def create_novel(
        self, title: str, text: str, source_type: str, copyright_ack: bool
    ) -> str:
        nid = _new_id("nov")
        raw_dir = self.storage_root / "novels" / nid
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / "raw.txt"
        raw_path.write_text(text, encoding="utf-8")
        with self._maker() as s:
            novel = Novel(
                id=nid,
                title=title or "未命名",
                source_type=source_type,
                raw_path=str(raw_path),
                status="parsing",
                copyright_ack=1 if copyright_ack else 0,
                char_count=len(text),
            )
            s.add(novel)
            s.commit()
        return nid

    def get_novel(self, nid: str) -> Novel | None:
        with self._maker() as s:
            return s.get(Novel, nid)

    def list_novels(self) -> list[dict[str, Any]]:
        with self._maker() as s:
            rows = (
                s.execute(
                    select(
                        Novel.id,
                        Novel.title,
                        Novel.status,
                        Novel.char_count,
                        Novel.created_at,
                        func.coalesce(
                            select(func.count())
                            .where(Segment.chapter_id == Chapter.id)
                            .correlate(Chapter)
                            .scalar_subquery(),
                            0,
                        ).label("segs"),
                    )
                    .join(Chapter, Chapter.novel_id == Novel.id, isouter=True)
                    .group_by(Novel.id)
                    .order_by(Novel.created_at.desc())
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]

    def set_status(self, nid: str, status: str) -> None:
        with self._lock, self._maker() as s:
            s.execute(sa.update(Novel).where(Novel.id == nid).values(status=status))
            s.commit()

    # ------------------------------------------------------------------ #
    # 章节 / 段落
    # ------------------------------------------------------------------ #
    def add_chapter(self, nid: str, idx: int, title: str) -> str:
        cid = _new_id("chap")
        with self._lock, self._maker() as s:
            s.add(Chapter(id=cid, novel_id=nid, idx=idx, title=title))
            s.commit()
        return cid

    def add_segment(
        self,
        chapter_id: str,
        idx: int,
        kind: str,
        speaker: str | None,
        text: str,
        raw_text: str | None,
        emotion: str | None,
        tone: str | None,
        speed: float,
        pause_before_ms: int,
    ) -> str:
        sid = _new_id("seg")
        with self._lock, self._maker() as s:
            s.add(
                Segment(
                    id=sid,
                    chapter_id=chapter_id,
                    idx=idx,
                    kind=kind,
                    speaker=speaker,
                    text=text,
                    raw_text=raw_text,
                    emotion=emotion,
                    tone=tone,
                    speed=speed,
                    pause_before_ms=pause_before_ms,
                )
            )
            s.commit()
        return sid

    def get_segments(self, chapter_id: str) -> list[Segment]:
        with self._maker() as s:
            return list(
                s.execute(
                    select(Segment)
                    .where(Segment.chapter_id == chapter_id)
                    .order_by(Segment.idx)
                )
                .scalars()
                .all()
            )

    def get_chapter_segments(self, nid: str) -> list[Segment]:
        with self._maker() as s:
            return list(
                s.execute(
                    select(Segment)
                    .join(Chapter, Chapter.id == Segment.chapter_id)
                    .where(Chapter.novel_id == nid)
                    .order_by(Chapter.idx, Segment.idx)
                )
                .scalars()
                .all()
            )

    def update_segment(self, seg_id: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return
        with self._lock, self._maker() as s:
            s.execute(sa.update(Segment).where(Segment.id == seg_id).values(**fields))
            s.commit()

    # ------------------------------------------------------------------ #
    # 角色 / 发音词典
    # ------------------------------------------------------------------ #
    def ensure_speaker(self, nid: str, name: str, default_voice: str) -> Speaker:
        with self._lock, self._maker() as s:
            sp = s.execute(
                select(Speaker).where(Speaker.novel_id == nid, Speaker.name == name)
            ).scalar_one_or_none()
            if sp is None:
                sp = Speaker(id=_new_id("spk"), novel_id=nid, name=name, voice_id=default_voice)
                s.add(sp)
                s.commit()
            return sp

    def get_speaker(self, nid: str, name: str) -> Speaker | None:
        with self._maker() as s:
            return s.execute(
                select(Speaker).where(Speaker.novel_id == nid, Speaker.name == name)
            ).scalar_one_or_none()

    def update_speaker(self, nid: str, name: str, **fields: Any) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            return
        with self._lock, self._maker() as s:
            s.execute(
                sa.update(Speaker)
                .where(Speaker.novel_id == nid, Speaker.name == name)
                .values(**fields)
            )
            s.commit()

    def list_speakers(self, nid: str) -> list[Speaker]:
        with self._maker() as s:
            return list(
                s.execute(select(Speaker).where(Speaker.novel_id == nid)).scalars().all()
            )

    def upsert_lexicon(self, nid: str, word: str, pinyin: str | None, note: str | None) -> None:
        with self._lock, self._maker() as s:
            row = s.get(Lexicon, (nid, word))
            if row is None:
                s.add(Lexicon(novel_id=nid, word=word, pinyin=pinyin, note=note))
            else:
                row.pinyin = pinyin
                row.note = note
            s.commit()

    # ------------------------------------------------------------------ #
    # 合成任务队列
    # ------------------------------------------------------------------ #
    def create_synthesis_jobs(self, nid: str) -> int:
        """为所有待合成段落（pending / failed）建立 job，返回新建数量。"""
        with self._lock, self._maker() as s:
            segs = list(
                s.execute(
                    select(Segment)
                    .join(Chapter, Chapter.id == Segment.chapter_id)
                    .where(Chapter.novel_id == nid, Segment.status.in_(["pending", "failed"]))
                ).scalars().all()
            )
            count = 0
            for seg in segs:
                s.add(
                    Job(
                        id=_new_id("job"),
                        novel_id=nid,
                        segment_id=seg.id,
                        status="queued",
                        attempts=0,
                    )
                )
                seg.status = "pending"
                seg.error = None
                count += 1
            s.commit()
        return count

    def claim_next_job(self) -> tuple[str, Segment, int] | None:
        """取出下一个待合成 job，标记 running；没有则返回 None。

        返回 (job_id, segment, 已尝试次数)。已尝试次数用于决定重试/放弃。
        """
        with self._lock, self._maker() as s:
            job = s.execute(
                select(Job)
                .where(Job.status == "queued")
                .order_by(Job.priority.desc(), Job.scheduled_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if job is None:
                return None
            seg = s.get(Segment, job.segment_id)
            if seg is None:
                job.status = "failed"
                job.error = "segment 已不存在"
                s.commit()
                return None
            job.status = "running"
            job.attempts = job.attempts + 1
            seg.status = "running"
            s.commit()
            return job.id, seg, job.attempts

    def get_chapter(self, chapter_id: str) -> Chapter | None:
        with self._maker() as s:
            return s.get(Chapter, chapter_id)

    def mark_segment_done(self, seg_id: str, audio_path: str) -> None:
        with self._lock, self._maker() as s:
            s.execute(
                sa.update(Segment)
                .where(Segment.id == seg_id)
                .values(status="done", audio_path=audio_path, error=None)
            )
            s.commit()

    def mark_segment_failed(self, seg_id: str, error: str) -> None:
        with self._lock, self._maker() as s:
            s.execute(
                sa.update(Segment)
                .where(Segment.id == seg_id)
                .values(status="failed", error=error[:300])
            )
            s.commit()

    def requeue(self, job_id: str, delay_sec: int, attempts: int) -> None:
        from datetime import datetime, timedelta, timezone

        when = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
        with self._lock, self._maker() as s:
            s.execute(
                sa.update(Job)
                .where(Job.id == job_id)
                .values(status="queued", attempts=attempts, scheduled_at=when)
            )
            s.commit()

    def reset_stale_jobs(self, older_than_sec: int = 600) -> int:
        """重启后把卡在 running 的 job 复位（断点续跑）。返回复位数量。"""
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
        with self._lock, self._maker() as s:
            n = s.execute(
                sa.update(Job)
                .where(Job.status == "running", Job.scheduled_at < cutoff)
                .values(status="queued")
            ).rowcount
            # 顺手把 running 的 segment 也复位，避免前端一直转圈
            running_seg_ids = s.execute(
                select(Segment.id).where(Segment.status == "running")
            ).scalars().all()
            if running_seg_ids:
                s.execute(
                    sa.update(Segment)
                    .where(Segment.id.in_(running_seg_ids))
                    .values(status="pending")
                )
            s.commit()
        return n

    # ------------------------------------------------------------------ #
    # 进度统计
    # ------------------------------------------------------------------ #
    def progress(self, nid: str) -> dict[str, Any]:
        with self._maker() as s:
            row = s.execute(
                select(
                    func.count().label("total"),
                    func.sum(func.cast(Segment.status == "done", sa.Integer)).label("done"),
                    func.sum(func.cast(Segment.status == "failed", sa.Integer)).label("failed"),
                )
                .select_from(Segment)
                .join(Chapter, Chapter.id == Segment.chapter_id)
                .where(Chapter.novel_id == nid)
            ).mappings().first()
            total = int(row["total"] or 0)
            done = int(row["done"] or 0)
            failed = int(row["failed"] or 0)
            pct = round(done / total * 100, 1) if total else 0.0
            return {"total": total, "done": done, "failed": failed, "pct": pct}

    def is_chapter_complete(self, chapter_id: str) -> bool:
        with self._maker() as s:
            row = s.execute(
                select(
                    func.count().label("n"),
                    func.sum(func.cast(Segment.status == "done", sa.Integer)).label("done"),
                ).where(Segment.chapter_id == chapter_id)
            ).mappings().first()
            n = int(row["n"] or 0)
            done = int(row["done"] or 0)
            return n > 0 and n == done

    def set_chapter_audio(self, chapter_id: str, path: str, duration: float | None) -> None:
        with self._lock, self._maker() as s:
            s.execute(
                sa.update(Chapter)
                .where(Chapter.id == chapter_id)
                .values(status="done", audio_path=path, duration_sec=duration)
            )
            s.commit()

    def is_novel_complete(self, nid: str) -> bool:
        with self._maker() as s:
            row = s.execute(
                select(
                    func.count().label("n"),
                    func.sum(func.cast(Segment.status == "done", sa.Integer)).label("done"),
                )
                .select_from(Segment)
                .join(Chapter, Chapter.id == Segment.chapter_id)
                .where(Chapter.novel_id == nid)
            ).mappings().first()
            n = int(row["n"] or 0)
            done = int(row["done"] or 0)
            return n > 0 and n == done

    def get_chapters(self, nid: str) -> list[Chapter]:
        with self._maker() as s:
            return list(
                s.execute(select(Chapter).where(Chapter.novel_id == nid).order_by(Chapter.idx))
                .scalars()
                .all()
            )

    def raw_text(self, nid: str) -> str | None:
        novel = self.get_novel(nid)
        if not novel or not novel.raw_path:
            return None
        p = Path(novel.raw_path)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def reset_parsed(self, nid: str) -> None:
        """清空一本书已解析/合成的产物，回到可重新解析状态（用于重新解析）。

        顺序：先删依赖子表（job→segment→chapter），再删 speakers，最后复位状态。
        """
        with self._lock, self._maker() as s:
            chap_ids = s.execute(
                select(Chapter.id).where(Chapter.novel_id == nid)
            ).scalars().all()
            if chap_ids:
                s.execute(
                    Segment.__table__.delete().where(Segment.chapter_id.in_(chap_ids))
                )
            s.execute(Job.__table__.delete().where(Job.novel_id == nid))
            s.execute(Chapter.__table__.delete().where(Chapter.novel_id == nid))
            s.execute(Speaker.__table__.delete().where(Speaker.novel_id == nid))
            s.commit()
        self.set_status(nid, "parsing")
