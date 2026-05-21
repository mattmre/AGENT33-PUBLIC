"""Persistent storage for training rollouts and spans."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class _TrainingBase(DeclarativeBase):
    pass


class RolloutRecord(_TrainingBase):
    """A complete agent rollout with reward."""

    __tablename__ = "training_rollouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rollout_id = Column(String(64), unique=True, nullable=False, index=True)
    agent_name = Column(String(256), nullable=False, index=True)
    total_reward = Column(Float, nullable=False, default=0.0)
    span_count = Column(Integer, nullable=False, default=0)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class SpanRecord(_TrainingBase):
    """A single span within a rollout."""

    __tablename__ = "training_spans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    span_id = Column(String(64), nullable=False, index=True)
    rollout_id = Column(String(64), nullable=False, index=True)
    span_type = Column(String(32), nullable=False)
    agent_name = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    parent_span_id = Column(String(64), nullable=False, default="")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class PromptVersionRecord(_TrainingBase):
    """Versioned prompt storage for tracking improvements."""

    __tablename__ = "training_prompt_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(256), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    avg_reward = Column(Float, nullable=False, default=0.0)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class TrainingStore:
    """Persistent storage for training data in PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        """Create training tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(_TrainingBase.metadata.create_all)

    async def store_rollout(
        self,
        rollout_id: str,
        agent_name: str,
        spans: list[Any],
        total_reward: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a complete rollout with its spans."""
        async with self._session_factory() as session, session.begin():
            record = RolloutRecord(
                rollout_id=rollout_id,
                agent_name=agent_name,
                total_reward=total_reward,
                span_count=len(spans),
                metadata_=metadata or {},
            )
            session.add(record)

            for span in spans:
                span_record = SpanRecord(
                    span_id=span.id,
                    rollout_id=rollout_id,
                    span_type=span.span_type,
                    agent_name=span.agent_name,
                    content=span.content,
                    parent_span_id=span.parent_span_id,
                )
                session.add(span_record)

    async def get_rollouts(self, agent_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Query rollouts for an agent."""
        sql = text(
            "SELECT rollout_id, agent_name, total_reward, span_count, created_at "
            "FROM training_rollouts WHERE agent_name = :agent "
            "ORDER BY created_at DESC LIMIT :limit"
        )
        async with self._session_factory() as session:
            result = await session.execute(sql, {"agent": agent_name, "limit": limit})
            rows = result.fetchall()
        return [
            {
                "rollout_id": r[0],
                "agent_name": r[1],
                "total_reward": r[2],
                "span_count": r[3],
                "created_at": r[4].isoformat() if r[4] else "",
            }
            for r in rows
        ]

    async def get_top_rollouts(self, agent_name: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Get highest-reward rollouts for learning."""
        sql = text(
            "SELECT rollout_id, agent_name, total_reward, span_count, created_at "
            "FROM training_rollouts WHERE agent_name = :agent "
            "ORDER BY total_reward DESC LIMIT :limit"
        )
        async with self._session_factory() as session:
            result = await session.execute(sql, {"agent": agent_name, "limit": top_k})
            rows = result.fetchall()
        return [
            {
                "rollout_id": r[0],
                "agent_name": r[1],
                "total_reward": r[2],
                "span_count": r[3],
                "created_at": r[4].isoformat() if r[4] else "",
            }
            for r in rows
        ]

    async def get_spans(self, rollout_id: str) -> list[dict[str, Any]]:
        """Get all spans for a rollout."""
        sql = text(
            "SELECT span_id, span_type, agent_name, content, parent_span_id, created_at "
            "FROM training_spans WHERE rollout_id = :rid ORDER BY created_at"
        )
        async with self._session_factory() as session:
            result = await session.execute(sql, {"rid": rollout_id})
            rows = result.fetchall()
        return [
            {
                "span_id": r[0],
                "span_type": r[1],
                "agent_name": r[2],
                "content": r[3],
                "parent_span_id": r[4],
                "created_at": r[5].isoformat() if r[5] else "",
            }
            for r in rows
        ]

    async def store_prompt_version(
        self,
        agent_name: str,
        version: int,
        prompt_text: str,
        avg_reward: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a new prompt version."""
        async with self._session_factory() as session, session.begin():
            record = PromptVersionRecord(
                agent_name=agent_name,
                version=version,
                prompt_text=prompt_text,
                avg_reward=avg_reward,
                metadata_=metadata or {},
            )
            session.add(record)

    async def get_latest_prompt(self, agent_name: str) -> dict[str, Any] | None:
        """Get the latest prompt version for an agent."""
        sql = text(
            "SELECT version, prompt_text, avg_reward, created_at "
            "FROM training_prompt_versions WHERE agent_name = :agent "
            "ORDER BY version DESC LIMIT 1"
        )
        async with self._session_factory() as session:
            result = await session.execute(sql, {"agent": agent_name})
            row = result.fetchone()
        if row is None:
            return None
        return {
            "version": row[0],
            "prompt_text": row[1],
            "avg_reward": row[2],
            "created_at": row[3].isoformat() if row[3] else "",
        }

    async def close(self) -> None:
        """Dispose engine."""
        await self._engine.dispose()
