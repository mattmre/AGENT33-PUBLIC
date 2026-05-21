"""Resource manifest repository and search service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agent33.resources.manifest import ResourceKind, ResourceManifest, validate_resource_manifest

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_NAMESPACE = "resources"


class ResourceSubmissionStatus(str):
    PENDING = "pending"
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"


class ResourceSubmission(BaseModel):
    resource_id: str
    manifest: ResourceManifest
    status: str = ResourceSubmissionStatus.PENDING
    reviewer_notes: list[str] = Field(default_factory=list)


class ResourceSearchResult(BaseModel):
    items: list[ResourceManifest] = Field(default_factory=list)
    total: int = 0


class ResourceService:
    """In-memory resource manifest service with optional state persistence."""

    def __init__(
        self,
        manifests: list[ResourceManifest] | None = None,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._manifests: dict[str, ResourceManifest] = {}
        self._submissions: dict[str, ResourceSubmission] = {}
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "resource_service_no_state_store: manifests will not persist across restarts"
            )
        loaded = self._load_state()
        if not loaded:
            # Seed with provided manifests or built-in defaults when no persisted state exists
            for manifest in manifests or _default_manifests():
                self.register(manifest)
            self._persist_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            _NAMESPACE,
            {
                "manifests": [m.model_dump(mode="json") for m in self._manifests.values()],
                "submissions": [s.model_dump(mode="json") for s in self._submissions.values()],
            },
        )

    def _load_state(self) -> bool:
        """Load state from state_store. Returns True if any data was loaded."""
        if self._state_store is None:
            return False
        payload = self._state_store.read_namespace(_NAMESPACE)
        if not payload:
            return False
        loaded_any = False
        for item in payload.get("manifests", []):
            if not isinstance(item, dict):
                continue
            try:
                manifest = ResourceManifest.model_validate(item)
                self._manifests[manifest.id] = manifest
                loaded_any = True
            except Exception as exc:
                logger.warning("resource_manifest_restore_failed: %s", exc)
        for item in payload.get("submissions", []):
            if not isinstance(item, dict):
                continue
            try:
                submission = ResourceSubmission.model_validate(item)
                self._submissions[submission.resource_id] = submission
            except Exception as exc:
                logger.warning("resource_submission_restore_failed: %s", exc)
        return loaded_any

    def register(self, manifest: ResourceManifest) -> ResourceManifest:
        self._manifests[manifest.id] = manifest
        self._persist_state()
        return manifest

    def get(self, resource_id: str) -> ResourceManifest | None:
        return self._manifests.get(resource_id)

    def search(
        self,
        *,
        query: str = "",
        kind: ResourceKind | None = None,
        limit: int = 50,
    ) -> ResourceSearchResult:
        normalized_query = query.strip().lower()
        items = list(self._manifests.values())
        if kind is not None:
            items = [item for item in items if item.kind == kind]
        if normalized_query:
            items = [item for item in items if _matches_query(item, normalized_query)]
        items.sort(key=lambda item: (item.kind.value, item.name.lower()))
        limited = items[: max(1, limit)]
        return ResourceSearchResult(items=limited, total=len(items))

    def validate(self, payload: object) -> ResourceManifest:
        return validate_resource_manifest(payload)

    def submit(self, payload: object) -> ResourceSubmission:
        manifest = self.validate(payload)
        submission = ResourceSubmission(resource_id=manifest.id, manifest=manifest)
        self._submissions[manifest.id] = submission
        self.register(manifest)  # register() calls _persist_state() which also saves submissions
        return submission

    def quarantine(self, resource_id: str, *, note: str = "") -> ResourceSubmission | None:
        submission = self._submissions.get(resource_id)
        manifest = self.get(resource_id)
        if submission is None and manifest is not None:
            submission = ResourceSubmission(resource_id=resource_id, manifest=manifest)
            self._submissions[resource_id] = submission
        if submission is None:
            return None
        submission.status = ResourceSubmissionStatus.QUARANTINED
        if note:
            submission.reviewer_notes.append(note)
        self._persist_state()
        return submission

    def feedback(self, resource_id: str, *, note: str) -> ResourceSubmission | None:
        submission = self._submissions.get(resource_id)
        if submission is None:
            return None
        normalized = note.strip()
        if normalized:
            submission.reviewer_notes.append(normalized)
        self._persist_state()
        return submission


def _matches_query(manifest: ResourceManifest, query: str) -> bool:
    haystack = " ".join(
        [
            manifest.id,
            manifest.name,
            manifest.description,
            manifest.kind.value,
            " ".join(manifest.tags),
        ]
    ).lower()
    return query in haystack


def _default_manifests() -> list[ResourceManifest]:
    return [
        ResourceManifest(
            id="pack.core-ops",
            name="Core Ops Pack",
            version="1.0.0",
            kind=ResourceKind.PACK,
            description="Built-in operational workflows and guardrails.",
            tags=["ops", "built-in"],
        ),
        ResourceManifest(
            id="skill.review-first-pr-slice",
            name="Review First PR Slice",
            version="1.0.0",
            kind=ResourceKind.SKILL,
            description="Review, validate, and merge focused PR slices.",
            tags=["github", "review"],
        ),
    ]


_service = ResourceService()


def set_resource_service(service: ResourceService) -> None:
    global _service  # noqa: PLW0603
    _service = service


def get_resource_service() -> ResourceService:
    return _service
