"""Adaptive effort-based model/token routing for agent execution.

Operational Tuning Guide – Alert Ownership & Threshold Cadence
==============================================================

The effort router exposes several configurable heuristic thresholds that
directly affect routing decisions and cost. Teams operating this system
should follow this tuning cadence:

**Weekly review (Ops / Platform team)**
  - Check ``effort_routing_estimated_cost_usd`` dashboards for cost drift.
  - Review ``effort_routing_high_effort_total`` trends; a sustained spike
    may indicate the heuristic thresholds need tightening.
  - Validate that alert rules on ``effort_routing_estimated_cost_usd``
    fire correctly by inspecting ``/v1/dashboard/alerts``.

**Monthly calibration (ML / Platform team)**
  - Re-evaluate ``heuristic_low_score_threshold`` and
    ``heuristic_high_score_threshold`` against production request profiles.
  - Adjust ``heuristic_medium_payload_chars`` and
    ``heuristic_large_payload_chars`` if average request sizes shift.
  - Review tenant and domain policy overrides for stale entries.
  - Run the acceptance matrix test suite
    (``tests/test_phase30_effort_routing.py::TestAgentEffortRouter``)
    after any threshold change to confirm routing outcomes.

**Quarterly review (Engineering leadership)**
  - Assess per-model ``cost_per_1k_tokens`` against provider pricing.
  - Evaluate whether new effort tiers or model slots are needed.
  - Archive unused tenant/domain policies.

**Alert ownership**
  - ``effort_routing_high_effort_total`` – owned by the Platform team.
  - ``effort_routing_estimated_cost_usd`` – owned by the Platform team;
    escalation target: Engineering leadership for budget exceptions.
  - ``effort_routing_export_failures_total`` – owned by the Observability
    team; indicates telemetry pipeline issues.

All threshold settings are exposed via ``agent33.config.Settings`` and can
be changed through environment variables without code changes. See
``docs/research/session53-phase30-threshold-calibration.md`` for the
design rationale behind configurable thresholds.
"""

from __future__ import annotations

import dataclasses
import json
import re
from enum import StrEnum
from typing import Any


class AgentEffort(StrEnum):
    """Execution effort level for adaptive routing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EffortSelectionSource(StrEnum):
    """Source that selected the final effort value."""

    REQUEST = "request"
    POLICY = "policy"
    HEURISTIC = "heuristic"
    DEFAULT = "default"


@dataclasses.dataclass(frozen=True, slots=True)
class EffortRoutingDecision:
    """Resolved model/token parameters for a single invocation."""

    effort: AgentEffort
    effort_source: EffortSelectionSource
    model: str
    max_tokens: int
    token_multiplier: float
    estimated_token_budget: int
    estimated_cost: float | None
    estimated_cost_status: str | None = None
    estimated_cost_source: str | None = None
    estimated_cost_source_url: str | None = None
    estimated_cost_fetched_at: str | None = None
    tenant_id: str | None = None
    domain: str | None = None
    policy_key: str | None = None
    heuristic_confidence: float | None = None
    heuristic_score: int | None = None
    heuristic_low_threshold: int | None = None
    heuristic_high_threshold: int | None = None
    heuristic_reasons: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class EffortHeuristicDecision:
    """Deterministic heuristic output for effort selection."""

    effort: AgentEffort
    confidence: float
    score: int
    low_threshold: int
    high_threshold: int
    reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class EffortCostEstimate:
    """Resolved cost estimate plus provenance metadata."""

    amount: float
    status: str
    source: str
    source_url: str | None
    fetched_at: str | None


class AgentEffortRouter:
    """Resolves model and max_tokens based on effort and feature flags."""

    # Expanded keyword categories for heuristic classification (Phase 49).
    # Each keyword contributes +1 to the heuristic score when found in the
    # lowered payload.  Only one match per category is counted.
    _KEYWORD_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "debugging",
            ("debug", "traceback", "stacktrace", "exception", "error", "crash"),
        ),
        (
            "implementation",
            ("implement", "refactor", "patch", "migrate", "rewrite"),
        ),
        (
            "analysis",
            ("analyze", "investigate", "compare", "benchmark", "profile"),
        ),
        (
            "architecture",
            ("architecture", "design", "plan", "planning", "proposal"),
        ),
        (
            "testing",
            ("pytest", "test", "tests", "coverage", "regression"),
        ),
        (
            "operations",
            ("deploy", "docker", "kubernetes", "terraform", "helm"),
        ),
        (
            "security",
            ("security", "vulnerability", "exploit", "cve", "pentest"),
        ),
        (
            "incident",
            ("root cause", "postmortem", "incident", "outage", "downtime"),
        ),
        (
            "optimization",
            ("optimize", "performance", "latency", "throughput", "bottleneck"),
        ),
    )

    # Pre-compiled regex for detecting URLs in payload text.
    _URL_RE: re.Pattern[str] = re.compile(r"https?://", re.IGNORECASE)

    # Pre-compiled regex for detecting code fences in payload text.
    _CODE_FENCE_RE: re.Pattern[str] = re.compile(r"```")

    def __init__(
        self,
        *,
        enabled: bool = False,
        default_effort: AgentEffort | str = AgentEffort.MEDIUM,
        low_model: str | None = None,
        medium_model: str | None = None,
        high_model: str | None = None,
        low_token_multiplier: float = 1.0,
        medium_token_multiplier: float = 1.0,
        high_token_multiplier: float = 1.0,
        heuristic_enabled: bool = True,
        tenant_policies: dict[str, AgentEffort | str] | None = None,
        domain_policies: dict[str, AgentEffort | str] | None = None,
        tenant_domain_policies: dict[str, AgentEffort | str] | None = None,
        cost_per_1k_tokens: float = 0.0,
        heuristic_low_score_threshold: int = 1,
        heuristic_high_score_threshold: int = 4,
        heuristic_medium_payload_chars: int = 800,
        heuristic_large_payload_chars: int = 2000,
        heuristic_many_input_fields_threshold: int = 10,
        heuristic_high_iteration_threshold: int = 15,
        heuristic_simple_max_chars: int = 160,
        heuristic_simple_max_words: int = 28,
    ) -> None:
        self._enabled = enabled
        self._heuristic_enabled = heuristic_enabled
        self._default_effort = self._coerce_effort(default_effort, AgentEffort.MEDIUM)
        self._models: dict[AgentEffort, str | None] = {
            AgentEffort.LOW: low_model or None,
            AgentEffort.MEDIUM: medium_model or None,
            AgentEffort.HIGH: high_model or None,
        }
        self._token_multipliers: dict[AgentEffort, float] = {
            AgentEffort.LOW: low_token_multiplier,
            AgentEffort.MEDIUM: medium_token_multiplier,
            AgentEffort.HIGH: high_token_multiplier,
        }
        self._cost_per_1k_tokens = max(0.0, cost_per_1k_tokens)
        self._heuristic_low_score_threshold = max(0, heuristic_low_score_threshold)
        self._heuristic_high_score_threshold = max(
            self._heuristic_low_score_threshold + 1,
            heuristic_high_score_threshold,
        )
        self._heuristic_medium_payload_chars = max(1, heuristic_medium_payload_chars)
        self._heuristic_large_payload_chars = max(
            self._heuristic_medium_payload_chars + 1,
            heuristic_large_payload_chars,
        )
        self._heuristic_many_input_fields_threshold = max(
            1,
            heuristic_many_input_fields_threshold,
        )
        self._heuristic_high_iteration_threshold = max(1, heuristic_high_iteration_threshold)
        self._heuristic_simple_max_chars = max(1, heuristic_simple_max_chars)
        self._heuristic_simple_max_words = max(1, heuristic_simple_max_words)
        self._tenant_policies = self._coerce_policy_map(tenant_policies or {})
        self._domain_policies = self._coerce_policy_map(domain_policies or {}, lower_keys=True)
        self._tenant_domain_policies = self._coerce_policy_map(
            tenant_domain_policies or {}, lower_keys=True
        )

    @staticmethod
    def _coerce_effort(
        effort: AgentEffort | str | None,
        fallback: AgentEffort,
    ) -> AgentEffort:
        if effort is None:
            return fallback
        if isinstance(effort, AgentEffort):
            return effort
        try:
            return AgentEffort(effort)
        except ValueError:
            return fallback

    @staticmethod
    def _coerce_policy_map(
        policies: dict[str, AgentEffort | str],
        *,
        lower_keys: bool = False,
    ) -> dict[str, AgentEffort]:
        resolved: dict[str, AgentEffort] = {}
        for key, value in policies.items():
            normalized_key = key.strip()
            if not normalized_key:
                continue
            if lower_keys:
                normalized_key = normalized_key.lower()
            try:
                resolved_value = (
                    value if isinstance(value, AgentEffort) else AgentEffort(value.strip().lower())
                )
            except ValueError:
                continue
            resolved[normalized_key] = resolved_value
        return resolved

    @staticmethod
    def _normalize_tenant(tenant_id: str | None) -> str:
        return (tenant_id or "").strip()

    @staticmethod
    def _normalize_domain(domain: str | None) -> str:
        return (domain or "").strip().lower()

    def _resolve_policy_effort(
        self,
        *,
        tenant_id: str,
        domain: str,
    ) -> tuple[AgentEffort | None, str | None]:
        if tenant_id and domain:
            composite_key = f"{tenant_id}|{domain}"
            if composite_key in self._tenant_domain_policies:
                return self._tenant_domain_policies[composite_key], composite_key
        if tenant_id and tenant_id in self._tenant_policies:
            return self._tenant_policies[tenant_id], tenant_id
        if domain and domain in self._domain_policies:
            return self._domain_policies[domain], domain
        return None, None

    def _is_simple_message(self, payload: str, lowered: str) -> bool:
        """Fast-path check: return True if the payload is short and simple.

        A message is "simple" when ALL of the following hold:
        - Character length <= ``heuristic_simple_max_chars``
        - Character length < ``heuristic_medium_payload_chars`` (so the
          fast-path never bypasses payload-size scoring)
        - Word count <= ``heuristic_simple_max_words``
        - No code fences (```````)
        - No URLs (``http://`` or ``https://``)
        - No complex-task keywords from any category
        """
        if len(payload) > self._heuristic_simple_max_chars:
            return False
        if len(payload) >= self._heuristic_medium_payload_chars:
            return False
        if len(payload.split()) > self._heuristic_simple_max_words:
            return False
        if self._CODE_FENCE_RE.search(payload):
            return False
        if self._URL_RE.search(payload):
            return False
        # Check all keyword categories
        for _cat_name, keywords in self._KEYWORD_CATEGORIES:
            if any(kw in lowered for kw in keywords):
                return False
        return True

    def classify_effort(
        self,
        *,
        inputs: dict[str, Any] | None,
        iterative: bool = False,
        max_iterations: int | None = None,
    ) -> EffortHeuristicDecision:
        """Deterministically classify effort from request shape."""
        if not inputs:
            return EffortHeuristicDecision(
                effort=AgentEffort.LOW,
                confidence=0.8,
                score=0,
                low_threshold=self._heuristic_low_score_threshold,
                high_threshold=self._heuristic_high_score_threshold,
                reasons=("empty_or_missing_inputs",),
            )

        payload = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
        payload_len = len(payload)
        top_level_keys = len(inputs)
        lowered = payload.lower()

        # Fast-path pre-filter (Phase 49): if the message is short and simple
        # and we are not in iterative mode, skip the full scoring pipeline.
        if not iterative and self._is_simple_message(payload, lowered):
            return EffortHeuristicDecision(
                effort=AgentEffort.LOW,
                confidence=0.85,
                score=0,
                low_threshold=self._heuristic_low_score_threshold,
                high_threshold=self._heuristic_high_score_threshold,
                reasons=("simple_message_fast_path",),
            )

        score = 0
        reasons: list[str] = []

        if iterative:
            score += 2
            reasons.append("iterative_mode")
        if (
            max_iterations is not None
            and max_iterations >= self._heuristic_high_iteration_threshold
        ):
            score += 1
            reasons.append("high_iteration_budget")
        if payload_len >= self._heuristic_large_payload_chars:
            score += 2
            reasons.append("large_payload")
        elif payload_len >= self._heuristic_medium_payload_chars:
            score += 1
            reasons.append("medium_payload")
        if top_level_keys >= self._heuristic_many_input_fields_threshold:
            score += 1
            reasons.append("many_input_fields")

        # Expanded keyword detection (Phase 49): check each category, adding
        # +1 per category that has at least one keyword match.
        matched_categories = 0
        for _cat_name, keywords in self._KEYWORD_CATEGORIES:
            if any(kw in lowered for kw in keywords):
                matched_categories += 1
        if matched_categories > 0:
            score += matched_categories
            reasons.append("complex_task_keywords")

        if score >= self._heuristic_high_score_threshold:
            effort = AgentEffort.HIGH
            confidence = 0.8
        elif score <= self._heuristic_low_score_threshold:
            effort = AgentEffort.LOW
            confidence = 0.72
        else:
            effort = AgentEffort.MEDIUM
            confidence = 0.68
        return EffortHeuristicDecision(
            effort=effort,
            confidence=confidence,
            score=score,
            low_threshold=self._heuristic_low_score_threshold,
            high_threshold=self._heuristic_high_score_threshold,
            reasons=tuple(reasons) if reasons else ("balanced_request",),
        )

    def _estimate_cost_for_tokens(
        self,
        model: str,
        provider: str | None,
        token_budget: int,
    ) -> EffortCostEstimate | None:
        """Compute estimated cost, preferring pricing catalog over flat rate.

        If a ``provider`` is given, tries the per-model pricing catalog first.
        Falls back to the legacy ``cost_per_1k_tokens`` flat rate.
        """
        if provider:
            from agent33.llm.pricing import CostStatus, estimate_cost, get_default_catalog

            catalog = get_default_catalog()
            result = estimate_cost(
                model=model,
                provider=provider,
                input_tokens=token_budget,
                output_tokens=token_budget,
                catalog=catalog,
            )
            entry = catalog.lookup(provider, model)
            if result.status != CostStatus.UNKNOWN and entry is not None:
                return EffortCostEstimate(
                    amount=float(result.amount_usd),
                    status=result.status.value,
                    source=entry.source.value,
                    source_url=entry.source_url or None,
                    fetched_at=entry.fetched_at.isoformat() if entry.fetched_at else None,
                )

        # Legacy flat-rate fallback
        if self._cost_per_1k_tokens > 0:
            return EffortCostEstimate(
                amount=round((token_budget / 1000.0) * self._cost_per_1k_tokens, 6),
                status="estimated",
                source="legacy_flat_rate",
                source_url=None,
                fetched_at=None,
            )
        return None

    @staticmethod
    def _serialize_cost_estimate(cost_estimate: EffortCostEstimate | None) -> dict[str, Any]:
        """Normalize cost metadata for EffortRoutingDecision construction."""
        if cost_estimate is None:
            return {
                "estimated_cost": None,
                "estimated_cost_status": None,
                "estimated_cost_source": None,
                "estimated_cost_source_url": None,
                "estimated_cost_fetched_at": None,
            }
        return {
            "estimated_cost": cost_estimate.amount,
            "estimated_cost_status": cost_estimate.status,
            "estimated_cost_source": cost_estimate.source,
            "estimated_cost_source_url": cost_estimate.source_url,
            "estimated_cost_fetched_at": cost_estimate.fetched_at,
        }

    def resolve(
        self,
        *,
        requested_model: str | None,
        default_model: str,
        max_tokens: int,
        effort: AgentEffort | str | None = None,
        tenant_id: str | None = None,
        domain: str | None = None,
        inputs: dict[str, Any] | None = None,
        iterative: bool = False,
        max_iterations: int | None = None,
        provider: str | None = None,
    ) -> EffortRoutingDecision:
        """Resolve effective model + max_tokens for this execution.

        Parameters
        ----------
        provider:
            Optional LLM provider name (e.g. ``"openai"``, ``"ollama"``).
            When supplied, cost estimation uses the per-model pricing catalog
            (Phase 49) instead of the flat ``cost_per_1k_tokens`` rate.
        """
        normalized_tenant = self._normalize_tenant(tenant_id)
        normalized_domain = self._normalize_domain(domain)

        explicit_effort: AgentEffort | None = None
        if effort is not None:
            explicit_effort = self._coerce_effort(effort, self._default_effort)

        policy_effort: AgentEffort | None = None
        policy_key: str | None = None
        if explicit_effort is None:
            policy_effort, policy_key = self._resolve_policy_effort(
                tenant_id=normalized_tenant,
                domain=normalized_domain,
            )

        heuristic_decision: EffortHeuristicDecision | None = None
        if explicit_effort is not None:
            resolved_effort = explicit_effort
            effort_source = EffortSelectionSource.REQUEST
        elif policy_effort is not None:
            resolved_effort = policy_effort
            effort_source = EffortSelectionSource.POLICY
        elif self._heuristic_enabled:
            heuristic_decision = self.classify_effort(
                inputs=inputs,
                iterative=iterative,
                max_iterations=max_iterations,
            )
            resolved_effort = heuristic_decision.effort
            effort_source = EffortSelectionSource.HEURISTIC
        else:
            resolved_effort = self._default_effort
            effort_source = EffortSelectionSource.DEFAULT

        if not self._enabled:
            effective_model = requested_model or default_model
            cost_estimate = self._estimate_cost_for_tokens(effective_model, provider, max_tokens)
            return EffortRoutingDecision(
                effort=resolved_effort,
                effort_source=effort_source,
                model=effective_model,
                max_tokens=max_tokens,
                token_multiplier=1.0,
                estimated_token_budget=max_tokens,
                **self._serialize_cost_estimate(cost_estimate),
                tenant_id=normalized_tenant or None,
                domain=normalized_domain or None,
                policy_key=policy_key,
                heuristic_confidence=(
                    heuristic_decision.confidence if heuristic_decision is not None else None
                ),
                heuristic_score=(
                    heuristic_decision.score if heuristic_decision is not None else None
                ),
                heuristic_low_threshold=(
                    heuristic_decision.low_threshold if heuristic_decision is not None else None
                ),
                heuristic_high_threshold=(
                    heuristic_decision.high_threshold if heuristic_decision is not None else None
                ),
                heuristic_reasons=(
                    heuristic_decision.reasons if heuristic_decision is not None else ()
                ),
            )

        selected_model = requested_model or self._models[resolved_effort] or default_model
        multiplier = self._token_multipliers[resolved_effort]
        routed_max_tokens = max(1, int(max_tokens * multiplier))
        cost_estimate = self._estimate_cost_for_tokens(selected_model, provider, routed_max_tokens)
        return EffortRoutingDecision(
            effort=resolved_effort,
            effort_source=effort_source,
            model=selected_model,
            max_tokens=routed_max_tokens,
            token_multiplier=multiplier,
            estimated_token_budget=routed_max_tokens,
            **self._serialize_cost_estimate(cost_estimate),
            tenant_id=normalized_tenant or None,
            domain=normalized_domain or None,
            policy_key=policy_key,
            heuristic_confidence=heuristic_decision.confidence if heuristic_decision else None,
            heuristic_score=heuristic_decision.score if heuristic_decision else None,
            heuristic_low_threshold=(
                heuristic_decision.low_threshold if heuristic_decision else None
            ),
            heuristic_high_threshold=(
                heuristic_decision.high_threshold if heuristic_decision else None
            ),
            heuristic_reasons=heuristic_decision.reasons if heuristic_decision else (),
        )
