"""Mixture-of-Agents (MoA) workflow template builder.

Implements the MoA methodology (arXiv:2406.04692) as a native AGENT-33 DAG
workflow.  Multiple reference models answer the same query in parallel, then
an aggregator model synthesizes their responses into a single high-quality
answer.

Phase 58 extends the original single-layer design with:
- Multi-round proposer layers where each round's outputs feed the next
- Temperature diversity across proposers for response variety
- Cost estimation using PricingCatalog (Phase 49)

The builder produces a ``WorkflowDefinition`` that the standard
``WorkflowExecutor`` can execute without any engine changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from agent33.llm.pricing import (
    CostResult,
    CostStatus,
    PricingCatalog,
    estimate_cost,
    get_default_catalog,
)
from agent33.workflows.definition import (
    ExecutionMode,
    StepAction,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowMetadata,
    WorkflowStep,
)

# ---------------------------------------------------------------------------
# Aggregator system prompt -- derived from the MoA paper (arXiv:2406.04692)
# ---------------------------------------------------------------------------

MOA_AGGREGATOR_SYSTEM_PROMPT: str = (
    "You have been provided with a set of responses from various open-source "
    "AI models to the latest user query. Your task is to synthesize these "
    "responses into a single, high-quality response. It is crucial to "
    "critically evaluate the information provided in these responses, "
    "recognizing that some of it may be biased or incorrect. Your response "
    "should not simply replicate the given answers but should offer a refined, "
    "accurate, and comprehensive reply to the instruction. Ensure your "
    "response is well-structured, coherent, and adheres to the highest "
    "standards of accuracy and reliability.\n\n"
    "Responses from models:"
)

# System prompt used for intermediate rounds (not the final aggregator).
MOA_INTERMEDIATE_SYSTEM_PROMPT: str = (
    "You have been provided with the original user query and responses from "
    "the previous round of AI models. Use these responses as additional "
    "context and reference points. Critically evaluate them, correct any "
    "errors, and produce your own high-quality response to the original query. "
    "Do not simply repeat the prior responses.\n\n"
    "Previous round responses:"
)

# ---------------------------------------------------------------------------
# Temperature diversity
# ---------------------------------------------------------------------------

DEFAULT_TEMPERATURE_SPREAD: float = 0.3
"""Default offset spread for temperature diversity.

When ``temperature_diversity=True``, proposer temperatures are spread
symmetrically around the base temperature by this half-range.  For example,
with base 0.6 and spread 0.3, two models get [0.3, 0.9].
"""


def compute_diverse_temperatures(
    base_temperature: float,
    count: int,
    spread: float = DEFAULT_TEMPERATURE_SPREAD,
) -> list[float]:
    """Compute evenly-spaced temperatures around a base value.

    Returns exactly ``count`` temperature values spread symmetrically around
    ``base_temperature``.  Values are clamped to [0.0, 2.0] (the common LLM
    temperature range).

    For a single model, returns ``[base_temperature]``.
    """
    if count <= 0:
        return []
    if count == 1:
        return [round(base_temperature, 4)]

    temps: list[float] = []
    for i in range(count):
        # Spread from -spread to +spread evenly
        offset = -spread + (2 * spread * i / (count - 1))
        t = base_temperature + offset
        # Clamp to valid range
        t = max(0.0, min(2.0, t))
        temps.append(round(t, 4))
    return temps


# ---------------------------------------------------------------------------
# Step ID helpers
# ---------------------------------------------------------------------------


def _sanitize_step_id(raw: str) -> str:
    """Convert an arbitrary model name into a valid WorkflowStep id.

    Step IDs must match ``^[a-z][a-z0-9_-]*$``.  This helper lower-cases the
    name, replaces non-alphanumeric characters with underscores (not hyphens),
    collapses consecutive underscores, and ensures the result starts with a letter.

    Underscores are used instead of hyphens because Jinja2 parses hyphens as
    subtraction operators, which would cause ``UndefinedError`` when the
    expression evaluator resolves aggregator prompt references like
    ``{{ ref_llama3.result }}``.
    """
    lowered = raw.lower().strip()
    # Replace any character that is not a-z or 0-9 with an underscore
    sanitized = re.sub(r"[^a-z0-9]", "_", lowered)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Strip leading/trailing underscores
    sanitized = sanitized.strip("_")
    # Ensure it starts with a letter
    if not sanitized or not sanitized[0].isalpha():
        sanitized = f"m_{sanitized}" if sanitized else "model"
    return sanitized


def _make_unique_ids(
    models: list[str],
    prefix: str = "ref",
) -> list[tuple[str, str]]:
    """Return (step_id, model_name) pairs with unique step IDs.

    If two models would produce the same sanitized ID, a numeric suffix is
    appended.
    """
    seen: dict[str, int] = {}
    pairs: list[tuple[str, str]] = []
    for model in models:
        base = f"{prefix}_{_sanitize_step_id(model)}"
        count = seen.get(base, 0)
        step_id = f"{base}_{count}" if count > 0 else base
        seen[base] = count + 1
        pairs.append((step_id, model))
    return pairs


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_reference_prompt(query: str) -> str:
    """Build the prompt sent to each reference model."""
    return query


def _build_intermediate_prompt(
    query: str,
    previous_step_ids: list[str],
) -> str:
    """Build the prompt for an intermediate-round proposer.

    Includes the original query plus Jinja2 references to the prior round's
    outputs so the ``ExpressionEvaluator`` can substitute at runtime.
    """
    lines: list[str] = [
        f"Original query: {query}",
        "",
        "Previous round responses:",
    ]
    for idx, step_id in enumerate(previous_step_ids, 1):
        lines.append(f"{idx}. {{{{ {step_id}.result | default('(no response)') }}}}")
    lines.append("")
    lines.append("Provide your own improved response to the original query.")
    return "\n".join(lines)


def _build_aggregator_user_prompt(
    query: str,
    reference_step_ids: list[str],
) -> str:
    """Build the user prompt for the aggregator step.

    Uses Jinja2-style expression references so the ``ExpressionEvaluator``
    inside ``WorkflowExecutor`` can substitute actual reference outputs at
    runtime.
    """
    lines: list[str] = [f"Original query: {query}", "", "Reference responses:"]
    for idx, step_id in enumerate(reference_step_ids, 1):
        # Reference the "result" key that invoke_agent.execute() returns
        lines.append(f"{idx}. {{{{ {step_id}.result | default('(no response)') }}}}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MoACostEstimate:
    """Pre-execution cost estimate for an MoA workflow.

    All costs are in USD and represent estimates based on the PricingCatalog.
    Token counts are heuristic (based on query length) since actual token
    counts are only known after execution.
    """

    total_usd: Decimal
    per_step: list[CostResult] = field(default_factory=list)
    proposer_count: int = 0
    rounds: int = 1
    aggregator_model: str = ""
    status: CostStatus = CostStatus.ESTIMATED


# Rough token-per-char ratio for estimation.  English text averages ~4 chars
# per token for most LLMs; we use a conservative 3.5 to slightly overestimate.
_CHARS_PER_TOKEN: float = 3.5

# Assumed average output tokens per proposer step (conservative estimate).
_DEFAULT_PROPOSER_OUTPUT_TOKENS: int = 500

# Assumed average output tokens for the aggregator step.
_DEFAULT_AGGREGATOR_OUTPUT_TOKENS: int = 800


def estimate_moa_cost(
    query: str,
    reference_models: list[str],
    aggregator_model: str,
    rounds: int = 1,
    provider: str = "openai",
    proposer_output_tokens: int = _DEFAULT_PROPOSER_OUTPUT_TOKENS,
    aggregator_output_tokens: int = _DEFAULT_AGGREGATOR_OUTPUT_TOKENS,
    catalog: PricingCatalog | None = None,
) -> MoACostEstimate:
    """Estimate the total cost of a MoA workflow before execution.

    Uses query length to estimate input tokens and default output token
    assumptions.  Multi-round workflows multiply proposer costs by the number
    of rounds, with intermediate rounds receiving larger prompts (prior round
    outputs are included in input).

    Parameters
    ----------
    query:
        The user query (used for input-token estimation).
    reference_models:
        Model IDs for the proposer layer.
    aggregator_model:
        Model ID for the final aggregator.
    rounds:
        Number of proposer rounds (1 = single layer, 2+ = multi-round).
    provider:
        Default provider for pricing lookup (can be overridden per model
        if models use ``provider/model`` format).
    proposer_output_tokens:
        Estimated output tokens per proposer step.
    aggregator_output_tokens:
        Estimated output tokens for the aggregator.
    catalog:
        Optional custom PricingCatalog; defaults to module singleton.

    Returns
    -------
    MoACostEstimate
        Aggregated cost estimate with per-step breakdown.
    """
    cat = catalog or get_default_catalog()
    query_input_tokens = max(1, int(len(query) / _CHARS_PER_TOKEN))

    step_costs: list[CostResult] = []
    total = Decimal("0")
    any_unknown = False

    num_proposers = len(reference_models)

    for rnd in range(rounds):
        if rnd == 0:
            # First round: only the query as input
            round_input_tokens = query_input_tokens
        else:
            # Subsequent rounds: query + prior round outputs as context
            prior_context_tokens = num_proposers * proposer_output_tokens
            round_input_tokens = query_input_tokens + prior_context_tokens

        for model in reference_models:
            prov, mdl = _parse_provider_model(model, provider)
            cost = estimate_cost(
                model=mdl,
                provider=prov,
                input_tokens=round_input_tokens,
                output_tokens=proposer_output_tokens,
                catalog=cat,
            )
            step_costs.append(cost)
            total += cost.amount_usd
            if cost.status == CostStatus.UNKNOWN:
                any_unknown = True

    # Aggregator: receives query + all final-round proposer outputs
    agg_input_tokens = query_input_tokens + (num_proposers * proposer_output_tokens)
    agg_prov, agg_mdl = _parse_provider_model(aggregator_model, provider)
    agg_cost = estimate_cost(
        model=agg_mdl,
        provider=agg_prov,
        input_tokens=agg_input_tokens,
        output_tokens=aggregator_output_tokens,
        catalog=cat,
    )
    step_costs.append(agg_cost)
    total += agg_cost.amount_usd
    if agg_cost.status == CostStatus.UNKNOWN:
        any_unknown = True

    return MoACostEstimate(
        total_usd=total.quantize(Decimal("0.000001")),
        per_step=step_costs,
        proposer_count=num_proposers,
        rounds=rounds,
        aggregator_model=aggregator_model,
        status=CostStatus.UNKNOWN if any_unknown else CostStatus.ESTIMATED,
    )


def _parse_provider_model(model: str, default_provider: str) -> tuple[str, str]:
    """Parse ``provider/model`` format, falling back to default_provider.

    Examples::

        _parse_provider_model("openai/gpt-4o", "ollama") -> ("openai", "gpt-4o")
        _parse_provider_model("llama3.2", "ollama") -> ("ollama", "llama3.2")
    """
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    return default_provider, model


# ---------------------------------------------------------------------------
# Workflow builders
# ---------------------------------------------------------------------------


def build_moa_workflow(
    query: str,
    reference_models: list[str],
    aggregator_model: str,
    reference_temperature: float = 0.6,
    aggregator_temperature: float = 0.4,
    *,
    rounds: int = 1,
    temperature_diversity: bool = False,
    temperature_spread: float = DEFAULT_TEMPERATURE_SPREAD,
    agent_resolver: Callable[[str], str] | None = None,
) -> WorkflowDefinition:
    """Build a Mixture-of-Agents DAG workflow.

    Creates *N* parallel reference-model steps followed by a single aggregator
    step that depends on all of them.  The aggregator receives every reference
    output and synthesizes a unified answer.

    Multi-round mode (``rounds > 1``) adds intermediate layers where each
    round of proposers receives the prior round's outputs as additional
    context, producing progressively refined responses before the final
    aggregator synthesis.

    Args:
        query: The user question / instruction to answer.
        reference_models: List of model identifiers to query in parallel.
        aggregator_model: Model identifier for the synthesis step.
        reference_temperature: Base sampling temperature for reference models.
        aggregator_temperature: Sampling temperature for the aggregator.
        rounds: Number of proposer rounds (1 = original single-layer MoA).
        temperature_diversity: If True, spread temperatures across proposers
            for response variety instead of using a uniform temperature.
        temperature_spread: Half-range for temperature diversity (default 0.3).
        agent_resolver: Optional callback that maps a model identifier to an
            executable workflow agent name. If omitted, the model identifier is
            used as-is for backward compatibility.

    Returns:
        A fully-formed ``WorkflowDefinition`` ready for ``WorkflowExecutor``.

    Raises:
        ValueError: If ``reference_models`` is empty or ``rounds < 1``.
    """
    if not reference_models:
        raise ValueError("At least one reference model is required")
    if rounds < 1:
        raise ValueError("At least one round is required")

    num_models = len(reference_models)

    # Compute per-proposer temperatures
    if temperature_diversity and num_models > 1:
        temperatures = compute_diverse_temperatures(
            reference_temperature, num_models, temperature_spread
        )
    else:
        temperatures = [reference_temperature] * num_models

    all_steps: list[WorkflowStep] = []
    previous_round_step_ids: list[str] = []

    for rnd in range(rounds):
        round_num = rnd + 1
        prefix = f"r{round_num}" if rounds > 1 else "ref"
        id_model_pairs = _make_unique_ids(reference_models, prefix=prefix)
        current_round_step_ids = [sid for sid, _ in id_model_pairs]

        for idx, (step_id, model_name) in enumerate(id_model_pairs):
            temp = temperatures[idx]
            agent_name = agent_resolver(model_name) if agent_resolver else model_name

            if rnd == 0:
                # First round: use the raw query
                prompt = _build_reference_prompt(query)
                system_prompt = None
                deps: list[str] = []
            else:
                # Subsequent rounds: include prior round outputs
                prompt = _build_intermediate_prompt(query, previous_round_step_ids)
                system_prompt = MOA_INTERMEDIATE_SYSTEM_PROMPT
                deps = list(previous_round_step_ids)

            inputs: dict[str, Any] = {
                "prompt": prompt,
                "temperature": temp,
                "agent_name": model_name,
                "model": model_name,
            }
            if system_prompt is not None:
                inputs["system_prompt"] = system_prompt

            step = WorkflowStep(
                id=step_id,
                name=(
                    f"Round {round_num} Reference: {model_name}"
                    if rounds > 1
                    else f"Reference: {model_name}"
                ),
                action=StepAction.INVOKE_AGENT,
                agent=agent_name,
                depends_on=deps,
                inputs=inputs,
            )
            all_steps.append(step)

        previous_round_step_ids = current_round_step_ids

    # -- Aggregator step (depends on the final round of reference steps) --
    aggregator_step = WorkflowStep(
        id="moa_aggregator",
        name=f"MoA Aggregator: {aggregator_model}",
        action=StepAction.INVOKE_AGENT,
        agent=agent_resolver(aggregator_model) if agent_resolver else aggregator_model,
        depends_on=previous_round_step_ids,
        inputs={
            "system_prompt": MOA_AGGREGATOR_SYSTEM_PROMPT,
            "prompt": _build_aggregator_user_prompt(query, previous_round_step_ids),
            "temperature": aggregator_temperature,
            "agent_name": aggregator_model,
            "model": aggregator_model,
        },
    )
    all_steps.append(aggregator_step)

    return WorkflowDefinition(
        name="moa-workflow",
        version="1.0.0",
        description=(
            "Mixture-of-Agents workflow: parallel reference models "
            "followed by aggregator synthesis (arXiv:2406.04692)."
        ),
        steps=all_steps,
        execution=WorkflowExecution(
            mode=ExecutionMode.DEPENDENCY_AWARE,
            parallel_limit=len(reference_models),
        ),
        metadata=WorkflowMetadata(
            tags=["moa", "multi-model", "ensemble"],
        ),
    )


def format_moa_result(workflow_outputs: dict[str, Any]) -> str:
    """Extract the aggregated response from a MoA workflow result.

    Args:
        workflow_outputs: The ``outputs`` dict from ``WorkflowResult``.

    Returns:
        The aggregated text response, or a fallback message.
    """
    # The aggregator step writes its output under "result" key
    result = workflow_outputs.get("result")
    if isinstance(result, str):
        return result
    # Fallback: return stringified outputs
    return str(workflow_outputs) if workflow_outputs else "(no aggregated response)"
