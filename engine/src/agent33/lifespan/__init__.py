"""Lifespan modularization package for AGENT-33 (P60a).

This package breaks the monolithic lifespan context manager into discrete,
independently-testable init functions with conditional skip paths for
lite-mode startup.
"""

from agent33.lifespan.fallbacks import InProcessCache, InProcessMessageBus
from agent33.lifespan.phases import init_database, init_nats, init_redis

__all__ = [
    "InProcessCache",
    "InProcessMessageBus",
    "init_database",
    "init_nats",
    "init_redis",
]
