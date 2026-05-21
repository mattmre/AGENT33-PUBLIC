"""Onboarding checklist for operator first-run experience (Track 9)."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OnboardingStep(BaseModel):
    """A single onboarding checklist step."""

    step_id: str
    category: str
    title: str
    description: str
    completed: bool
    remediation: str = ""


class OnboardingStatus(BaseModel):
    """Overall onboarding status with individual steps."""

    steps: list[OnboardingStep] = Field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0
    overall_complete: bool = False


class OnboardingService:
    """Evaluates onboarding readiness against the running application.

    Each step checks a concrete runtime condition (settings value, app.state
    attribute, etc.) so that the status reflects the actual deployment, not
    just configuration file presence.
    """

    def __init__(self, app_state: Any, settings: Any) -> None:
        self._app_state = app_state
        self._settings = settings

    def check(self) -> OnboardingStatus:
        """Run all onboarding checks and return the aggregated status."""
        steps: list[OnboardingStep] = [
            self._check_database(),
            self._check_llm_provider(),
            self._check_agent_definitions(),
            self._check_jwt_secret(),
            self._check_backup_dir(),
            self._check_redis(),
            self._check_nats(),
            self._check_api_secret(),
        ]

        completed_count = sum(1 for s in steps if s.completed)
        return OnboardingStatus(
            steps=steps,
            completed_count=completed_count,
            total_count=len(steps),
            overall_complete=completed_count == len(steps),
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_database(self) -> OnboardingStep:
        """OB-01: Database is configured and reachable."""
        ltm = getattr(self._app_state, "long_term_memory", None)
        completed = ltm is not None
        return OnboardingStep(
            step_id="OB-01",
            category="infrastructure",
            title="Database configured",
            description="PostgreSQL connection is established via DATABASE_URL.",
            completed=completed,
            remediation=(
                "Set DATABASE_URL and ensure PostgreSQL is running." if not completed else ""
            ),
        )

    def _check_llm_provider(self) -> OnboardingStep:
        """OB-02: At least one LLM provider is registered."""
        model_router = getattr(self._app_state, "model_router", None)
        providers = getattr(model_router, "_providers", {}) if model_router else {}
        completed = len(providers) > 0
        return OnboardingStep(
            step_id="OB-02",
            category="llm",
            title="LLM provider set",
            description="At least one LLM provider is registered in the model router.",
            completed=completed,
            remediation=(
                "Configure OLLAMA_BASE_URL or OPENAI_API_KEY to register an LLM provider."
                if not completed
                else ""
            ),
        )

    def _check_agent_definitions(self) -> OnboardingStep:
        """OB-03: Agent definitions exist and are loaded."""
        registry = getattr(self._app_state, "agent_registry", None)
        count = len(registry.list_all()) if registry is not None else 0
        completed = count > 0
        return OnboardingStep(
            step_id="OB-03",
            category="agents",
            title="Agent definitions exist",
            description="Agent JSON definitions are loaded from AGENT_DEFINITIONS_DIR.",
            completed=completed,
            remediation=(
                "Add agent JSON files to the AGENT_DEFINITIONS_DIR directory."
                if not completed
                else ""
            ),
        )

    def _check_jwt_secret(self) -> OnboardingStep:
        """OB-04: JWT secret is not the default value."""
        from agent33.config import Settings

        default_jwt = Settings.model_fields["jwt_secret"].default
        current = self._settings.jwt_secret
        completed = current.get_secret_value() != default_jwt.get_secret_value()
        return OnboardingStep(
            step_id="OB-04",
            category="security",
            title="JWT secret non-default",
            description="JWT_SECRET is changed from the insecure default value.",
            completed=completed,
            remediation=(
                "Set JWT_SECRET to a cryptographically random value." if not completed else ""
            ),
        )

    def _check_backup_dir(self) -> OnboardingStep:
        """OB-05: Backup directory is configured."""
        backup_dir = self._settings.backup_dir
        completed = bool(backup_dir and backup_dir.strip())
        return OnboardingStep(
            step_id="OB-05",
            category="operations",
            title="Backup directory configured",
            description="BACKUP_DIR is set for backup storage.",
            completed=completed,
            remediation=(
                "Set BACKUP_DIR to a valid directory path for backup storage."
                if not completed
                else ""
            ),
        )

    def _check_redis(self) -> OnboardingStep:
        """OB-06: Redis is connected."""
        redis_conn = getattr(self._app_state, "redis", None)
        completed = redis_conn is not None
        return OnboardingStep(
            step_id="OB-06",
            category="infrastructure",
            title="Redis connected",
            description="Redis is available for caching and session state.",
            completed=completed,
            remediation=("Set REDIS_URL and ensure Redis is running." if not completed else ""),
        )

    def _check_nats(self) -> OnboardingStep:
        """OB-07: NATS bus is connected."""
        nats_bus = getattr(self._app_state, "nats_bus", None)
        connected = nats_bus is not None and getattr(nats_bus, "is_connected", False)
        return OnboardingStep(
            step_id="OB-07",
            category="infrastructure",
            title="NATS connected",
            description="NATS message bus is connected for event streaming.",
            completed=connected,
            remediation=(
                "Set NATS_URL and ensure NATS server is running." if not connected else ""
            ),
        )

    def _check_api_secret(self) -> OnboardingStep:
        """OB-08: API secret key is not the default value."""
        from agent33.config import Settings

        default_api_secret = Settings.model_fields["api_secret_key"].default
        current = self._settings.api_secret_key
        completed = current.get_secret_value() != default_api_secret.get_secret_value()
        return OnboardingStep(
            step_id="OB-08",
            category="security",
            title="API secret key non-default",
            description="API_SECRET_KEY is changed from the insecure default value.",
            completed=completed,
            remediation=("Set API_SECRET_KEY to a strong random value." if not completed else ""),
        )
