"""Pre-restart validation guard for configuration changes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class RestartGuard:
    """Validates proposed configuration changes before an engine restart.

    Instantiate with the *Settings* class (not an instance) so validation
    can be attempted with the proposed overrides without affecting the running
    configuration.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        self._settings_cls = settings_cls

    def validate_before_restart(
        self,
        proposed_changes: dict[str, Any] | None = None,
    ) -> tuple[bool, list[str]]:
        """Return ``(ok, errors)`` for *proposed_changes*.

        Attempts to construct a new Settings instance with the proposed
        values overlaid.  If construction succeeds (including all Pydantic
        validators), the guard reports ``(True, [])``.  Otherwise, it
        collects the validation error messages and returns ``(False, errors)``.
        """
        if not proposed_changes:
            return True, []

        errors: list[str] = []
        try:
            # Build kwargs: start from current env/defaults, overlay proposed.
            self._settings_cls.model_validate(proposed_changes)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "restart_guard_validation_failed",
                extra={"error": str(exc)},
            )
            # Pydantic ValidationError has `.errors()`, others just str.
            if hasattr(exc, "errors"):
                for err in exc.errors():  # type: ignore[union-attr,unused-ignore]
                    loc = ".".join(str(p) for p in err.get("loc", []))
                    msg = err.get("msg", str(err))
                    errors.append(f"{loc}: {msg}" if loc else msg)
            else:
                errors.append(str(exc))

        ok = len(errors) == 0
        return ok, errors
