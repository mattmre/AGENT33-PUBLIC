"""Tests for skill lifecycle lineage and promotion audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent33.main import app
from agent33.skills.definition import SkillDefinition, SkillStatus
from agent33.skills.lineage import SkillLineageStore, SkillPromotionRequest
from agent33.skills.registry import SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def test_lineage_store_persists_registration_and_promotion(tmp_path: Path) -> None:
    store_path = tmp_path / "lineage.json"
    store = SkillLineageStore(store_path)
    registry = SkillRegistry(lineage_store=store)

    registry.register(
        SkillDefinition(
            name="deploy",
            version="1.2.0",
            status=SkillStatus.EXPERIMENTAL,
            provenance="operator-wizard",
            allowed_tools=["shell"],
        )
    )
    event = registry.promote(
        "deploy",
        SkillPromotionRequest(
            target_status=SkillStatus.ACTIVE,
            actor="reviewer",
            reason="Validated against deployment fixture.",
            evidence=["pytest:engine/tests/test_deploy.py", "review:#123"],
        ),
    )

    assert event is not None
    assert event.from_status == SkillStatus.EXPERIMENTAL
    assert event.to_status == SkillStatus.ACTIVE
    assert registry.get("deploy").status == SkillStatus.ACTIVE  # type: ignore[union-attr]

    reloaded = SkillLineageStore(store_path)
    events = reloaded.events_for("deploy")
    assert [item.action for item in events] == ["register", "promote"]
    assert events[1].evidence == ["pytest:engine/tests/test_deploy.py", "review:#123"]


def test_skill_authoring_promotion_endpoint_records_lineage(client: TestClient) -> None:
    original_registry = getattr(app.state, "skill_registry", None)
    registry = SkillRegistry(lineage_store=SkillLineageStore())
    registry.register(SkillDefinition(name="review", status=SkillStatus.EXPERIMENTAL))
    app.state.skill_registry = registry
    try:
        response = client.post(
            "/v1/skills/authoring/review/promotion",
            json={
                "target_status": "active",
                "actor": "operator",
                "reason": "Focused tests passed and reviewer approved.",
                "evidence": ["pytest:engine/tests/test_skills.py"],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["action"] == "promote"
        assert payload["from_status"] == "experimental"
        assert payload["to_status"] == "active"

        lineage = client.get("/v1/skills/authoring/review/lineage")
        assert lineage.status_code == 200
        events = lineage.json()
        assert [event["action"] for event in events] == ["register", "promote"]
        assert events[1]["actor"] == "operator"
    finally:
        app.state.skill_registry = original_registry


def test_skill_authoring_promotion_endpoint_rejects_missing_skill(client: TestClient) -> None:
    original_registry = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = SkillRegistry(lineage_store=SkillLineageStore())
    try:
        response = client.post(
            "/v1/skills/authoring/missing/promotion",
            json={
                "target_status": "active",
                "actor": "operator",
                "reason": "No registered skill exists.",
            },
        )
        assert response.status_code == 404
    finally:
        app.state.skill_registry = original_registry
