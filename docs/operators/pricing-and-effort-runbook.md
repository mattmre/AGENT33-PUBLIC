# Pricing And Effort Runbook

## Purpose

Provide the operator verification path for the Phase 49 economics baseline:

- auditable per-model pricing with source attribution
- live effort-routing heuristic thresholds
- a stable fast-path spot-check for short simple prompts

Use this document with:

- [Production Deployment Runbook](production-deployment-runbook.md)
- [Operator Verification Runbook](operator-verification-runbook.md)
- [Service Level Objectives](service-level-objectives.md)

## MCP Inspection Surface

The stable inspection surface is the MCP resource `agent33://pricing-catalog`.

- Required scope: `component-security:read`
- Resource payload includes:
  - `entries`
  - `catalog_snapshot_fetched_at`
  - `cost_estimation_policy`
  - `heuristic_policy`

The resource is intentionally read-only. Phase 49 does not ship dynamic pricing
refresh from provider APIs or any billing UI.

Startup corrections are supported through `pricing_catalog_overrides`, which
accepts a JSON array of override entries applied during app boot.

## Pricing Catalog Contract

Each catalog entry includes:

- `provider`
- `model`
- `input_cost_per_million`
- `output_cost_per_million`
- `cache_read_cost_per_million`
- `cache_write_cost_per_million`
- `source`
- `source_url`
- `fetched_at`

The expected source for builtin rows is `official_docs_snapshot`. User-defined
overrides remain visible through the same resource because the effective catalog
is emitted after overrides are applied.

## Effort Heuristic Contract

The `heuristic_policy` block exposes the live runtime thresholds that shape
routing decisions:

- `simple_message_fast_path.max_chars`
- `simple_message_fast_path.max_words`
- `score_thresholds`
- `payload_thresholds`
- `many_input_fields_threshold`
- `high_iteration_threshold`
- `model_overrides`
- `token_multipliers`

The cost-estimation contract also exposes the legacy fallback:

- `flat_rate_fallback_cost_per_1k_tokens`

Per-invocation routing metadata now also preserves:

- `estimated_cost_status`
- `estimated_cost_source`
- `estimated_cost_source_url`
- `estimated_cost_fetched_at`

That value should be treated as a compatibility fallback, not the primary
economics baseline.

## Verification Steps

1. Read `agent33://pricing-catalog` with a token that has
   `component-security:read`.
2. Confirm `catalog_snapshot_fetched_at` is populated and the resource returns
   the expected `entry_count`.
3. Spot-check the active models you care about. Known examples include:
   - `openai/gpt-4.1`
   - `openai/gpt-4.1-mini`
   - `openai/gpt-4o`
   - `ollama/llama3.2`
4. Verify each checked row has a non-empty `source_url` unless the provider is
   intentionally local and free (`ollama`, `local`, or `airllm`).
5. Confirm the live `heuristic_policy.simple_message_fast_path` values match the
   deployment’s intended threshold configuration.
6. Confirm `cost_estimation_policy.prefers_per_model_catalog_when_provider_resolves`
   is `true`.
7. If `override_count > 0`, verify each override row has `source = user_override`
   and the intended `source_url`.

## Fast-Path Spot Check

Use a short request through `/v1/agents/{id}/invoke` and confirm the routing
metadata shows the heuristic fast path:

- `effort_source = heuristic`
- `effort = low`
- `heuristic_reasons` includes `simple_message_fast_path`

If a simple prompt does not take the fast path, verify that the prompt does not
include URLs, code fences, or complexity keywords before changing thresholds.

## Escalation Guidance

- If source attribution is missing for non-local priced models, treat the
  catalog as non-auditable and block any pricing-sensitive rollout.
- If pricing corrections are needed, prefer `pricing_catalog_overrides` over
  code edits so the effective catalog remains operator-auditable.
- If the heuristic thresholds drift unexpectedly, review recent config changes
  before changing alert thresholds in [Service Level Objectives](service-level-objectives.md).
- If cost estimates appear missing for priced models, verify provider
  resolution first; unknown provider/model pairs can still fall back to the
  flat-rate policy or omit `estimated_cost`.
