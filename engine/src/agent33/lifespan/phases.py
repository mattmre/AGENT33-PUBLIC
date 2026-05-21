"""Discrete lifespan init phase functions (P60a).

Each function handles one logical infrastructure group.  The functions are
conditionally skip-safe: in lite mode they fall back to in-process
implementations instead of crashing on missing services.

The main lifespan in ``main.py`` calls these functions after reading settings
so that the existing 1700-line startup block continues to work unchanged while
new lite-mode callers can use the phase helpers directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from fastapi import FastAPI

    from agent33.config import Settings

logger: Any = structlog.get_logger()


def _redact_url(url: str) -> str:
    """Return the host portion of a URL, stripping credentials."""
    if "@" in url:
        return url.split("@", 1)[-1]
    return url


async def init_database(app: FastAPI, settings: Settings) -> None:
    """Initialise the long-term memory store.

    In lite mode (``AGENT33_MODE=lite``) or when the database_url is empty,
    a ``SQLiteLongTermMemory`` adapter is used instead of PostgreSQL/pgvector.
    This means lite mode has a functioning long-term memory without any external
    database service.
    """
    # Local import so the module-level load does not trigger SQLAlchemy import.
    from agent33.memory.long_term import _SQLALCHEMY_AVAILABLE, LongTermMemory

    db_url = settings.database_url.strip()

    if settings.agent33_mode == "lite" or not db_url:
        from agent33.memory.sqlite_long_term import SQLiteLongTermMemory

        reason = "lite mode" if settings.agent33_mode == "lite" else "no database_url"
        logger.info(
            "database_init_sqlite",
            reason=reason,
            db_path=settings.sqlite_memory_db_path,
        )
        sqlite_ltm = SQLiteLongTermMemory(db_path=settings.sqlite_memory_db_path)
        await sqlite_ltm.initialize()
        app.state.long_term_memory = sqlite_ltm
        return

    if not _SQLALCHEMY_AVAILABLE:
        logger.warning(
            "database_init_skipped",
            reason="sqlalchemy not installed — install agent33[standard]",
        )
        app.state.long_term_memory = None
        return

    long_term_memory = LongTermMemory(
        db_url,
        embedding_dim=settings.embedding_dim,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_recycle=settings.db_pool_recycle,
    )
    try:
        await long_term_memory.initialize()
        logger.info(
            "database_connected",
            url=_redact_url(db_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
    except Exception as exc:
        logger.warning("database_init_failed", error=str(exc))

    app.state.long_term_memory = long_term_memory


async def init_redis(app: FastAPI, settings: Settings) -> None:
    """Initialise the Redis connection or fall back to InProcessCache.

    In lite mode, falls back automatically to ``InProcessCache`` and stores it
    on ``app.state.redis`` so downstream consumers continue to work.
    """
    from agent33.lifespan.fallbacks import InProcessCache

    redis_url = settings.redis_url.strip()

    if settings.agent33_mode == "lite" or not redis_url:
        logger.warning(
            "redis_init_skipped_using_in_process_cache",
            reason="lite mode" if settings.agent33_mode == "lite" else "no redis_url",
        )
        app.state.redis = InProcessCache()
        return

    redis_conn: Any = None
    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
        )
        await _redis_client.ping()
        redis_conn = _redis_client
        logger.info(
            "redis_connected",
            url=_redact_url(redis_url),
            max_connections=settings.redis_max_connections,
        )
    except Exception as exc:
        logger.warning("redis_init_failed_using_in_process_cache", error=str(exc))
        redis_conn = InProcessCache()

    app.state.redis = redis_conn


async def init_nats(app: FastAPI, settings: Settings) -> None:
    """Initialise the NATS message bus or fall back to InProcessMessageBus.

    In lite mode, falls back automatically to ``InProcessMessageBus`` and
    stores it on ``app.state.nats_bus`` so downstream consumers continue to
    work with the is_connected / publish / subscribe interface.
    """
    from agent33.lifespan.fallbacks import InProcessMessageBus

    nats_url = settings.nats_url.strip()

    if settings.agent33_mode == "lite" or not nats_url:
        logger.warning(
            "nats_init_skipped_using_in_process_bus",
            reason="lite mode" if settings.agent33_mode == "lite" else "no nats_url",
        )
        app.state.nats_bus = InProcessMessageBus()
        return

    try:
        from agent33.messaging.bus import _NATS_AVAILABLE, NATSMessageBus
    except ImportError:
        logger.warning("nats_init_skipped_nats_not_installed")
        app.state.nats_bus = InProcessMessageBus()
        return

    if not _NATS_AVAILABLE:
        logger.warning(
            "nats_init_skipped_using_in_process_bus",
            reason="nats-py not installed — install agent33[standard]",
        )
        app.state.nats_bus = InProcessMessageBus()
        return

    nats_bus = NATSMessageBus(nats_url)
    try:
        await nats_bus.connect()
        logger.info("nats_connected", url=_redact_url(nats_url))
    except Exception as exc:
        logger.warning("nats_init_failed_using_in_process_bus", error=str(exc))
        nats_bus = InProcessMessageBus()  # type: ignore[assignment]

    app.state.nats_bus = nats_bus
