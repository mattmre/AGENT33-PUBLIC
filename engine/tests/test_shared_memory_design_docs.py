"""Structural validation for P2.3 shared conversation-memory design document."""

from __future__ import annotations

from pathlib import Path

# Resolve the design document relative to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_DOC = _REPO_ROOT / "docs" / "research" / "session104-p23-shared-memory-design.md"

# Required top-level sections that must appear as markdown headings.
_REQUIRED_SECTIONS: list[str] = [
    "Current Memory Model",
    "Multi-Agent Sharing Requirements",
    "Isolation Constraints",
    "Proposed Design",
    "Implementation Boundary",
]


def _read_doc() -> str:
    """Read the design document and return its content."""
    assert _DESIGN_DOC.exists(), f"Design document not found at {_DESIGN_DOC}"
    content = _DESIGN_DOC.read_text(encoding="utf-8")
    assert len(content.strip()) > 0, "Design document is empty"
    return content


def test_design_document_exists_and_non_empty() -> None:
    """The design document file must exist and contain non-trivial content."""
    content = _read_doc()
    # A real design doc should be at least a few hundred characters.
    assert len(content) > 500, (
        f"Design document is suspiciously short ({len(content)} chars); "
        "expected a substantive design document"
    )


def test_design_document_contains_required_sections() -> None:
    """Each required section must appear as a heading in the document."""
    content = _read_doc()
    missing: list[str] = []
    for section in _REQUIRED_SECTIONS:
        # Check for the section title as part of a markdown heading line.
        # Match either "## 1. Current Memory Model" or "## Current Memory Model".
        found = any(
            section.lower() in line.lower()
            for line in content.splitlines()
            if line.strip().startswith("#")
        )
        if not found:
            missing.append(section)
    assert not missing, (
        f"Design document is missing required sections: {missing}. "
        f"Expected headings containing: {_REQUIRED_SECTIONS}"
    )


def test_design_document_has_non_goals_section() -> None:
    """The design document must include a Non-Goals section."""
    content = _read_doc()
    heading_lines = [line for line in content.splitlines() if line.strip().startswith("#")]
    found = any("non-goal" in line.lower() for line in heading_lines)
    assert found, "Design document must include a 'Non-Goals' section"


def test_design_document_references_scaling_primitives() -> None:
    """The design must reference P1.2 distributed lock primitives."""
    content = _read_doc()
    assert "DistributedLock" in content or "distributed lock" in content.lower(), (
        "Design document must reference the P1.2 distributed lock primitives"
    )
    assert "RedisDistributedLock" in content or "redis" in content.lower(), (
        "Design document must reference Redis-based locking from the scaling module"
    )


def test_design_document_addresses_tenant_isolation() -> None:
    """The design must address tenant_id isolation in the memory layer."""
    content = _read_doc()
    assert "tenant_id" in content, "Design document must discuss tenant_id for memory isolation"
    # Must mention the current gap (no tenant_id on MemoryRecord).
    assert "MemoryRecord" in content, (
        "Design document must reference the existing MemoryRecord model"
    )


def test_design_document_defines_namespace_model() -> None:
    """The design must define the memory namespace model."""
    content = _read_doc()
    content_lower = content.lower()
    assert "namespace" in content_lower, (
        "Design document must define a namespace model for shared memory"
    )
    # Check for the three namespace types.
    assert "shared" in content_lower, "Design must define a 'shared' namespace"
    assert "global" in content_lower, "Design must define a 'global' namespace"
    assert "agent" in content_lower, "Design must define an 'agent' namespace"
