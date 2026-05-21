"""Alembic async environment for PostgreSQL migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Column, DateTime, MetaData, Text, pool
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True)
    workflow_id = Column(Text, nullable=False)
    step_id = Column(Text, nullable=False)
    state = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(Text, nullable=False)
    agent_name = Column(Text, nullable=False)
    data_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class MemoryDocument(Base):
    __tablename__ = "memory_documents"

    id = Column(UUID(as_uuid=True), primary_key=True)
    content = Column(Text, nullable=False)
    # pgvector column -- represented as Text here; the migration uses raw SQL
    embedding = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


target_metadata: MetaData = Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow override via environment variable
db_url = os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emit SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
