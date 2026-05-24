"""Tests for Phase 11 agent registry, capabilities, and search."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.agents.capabilities import CAPABILITY_CATALOG, get_catalog_by_category
from agent33.agents.definition import (
    AgentCadre,
    AgentDefinition,
    AgentRole,
    AgentStatus,
    CapabilityCategory,
    SpecCapability,
)
from agent33.agents.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_DEF = {
    "name": "test-agent",
    "version": "1.0.0",
    "role": "implementer",
    "description": "A test agent",
}

_FULL_DEF = {
    **_MINIMAL_DEF,
    "agent_id": "AGT-099",
    "status": "active",
    "spec_capabilities": ["P-01", "I-01", "V-01"],
    "governance": {
        "scope": "workspace",
        "commands": "test,lint",
        "network": "none",
        "approval_required": ["deploy"],
    },
    "ownership": {
        "owner": "platform-team",
        "escalation_target": "orchestrator",
    },
}


@pytest.fixture()
def registry_with_agents() -> AgentRegistry:
    """Build a registry with several agents for search tests."""
    reg = AgentRegistry()
    agents = [
        {
            "name": "planner",
            "version": "1.0.0",
            "role": "director",
            "agent_id": "AGT-001",
            "spec_capabilities": ["P-01", "P-02", "P-03"],
            "status": "active",
        },
        {
            "name": "coder",
            "version": "1.0.0",
            "role": "implementer",
            "agent_id": "AGT-002",
            "spec_capabilities": ["I-01", "I-02"],
            "status": "active",
        },
        {
            "name": "tester",
            "version": "1.0.0",
            "role": "qa",
            "agent_id": "AGT-003",
            "spec_capabilities": ["V-01", "V-02", "V-03"],
            "status": "active",
        },
        {
            "name": "old-agent",
            "version": "0.1.0",
            "role": "researcher",
            "agent_id": "AGT-004",
            "spec_capabilities": ["X-01"],
            "status": "deprecated",
        },
    ]
    for a in agents:
        reg.register(AgentDefinition.model_validate(a))
    return reg


# ---------------------------------------------------------------------------
# AgentDefinition model tests
# ---------------------------------------------------------------------------


class TestAgentDefinition:
    def test_minimal_definition(self) -> None:
        d = AgentDefinition.model_validate(_MINIMAL_DEF)
        assert d.name == "test-agent"
        assert d.role == AgentRole.IMPLEMENTER
        assert d.agent_id is None
        assert d.spec_capabilities == []
        assert d.status == AgentStatus.ACTIVE

    def test_full_definition(self) -> None:
        d = AgentDefinition.model_validate(_FULL_DEF)
        assert d.agent_id == "AGT-099"
        assert SpecCapability.P_01 in d.spec_capabilities
        assert SpecCapability.I_01 in d.spec_capabilities
        assert d.governance.scope == "workspace"
        assert d.ownership.owner == "platform-team"

    def test_worker_role_maps_to_implementer(self) -> None:
        data = {**_MINIMAL_DEF, "role": "worker"}
        d = AgentDefinition.model_validate(data)
        assert d.role == AgentRole.IMPLEMENTER

    def test_validator_role_maps_to_qa(self) -> None:
        data = {**_MINIMAL_DEF, "role": "validator"}
        d = AgentDefinition.model_validate(data)
        assert d.role == AgentRole.QA

    def test_cadre_profile_is_derived_from_agent_role(self) -> None:
        d = AgentDefinition.model_validate({**_MINIMAL_DEF, "role": "researcher"})

        profile = d.cadre_profile()

        assert profile.cadre == AgentCadre.RESEARCH_INGESTION
        assert profile.label == "Research / Ingestion"
        assert "research memo" in profile.required_artifact.lower()

    def test_load_from_json_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump(_FULL_DEF, f)
            f.flush()
            d = AgentDefinition.load_from_file(f.name)
        assert d.name == "test-agent"
        assert d.agent_id == "AGT-099"

    def test_invalid_agent_id_rejected(self) -> None:
        from pydantic import ValidationError

        data = {**_MINIMAL_DEF, "agent_id": "INVALID"}
        with pytest.raises(ValidationError):
            AgentDefinition.model_validate(data)


# ---------------------------------------------------------------------------
# SpecCapability tests
# ---------------------------------------------------------------------------


class TestSpecCapability:
    def test_category_property(self) -> None:
        assert SpecCapability.P_01.category == CapabilityCategory.PLANNING
        assert SpecCapability.I_03.category == CapabilityCategory.IMPLEMENTATION
        assert SpecCapability.V_05.category == CapabilityCategory.VERIFICATION
        assert SpecCapability.R_02.category == CapabilityCategory.REVIEW
        assert SpecCapability.X_04.category == CapabilityCategory.RESEARCH

    def test_catalog_has_25_entries(self) -> None:
        assert len(CAPABILITY_CATALOG) == 25

    def test_catalog_grouped_by_category(self) -> None:
        grouped = get_catalog_by_category()
        assert len(grouped) == 5
        for category_entries in grouped.values():
            assert len(category_entries) == 5


# ---------------------------------------------------------------------------
# AgentRegistry search tests
# ---------------------------------------------------------------------------


class TestRegistrySearch:
    def test_find_by_role(self, registry_with_agents: AgentRegistry) -> None:
        results = registry_with_agents.find_by_role(AgentRole.DIRECTOR)
        assert len(results) == 1
        assert results[0].name == "planner"

    def test_find_by_spec_capability(self, registry_with_agents: AgentRegistry) -> None:
        results = registry_with_agents.find_by_spec_capability(SpecCapability.V_01)
        assert len(results) == 1
        assert results[0].name == "tester"

    def test_find_by_capability_category(self, registry_with_agents: AgentRegistry) -> None:
        results = registry_with_agents.find_by_capability_category(
            CapabilityCategory.PLANNING,
        )
        assert len(results) == 1
        assert results[0].name == "planner"

    def test_find_by_status(self, registry_with_agents: AgentRegistry) -> None:
        deprecated = registry_with_agents.find_by_status(AgentStatus.DEPRECATED)
        assert len(deprecated) == 1
        assert deprecated[0].name == "old-agent"

    def test_get_by_agent_id(self, registry_with_agents: AgentRegistry) -> None:
        result = registry_with_agents.get_by_agent_id("AGT-002")
        assert result is not None
        assert result.name == "coder"

    def test_get_by_agent_id_not_found(self, registry_with_agents: AgentRegistry) -> None:
        assert registry_with_agents.get_by_agent_id("AGT-999") is None

    def test_multi_criteria_search(self, registry_with_agents: AgentRegistry) -> None:
        results = registry_with_agents.search(
            role=AgentRole.QA,
            status=AgentStatus.ACTIVE,
        )
        assert len(results) == 1
        assert results[0].name == "tester"

    def test_search_no_matches(self, registry_with_agents: AgentRegistry) -> None:
        results = registry_with_agents.search(
            role=AgentRole.SECURITY,
        )
        assert results == []


# ---------------------------------------------------------------------------
# Registry discover from filesystem
# ---------------------------------------------------------------------------


class TestRegistryDiscover:
    def test_discover_loads_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("alpha", "beta"):
                data = {**_MINIMAL_DEF, "name": name}
                (Path(tmpdir) / f"{name}.json").write_text(json.dumps(data))

            reg = AgentRegistry()
            count = reg.discover(tmpdir)
            assert count == 2
            assert reg.get("alpha") is not None
            assert reg.get("beta") is not None

    def test_discover_skips_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "good.json").write_text(json.dumps(_MINIMAL_DEF))
            (Path(tmpdir) / "bad.json").write_text("{invalid json")

            reg = AgentRegistry()
            count = reg.discover(tmpdir)
            assert count == 1

    def test_default_definitions_cover_canonical_core_registry_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        core_registry_doc = repo_root / "core" / "orchestrator" / "AGENT_REGISTRY.md"
        canonical_ids = set(
            re.findall(r"^### (AGT-\d{3}):", core_registry_doc.read_text(encoding="utf-8"), re.M)
        )

        reg = AgentRegistry()
        count = reg.discover(repo_root / "engine" / "agent-definitions")
        loaded_ids = {d.agent_id for d in reg.list_all() if d.agent_id}

        assert count >= len(canonical_ids)
        assert canonical_ids <= loaded_ids

    def test_default_definitions_are_queryable_and_governed(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        reg = AgentRegistry()
        reg.discover(repo_root / "engine" / "agent-definitions")

        for definition in reg.list_all():
            assert definition.agent_id is not None
            assert definition.spec_capabilities
            assert definition.governance.scope
            assert definition.governance.commands
            assert definition.governance.network
            assert definition.ownership.owner
            assert definition.ownership.escalation_target


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestAgentRoutes:
    @pytest.fixture()
    def client(self, registry_with_agents: AgentRegistry) -> TestClient:
        from agent33.main import app
        from agent33.security.auth import create_access_token

        app.state.agent_registry = registry_with_agents
        token = create_access_token("test-user", scopes=["admin"])
        return TestClient(
            app,
            headers={"Authorization": f"Bearer {token}"},
            raise_server_exceptions=False,
        )

    def test_list_agents(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        names = {a["name"] for a in data}
        assert "planner" in names
        assert all("spec_capabilities" in a for a in data)
        planner = next(a for a in data if a["name"] == "planner")
        assert planner["cadre"] == "synthesis_judgment"
        assert planner["cadre_label"] == "Synthesis / Judgment"
        assert planner["cadre_required_artifact"]

    def test_get_agent_includes_visible_cadre_profile(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/coder")

        assert resp.status_code == 200
        profile = resp.json()["cadre_profile"]
        assert profile["cadre"] == "execution_orchestration"
        assert profile["label"] == "Execution / Orchestration"
        assert "Patch summary" in profile["required_artifact"]

    def test_capabilities_catalog(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/capabilities/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5

    def test_search_by_role(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/search", params={"role": "director"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "planner"

    def test_search_filter_parity_for_capability_category_and_status(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get(
            "/v1/agents/search",
            params={
                "role": "qa",
                "spec_capability": "V-02",
                "category": "V",
                "status": "active",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "tester"
        assert data[0]["role"] == "qa"
        assert data[0]["status"] == "active"
        assert "V-02" in data[0]["spec_capabilities"]

    def test_search_invalid_role_returns_422(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/search", params={"role": "nonexistent"})
        assert resp.status_code == 422

    def test_get_agent_by_spec_id(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/by-id/AGT-001")
        assert resp.status_code == 200
        assert resp.json()["name"] == "planner"

    def test_get_agent_by_spec_id_not_found(self, client: TestClient) -> None:
        resp = client.get("/v1/agents/by-id/AGT-999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# invoke_agent definition registry bridge
# ---------------------------------------------------------------------------


class TestInvokeAgentBridge:
    def test_set_definition_registry_fallback(self) -> None:
        from agent33.workflows.actions import invoke_agent as mod

        # Save and clear state
        old_reg = mod._definition_registry
        old_agents = dict(mod._agent_registry)
        mod._agent_registry.clear()

        try:
            mock_def = MagicMock()
            mock_registry = MagicMock()
            mock_registry.get.return_value = mock_def

            mod.set_definition_registry(mock_registry)
            result = mod.get_agent("some-agent")
            assert result is mock_def
            mock_registry.get.assert_called_once_with("some-agent")
        finally:
            mod._definition_registry = old_reg
            mod._agent_registry.update(old_agents)

    def test_explicit_handler_takes_priority(self) -> None:
        from agent33.workflows.actions import invoke_agent as mod

        old_agents = dict(mod._agent_registry)
        try:
            handler = MagicMock()
            mod.register_agent("priority-test", handler)
            assert mod.get_agent("priority-test") is handler
        finally:
            mod._agent_registry.clear()
            mod._agent_registry.update(old_agents)

    def test_missing_agent_raises_key_error(self) -> None:
        from agent33.workflows.actions import invoke_agent as mod

        old_reg = mod._definition_registry
        old_agents = dict(mod._agent_registry)
        mod._agent_registry.clear()
        mod._definition_registry = None

        try:
            with pytest.raises(KeyError):
                mod.get_agent("nonexistent")
        finally:
            mod._definition_registry = old_reg
            mod._agent_registry.update(old_agents)

    @pytest.mark.asyncio
    async def test_execute_routes_definition_only_agent_through_default_bridge(self) -> None:
        from agent33.workflows.actions import invoke_agent as mod

        old_reg = mod._definition_registry
        old_agents = dict(mod._agent_registry)
        mod._agent_registry.clear()

        calls: list[dict[str, object]] = []

        async def default_bridge(inputs: dict[str, object]) -> dict[str, object]:
            calls.append(dict(inputs))
            return {"agent": inputs["agent_name"], "prompt": inputs["prompt"]}

        try:
            reg = AgentRegistry()
            reg.register(
                AgentDefinition.model_validate(
                    {
                        **_MINIMAL_DEF,
                        "name": "registry-only",
                        "agent_id": "AGT-098",
                    }
                )
            )

            mod.set_definition_registry(reg)
            mod.register_agent("__default__", default_bridge)

            result = await mod.execute("registry-only", {"prompt": "hello"})

            assert result == {"agent": "registry-only", "prompt": "hello"}
            assert calls == [{"prompt": "hello", "agent_name": "registry-only"}]
        finally:
            mod._definition_registry = old_reg
            mod._agent_registry.clear()
            mod._agent_registry.update(old_agents)

    @pytest.mark.asyncio
    async def test_workflow_executor_uses_default_bridge_for_registered_definition(
        self,
    ) -> None:
        from agent33.workflows.actions import invoke_agent as mod
        from agent33.workflows.definition import (
            StepAction,
            WorkflowDefinition,
            WorkflowExecution,
            WorkflowStep,
        )
        from agent33.workflows.executor import WorkflowExecutor, WorkflowStatus

        old_reg = mod._definition_registry
        old_agents = dict(mod._agent_registry)
        mod._agent_registry.clear()

        async def default_bridge(inputs: dict[str, object]) -> dict[str, object]:
            return {"agent": inputs["agent_name"], "prompt": inputs["prompt"]}

        try:
            reg = AgentRegistry()
            reg.register(
                AgentDefinition.model_validate(
                    {
                        **_MINIMAL_DEF,
                        "name": "registry-only",
                        "agent_id": "AGT-096",
                    }
                )
            )
            mod.set_definition_registry(reg)
            mod.register_agent("__default__", default_bridge)

            workflow = WorkflowDefinition(
                name="definition-only-workflow",
                version="1.0.0",
                execution=WorkflowExecution(),
                steps=[
                    WorkflowStep(
                        id="invoke",
                        action=StepAction.INVOKE_AGENT,
                        agent="registry-only",
                        inputs={"prompt": "hello"},
                    )
                ],
            )

            result = await WorkflowExecutor(workflow).execute()

            assert result.status == WorkflowStatus.SUCCESS
            assert result.step_results[0].outputs == {
                "agent": "registry-only",
                "prompt": "hello",
            }
        finally:
            mod._definition_registry = old_reg
            mod._agent_registry.clear()
            mod._agent_registry.update(old_agents)

    @pytest.mark.asyncio
    async def test_execute_definition_only_agent_without_bridge_fails_clearly(self) -> None:
        from agent33.workflows.actions import invoke_agent as mod

        old_reg = mod._definition_registry
        old_agents = dict(mod._agent_registry)
        mod._agent_registry.clear()

        try:
            reg = AgentRegistry()
            reg.register(
                AgentDefinition.model_validate(
                    {
                        **_MINIMAL_DEF,
                        "name": "registry-only",
                        "agent_id": "AGT-097",
                    }
                )
            )
            mod.set_definition_registry(reg)

            with pytest.raises(TypeError, match="no executable handler"):
                await mod.execute("registry-only", {"prompt": "hello"})
        finally:
            mod._definition_registry = old_reg
            mod._agent_registry.clear()
            mod._agent_registry.update(old_agents)
