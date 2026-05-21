"""Tests for outcome pack readiness and safe-default policy evaluation."""

from __future__ import annotations

from typing import Any

from agent33.packs.outcome_pack import OutcomePackManifest
from agent33.packs.readiness import (
    OutcomePackReadinessContext,
    OutcomePackReadinessEvaluator,
    OutcomePackReadinessState,
    OutcomePackRequirementState,
)


def _manifest(
    *,
    trust_tier: str = "official",
    risk_level: str = "low",
    approval_required: bool = False,
    requirements: list[dict[str, Any]] | None = None,
) -> OutcomePackManifest:
    return OutcomePackManifest.model_validate(
        {
            "name": "founder-mvp",
            "version": "1.0.0",
            "kind": "outcome-pack",
            "description": "Build a founder-ready MVP plan.",
            "author": "agent33",
            "workflows": [{"name": "build-app", "path": "workflows/build-app.yaml"}],
            "presentation": {
                "title": "Founder MVP Builder",
                "summary": "Turn an app idea into a reviewed first implementation slice.",
            },
            "requirements": requirements or [],
            "governance": {
                "approval_required": approval_required,
                "risk_level": risk_level,
            },
            "provenance": {"trust_tier": trust_tier},
        }
    )


class TestOutcomePackReadinessEvaluator:
    """Readiness verdicts for beginner-safe outcome packs."""

    def test_official_low_risk_pack_is_ready_when_requirements_ready(self) -> None:
        manifest = _manifest(
            requirements=[
                {
                    "kind": "llm",
                    "name": "chat-model",
                    "preferences": ["openrouter", "ollama"],
                }
            ]
        )
        context = OutcomePackReadinessContext(available={"llm": ["ollama"]})

        result = OutcomePackReadinessEvaluator().evaluate(manifest, context)

        assert result.state == OutcomePackReadinessState.READY
        assert result.can_install is True
        assert result.can_run is True
        assert result.requirement_results[0].matched == ["ollama"]

    def test_default_manifest_governance_requires_review(self) -> None:
        manifest = OutcomePackManifest.model_validate(
            {
                "name": "reviewed-pack",
                "version": "1.0.0",
                "description": "Needs review by default.",
                "author": "agent33",
                "workflows": [{"name": "review-flow", "path": "workflows/review.yaml"}],
                "presentation": {
                    "title": "Reviewed Pack",
                    "summary": "Demonstrates safe default approval.",
                },
                "provenance": {"trust_tier": "official"},
            }
        )

        result = OutcomePackReadinessEvaluator().evaluate(manifest)

        assert result.state == OutcomePackReadinessState.REVIEW_REQUIRED
        assert result.can_install is True
        assert result.can_run is False
        assert result.approval_required is True

    def test_approval_grant_allows_run(self) -> None:
        manifest = _manifest(approval_required=True)
        context = OutcomePackReadinessContext(approval_granted=True)

        result = OutcomePackReadinessEvaluator().evaluate(manifest, context)

        assert result.state == OutcomePackReadinessState.READY
        assert result.can_run is True
        assert result.approval_satisfied is True

    def test_missing_required_requirement_blocks_run_but_not_install(self) -> None:
        manifest = _manifest(
            requirements=[
                {
                    "kind": "local-runtime",
                    "name": "ollama",
                    "setup_hint": "Start Ollama and load a model.",
                }
            ]
        )

        result = OutcomePackReadinessEvaluator().evaluate(manifest)

        assert result.state == OutcomePackReadinessState.BLOCKED
        assert result.can_install is True
        assert result.can_run is False
        assert result.requirement_results[0].state == OutcomePackRequirementState.MISSING
        assert "Start Ollama" in result.next_steps[0]

    def test_optional_requirement_missing_needs_setup_without_blocking_run(self) -> None:
        manifest = _manifest(
            requirements=[{"kind": "embeddings", "name": "local-embeddings", "required": False}]
        )

        result = OutcomePackReadinessEvaluator().evaluate(manifest)

        assert result.state == OutcomePackReadinessState.NEEDS_SETUP
        assert result.can_run is True
        assert result.requirement_results[0].state == OutcomePackRequirementState.OPTIONAL_MISSING

    def test_blocked_requirement_blocks_run_but_not_install(self) -> None:
        manifest = _manifest(requirements=[{"kind": "tool", "name": "shell"}])
        context = OutcomePackReadinessContext(blocked={"tool": ["shell"]})

        result = OutcomePackReadinessEvaluator().evaluate(manifest, context)

        assert result.state == OutcomePackReadinessState.BLOCKED
        assert result.can_install is True
        assert result.can_run is False
        assert result.requirement_results[0].state == OutcomePackRequirementState.BLOCKED

    def test_untrusted_pack_is_blocked_for_install_and_run(self) -> None:
        manifest = _manifest(trust_tier="untrusted")

        result = OutcomePackReadinessEvaluator().evaluate(manifest)

        assert result.state == OutcomePackReadinessState.BLOCKED
        assert result.can_install is False
        assert result.can_run is False
        assert "untrusted" in result.blocking_reasons[0]

    def test_imported_pack_requires_allowance(self) -> None:
        manifest = _manifest(trust_tier="imported")

        blocked = OutcomePackReadinessEvaluator().evaluate(manifest)
        allowed = OutcomePackReadinessEvaluator().evaluate(
            manifest,
            OutcomePackReadinessContext(allow_imported=True, approval_granted=True),
        )

        assert blocked.can_install is False
        assert allowed.can_install is True
        assert allowed.can_run is True

    def test_community_pack_requires_review_even_if_manifest_opts_out(self) -> None:
        manifest = _manifest(trust_tier="community", approval_required=False)

        result = OutcomePackReadinessEvaluator().evaluate(manifest)

        assert result.state == OutcomePackReadinessState.REVIEW_REQUIRED
        assert result.approval_required is True
        assert result.can_run is False

    def test_beginner_mode_requires_review_for_verified_medium_risk_pack(self) -> None:
        manifest = _manifest(trust_tier="verified", risk_level="medium")

        beginner = OutcomePackReadinessEvaluator().evaluate(manifest)
        advanced = OutcomePackReadinessEvaluator().evaluate(
            manifest,
            OutcomePackReadinessContext(beginner_mode=False),
        )

        assert beginner.state == OutcomePackReadinessState.REVIEW_REQUIRED
        assert advanced.state == OutcomePackReadinessState.READY

    def test_result_serializes_timestamp_for_api_responses(self) -> None:
        result = OutcomePackReadinessEvaluator().evaluate(_manifest())

        data = result.model_dump(mode="json")

        assert isinstance(data["checked_at"], str)
        assert "T" in data["checked_at"]

    def test_context_defaults_are_not_shared(self) -> None:
        first = OutcomePackReadinessContext()
        first.available["llm"] = ["ollama"]
        second = OutcomePackReadinessContext()

        assert second.available == {}
