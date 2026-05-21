"""Data models for knowledge sources and ingestion records."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    """Supported knowledge source types."""

    RSS = "rss"
    GITHUB = "github"
    WEB = "web"
    LOCAL_FOLDER = "local_folder"


class KnowledgeSource(BaseModel):
    """A registered external knowledge source for scheduled ingestion."""

    id: str  # auto-generated slug
    name: str
    source_type: SourceType
    url: str | None = None  # for rss/github/web
    local_path: str | None = None  # for local_folder
    cron_expression: str = "0 */6 * * *"  # every 6 hours by default
    enabled: bool = True
    last_ingested_at: datetime | None = None
    last_content_hash: str | None = None  # for staleness detection
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str = "system"


class IngestionResult(BaseModel):
    """Outcome of a single knowledge ingestion attempt."""

    source_id: str
    status: Literal["success", "skipped", "error"]
    chunks_ingested: int = 0
    error: str | None = None
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
