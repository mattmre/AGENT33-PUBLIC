"""Tests for Phase 47 capability pack system.

Covers:
- CapabilityPack model validation and deduplication
- CapabilityPackRegistry CRUD, search, built-in loading
- Compatibility checks (engine version, tools, required/excluded capabilities)
- Pack application and removal (augmentation semantics)
- Cross-pack protection on removal
- API routes (list, search, get, create, update, delete, apply, remove, compat)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.agents.capability_packs import (
    CapabilityPack,
    CapabilityPackRegistry,
    CompatibilityRequirements,
    _parse_version,
    _version_gte,
)
from agent33.agents.definition import AgentDefinition, SpecCapability
from agent33.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent(
    name: str = "test-agent",
    caps: list[str] | None = None,
) -> AgentDefinition:
    data: dict = {
        "name": name,
        "version": "1.0.0",
        "role": "implementer",
        "description": "A test agent",
    }
    if caps:
        data["spec_capabilities"] = caps
    return AgentDefinition.model_validate(data)


@pytest.fixture()
def registry() -> CapabilityPackRegistry:
    """Empty registry (no builtins)."""
    return CapabilityPackRegistry(load_builtins=False)


@pytest.fixture()
def full_registry() -> CapabilityPackRegistry:
    """Registry with built-in packs."""
    return CapabilityPackRegistry(load_builtins=True)


@pytest.fixture()
def sample_pack() -> CapabilityPack:
    return CapabilityPack(
        name="test-pack",
        description="A test pack",
        version="1.0.0",
        capabilities=[SpecCapability.I_01, SpecCapability.I_02],
        tags=["test", "coding"],
        author="tester",
        builtin=False,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestCapabilityPackModel:
    def test_minimal_creation(self) -> None:
        pack = CapabilityPack(
            name="minimal",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
        )
        assert pack.name == "minimal"
        assert pack.version == "1.0.0"
        assert pack.capabilities == [SpecCapability.P_01]
        assert pack.builtin is False

    def test_deduplicates_capabilities(self) -> None:
        pack = CapabilityPack(
            name="dedup-test",
            version="1.0.0",
            capabilities=[SpecCapability.P_01, SpecCapability.P_01, SpecCapability.P_02],
        )
        assert pack.capabilities == [SpecCapability.P_01, SpecCapability.P_02]

    def test_rejects_empty_capabilities(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 -- pydantic ValidationError
            CapabilityPack(name="empty", version="1.0.0", capabilities=[])

    def test_rejects_bad_name(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            CapabilityPack(
                name="Invalid Name",
                version="1.0.0",
                capabilities=[SpecCapability.P_01],
            )

    def test_rejects_bad_version(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            CapabilityPack(
                name="bad-ver",
                version="not-a-version",
                capabilities=[SpecCapability.P_01],
            )

    def test_default_compatibility_requirements(self) -> None:
        pack = CapabilityPack(
            name="defaults",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
        )
        assert pack.compatibility.min_engine_version == "0.1.0"
        assert pack.compatibility.required_tools == []
        assert pack.compatibility.required_capabilities == []
        assert pack.compatibility.excluded_capabilities == []


# ---------------------------------------------------------------------------
# Version comparison tests
# ---------------------------------------------------------------------------


class TestVersionComparison:
    def test_parse_version(self) -> None:
        assert _parse_version("1.2.3") == (1, 2, 3)
        assert _parse_version("0.1.0") == (0, 1, 0)

    def test_parse_invalid_version(self) -> None:
        assert _parse_version("invalid") == (0, 0, 0)
        assert _parse_version("") == (0, 0, 0)

    def test_version_gte_equal(self) -> None:
        assert _version_gte("1.0.0", "1.0.0") is True

    def test_version_gte_greater(self) -> None:
        assert _version_gte("2.0.0", "1.0.0") is True

    def test_version_gte_lesser(self) -> None:
        assert _version_gte("0.1.0", "1.0.0") is False

    def test_version_gte_minor(self) -> None:
        assert _version_gte("1.1.0", "1.0.0") is True
        assert _version_gte("1.0.0", "1.1.0") is False

    def test_version_gte_patch(self) -> None:
        assert _version_gte("1.0.1", "1.0.0") is True
        assert _version_gte("1.0.0", "1.0.1") is False


# ---------------------------------------------------------------------------
# Registry CRUD tests
# ---------------------------------------------------------------------------


class TestCapabilityPackRegistry:
    def test_builtin_packs_loaded(self, full_registry: CapabilityPackRegistry) -> None:
        assert len(full_registry) >= 5
        assert "research-pack" in full_registry
        assert "coding-pack" in full_registry
        assert "operations-pack" in full_registry
        assert "security-pack" in full_registry
        assert "data-pack" in full_registry

    def test_empty_registry(self, registry: CapabilityPackRegistry) -> None:
        assert len(registry) == 0

    def test_register_custom_pack(
        self,
        registry: CapabilityPackRegistry,
        sample_pack: CapabilityPack,
    ) -> None:
        registry.register(sample_pack)
        assert sample_pack.name in registry
        retrieved = registry.get(sample_pack.name)
        assert retrieved is not None
        assert retrieved.name == sample_pack.name
        assert retrieved.capabilities == sample_pack.capabilities

    def test_cannot_replace_builtin(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        override = CapabilityPack(
            name="research-pack",
            version="2.0.0",
            capabilities=[SpecCapability.P_01],
        )
        with pytest.raises(ValueError, match="built-in"):
            full_registry.register(override)

    def test_register_force_replaces_builtin(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        override = CapabilityPack(
            name="research-pack",
            version="2.0.0",
            capabilities=[SpecCapability.P_01],
        )
        full_registry.register_force(override)
        result = full_registry.get("research-pack")
        assert result is not None
        assert result.version == "2.0.0"

    def test_unregister_custom(
        self,
        registry: CapabilityPackRegistry,
        sample_pack: CapabilityPack,
    ) -> None:
        registry.register(sample_pack)
        assert registry.unregister(sample_pack.name) is True
        assert sample_pack.name not in registry

    def test_unregister_nonexistent(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        assert registry.unregister("nonexistent") is False

    def test_unregister_builtin_requires_force(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        with pytest.raises(ValueError, match="built-in"):
            full_registry.unregister("research-pack")

    def test_unregister_builtin_with_force(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        assert full_registry.unregister("research-pack", force=True) is True
        assert "research-pack" not in full_registry

    def test_list_all(self, full_registry: CapabilityPackRegistry) -> None:
        packs = full_registry.list_all()
        assert len(packs) >= 5
        names = [p.name for p in packs]
        assert names == sorted(names)

    def test_list_builtin(self, full_registry: CapabilityPackRegistry) -> None:
        custom = CapabilityPack(
            name="custom-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            builtin=False,
        )
        full_registry.register(custom)
        builtins = full_registry.list_builtin()
        assert all(p.builtin for p in builtins)
        assert "custom-pack" not in [p.name for p in builtins]

    def test_list_custom(self, full_registry: CapabilityPackRegistry) -> None:
        custom = CapabilityPack(
            name="custom-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            builtin=False,
        )
        full_registry.register(custom)
        customs = full_registry.list_custom()
        assert len(customs) == 1
        assert customs[0].name == "custom-pack"

    def test_search_by_name(self, full_registry: CapabilityPackRegistry) -> None:
        results = full_registry.search("research")
        assert any(p.name == "research-pack" for p in results)

    def test_search_by_tag(self, full_registry: CapabilityPackRegistry) -> None:
        results = full_registry.search("security")
        assert any(p.name == "security-pack" for p in results)

    def test_search_by_description(self, full_registry: CapabilityPackRegistry) -> None:
        results = full_registry.search("web search")
        assert len(results) > 0

    def test_search_no_results(self, full_registry: CapabilityPackRegistry) -> None:
        results = full_registry.search("zzz-nonexistent")
        assert len(results) == 0

    def test_get_nonexistent(self, registry: CapabilityPackRegistry) -> None:
        assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Compatibility check tests
# ---------------------------------------------------------------------------


class TestCompatibilityChecks:
    def test_compatible_default(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        result = full_registry.check_compatibility("coding-pack", agent)
        assert result.compatible is True
        assert result.errors == []

    def test_incompatible_engine_version(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="future-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(min_engine_version="99.0.0"),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.check_compatibility("future-pack", agent)
        assert result.compatible is False
        assert any("Engine version" in e for e in result.errors)

    def test_missing_required_tools(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="tool-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(required_tools=["shell", "web_fetch"]),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.check_compatibility("tool-pack", agent, available_tools=["shell"])
        assert result.compatible is False
        assert any("Missing required tools" in e for e in result.errors)

    def test_tools_satisfied(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="tool-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(required_tools=["shell", "web_fetch"]),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.check_compatibility(
            "tool-pack", agent, available_tools=["shell", "web_fetch", "extra"]
        )
        assert result.compatible is True

    def test_missing_required_capabilities(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="dep-pack",
            version="1.0.0",
            capabilities=[SpecCapability.I_02],
            compatibility=CompatibilityRequirements(
                required_capabilities=[SpecCapability.I_01],
            ),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.check_compatibility("dep-pack", agent)
        assert result.compatible is False
        assert any("missing required capability I-01" in e for e in result.errors)

    def test_required_capabilities_satisfied(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="dep-pack",
            version="1.0.0",
            capabilities=[SpecCapability.I_02],
            compatibility=CompatibilityRequirements(
                required_capabilities=[SpecCapability.I_01],
            ),
        )
        registry.register(pack)
        agent = _make_agent(caps=["I-01"])
        result = registry.check_compatibility("dep-pack", agent)
        assert result.compatible is True

    def test_excluded_capability_conflict(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="excl-pack",
            version="1.0.0",
            capabilities=[SpecCapability.V_04],
            compatibility=CompatibilityRequirements(
                excluded_capabilities=[SpecCapability.P_01],
            ),
        )
        registry.register(pack)
        agent = _make_agent(caps=["P-01"])
        result = registry.check_compatibility("excl-pack", agent)
        assert result.compatible is False
        assert any("conflicting capability P-01" in e for e in result.errors)

    def test_overlap_warning(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent(caps=["I-01"])
        result = full_registry.check_compatibility("coding-pack", agent)
        assert result.compatible is True
        assert any("already has capabilities" in w for w in result.warnings)

    def test_nonexistent_pack(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        result = registry.check_compatibility("nonexistent", agent)
        assert result.compatible is False
        assert any("not found" in e for e in result.errors)

    def test_custom_engine_version(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="ver-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(min_engine_version="2.0.0"),
        )
        registry.register(pack)
        agent = _make_agent()
        # Pass a high version -- should be compatible
        result = registry.check_compatibility("ver-pack", agent, engine_version="3.0.0")
        assert result.compatible is True


# ---------------------------------------------------------------------------
# Pack application / removal tests
# ---------------------------------------------------------------------------


class TestPackApplication:
    def test_apply_adds_capabilities(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        assert agent.spec_capabilities == []
        result = full_registry.apply_pack("coding-pack", agent)
        assert result.success is True
        assert len(result.capabilities_added) == 5
        assert "I-01" in result.capabilities_added
        assert "I-02" in result.capabilities_added
        assert "V-01" in result.capabilities_added
        assert "V-02" in result.capabilities_added
        assert "R-01" in result.capabilities_added
        # Verify the agent was actually mutated
        assert SpecCapability.I_01 in agent.spec_capabilities

    def test_apply_skips_existing_capabilities(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent(caps=["I-01", "I-02"])
        result = full_registry.apply_pack("coding-pack", agent)
        assert result.success is True
        assert "I-01" not in result.capabilities_added
        assert "I-02" not in result.capabilities_added
        assert "V-01" in result.capabilities_added
        assert any("Skipped" in w for w in result.warnings)

    def test_apply_nonexistent_pack(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        result = registry.apply_pack("nonexistent", agent)
        assert result.success is False
        assert any("not found" in e for e in result.errors)

    def test_apply_fails_on_incompatible(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="strict-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(min_engine_version="99.0.0"),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.apply_pack("strict-pack", agent)
        assert result.success is False
        assert any("Engine version" in e for e in result.errors)

    def test_apply_with_skip_compat_check(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="strict-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
            compatibility=CompatibilityRequirements(min_engine_version="99.0.0"),
        )
        registry.register(pack)
        agent = _make_agent()
        result = registry.apply_pack("strict-pack", agent, skip_compat_check=True)
        assert result.success is True
        assert "P-01" in result.capabilities_added

    def test_remove_pack(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        full_registry.apply_pack("coding-pack", agent)
        assert len(agent.spec_capabilities) == 5

        result = full_registry.remove_pack("coding-pack", agent)
        assert result.success is True
        assert len(result.capabilities_removed) == 5
        assert agent.spec_capabilities == []

    def test_remove_unapplied_pack(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        result = full_registry.remove_pack("coding-pack", agent)
        assert result.success is False
        assert any("not applied" in e for e in result.errors)

    def test_remove_preserves_shared_capabilities(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        """When two packs share a capability, removing one keeps it."""
        agent = _make_agent()
        # Both coding-pack and data-pack contribute X-02 (Codebase Analysis)?
        # Actually data-pack has X-02 and coding-pack doesn't.
        # Let's use a concrete overlap: V-03 is in both operations-pack and security-pack
        full_registry.apply_pack("operations-pack", agent)
        full_registry.apply_pack("security-pack", agent)

        caps_before = set(agent.spec_capabilities)
        assert SpecCapability.V_03 in caps_before

        result = full_registry.remove_pack("operations-pack", agent)
        assert result.success is True
        # V-03 should be preserved because security-pack also provides it
        assert SpecCapability.V_03 in agent.spec_capabilities
        assert any("Kept" in w for w in result.warnings)

    def test_get_agent_packs(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        full_registry.apply_pack("coding-pack", agent)
        full_registry.apply_pack("research-pack", agent)
        packs = full_registry.get_agent_packs("test-agent")
        assert packs == ["coding-pack", "research-pack"]

    def test_get_pack_agents(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent1 = _make_agent("agent-one")
        agent2 = _make_agent("agent-two")
        full_registry.apply_pack("coding-pack", agent1)
        full_registry.apply_pack("coding-pack", agent2)
        agents = full_registry.get_pack_agents("coding-pack")
        assert agents == ["agent-one", "agent-two"]

    def test_remove_cleans_up_tracking(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        agent = _make_agent()
        full_registry.apply_pack("coding-pack", agent)
        assert full_registry.get_agent_packs("test-agent") == ["coding-pack"]
        full_registry.remove_pack("coding-pack", agent)
        assert full_registry.get_agent_packs("test-agent") == []

    def test_unregister_cleans_up_agent_tracking(
        self,
        registry: CapabilityPackRegistry,
    ) -> None:
        pack = CapabilityPack(
            name="temp-pack",
            version="1.0.0",
            capabilities=[SpecCapability.P_01],
        )
        registry.register(pack)
        agent = _make_agent()
        registry.apply_pack("temp-pack", agent)
        assert registry.get_agent_packs("test-agent") == ["temp-pack"]
        registry.unregister("temp-pack")
        assert registry.get_agent_packs("test-agent") == []


# ---------------------------------------------------------------------------
# Serialization helper tests
# ---------------------------------------------------------------------------


class TestSerializationHelpers:
    def test_to_summary(self, full_registry: CapabilityPackRegistry) -> None:
        pack = full_registry.get("coding-pack")
        assert pack is not None
        summary = full_registry.to_summary(pack)
        assert summary["name"] == "coding-pack"
        assert summary["capabilities_count"] == 5
        assert summary["builtin"] is True
        assert isinstance(summary["capabilities"], list)

    def test_to_detail(self, full_registry: CapabilityPackRegistry) -> None:
        pack = full_registry.get("security-pack")
        assert pack is not None
        detail = full_registry.to_detail(pack)
        assert detail["name"] == "security-pack"
        assert "capability_details" in detail
        assert len(detail["capability_details"]) == 5
        # Each capability detail should have name/description/category
        for cap_detail in detail["capability_details"]:
            assert "id" in cap_detail
            assert "name" in cap_detail
            assert "description" in cap_detail
            assert cap_detail["description"] != ""
        assert "compatibility" in detail
        assert "applied_to_agents" in detail


# ---------------------------------------------------------------------------
# Built-in pack content tests
# ---------------------------------------------------------------------------


class TestBuiltinPacks:
    def test_research_pack_has_all_research_capabilities(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        pack = full_registry.get("research-pack")
        assert pack is not None
        caps = set(pack.capabilities)
        assert SpecCapability.X_01 in caps
        assert SpecCapability.X_02 in caps
        assert SpecCapability.X_03 in caps
        assert SpecCapability.X_04 in caps
        assert SpecCapability.X_05 in caps

    def test_coding_pack_covers_dev_lifecycle(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        pack = full_registry.get("coding-pack")
        assert pack is not None
        caps = set(pack.capabilities)
        assert SpecCapability.I_01 in caps  # Code Generation
        assert SpecCapability.I_02 in caps  # Code Modification
        assert SpecCapability.V_01 in caps  # Unit Testing
        assert SpecCapability.V_02 in caps  # Integration Testing
        assert SpecCapability.R_01 in caps  # Code Review

    def test_security_pack_includes_scanning_and_compliance(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        pack = full_registry.get("security-pack")
        assert pack is not None
        caps = set(pack.capabilities)
        assert SpecCapability.V_04 in caps  # Security Scanning
        assert SpecCapability.V_05 in caps  # Compliance Checking
        assert SpecCapability.R_05 in caps  # Security Review

    def test_all_builtin_packs_are_marked_builtin(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        for pack in full_registry.list_builtin():
            assert pack.builtin is True

    def test_all_builtin_packs_have_tags(
        self,
        full_registry: CapabilityPackRegistry,
    ) -> None:
        for pack in full_registry.list_builtin():
            assert len(pack.tags) > 0, f"Pack {pack.name} has no tags"


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    """Authenticated test client with capability_pack_registry on app.state."""
    from agent33.agents.registry import AgentRegistry
    from agent33.security.auth import create_access_token

    token = create_access_token("test-user", scopes=["admin"])

    # Ensure registries are on app.state
    if not hasattr(app.state, "capability_pack_registry"):
        app.state.capability_pack_registry = CapabilityPackRegistry()

    if not hasattr(app.state, "agent_registry"):
        app.state.agent_registry = AgentRegistry()

    # Register a test agent for apply/remove endpoints
    reg: AgentRegistry = app.state.agent_registry
    if reg.get("test-agent") is None:
        reg.register(
            AgentDefinition.model_validate(
                {
                    "name": "test-agent",
                    "version": "1.0.0",
                    "role": "implementer",
                    "description": "A test agent",
                }
            )
        )

    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestCapabilityPackRoutes:
    def test_list_all_packs(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs")
        assert resp.status_code == 200
        data = resp.json()
        assert "packs" in data
        assert "count" in data
        assert data["count"] >= 5
        names = {p["name"] for p in data["packs"]}
        assert "coding-pack" in names
        assert "research-pack" in names

    def test_list_builtin_only(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs?builtin_only=true")
        assert resp.status_code == 200
        data = resp.json()
        assert all(p["builtin"] for p in data["packs"])

    def test_search_packs(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/search?q=security")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert data["query"] == "security"
        names = {p["name"] for p in data["results"]}
        assert "security-pack" in names

    def test_get_pack_detail(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/coding-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "coding-pack"
        assert "capability_details" in data
        assert len(data["capability_details"]) == 5
        assert data["builtin"] is True

    def test_get_nonexistent_pack(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/nonexistent")
        assert resp.status_code == 404

    def test_create_custom_pack(self, client: TestClient) -> None:
        body = {
            "name": "my-custom-pack",
            "description": "A custom pack for testing",
            "version": "1.0.0",
            "capabilities": ["P-01", "P-02"],
            "tags": ["custom", "planning"],
            "author": "tester",
        }
        resp = client.post("/v1/capability-packs", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-custom-pack"
        assert data["builtin"] is False
        assert len(data["capabilities"]) == 2

    def test_create_duplicate_pack(self, client: TestClient) -> None:
        body = {
            "name": "coding-pack",
            "version": "1.0.0",
            "capabilities": ["P-01"],
        }
        resp = client.post("/v1/capability-packs", json=body)
        assert resp.status_code == 409

    def test_create_pack_invalid_capability(self, client: TestClient) -> None:
        body = {
            "name": "invalid-cap-pack",
            "version": "1.0.0",
            "capabilities": ["INVALID-01"],
        }
        resp = client.post("/v1/capability-packs", json=body)
        assert resp.status_code == 422

    def test_update_custom_pack(self, client: TestClient) -> None:
        # First create the pack
        create_body = {
            "name": "updatable-pack",
            "version": "1.0.0",
            "capabilities": ["P-01"],
            "description": "Original description",
        }
        client.post("/v1/capability-packs", json=create_body)

        update_body = {
            "description": "Updated description",
            "version": "1.1.0",
        }
        resp = client.put("/v1/capability-packs/updatable-pack", json=update_body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated description"
        assert data["version"] == "1.1.0"

    def test_update_builtin_pack_rejected(self, client: TestClient) -> None:
        update_body = {"description": "Hacked"}
        resp = client.put("/v1/capability-packs/coding-pack", json=update_body)
        assert resp.status_code == 403

    def test_delete_custom_pack(self, client: TestClient) -> None:
        create_body = {
            "name": "deletable-pack",
            "version": "1.0.0",
            "capabilities": ["P-01"],
        }
        client.post("/v1/capability-packs", json=create_body)
        resp = client.delete("/v1/capability-packs/deletable-pack")
        assert resp.status_code == 204
        # Verify it's gone
        resp = client.get("/v1/capability-packs/deletable-pack")
        assert resp.status_code == 404

    def test_delete_builtin_without_force(self, client: TestClient) -> None:
        resp = client.delete("/v1/capability-packs/coding-pack")
        assert resp.status_code == 403

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/v1/capability-packs/nonexistent")
        assert resp.status_code == 404

    def test_check_compatibility(self, client: TestClient) -> None:
        body = {"agent_name": "test-agent"}
        resp = client.post(
            "/v1/capability-packs/coding-pack/check-compatibility",
            json=body,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is True
        assert data["pack_name"] == "coding-pack"
        assert data["agent_name"] == "test-agent"

    def test_apply_pack_to_agent(self, client: TestClient) -> None:
        body = {"agent_name": "test-agent"}
        resp = client.post(
            "/v1/capability-packs/research-pack/apply",
            json=body,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["capabilities_added"]) > 0

    def test_apply_nonexistent_agent(self, client: TestClient) -> None:
        body = {"agent_name": "nonexistent-agent"}
        resp = client.post(
            "/v1/capability-packs/coding-pack/apply",
            json=body,
        )
        assert resp.status_code == 404

    def test_remove_pack_from_agent(self, client: TestClient) -> None:
        # First apply
        client.post(
            "/v1/capability-packs/security-pack/apply",
            json={"agent_name": "test-agent"},
        )
        # Then remove
        resp = client.post(
            "/v1/capability-packs/security-pack/remove",
            json={"agent_name": "test-agent"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_list_pack_agents(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/research-pack/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "count" in data
        assert data["pack_name"] == "research-pack"

    def test_list_agent_packs(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/agents/test-agent/packs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "test-agent"
        assert "packs" in data
        assert "count" in data

    def test_list_agent_packs_nonexistent_agent(self, client: TestClient) -> None:
        resp = client.get("/v1/capability-packs/agents/nonexistent-agent/packs")
        assert resp.status_code == 404

    def test_unauthenticated_request(self) -> None:
        unauthenticated = TestClient(app)
        resp = unauthenticated.get("/v1/capability-packs")
        assert resp.status_code == 401
