"""Onboarding checklist — auto-resolving system-state checks for first-run.

Wraps the existing :class:`~agent33.operator.onboarding.OnboardingService`
and adds the ``/v1/ops/onboarding`` compatible models.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class StepStatus(StrEnum):
    """Status of a single onboarding step."""

    COMPLETE = "complete"
    PENDING = "pending"
    SKIPPED = "skipped"


class OnboardingStep(BaseModel):
    """A single onboarding checklist step for the ops API."""

    id: str
    title: str
    description: str
    status: StepStatus
    category: str


class OnboardingChecklist(BaseModel):
    """Aggregated onboarding status with individual steps."""

    steps: list[OnboardingStep] = Field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0
    overall_complete: bool = False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OnboardingChecklistService:
    """Auto-resolving onboarding checklist that checks actual system state.

    Wraps the existing :class:`~agent33.operator.onboarding.OnboardingService`
    under the ``ops`` namespace and converts to ops-compatible models.

    Parameters
    ----------
    app_state:
        The ``app.state`` object from FastAPI.
    settings:
        The live Settings instance.
    """

    def __init__(self, app_state: Any, settings: Any) -> None:
        self._app_state = app_state
        self._settings = settings

    def get_checklist(self) -> OnboardingChecklist:
        """Evaluate all onboarding steps and return the checklist.

        Each step resolves its status by checking the actual running system
        state (app.state attributes, settings values, etc.).
        """
        steps = [
            self._check_config_file(),
            self._check_database(),
            self._check_agent_definitions(),
            self._check_llm_provider(),
            self._check_api_key(),
            self._check_jwt_secret(),
            self._check_redis(),
            self._check_nats(),
        ]
        completed = sum(1 for s in steps if s.status == StepStatus.COMPLETE)
        return OnboardingChecklist(
            steps=steps,
            completed_count=completed,
            total_count=len(steps),
            overall_complete=completed == len(steps),
        )

    # ------------------------------------------------------------------
    # Individual checks — each checks concrete runtime state
    # ------------------------------------------------------------------

    def _check_config_file(self) -> OnboardingStep:
        """Check that a .env or equivalent config source exists."""
        from pathlib import Path

        env_exists = Path(".env").exists()
        return OnboardingStep(
            id="onboard-01",
            title="Configuration file exists",
            description="A .env file or equivalent environment configuration is present.",
            status=StepStatus.COMPLETE if env_exists else StepStatus.PENDING,
            category="config",
        )

    def _check_database(self) -> OnboardingStep:
        """Check that the database connection was established at startup."""
        ltm = getattr(self._app_state, "long_term_memory", None)
        connected = ltm is not None
        return OnboardingStep(
            id="onboard-02",
            title="Database initialized",
            description="PostgreSQL connection was established via DATABASE_URL.",
            status=StepStatus.COMPLETE if connected else StepStatus.PENDING,
            category="infrastructure",
        )

    def _check_agent_definitions(self) -> OnboardingStep:
        """Check that at least one agent definition is loaded."""
        registry = getattr(self._app_state, "agent_registry", None)
        count = len(registry.list_all()) if registry is not None else 0
        return OnboardingStep(
            id="onboard-03",
            title="Agent definitions loaded",
            description=(
                "At least one agent JSON definition is discovered from AGENT_DEFINITIONS_DIR."
            ),
            status=StepStatus.COMPLETE if count > 0 else StepStatus.PENDING,
            category="agents",
        )

    def _check_llm_provider(self) -> OnboardingStep:
        """Check that an LLM provider is configured and registered."""
        model_router = getattr(self._app_state, "model_router", None)
        providers = getattr(model_router, "_providers", {}) if model_router else {}
        has_provider = len(providers) > 0
        return OnboardingStep(
            id="onboard-04",
            title="LLM provider configured",
            description="At least one LLM provider (Ollama, OpenAI, etc.) is registered.",
            status=StepStatus.COMPLETE if has_provider else StepStatus.PENDING,
            category="llm",
        )

    def _check_api_key(self) -> OnboardingStep:
        """Check that the API secret key is not using the default."""
        from pydantic import SecretStr

        default_api_secret = "change-me-in-production"
        current = self._settings.api_secret_key
        if isinstance(current, SecretStr):
            is_default = current.get_secret_value() == default_api_secret
        else:
            is_default = str(current) == default_api_secret
        return OnboardingStep(
            id="onboard-05",
            title="API secret key configured",
            description="API_SECRET_KEY is changed from the insecure default.",
            status=StepStatus.PENDING if is_default else StepStatus.COMPLETE,
            category="security",
        )

    def _check_jwt_secret(self) -> OnboardingStep:
        """Check that the JWT secret is not using the default."""
        from pydantic import SecretStr

        default_jwt = "change-me-in-production"
        current = self._settings.jwt_secret
        if isinstance(current, SecretStr):
            is_default = current.get_secret_value() == default_jwt
        else:
            is_default = str(current) == default_jwt
        return OnboardingStep(
            id="onboard-06",
            title="JWT secret configured",
            description="JWT_SECRET is changed from the insecure default.",
            status=StepStatus.PENDING if is_default else StepStatus.COMPLETE,
            category="security",
        )

    def _check_redis(self) -> OnboardingStep:
        """Check that Redis is connected."""
        redis_conn = getattr(self._app_state, "redis", None)
        return OnboardingStep(
            id="onboard-07",
            title="Redis connected",
            description="Redis is available for caching and rate limiting.",
            status=StepStatus.COMPLETE if redis_conn is not None else StepStatus.PENDING,
            category="infrastructure",
        )

    def _check_nats(self) -> OnboardingStep:
        """Check that NATS is connected."""
        nats_bus = getattr(self._app_state, "nats_bus", None)
        connected = nats_bus is not None and getattr(nats_bus, "is_connected", False)
        return OnboardingStep(
            id="onboard-08",
            title="NATS connected",
            description="NATS message bus is connected for event streaming.",
            status=StepStatus.COMPLETE if connected else StepStatus.PENDING,
            category="infrastructure",
        )
