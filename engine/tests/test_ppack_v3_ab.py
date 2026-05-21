"""Tests for P-PACK v3 treatment behavior behind the A/B harness flag."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any
from unittest.mock import MagicMock

from agent33.agents.runtime import AgentRuntime
from agent33.packs.models import InstalledPack, PackSkillEntry, PackStatus
from agent33.packs.sharing import PackShareRequest, PackSharingService


def _make_installed_pack(
    name: str,
    *,
    prompt_addenda: list[str] | None = None,
    tool_config: dict[str, dict[str, Any]] | None = None,
) -> InstalledPack:
    return InstalledPack(
        name=name,
        version="1.0.0",
        description=f"{name} pack",
        author="tester",
        skills=[PackSkillEntry(name="skill-a", path="skills/a")],
        loaded_skill_names=[f"{name}/skill-a"],
        prompt_addenda=prompt_addenda or [],
        tool_config=tool_config or {},
        pack_dir=Path("/tmp/fake-packs") / name,
        status=PackStatus.INSTALLED,
    )


def _make_registry(
    packs: list[InstalledPack] | None = None,
    *,
    ppack_v3_enabled: bool = True,
) -> Any:
    from agent33.packs.provenance_models import PackTrustPolicy
    from agent33.packs.registry import PackRegistry

    registry = PackRegistry.__new__(PackRegistry)
    registry._packs_dir = Path("/tmp/fake-packs")
    registry._skill_registry = MagicMock()
    registry._installed = {}
    registry._enabled = {}
    registry._session_enabled = {}
    registry._session_pack_sources = {}
    registry._session_pack_sequence = {}
    registry._session_activation_counter = {}
    registry._session_tracking_lock = RLock()
    registry._marketplace = None
    registry._trust_policy = PackTrustPolicy()
    registry._trust_policy_manager = None
    registry._ppack_v3_enabled = ppack_v3_enabled

    for pack in packs or []:
        registry._installed[pack.name] = pack

    return registry


def test_ppack_v3_control_variant_keeps_v1_name_sort() -> None:
    alpha = _make_installed_pack("alpha")
    zeta = _make_installed_pack("zeta")
    registry = _make_registry([alpha, zeta], ppack_v3_enabled=True)
    sharing = PackSharingService(registry)

    sharing.apply_shares([PackShareRequest(pack_ref="zeta")], "sess-001")
    registry.enable_for_session("alpha", "sess-001")

    packs = registry.get_session_packs("sess-001", ppack_variant="control")

    assert [pack.name for pack in packs] == ["alpha", "zeta"]


def test_ppack_v3_treatment_orders_shared_before_explicit() -> None:
    alpha = _make_installed_pack("alpha")
    zeta = _make_installed_pack("zeta")
    registry = _make_registry([alpha, zeta], ppack_v3_enabled=True)
    sharing = PackSharingService(registry)

    registry.enable_for_session("alpha", "sess-001")
    sharing.apply_shares([PackShareRequest(pack_ref="zeta")], "sess-001")

    packs = registry.get_session_packs("sess-001", ppack_variant="treatment")

    assert [pack.name for pack in packs] == ["zeta", "alpha"]


def test_ppack_v3_treatment_preserves_share_activation_order() -> None:
    alpha = _make_installed_pack("alpha")
    beta = _make_installed_pack("beta")
    gamma = _make_installed_pack("gamma")
    registry = _make_registry([alpha, beta, gamma], ppack_v3_enabled=True)
    sharing = PackSharingService(registry)

    sharing.apply_shares(
        [
            PackShareRequest(pack_ref="beta"),
            PackShareRequest(pack_ref="alpha"),
        ],
        "sess-001",
    )
    registry.enable_for_session("gamma", "sess-001")

    packs = registry.get_session_packs("sess-001", ppack_variant="treatment")

    assert [pack.name for pack in packs] == ["beta", "alpha", "gamma"]


def test_ppack_v3_treatment_applies_explicit_tool_config_last() -> None:
    shared_pack = _make_installed_pack(
        "shared-pack",
        prompt_addenda=["Shared guidance."],
        tool_config={"shell": {"timeout": 30}, "web_fetch": {"retries": 2}},
    )
    explicit_pack = _make_installed_pack(
        "explicit-pack",
        prompt_addenda=["Explicit operator guidance."],
        tool_config={"shell": {"timeout": 90, "cwd": "/repo"}},
    )
    registry = _make_registry([shared_pack, explicit_pack], ppack_v3_enabled=True)
    sharing = PackSharingService(registry)

    sharing.apply_shares([PackShareRequest(pack_ref="shared-pack")], "sess-001")
    registry.enable_for_session("explicit-pack", "sess-001")

    addenda = registry.get_session_prompt_addenda("sess-001", ppack_variant="treatment")
    config = registry.get_session_tool_config("sess-001", ppack_variant="treatment")

    assert addenda == ["Shared guidance.", "Explicit operator guidance."]
    assert config["shell"]["timeout"] == 90
    assert config["shell"]["cwd"] == "/repo"
    assert config["web_fetch"]["retries"] == 2


def test_runtime_passes_treatment_variant_to_pack_registry() -> None:
    pack_registry = MagicMock()
    pack_registry.get_session_prompt_addenda.return_value = []
    pack_registry.get_session_tool_config.return_value = {}

    runtime = AgentRuntime(
        definition=MagicMock(),
        router=MagicMock(),
        session_id="sess-001",
        pack_registry=pack_registry,
        ppack_variant="treatment",
    )

    runtime._inject_pack_addenda("Base prompt")
    runtime._get_pack_tool_config()

    pack_registry.get_session_prompt_addenda.assert_called_once_with(
        "sess-001",
        ppack_variant="treatment",
    )
    pack_registry.get_session_tool_config.assert_called_once_with(
        "sess-001",
        ppack_variant="treatment",
    )
