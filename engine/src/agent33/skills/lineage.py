"""Skill lifecycle lineage and promotion audit records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from agent33.skills.definition import SkillDefinition, SkillStatus


class SkillLineageEvent(BaseModel):
    """Audit event for a skill lifecycle transition."""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    skill_name: str
    version: str
    action: str
    from_status: SkillStatus | None = None
    to_status: SkillStatus
    actor: str = "system"
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    source_path: str | None = None
    provenance: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillPromotionRequest(BaseModel):
    """Operator request to promote or demote a registered skill."""

    target_status: SkillStatus = SkillStatus.ACTIVE
    actor: str = Field(default="operator", min_length=1, max_length=120)
    reason: str = Field(..., min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillLineageStore:
    """JSON-backed lineage store for skill lifecycle events."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._events: list[SkillLineageEvent] = []
        if self._path is not None:
            self._load()

    def record_registration(
        self,
        skill: SkillDefinition,
        *,
        previous: SkillDefinition | None = None,
        actor: str = "registry",
        reason: str = "Skill registered in runtime registry.",
    ) -> SkillLineageEvent:
        """Record a registration or replacement event for a skill."""
        return self.record_event(
            skill=skill,
            action="replace" if previous is not None else "register",
            from_status=previous.status if previous is not None else None,
            to_status=skill.status,
            actor=actor,
            reason=reason,
            evidence=_default_skill_evidence(skill),
            metadata={
                "previous_version": previous.version if previous is not None else None,
                "dependencies": [
                    dependency.model_dump(mode="json") for dependency in skill.dependencies
                ],
                "allowed_tools": list(skill.allowed_tools),
                "disallowed_tools": list(skill.disallowed_tools),
            },
        )

    def record_event(
        self,
        *,
        skill: SkillDefinition,
        action: str,
        from_status: SkillStatus | None,
        to_status: SkillStatus,
        actor: str,
        reason: str,
        evidence: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillLineageEvent:
        """Append a lifecycle audit event."""
        event = SkillLineageEvent(
            skill_name=skill.name,
            version=skill.version,
            action=action,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
            evidence=_clean_evidence(evidence or []),
            source_path=_source_path(skill),
            provenance=skill.provenance,
            metadata={key: value for key, value in (metadata or {}).items() if value is not None},
        )
        self._events.append(event)
        self._persist()
        return event

    def events_for(self, skill_name: str) -> list[SkillLineageEvent]:
        """Return all lineage events for one skill in creation order."""
        return [event for event in self._events if event.skill_name == skill_name]

    def list_events(self) -> list[SkillLineageEvent]:
        """Return every recorded event in creation order."""
        return list(self._events)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._events = []
            return
        self._events = [SkillLineageEvent.model_validate(item) for item in payload]

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [event.model_dump(mode="json") for event in self._events]
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _clean_evidence(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _default_skill_evidence(skill: SkillDefinition) -> list[str]:
    evidence = [f"version:{skill.version}", f"status:{skill.status.value}"]
    if skill.base_path is not None:
        evidence.append(f"source:{_source_path(skill)}")
    if skill.provenance:
        evidence.append(f"provenance:{skill.provenance}")
    return evidence


def _source_path(skill: SkillDefinition) -> str | None:
    if skill.base_path is None:
        return None
    return skill.base_path.as_posix()
