"""Tests for the Session Analytics & Insights Engine (Phase 57).

Extended by Architecture & Planning H-03: tenant isolation enforcement, CostTracker
bounded records, and iter_records() public API.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes.insights import set_insights_dependencies
from agent33.observability.insights import InsightsEngine, InsightsReport
from agent33.observability.metrics import CostTracker, MetricsCollector, UsageRecord
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Unit tests: InsightsEngine
# ---------------------------------------------------------------------------


class TestInsightsEngineAggregation:
    """Verify the engine computes correct aggregate values."""

    def test_basic_aggregation_with_cost_tracker(self) -> None:
        """Engine sums tokens and cost from CostTracker records."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"gpt-4": {"input": 0.03, "output": 0.06}})

        # Record two invocations
        ct.record_usage("gpt-4", tokens_in=1000, tokens_out=500, scope="global")
        ct.record_usage("gpt-4", tokens_in=2000, tokens_out=1000, scope="global")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1)

        assert isinstance(report, InsightsReport)
        assert report.total_tokens == 4500  # 1000+500+2000+1000
        assert report.total_cost_usd > Decimal("0")
        assert report.period_days == 1
        assert report.generated_at != ""

    def test_model_usage_breakdown(self) -> None:
        """Engine produces per-model usage data with correct structure."""
        mc = MetricsCollector()
        ct = CostTracker(
            pricing={
                "gpt-4": {"input": 0.03, "output": 0.06},
                "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            }
        )

        ct.record_usage("gpt-4", tokens_in=1000, tokens_out=500, scope="global")
        ct.record_usage("gpt-3.5-turbo", tokens_in=5000, tokens_out=3000, scope="global")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1)

        assert "gpt-4" in report.model_usage
        assert "gpt-3.5-turbo" in report.model_usage

        gpt4 = report.model_usage["gpt-4"]
        assert gpt4["tokens"] == 1500
        assert gpt4["input_tokens"] == 1000
        assert gpt4["output_tokens"] == 500
        assert gpt4["invocations"] == 1
        assert gpt4["cost_usd"] > 0

        gpt35 = report.model_usage["gpt-3.5-turbo"]
        assert gpt35["tokens"] == 8000
        assert gpt35["invocations"] == 1

    def test_cost_computation_accuracy(self) -> None:
        """Verify dollar cost matches expected value from pricing table."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})

        # 2000 input tokens at $0.01/1K = $0.02
        # 1000 output tokens at $0.02/1K = $0.02
        # Total = $0.04
        ct.record_usage("test-model", tokens_in=2000, tokens_out=1000, scope="global")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1)

        assert report.total_cost_usd == Decimal("0.04")

    def test_sessions_from_http_counter(self) -> None:
        """Engine derives total_sessions from http_requests_total counter."""
        mc = MetricsCollector()
        mc.increment("http_requests_total")
        mc.increment("http_requests_total")
        mc.increment("http_requests_total")

        engine = InsightsEngine(mc)
        report = engine.generate(days=1)

        assert report.total_sessions == 3

    def test_sessions_from_labeled_http_counter(self) -> None:
        """Engine sums labeled http_requests_total counters."""
        mc = MetricsCollector()
        mc.increment("http_requests_total", {"method": "GET"})
        mc.increment("http_requests_total", {"method": "GET"})
        mc.increment("http_requests_total", {"method": "POST"})

        engine = InsightsEngine(mc)
        report = engine.generate(days=1)

        assert report.total_sessions == 3

    def test_avg_duration_from_latency_observation(self) -> None:
        """Engine derives avg_session_duration from request latency observations."""
        mc = MetricsCollector()
        mc.observe("http_request_duration_seconds", 0.5)
        mc.observe("http_request_duration_seconds", 1.5)

        engine = InsightsEngine(mc)
        report = engine.generate(days=1)

        assert report.avg_session_duration_seconds == pytest.approx(1.0, abs=0.01)


class TestInsightsEngineTimeWindow:
    """Verify time-window filtering."""

    def test_excludes_old_records(self) -> None:
        """Records older than the window are excluded from token/cost totals."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})

        # Record a usage event, then manually backdate it
        ct.record_usage("test-model", tokens_in=1000, tokens_out=500, scope="global")
        # Backdate the record to 10 days ago
        ct._records[-1] = ct._records[-1].__class__(
            model="test-model",
            tokens_in=1000,
            tokens_out=500,
            cost=ct._records[-1].cost,
            timestamp=time.time() - (10 * 86400),
            scope="global",
        )

        # Record a recent usage event
        ct.record_usage("test-model", tokens_in=2000, tokens_out=1000, scope="global")

        engine = InsightsEngine(mc, ct)

        # 1-day window should only include the recent record
        report_1d = engine.generate(days=1)
        assert report_1d.total_tokens == 3000  # only 2000+1000

        # 30-day window should include both records
        report_30d = engine.generate(days=30)
        assert report_30d.total_tokens == 4500  # 1000+500+2000+1000

    def test_daily_activity_fills_gaps(self) -> None:
        """Daily activity includes entries for days with no activity."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})
        ct.record_usage("test-model", tokens_in=100, tokens_out=50, scope="global")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=3)

        # Should have entries for each day in the 3-day window
        assert len(report.daily_activity) >= 3
        # Today's entry should have activity
        today_entry = report.daily_activity[-1]
        assert today_entry["tokens"] == 150
        assert today_entry["sessions"] == 1

    def test_minimum_days_clamped_to_1(self) -> None:
        """Days parameter below 1 is clamped to 1."""
        mc = MetricsCollector()
        engine = InsightsEngine(mc)
        report = engine.generate(days=0)
        assert report.period_days == 1

        report_neg = engine.generate(days=-5)
        assert report_neg.period_days == 1


class TestInsightsEngineTenantIsolation:
    """Verify per-tenant filtering."""

    def test_tenant_filter_includes_matching_records(self) -> None:
        """Only records matching the tenant scope are included."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})

        ct.record_usage("test-model", tokens_in=1000, tokens_out=500, scope="tenant:acme")
        ct.record_usage("test-model", tokens_in=2000, tokens_out=1000, scope="tenant:globex")
        ct.record_usage(
            "test-model", tokens_in=500, tokens_out=250, scope="tenant:acme:workflow:build"
        )

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1, tenant_id="acme")

        # Should include tenant:acme (1000+500) + tenant:acme:workflow:build (500+250)
        assert report.total_tokens == 2250

    def test_tenant_filter_excludes_other_tenants(self) -> None:
        """Records from other tenants are excluded."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})

        ct.record_usage("test-model", tokens_in=1000, tokens_out=500, scope="tenant:acme")
        ct.record_usage("test-model", tokens_in=2000, tokens_out=1000, scope="tenant:globex")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1, tenant_id="globex")

        assert report.total_tokens == 3000  # only globex tokens

    def test_no_tenant_filter_includes_all(self) -> None:
        """Without tenant_id, all records are included."""
        mc = MetricsCollector()
        ct = CostTracker(pricing={"test-model": {"input": 0.01, "output": 0.02}})

        ct.record_usage("test-model", tokens_in=1000, tokens_out=500, scope="tenant:acme")
        ct.record_usage("test-model", tokens_in=2000, tokens_out=1000, scope="tenant:globex")

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1, tenant_id=None)

        assert report.total_tokens == 4500  # all tenants


class TestInsightsEngineEdgeCases:
    """Edge cases and empty-data scenarios."""

    def test_empty_metrics_produces_zero_report(self) -> None:
        """Engine returns a valid report with zero values when no data exists."""
        mc = MetricsCollector()
        engine = InsightsEngine(mc)
        report = engine.generate(days=30)

        assert report.total_sessions == 0
        assert report.total_tokens == 0
        assert report.total_cost_usd == Decimal("0")
        assert report.avg_session_duration_seconds == 0.0
        assert report.tool_usage == {}
        assert report.model_usage == {}
        assert report.daily_activity == []
        assert report.period_days == 30

    def test_no_cost_tracker_still_reports_sessions(self) -> None:
        """Without CostTracker, session count from MetricsCollector is reported."""
        mc = MetricsCollector()
        mc.increment("http_requests_total")
        mc.increment("http_requests_total")

        engine = InsightsEngine(mc, cost_tracker=None)
        report = engine.generate(days=1)

        assert report.total_sessions == 2
        assert report.total_tokens == 0
        assert report.total_cost_usd == Decimal("0")

    def test_tool_usage_from_effort_routing(self) -> None:
        """When no tool-specific counters exist, effort routing is reported."""
        mc = MetricsCollector()
        mc.increment("effort_routing_decisions_total")
        mc.increment("effort_routing_decisions_total")

        engine = InsightsEngine(mc)
        report = engine.generate(days=1)

        assert "effort_routing" in report.tool_usage
        assert report.tool_usage["effort_routing"] == 2


# ---------------------------------------------------------------------------
# API route integration tests
# ---------------------------------------------------------------------------


class TestInsightsRoute:
    """Test the GET /v1/insights endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        # Wire a fresh MetricsCollector + CostTracker for the route
        self.mc = MetricsCollector()
        self.ct = CostTracker(pricing={"gpt-4": {"input": 0.03, "output": 0.06}})
        self.mc.increment("http_requests_total")
        self.ct.record_usage("gpt-4", tokens_in=1000, tokens_out=500, scope="global")
        set_insights_dependencies(self.mc, self.ct)

    def test_default_response_shape(self) -> None:
        """GET /v1/insights returns all expected keys with correct types."""
        resp = self.client.get("/v1/insights")
        assert resp.status_code == 200

        data = resp.json()
        assert "total_sessions" in data
        assert "total_tokens" in data
        assert "total_cost_usd" in data
        assert "avg_session_duration_seconds" in data
        assert "tool_usage" in data
        assert "model_usage" in data
        assert "daily_activity" in data
        assert "period_days" in data
        assert "generated_at" in data

        assert isinstance(data["total_sessions"], int)
        assert isinstance(data["total_tokens"], int)
        assert isinstance(data["total_cost_usd"], float)
        assert isinstance(data["period_days"], int)
        assert isinstance(data["tool_usage"], dict)
        assert isinstance(data["model_usage"], dict)
        assert isinstance(data["daily_activity"], list)

    def test_response_values_match_seeded_data(self) -> None:
        """Returned values reflect the seeded MetricsCollector and CostTracker data."""
        resp = self.client.get("/v1/insights")
        data = resp.json()

        assert data["total_sessions"] == 1
        assert data["total_tokens"] == 1500  # 1000 + 500
        assert data["total_cost_usd"] > 0
        assert data["period_days"] == 30

        assert "gpt-4" in data["model_usage"]
        assert data["model_usage"]["gpt-4"]["invocations"] == 1

    def test_days_query_param(self) -> None:
        """The days query parameter controls the lookback period."""
        resp = self.client.get("/v1/insights?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7

    def test_days_validation_rejects_zero(self) -> None:
        """Days < 1 is rejected by the query param validator."""
        resp = self.client.get("/v1/insights?days=0")
        assert resp.status_code == 422  # FastAPI validation error

    def test_days_validation_rejects_too_large(self) -> None:
        """Days > 365 is rejected by the query param validator."""
        resp = self.client.get("/v1/insights?days=999")
        assert resp.status_code == 422

    def test_tenant_id_filter(self) -> None:
        """The tenant_id query parameter filters cost data."""
        # Seed tenant-specific data
        self.ct.record_usage("gpt-4", tokens_in=500, tokens_out=200, scope="tenant:acme")
        set_insights_dependencies(self.mc, self.ct)

        resp = self.client.get("/v1/insights?tenant_id=acme")
        assert resp.status_code == 200
        data = resp.json()

        # Only the tenant:acme record should be included
        assert data["total_tokens"] == 700  # 500 + 200

    def test_unauthenticated_returns_401(self) -> None:
        """Request without auth token gets 401."""
        from starlette.testclient import TestClient

        from agent33.main import app

        anon_client = TestClient(app)
        resp = anon_client.get("/v1/insights")
        assert resp.status_code == 401

    def test_daily_activity_shape(self) -> None:
        """Each entry in daily_activity has date, sessions, tokens, cost_usd."""
        resp = self.client.get("/v1/insights?days=3")
        data = resp.json()

        assert len(data["daily_activity"]) >= 3
        for entry in data["daily_activity"]:
            assert "date" in entry
            assert "sessions" in entry
            assert "tokens" in entry
            assert "cost_usd" in entry


# ---------------------------------------------------------------------------
# Phase 57 wiring tests: CostTracker + PricingCatalog integration
# ---------------------------------------------------------------------------


class TestCostTrackerPricingCatalog:
    """Verify CostTracker delegates to PricingCatalog when no legacy dict given."""

    def test_catalog_pricing_for_known_model(self) -> None:
        """CostTracker without pricing dict uses PricingCatalog for gpt-4o."""
        ct = CostTracker()  # no pricing dict -> catalog path
        cost = ct.record_usage(
            "gpt-4o", tokens_in=1000, tokens_out=500, scope="global", provider="openai"
        )
        # gpt-4o: $2.50/M input, $10/M output
        # 1000 input -> $0.0025, 500 output -> $0.005  => $0.0075
        assert cost > 0
        assert cost == pytest.approx(0.0075, abs=0.0001)

    def test_catalog_pricing_for_unknown_model_returns_zero(self) -> None:
        """CostTracker gracefully returns 0 cost for unrecognized models."""
        ct = CostTracker()
        cost = ct.record_usage(
            "totally-unknown-model",
            tokens_in=5000,
            tokens_out=2000,
            scope="global",
            provider="unknown-provider",
        )
        assert cost == 0.0

    def test_catalog_accumulates_across_calls(self) -> None:
        """Multiple record_usage calls accumulate in the cost report."""
        ct = CostTracker()
        ct.record_usage(
            "gpt-4o", tokens_in=1000, tokens_out=500, scope="global", provider="openai"
        )
        ct.record_usage(
            "gpt-4o", tokens_in=2000, tokens_out=1000, scope="global", provider="openai"
        )

        report = ct.get_cost()
        assert report.invocations == 2
        assert report.input_tokens == 3000
        assert report.output_tokens == 1500
        assert report.total_cost > 0

    def test_catalog_cost_produces_nonzero_insights(self) -> None:
        """InsightsEngine + catalog-backed CostTracker yields nonzero data."""
        mc = MetricsCollector()
        ct = CostTracker()  # catalog path
        ct.record_usage(
            "gpt-4o", tokens_in=1000, tokens_out=500, scope="global", provider="openai"
        )

        engine = InsightsEngine(mc, ct)
        report = engine.generate(days=1)

        assert report.total_tokens == 1500
        assert report.total_cost_usd > Decimal("0")
        assert "gpt-4o" in report.model_usage
        assert report.model_usage["gpt-4o"]["invocations"] == 1

    def test_legacy_pricing_still_works(self) -> None:
        """Explicit pricing dict takes precedence over catalog."""
        ct = CostTracker(pricing={"my-model": {"input": 0.05, "output": 0.10}})
        cost = ct.record_usage("my-model", tokens_in=1000, tokens_out=1000, scope="global")
        # 1000/1000 * 0.05 + 1000/1000 * 0.10 = 0.15
        assert cost == pytest.approx(0.15, abs=0.001)

    def test_set_pricing_creates_dict_when_none(self) -> None:
        """set_pricing on a catalog-backed tracker creates a pricing dict."""
        ct = CostTracker()
        assert ct._pricing is None

        ct.set_pricing("custom-model", 0.01, 0.02)
        assert ct._pricing is not None
        assert "custom-model" in ct._pricing

        cost = ct.record_usage("custom-model", tokens_in=1000, tokens_out=500, scope="global")
        # 1000/1000 * 0.01 + 500/1000 * 0.02 = 0.02
        assert cost == pytest.approx(0.02, abs=0.001)

    def test_custom_catalog_instance(self) -> None:
        """CostTracker can be given a custom PricingCatalog."""
        from agent33.llm.pricing import CostSource, PricingCatalog, PricingEntry

        catalog = PricingCatalog()
        catalog.set_override(
            "test-provider",
            "test-model",
            PricingEntry(
                input_cost_per_million=Decimal("10"),
                output_cost_per_million=Decimal("20"),
                source=CostSource.USER_OVERRIDE,
            ),
        )
        ct = CostTracker(pricing_catalog=catalog)
        cost = ct.record_usage(
            "test-model",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
            scope="global",
            provider="test-provider",
        )
        # $10 input + $20 output = $30
        assert cost == pytest.approx(30.0, abs=0.01)


class TestAgentRuntimeCostRecording:
    """Verify AgentRuntime records cost after LLM calls."""

    @pytest.fixture()
    def mock_definition(self) -> Any:
        """Minimal agent definition for testing."""
        defn = MagicMock()
        defn.name = "test-agent"
        defn.role.value = "worker"
        defn.capabilities = []
        defn.spec_capabilities = []
        defn.governance.scope = ""
        defn.governance.commands = ""
        defn.governance.network = ""
        defn.governance.approval_required = []
        defn.governance.tool_policies = {}
        defn.autonomy_level.value = "full"
        defn.ownership.owner = ""
        defn.ownership.escalation_target = ""
        defn.dependencies = []
        defn.inputs = {}
        defn.outputs = {}
        defn.constraints.max_tokens = 1024
        defn.constraints.timeout_seconds = 30
        defn.constraints.max_retries = 0
        defn.description = "test agent"
        defn.agent_id = "AGT-TEST"
        defn.skills = []
        return defn

    @pytest.fixture()
    def mock_router(self) -> Any:
        """ModelRouter mock that returns a fake LLMResponse."""
        from agent33.llm.base import LLMResponse

        router = AsyncMock()
        router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "ok"}',
                model="gpt-4o",
                prompt_tokens=500,
                completion_tokens=200,
            )
        )
        return router

    async def test_invoke_records_cost(self, mock_definition: Any, mock_router: Any) -> None:
        """AgentRuntime.invoke() calls cost_tracker.record_usage on success."""
        from agent33.agents.runtime import AgentRuntime

        cost_tracker = CostTracker(pricing={"gpt-4o": {"input": 0.01, "output": 0.02}})

        runtime = AgentRuntime(
            definition=mock_definition,
            router=mock_router,
            model="gpt-4o",
            cost_tracker=cost_tracker,
        )
        await runtime.invoke({})

        assert len(cost_tracker._records) == 1
        record = cost_tracker._records[0]
        assert record.model == "gpt-4o"
        assert record.tokens_in == 500
        assert record.tokens_out == 200
        assert record.cost > 0

    async def test_invoke_cost_scope_uses_tenant(
        self, mock_definition: Any, mock_router: Any
    ) -> None:
        """Cost record scope includes tenant_id when set."""
        from agent33.agents.runtime import AgentRuntime

        cost_tracker = CostTracker(pricing={"gpt-4o": {"input": 0.01, "output": 0.02}})

        runtime = AgentRuntime(
            definition=mock_definition,
            router=mock_router,
            model="gpt-4o",
            cost_tracker=cost_tracker,
            tenant_id="acme",
        )
        await runtime.invoke({})

        assert cost_tracker._records[0].scope == "tenant:acme"

    async def test_invoke_no_cost_tracker_is_harmless(
        self, mock_definition: Any, mock_router: Any
    ) -> None:
        """AgentRuntime works fine without a cost_tracker (no crash)."""
        from agent33.agents.runtime import AgentRuntime

        runtime = AgentRuntime(
            definition=mock_definition,
            router=mock_router,
            model="gpt-4o",
        )
        result = await runtime.invoke({})
        assert result.raw_response == '{"result": "ok"}'


class TestToolLoopMetricsEmission:
    """Verify ToolLoop emits tool_execution counters via MetricsCollector."""

    async def test_tool_execution_increments_counter(self) -> None:
        """Successful tool execution emits tool_execution_<name>_total counter."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
        from agent33.llm.base import (
            ChatMessage,
            LLMResponse,
            ToolCall,
            ToolCallFunction,
        )
        from agent33.tools.base import ToolResult

        mc = MetricsCollector()

        # Mock router: first call returns a tool call, second returns text
        router = AsyncMock()
        router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    model="test",
                    prompt_tokens=100,
                    completion_tokens=50,
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            function=ToolCallFunction(
                                name="web_fetch",
                                arguments='{"url": "https://example.com"}',
                            ),
                        )
                    ],
                ),
                LLMResponse(
                    content="COMPLETED: done",
                    model="test",
                    prompt_tokens=100,
                    completion_tokens=50,
                ),
            ]
        )

        # Mock tool registry
        tool_registry = MagicMock()
        tool_registry.get_tool_descriptions.return_value = []
        tool_registry.validated_execute = AsyncMock(return_value=ToolResult.ok("fetched content"))

        loop = ToolLoop(
            router=router,
            tool_registry=tool_registry,
            config=ToolLoopConfig(
                max_iterations=5,
                enable_double_confirmation=False,
            ),
            metrics_collector=mc,
        )

        messages = [
            ChatMessage(role="system", content="You are a test agent."),
            ChatMessage(role="user", content="Fetch a URL"),
        ]
        await loop.run(messages, model="test", temperature=0.7)

        # Verify the counter was emitted
        summary = mc.get_summary()
        assert "tool_execution_web_fetch_total" in summary
        assert summary["tool_execution_web_fetch_total"] == 1

    async def test_tool_counter_visible_in_insights_tool_usage(self) -> None:
        """InsightsEngine picks up tool_execution counters from MetricsCollector."""
        mc = MetricsCollector()
        mc.increment("tool_execution_shell_total")
        mc.increment("tool_execution_shell_total")
        mc.increment("tool_execution_web_fetch_total")

        engine = InsightsEngine(mc)
        report = engine.generate(days=1)

        assert "shell" in report.tool_usage
        assert report.tool_usage["shell"] == 2
        assert "web_fetch" in report.tool_usage
        assert report.tool_usage["web_fetch"] == 1


# ---------------------------------------------------------------------------
# Architecture & Planning H-03: Tenant isolation enforcement tests
# ---------------------------------------------------------------------------


class TestInsightsRouteTenantIsolation:
    """Verify the insights endpoint enforces tenant isolation (Architecture & Planning H-03).

    Non-admin callers must only see their own tenant's data.  Admin callers
    may view any tenant's data or all tenants.
    """

    @pytest.fixture(autouse=True)
    def _seed_data(self) -> None:
        """Seed cost data for two tenants."""
        self.mc = MetricsCollector()
        self.ct = CostTracker(pricing={"gpt-4": {"input": 0.03, "output": 0.06}})
        self.ct.record_usage("gpt-4", tokens_in=1000, tokens_out=500, scope="tenant:acme")
        self.ct.record_usage("gpt-4", tokens_in=2000, tokens_out=1000, scope="tenant:globex")
        self.ct.record_usage("gpt-4", tokens_in=300, tokens_out=100, scope="global")
        set_insights_dependencies(self.mc, self.ct)

    def _make_client(self, scopes: list[str], tenant_id: str = "") -> TestClient:
        """Build a TestClient with a JWT carrying specific scopes and tenant."""
        from agent33.main import app

        token = create_access_token("test-user", scopes=scopes, tenant_id=tenant_id)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    def test_nonadmin_scoped_to_own_tenant(self) -> None:
        """A non-admin caller sees only their own tenant's data."""
        client = self._make_client(scopes=["agents:read"], tenant_id="acme")
        resp = client.get("/v1/insights")
        assert resp.status_code == 200
        data = resp.json()
        # Only the tenant:acme record (1000+500 = 1500 tokens)
        assert data["total_tokens"] == 1500

    def test_nonadmin_cannot_view_other_tenant(self) -> None:
        """A non-admin caller gets 403 when requesting a different tenant."""
        client = self._make_client(scopes=["agents:read"], tenant_id="acme")
        resp = client.get("/v1/insights?tenant_id=globex")
        assert resp.status_code == 403
        assert "different tenant" in resp.json()["detail"].lower()

    def test_nonadmin_can_pass_own_tenant_id(self) -> None:
        """A non-admin caller may explicitly pass their own tenant_id."""
        client = self._make_client(scopes=["agents:read"], tenant_id="acme")
        resp = client.get("/v1/insights?tenant_id=acme")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] == 1500

    def test_admin_views_all_tenants(self) -> None:
        """An admin caller with no tenant_id param sees all data."""
        client = self._make_client(scopes=["admin"], tenant_id="acme")
        resp = client.get("/v1/insights")
        assert resp.status_code == 200
        data = resp.json()
        # All records: 1000+500 + 2000+1000 + 300+100 = 4900 tokens
        assert data["total_tokens"] == 4900

    def test_admin_can_filter_any_tenant(self) -> None:
        """An admin caller can request data for any specific tenant."""
        client = self._make_client(scopes=["admin"], tenant_id="acme")
        resp = client.get("/v1/insights?tenant_id=globex")
        assert resp.status_code == 200
        data = resp.json()
        # Only tenant:globex: 2000+1000 = 3000 tokens
        assert data["total_tokens"] == 3000

    def test_nonadmin_no_tenant_sees_unscoped_data(self) -> None:
        """A non-admin caller with empty tenant_id (no tenant) sees all data.

        When the caller's token has no tenant_id, ``_resolve_tenant_id``
        returns None which means no tenant filter is applied.  This is
        the expected behavior for tenantless installations.
        """
        client = self._make_client(scopes=["agents:read"], tenant_id="")
        resp = client.get("/v1/insights")
        assert resp.status_code == 200
        data = resp.json()
        # No tenant filter -> all records included
        assert data["total_tokens"] == 4900

    def test_missing_scope_returns_403(self) -> None:
        """Caller without agents:read scope gets 403."""
        client = self._make_client(scopes=["workflows:read"], tenant_id="acme")
        resp = client.get("/v1/insights")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Architecture & Planning H-03 / M-01: CostTracker bounded records & iter_records()
# ---------------------------------------------------------------------------


class TestCostTrackerMaxRecords:
    """Verify FIFO eviction when max_records is exceeded."""

    def test_eviction_removes_oldest_records(self) -> None:
        """When max_records is exceeded, the oldest records are evicted."""
        ct = CostTracker(
            pricing={"m": {"input": 0.01, "output": 0.01}},
            max_records=3,
        )
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="s1")
        ct.record_usage("m", tokens_in=200, tokens_out=50, scope="s2")
        ct.record_usage("m", tokens_in=300, tokens_out=50, scope="s3")
        # At capacity (3 records)
        assert len(ct._records) == 3

        # Adding a 4th should evict the first
        ct.record_usage("m", tokens_in=400, tokens_out=50, scope="s4")
        assert len(ct._records) == 3
        scopes = [r.scope for r in ct._records]
        assert scopes == ["s2", "s3", "s4"]

    def test_eviction_handles_burst(self) -> None:
        """Multiple records can push past the limit; eviction catches up."""
        ct = CostTracker(
            pricing={"m": {"input": 0.01, "output": 0.01}},
            max_records=2,
        )
        for i in range(10):
            ct.record_usage("m", tokens_in=i * 10, tokens_out=0, scope=f"s{i}")
        assert len(ct._records) == 2
        # Should be the last two
        assert ct._records[0].scope == "s8"
        assert ct._records[1].scope == "s9"

    def test_default_max_records(self) -> None:
        """Default max_records is 100_000."""
        ct = CostTracker()
        assert ct._max_records == 100_000

    def test_max_records_clamped_to_1(self) -> None:
        """max_records < 1 is clamped to 1."""
        ct = CostTracker(max_records=0)
        assert ct._max_records == 1
        ct2 = CostTracker(max_records=-5)
        assert ct2._max_records == 1


class TestCostTrackerIterRecords:
    """Verify the public iter_records() API."""

    def test_iter_records_no_filter(self) -> None:
        """iter_records with no arguments returns all records."""
        ct = CostTracker(pricing={"m": {"input": 0.01, "output": 0.01}})
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="tenant:a")
        ct.record_usage("m", tokens_in=200, tokens_out=50, scope="tenant:b")
        ct.record_usage("m", tokens_in=300, tokens_out=50, scope="global")

        records = ct.iter_records()
        assert len(records) == 3

    def test_iter_records_scope_filter(self) -> None:
        """iter_records filters by scope prefix."""
        ct = CostTracker(pricing={"m": {"input": 0.01, "output": 0.01}})
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="tenant:a")
        ct.record_usage("m", tokens_in=200, tokens_out=50, scope="tenant:a:wf:build")
        ct.record_usage("m", tokens_in=300, tokens_out=50, scope="tenant:b")

        records = ct.iter_records(scope="tenant:a")
        assert len(records) == 2
        assert all(r.scope.startswith("tenant:a") for r in records)

    def test_iter_records_since_filter(self) -> None:
        """iter_records filters by timestamp."""
        ct = CostTracker(pricing={"m": {"input": 0.01, "output": 0.01}})
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="s1")
        # Backdate the first record
        ct._records[0] = UsageRecord(
            model="m",
            tokens_in=100,
            tokens_out=50,
            cost=ct._records[0].cost,
            timestamp=time.time() - 86400 * 10,
            scope="s1",
        )
        ct.record_usage("m", tokens_in=200, tokens_out=50, scope="s2")

        # Only records from the last day
        since = time.time() - 86400
        records = ct.iter_records(since=since)
        assert len(records) == 1
        assert records[0].scope == "s2"

    def test_iter_records_combined_filters(self) -> None:
        """iter_records applies both scope and since filters together."""
        ct = CostTracker(pricing={"m": {"input": 0.01, "output": 0.01}})
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="tenant:a")
        ct.record_usage("m", tokens_in=200, tokens_out=50, scope="tenant:b")
        ct.record_usage("m", tokens_in=300, tokens_out=50, scope="tenant:a")

        # Backdate the first record
        ct._records[0] = UsageRecord(
            model="m",
            tokens_in=100,
            tokens_out=50,
            cost=ct._records[0].cost,
            timestamp=time.time() - 86400 * 10,
            scope="tenant:a",
        )

        since = time.time() - 86400
        records = ct.iter_records(scope="tenant:a", since=since)
        # Only the 3rd record (tenant:a, recent)
        assert len(records) == 1
        assert records[0].tokens_in == 300

    def test_iter_records_returns_list(self) -> None:
        """iter_records returns a list, not a generator."""
        ct = CostTracker(pricing={"m": {"input": 0.01, "output": 0.01}})
        ct.record_usage("m", tokens_in=100, tokens_out=50, scope="s")
        result = ct.iter_records()
        assert isinstance(result, list)

    def test_usage_record_public_type(self) -> None:
        """UsageRecord is a public type and can be constructed."""
        record = UsageRecord(
            model="gpt-4",
            tokens_in=100,
            tokens_out=50,
            cost=0.05,
            timestamp=time.time(),
            scope="global",
        )
        assert record.model == "gpt-4"
        assert record.tokens_in == 100
