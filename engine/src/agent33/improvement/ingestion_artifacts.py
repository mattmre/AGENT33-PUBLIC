"""Frontmatter-backed artifacts for repo-ingestion and remediation work."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_DEFAULT_PLANNING_REFS = (
    "task_plan.md",
    "findings.md",
    "progress.md",
)

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.improvement.repo_ingestion import RepoHarvestRecord


def _new_task_id() -> str:
    return f"ING-{uuid.uuid4().hex[:12]}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "task"


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and markdown body from a task artifact."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError("No YAML frontmatter found (expected --- delimiters)")

    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a YAML mapping")

    return metadata, match.group(2).strip()


class IngestionTaskKind(StrEnum):
    """Supported lightweight task artifact kinds."""

    INGESTION = "ingestion"
    REMEDIATION = "remediation"


class IngestionTaskStatus(StrEnum):
    """Minimal lifecycle states for ingestion artifacts."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    DEFERRED = "deferred"


class IngestionTaskArtifact(BaseModel):
    """Minimal, auditable artifact for repo-ingestion and remediation work."""

    task_id: str = Field(
        default_factory=_new_task_id,
        min_length=1,
        pattern=r"^ING-[A-Za-z0-9-]+$",
    )
    kind: IngestionTaskKind = IngestionTaskKind.INGESTION
    title: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    status: IngestionTaskStatus = IngestionTaskStatus.DRAFT
    target: str = Field(min_length=1)
    summary: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    planning_refs: list[str] = Field(default_factory=list)
    research_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    body: str = ""

    def to_frontmatter(self) -> dict[str, Any]:
        """Return the persisted frontmatter mapping for the artifact."""
        return {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "title": self.title,
            "owner": self.owner,
            "status": self.status.value,
            "target": self.target,
            "summary": self.summary,
            "acceptance_criteria": self.acceptance_criteria,
            "evidence": self.evidence,
            "planning_refs": self.planning_refs,
            "research_refs": self.research_refs,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
        }

    def to_markdown(self) -> str:
        """Serialize the artifact to a markdown file with YAML frontmatter."""
        frontmatter = yaml.safe_dump(
            self.to_frontmatter(),
            sort_keys=False,
            allow_unicode=False,
        ).strip()
        body = self.body.strip()
        if body:
            return f"---\n{frontmatter}\n---\n\n{body}\n"
        return f"---\n{frontmatter}\n---\n"

    @classmethod
    def from_markdown(cls, content: str) -> IngestionTaskArtifact:
        """Parse an artifact from markdown frontmatter content."""
        metadata, body = _parse_frontmatter(content)
        metadata["body"] = body
        return cls.model_validate(metadata)

    @classmethod
    def load(cls, path: Path) -> IngestionTaskArtifact:
        """Load a task artifact from disk."""
        return cls.from_markdown(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        """Persist the artifact to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")

    def suggested_filename(self) -> str:
        """Return a stable markdown filename for the artifact."""
        return f"{_slugify(self.task_id)}-{_slugify(self.target)}.md"


def build_repo_ingestion_task_artifact(
    record: RepoHarvestRecord,
    owner: str,
    *,
    status: IngestionTaskStatus = IngestionTaskStatus.DRAFT,
    planning_refs: list[str] | None = None,
    research_refs: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> IngestionTaskArtifact:
    """Build a default task artifact from a harvested repository record."""
    return IngestionTaskArtifact(
        kind=IngestionTaskKind.INGESTION,
        title=f"Ingest {record.full_name}",
        owner=owner,
        status=status,
        target=record.full_name,
        summary=(
            f"Analyze {record.full_name} from query '{record.source_query}' and record "
            "the adoption decision without duplicating the session planning files."
        ),
        acceptance_criteria=(
            acceptance_criteria
            if acceptance_criteria is not None
            else [
                "Primary source evidence is captured in docs/research.",
                "Adoption recommendations and explicit non-goals are recorded.",
                (
                    "The artifact links back to the repository-root planning files "
                    "task_plan.md, findings.md, and progress.md."
                ),
            ]
        ),
        evidence=[record.url],
        planning_refs=(
            planning_refs if planning_refs is not None else list(_DEFAULT_PLANNING_REFS)
        ),
        research_refs=research_refs if research_refs is not None else [],
        body=(
            "## Source Context\n"
            f"- Query: `{record.source_query}`\n"
            f"- Rank: `{record.rank}`\n"
            f"- Stars: `{record.stars}`\n\n"
            "## Notes\n"
            "- Fill in concrete adoption or remediation notes as the ingestion progresses.\n"
        ),
    )
