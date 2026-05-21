"""System doctor — pluggable diagnostic checks for the AGENT-33 engine.

Each check probes one concrete subsystem (database, Redis, NATS, config
validity, etc.) and reports a status, message, and timing.  ``SystemDoctor``
runs all checks and produces a :class:`DoctorReport`.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import sys
import time
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CheckCategory(StrEnum):
    """Logical category for a doctor check."""

    CONFIG = "config"
    SERVICE = "service"
    DEPENDENCY = "dependency"
    SECURITY = "security"


class CheckStatus(StrEnum):
    """Outcome of a single doctor check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class DoctorCheck(BaseModel):
    """Result of a single diagnostic check."""

    name: str
    category: CheckCategory
    status: CheckStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


class DoctorReport(BaseModel):
    """Aggregated diagnostic report from all doctor checks."""

    checks: list[DoctorCheck] = Field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.OK
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: str = ""


# ---------------------------------------------------------------------------
# Type alias for a check function
# ---------------------------------------------------------------------------

# A check function receives (app_state, settings) and returns a DoctorCheck.
CheckFn = Callable[[Any, Any], Coroutine[Any, Any, DoctorCheck]]


# ---------------------------------------------------------------------------
# Built-in check implementations
# ---------------------------------------------------------------------------


async def check_database(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify PostgreSQL connectivity via the async engine."""
    start = time.monotonic()
    try:
        import asyncpg

        raw_url = settings.database_url.replace("+asyncpg", "").replace("postgresql", "postgres")
        conn = await asyncio.wait_for(asyncpg.connect(raw_url), timeout=5)
        result = await asyncio.wait_for(conn.execute("SELECT 1"), timeout=5)
        await conn.close()
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="database",
            category=CheckCategory.DEPENDENCY,
            status=CheckStatus.OK,
            message="PostgreSQL is reachable",
            details={"result": result, "url_redacted": _redact(settings.database_url)},
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="database",
            category=CheckCategory.DEPENDENCY,
            status=CheckStatus.ERROR,
            message=f"PostgreSQL unreachable: {exc}",
            details={"url_redacted": _redact(settings.database_url)},
            duration_ms=round(elapsed, 2),
        )


async def check_redis(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify Redis connectivity."""
    start = time.monotonic()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, decode_responses=True
        )
        pong = await asyncio.wait_for(client.ping(), timeout=5)
        await client.aclose()
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="redis",
            category=CheckCategory.DEPENDENCY,
            status=CheckStatus.OK,
            message="Redis is reachable",
            details={"pong": pong},
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="redis",
            category=CheckCategory.DEPENDENCY,
            status=CheckStatus.ERROR,
            message=f"Redis unreachable: {exc}",
            duration_ms=round(elapsed, 2),
        )


async def check_nats(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify NATS connectivity."""
    start = time.monotonic()
    try:
        import nats as nats_lib

        nc = await asyncio.wait_for(nats_lib.connect(settings.nats_url), timeout=5)
        is_connected = nc.is_connected
        await nc.close()
        elapsed = (time.monotonic() - start) * 1000
        status = CheckStatus.OK if is_connected else CheckStatus.ERROR
        return DoctorCheck(
            name="nats",
            category=CheckCategory.DEPENDENCY,
            status=status,
            message="NATS is reachable" if is_connected else "NATS not connected",
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="nats",
            category=CheckCategory.DEPENDENCY,
            status=CheckStatus.ERROR,
            message=f"NATS unreachable: {exc}",
            duration_ms=round(elapsed, 2),
        )


async def check_config_validity(app_state: Any, settings: Any) -> DoctorCheck:
    """Validate that the current Settings instance passes Pydantic validation."""
    start = time.monotonic()
    try:
        # Re-validate the current settings by round-tripping through the model
        settings_cls = type(settings)
        data = {}
        for name in settings_cls.model_fields:
            val = getattr(settings, name)
            # SecretStr must be unwrapped for re-validation
            from pydantic import SecretStr

            if isinstance(val, SecretStr):
                data[name] = val.get_secret_value()
            else:
                data[name] = val
        settings_cls.model_validate(data)
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="config_validity",
            category=CheckCategory.CONFIG,
            status=CheckStatus.OK,
            message="Configuration passes validation",
            details={"field_count": len(settings_cls.model_fields)},
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="config_validity",
            category=CheckCategory.CONFIG,
            status=CheckStatus.ERROR,
            message=f"Configuration validation failed: {exc}",
            duration_ms=round(elapsed, 2),
        )


async def check_required_secrets(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify that security-critical secrets are not using default values."""
    start = time.monotonic()
    warnings: list[str] = []
    try:
        secret_warnings = settings.check_production_secrets()
        warnings.extend(secret_warnings)
    except RuntimeError:
        # Production mode with defaults raises; that's a clear error
        warnings.append("Production secrets check failed (default values in production)")

    elapsed = (time.monotonic() - start) * 1000
    if not warnings:
        return DoctorCheck(
            name="required_secrets",
            category=CheckCategory.SECURITY,
            status=CheckStatus.OK,
            message="All required secrets are configured",
            duration_ms=round(elapsed, 2),
        )
    # In development, defaults are tolerated but warned
    env = getattr(settings, "environment", "development")
    status = CheckStatus.WARNING if env in ("development", "test") else CheckStatus.ERROR
    return DoctorCheck(
        name="required_secrets",
        category=CheckCategory.SECURITY,
        status=status,
        message=f"{len(warnings)} secret(s) using defaults",
        details={"warnings": warnings, "environment": env},
        duration_ms=round(elapsed, 2),
    )


async def check_disk_space(app_state: Any, settings: Any) -> DoctorCheck:
    """Check available disk space on the working directory partition."""
    start = time.monotonic()
    try:
        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        pct_free = (usage.free / usage.total) * 100 if usage.total else 0
        elapsed = (time.monotonic() - start) * 1000

        if pct_free < 5:
            status = CheckStatus.ERROR
            message = f"Critically low disk: {free_gb:.1f} GB free ({pct_free:.0f}%)"
        elif pct_free < 15:
            status = CheckStatus.WARNING
            message = f"Low disk: {free_gb:.1f} GB free ({pct_free:.0f}%)"
        else:
            status = CheckStatus.OK
            message = f"Disk OK: {free_gb:.1f} GB free ({pct_free:.0f}%)"

        return DoctorCheck(
            name="disk_space",
            category=CheckCategory.SERVICE,
            status=status,
            message=message,
            details={
                "free_gb": round(free_gb, 2),
                "total_gb": round(total_gb, 2),
                "percent_free": round(pct_free, 1),
            },
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="disk_space",
            category=CheckCategory.SERVICE,
            status=CheckStatus.ERROR,
            message=f"Disk check failed: {exc}",
            duration_ms=round(elapsed, 2),
        )


async def check_python_version(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify Python version is >= 3.11."""
    start = time.monotonic()
    major, minor = sys.version_info[:2]
    version_str = f"{major}.{minor}.{sys.version_info[2]}"
    elapsed = (time.monotonic() - start) * 1000

    if (major, minor) >= (3, 11):
        return DoctorCheck(
            name="python_version",
            category=CheckCategory.SERVICE,
            status=CheckStatus.OK,
            message=f"Python {version_str} meets minimum requirement (>=3.11)",
            details={
                "version": version_str,
                "platform": platform.platform(),
                "implementation": platform.python_implementation(),
            },
            duration_ms=round(elapsed, 2),
        )
    return DoctorCheck(
        name="python_version",
        category=CheckCategory.SERVICE,
        status=CheckStatus.ERROR,
        message=f"Python {version_str} is below minimum 3.11",
        details={"version": version_str},
        duration_ms=round(elapsed, 2),
    )


async def check_migrations(app_state: Any, settings: Any) -> DoctorCheck:
    """Verify Alembic migration chain is valid (if checker is available)."""
    start = time.monotonic()
    migration_checker = getattr(app_state, "migration_checker", None)
    if migration_checker is None:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="migrations",
            category=CheckCategory.CONFIG,
            status=CheckStatus.SKIPPED,
            message="Migration checker not initialized",
            duration_ms=round(elapsed, 2),
        )
    try:
        mig_status = migration_checker.get_status()
        elapsed = (time.monotonic() - start) * 1000
        if not mig_status.chain_valid:
            return DoctorCheck(
                name="migrations",
                category=CheckCategory.CONFIG,
                status=CheckStatus.ERROR,
                message="Alembic migration chain is invalid",
                details={"heads": mig_status.heads},
                duration_ms=round(elapsed, 2),
            )
        if mig_status.has_multiple_heads:
            return DoctorCheck(
                name="migrations",
                category=CheckCategory.CONFIG,
                status=CheckStatus.WARNING,
                message="Alembic has multiple heads",
                details={"heads": mig_status.heads},
                duration_ms=round(elapsed, 2),
            )
        return DoctorCheck(
            name="migrations",
            category=CheckCategory.CONFIG,
            status=CheckStatus.OK,
            message="Alembic migration chain is valid",
            details={"current_head": mig_status.current_head},
            duration_ms=round(elapsed, 2),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return DoctorCheck(
            name="migrations",
            category=CheckCategory.CONFIG,
            status=CheckStatus.WARNING,
            message=f"Migration check failed: {exc}",
            duration_ms=round(elapsed, 2),
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _redact(url: str) -> str:
    """Redact credentials from a connection URL."""
    if "@" in url:
        return url.split("@", 1)[-1]
    return url


# ---------------------------------------------------------------------------
# SystemDoctor service
# ---------------------------------------------------------------------------


# Default built-in checks
_BUILTIN_CHECKS: list[CheckFn] = [
    check_database,
    check_redis,
    check_nats,
    check_config_validity,
    check_required_secrets,
    check_disk_space,
    check_python_version,
    check_migrations,
]


class SystemDoctor:
    """Pluggable diagnostic checker for the AGENT-33 engine.

    Parameters
    ----------
    app_state:
        The ``app.state`` object from FastAPI (provides access to live
        subsystem references like ``migration_checker``).
    settings:
        The live :class:`~agent33.config.Settings` instance.
    version:
        The engine version string (resolved at startup).
    """

    def __init__(
        self,
        app_state: Any,
        settings: Any,
        version: str = "",
    ) -> None:
        self._app_state = app_state
        self._settings = settings
        self._version = version
        self._checks: list[CheckFn] = list(_BUILTIN_CHECKS)

    def register_check(self, check_fn: CheckFn) -> None:
        """Register an additional doctor check."""
        self._checks.append(check_fn)

    async def run_all(self) -> DoctorReport:
        """Execute all registered checks and return a consolidated report."""
        checks: list[DoctorCheck] = []
        for check_fn in self._checks:
            try:
                result = await check_fn(self._app_state, self._settings)
                checks.append(result)
            except Exception as exc:
                logger.warning(
                    "doctor_check_failed: check=%s error=%s",
                    check_fn.__name__,
                    str(exc),
                )
                checks.append(
                    DoctorCheck(
                        name=check_fn.__name__,
                        category=CheckCategory.SERVICE,
                        status=CheckStatus.ERROR,
                        message=f"Check raised an exception: {exc}",
                    )
                )

        # Determine overall status
        overall = CheckStatus.OK
        for check in checks:
            if check.status == CheckStatus.ERROR:
                overall = CheckStatus.ERROR
                break
            if check.status == CheckStatus.WARNING and overall != CheckStatus.ERROR:
                overall = CheckStatus.WARNING

        return DoctorReport(
            checks=checks,
            overall_status=overall,
            version=self._version,
        )

    async def run_check(self, name: str) -> DoctorCheck | None:
        """Run a single check by name. Returns None if not found."""
        for check_fn in self._checks:
            if check_fn.__name__ == name or check_fn.__name__ == f"check_{name}":
                return await check_fn(self._app_state, self._settings)
        return None
