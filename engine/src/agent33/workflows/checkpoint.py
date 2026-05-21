"""Checkpoint manager for workflow state persistence using SQLAlchemy async."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from agent33.config import settings

logger = structlog.get_logger()


class Base(DeclarativeBase):
    pass


class WorkflowCheckpoint(Base):
    """SQLAlchemy model for persisting workflow checkpoints."""

    __tablename__ = "workflow_checkpoints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_id = Column(String(128), nullable=False, index=True)
    step_id = Column(String(128), nullable=False)
    state_json = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class CheckpointManager:
    """Manages workflow checkpoints for resumable execution.

    Uses SQLAlchemy async engine backed by PostgreSQL (or any async-compatible
    database) to save and load workflow state at each step boundary.
    """

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        self._engine = create_async_engine(url, echo=False)
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # type: ignore[call-overload]
        )

    async def initialize(self) -> None:
        """Create the checkpoint table if it does not exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("checkpoint_table_initialized")

    async def save_checkpoint(
        self,
        workflow_id: str,
        step_id: str,
        state: dict[str, Any],
    ) -> str:
        """Save a checkpoint for the given workflow at the given step.

        Args:
            workflow_id: Unique identifier for the workflow run.
            step_id: The step ID that was just completed.
            state: The full state dict to persist.

        Returns:
            The checkpoint record ID.
        """
        checkpoint = WorkflowCheckpoint(
            id=str(uuid4()),
            workflow_id=workflow_id,
            step_id=step_id,
            state_json=json.dumps(state, default=str),
            created_at=datetime.now(UTC),
        )

        async with self._session_factory() as session:
            session.add(checkpoint)
            await session.commit()

        logger.info(
            "checkpoint_saved",
            workflow_id=workflow_id,
            step_id=step_id,
            checkpoint_id=checkpoint.id,
        )
        return checkpoint.id  # type: ignore[return-value]

    async def load_checkpoint(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        """Load the most recent checkpoint for a workflow.

        Args:
            workflow_id: The workflow run identifier.

        Returns:
            The state dict from the latest checkpoint, or None if no
            checkpoint exists.
        """
        async with self._session_factory() as session:
            stmt = (
                select(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.workflow_id == workflow_id)
                .order_by(WorkflowCheckpoint.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            return None

        logger.info(
            "checkpoint_loaded",
            workflow_id=workflow_id,
            step_id=row.step_id,
        )
        parsed: dict[str, Any] = json.loads(row.state_json)
        return parsed

    async def list_checkpoints(
        self,
        workflow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List checkpoints, optionally filtered by workflow_id.

        Args:
            workflow_id: If provided, only return checkpoints for this workflow.

        Returns:
            A list of checkpoint summary dicts.
        """
        async with self._session_factory() as session:
            stmt = select(WorkflowCheckpoint).order_by(WorkflowCheckpoint.created_at.desc())
            if workflow_id is not None:
                stmt = stmt.where(WorkflowCheckpoint.workflow_id == workflow_id)

            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "id": row.id,
                "workflow_id": row.workflow_id,
                "step_id": row.step_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def close(self) -> None:
        """Dispose of the database engine."""
        await self._engine.dispose()
