"""Claude Code Security adapter for AGENT-33.

Wraps Claude Code Security GitHub Action SARIF output for ingestion into
the component security pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent33.component_security.sarif import SARIFConverter

if TYPE_CHECKING:
    from agent33.component_security.models import SecurityFinding

logger = structlog.get_logger()


class ClaudeSecurityAdapter:
    """Adapter for Claude Code Security GitHub Action output.

    In CI, the ``anthropics/claude-code-action`` action can produce
    SARIF-style output. This adapter ingests that SARIF and converts it to
    SecurityFindings for the AGENT-33 pipeline.

    For local development, use ``ingest_sarif()`` with pre-generated SARIF data.
    """

    def __init__(self) -> None:
        self._converter = SARIFConverter()

    def ingest_sarif(
        self,
        sarif_data: dict[str, Any],
        run_id: str,
    ) -> list[SecurityFinding]:
        """Ingest SARIF data from Claude Code Security and return findings."""
        logger.info(
            "claude_security_ingest",
            run_id=run_id,
            runs=len(sarif_data.get("runs", [])),
        )
        return self._converter.sarif_to_findings(sarif_data, run_id=run_id)

    @staticmethod
    def is_available() -> bool:
        """Check if Claude Code Security output is available.

        Availability is true when CI or a local operator provides a readable
        SARIF artifact path via ``CLAUDE_SECURITY_SARIF_PATH`` or when a common
        GitHub Actions SARIF output exists in the workspace.
        """
        configured_path = os.getenv("CLAUDE_SECURITY_SARIF_PATH", "").strip()
        candidate_paths = [
            Path(configured_path) if configured_path else None,
            Path("claude-code-security.sarif"),
            Path("reports/claude-code-security.sarif"),
            Path("security-results/claude-code-security.sarif"),
        ]
        return any(path is not None and path.is_file() for path in candidate_paths)
