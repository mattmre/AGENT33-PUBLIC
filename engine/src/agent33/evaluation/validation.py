"""Evaluation configuration validation (P4.11).

Provides utilities to validate that the ``evaluation_judge_model`` config
is properly set and that the configured model is actually available via the
``ModelRouter``.  These are used at startup or before creating an LLM
evaluator to give operators clear diagnostic messages.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.config import Settings
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)


def check_judge_model_configured(settings: Settings) -> bool:
    """Return ``True`` if ``evaluation_judge_model`` is set to a non-empty value.

    Logs a warning when the value is empty, indicating that the LLM evaluator
    will not be registered and the rule-based evaluator remains the default.
    """
    model = settings.evaluation_judge_model.strip()
    if not model:
        logger.info(
            "evaluation_judge_model is empty; LLM evaluator will not be registered. "
            "Set EVALUATION_JUDGE_MODEL to enable the LLM judge backend."
        )
        return False
    logger.info("evaluation_judge_model configured: %s", model)
    return True


def check_judge_model_available(
    settings: Settings,
    model_router: ModelRouter,
) -> bool:
    """Return ``True`` if the configured judge model can be routed to a provider.

    Parameters
    ----------
    settings:
        Application settings (reads ``evaluation_judge_model``).
    model_router:
        The configured ``ModelRouter`` with registered providers.

    Returns
    -------
    bool
        ``True`` if the model can be routed; ``False`` if routing fails.
    """
    model = settings.evaluation_judge_model.strip()
    if not model:
        return False

    try:
        model_router.route(model)
    except ValueError as exc:
        logger.warning(
            "evaluation_judge_model '%s' cannot be routed to any registered provider: %s",
            model,
            exc,
        )
        return False

    logger.info("evaluation_judge_model '%s' is routable", model)
    return True


def validate_evaluation_config(
    settings: Settings,
    model_router: ModelRouter | None = None,
) -> list[str]:
    """Run all evaluation configuration checks.

    Returns a list of warning messages (empty if everything is valid).
    """
    warnings: list[str] = []

    if not check_judge_model_configured(settings):
        warnings.append(
            "evaluation_judge_model is empty; "
            "LLM evaluator is disabled (rule-based evaluator will be used)"
        )
        return warnings

    if model_router is not None and not check_judge_model_available(settings, model_router):
        model = settings.evaluation_judge_model
        warnings.append(
            f"evaluation_judge_model '{model}' is configured but no provider "
            f"can serve this model. Check that the appropriate LLM provider "
            f"is registered (e.g., OPENAI_API_KEY for OpenAI models)."
        )

    return warnings
