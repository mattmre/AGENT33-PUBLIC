"""Runtime guard — startup invariant checks and runtime diagnostics.

Provides :class:`RuntimeGuard` which verifies that critical subsystems
have been initialised and collects live runtime information (PID, uptime,
memory usage, Python version, package version).
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import time
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class StartupInvariant(BaseModel):
    """Result of a single startup invariant check."""

    name: str
    required: bool = True
    present: bool = False
    message: str = ""


class RuntimeInfo(BaseModel):
    """Live runtime diagnostics snapshot."""

    pid: int = 0
    uptime_seconds: float = 0.0
    memory_rss_mb: float = 0.0
    python_version: str = ""
    package_version: str = "0.1.0"
    platform: str = ""
    invariants: list[StartupInvariant] = Field(default_factory=list)
    all_invariants_ok: bool = True


# ---------------------------------------------------------------------------
# Invariant definitions
# ---------------------------------------------------------------------------

# (attribute_name, display_name, required)
_DEFAULT_INVARIANTS: list[tuple[str, str, bool]] = [
    ("agent_registry", "Agent Registry", True),
    ("tool_registry", "Tool Registry", True),
    ("model_router", "Model Router", True),
    ("provenance_collector", "Provenance Collector", False),
    ("receipt_store", "Receipt Store", False),
    ("skill_registry", "Skill Registry", False),
]


# ---------------------------------------------------------------------------
# Memory introspection helper
# ---------------------------------------------------------------------------


def _get_memory_rss_mb() -> float:
    """Return resident set size in MB, or 0.0 if unavailable."""
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        return float(proc.memory_info().rss) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# RuntimeGuard service
# ---------------------------------------------------------------------------


class RuntimeGuard:
    """Verifies startup invariants and provides runtime diagnostics.

    Parameters
    ----------
    app_state:
        The ``app.state`` object from FastAPI.
    start_time:
        Monotonic timestamp captured at application startup.
    extra_invariants:
        Additional ``(attr_name, display_name, required)`` tuples to check.
    """

    def __init__(
        self,
        app_state: Any,
        start_time: float,
        extra_invariants: list[tuple[str, str, bool]] | None = None,
    ) -> None:
        self._app_state = app_state
        self._start_time = start_time
        self._invariants = list(_DEFAULT_INVARIANTS)
        if extra_invariants:
            self._invariants.extend(extra_invariants)

    # -- Invariant checks ----------------------------------------------------

    def check_startup_invariants(self) -> list[StartupInvariant]:
        """Verify that critical subsystems are initialised on app.state.

        Returns a list of :class:`StartupInvariant` results.
        """
        results: list[StartupInvariant] = []
        for attr_name, display_name, required in self._invariants:
            value = getattr(self._app_state, attr_name, None)
            present = value is not None
            if present:
                message = f"{display_name} initialised"
            elif required:
                message = f"{display_name} is MISSING (required)"
            else:
                message = f"{display_name} not initialised (optional)"
            results.append(
                StartupInvariant(
                    name=attr_name,
                    required=required,
                    present=present,
                    message=message,
                )
            )
        return results

    def check_graceful_shutdown(self) -> list[StartupInvariant]:
        """Verify all subsystems that need cleanup are still available.

        This checks the same invariants — if a required subsystem has already
        been torn down (set to ``None``), it reports it as missing.
        """
        return self.check_startup_invariants()

    # -- Runtime info --------------------------------------------------------

    def get_runtime_info(self) -> RuntimeInfo:
        """Collect a live snapshot of runtime diagnostics."""
        invariants = self.check_startup_invariants()
        all_ok = all(inv.present for inv in invariants if inv.required)

        memory_rss_mb = _get_memory_rss_mb()

        pkg_version = "0.1.0"
        try:
            import importlib.metadata

            pkg_version = importlib.metadata.version("agent33")
        except Exception:  # noqa: BLE001
            pass

        uptime = time.time() - self._start_time

        return RuntimeInfo(
            pid=os.getpid(),
            uptime_seconds=round(uptime, 2),
            memory_rss_mb=round(memory_rss_mb, 2),
            python_version=platform.python_version(),
            package_version=pkg_version,
            platform=sys.platform,
            invariants=invariants,
            all_invariants_ok=all_ok,
        )
