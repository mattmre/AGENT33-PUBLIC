"""Capability catalog — human-readable descriptions for the 25-entry spec taxonomy."""

from __future__ import annotations

from typing import NamedTuple

from agent33.agents.definition import CapabilityCategory, SpecCapability


class CapabilityInfo(NamedTuple):
    """Descriptor for a single spec capability."""

    id: str
    name: str
    description: str
    category: CapabilityCategory


CAPABILITY_CATALOG: dict[SpecCapability, CapabilityInfo] = {
    # --- Planning (P) ---
    SpecCapability.P_01: CapabilityInfo(
        "P-01",
        "Task Decomposition",
        "Break complex tasks into ordered sub-tasks with dependencies.",
        CapabilityCategory.PLANNING,
    ),
    SpecCapability.P_02: CapabilityInfo(
        "P-02",
        "Resource Allocation",
        "Assign agents, models, and compute to sub-tasks.",
        CapabilityCategory.PLANNING,
    ),
    SpecCapability.P_03: CapabilityInfo(
        "P-03",
        "Priority Scheduling",
        "Order execution based on urgency, cost, and dependency graphs.",
        CapabilityCategory.PLANNING,
    ),
    SpecCapability.P_04: CapabilityInfo(
        "P-04",
        "Risk Assessment",
        "Identify failure modes and plan mitigations before execution.",
        CapabilityCategory.PLANNING,
    ),
    SpecCapability.P_05: CapabilityInfo(
        "P-05",
        "Workflow Design",
        "Create and modify DAG workflow definitions.",
        CapabilityCategory.PLANNING,
    ),
    # --- Implementation (I) ---
    SpecCapability.I_01: CapabilityInfo(
        "I-01",
        "Code Generation",
        "Generate source code from specifications or natural language.",
        CapabilityCategory.IMPLEMENTATION,
    ),
    SpecCapability.I_02: CapabilityInfo(
        "I-02",
        "Code Modification",
        "Refactor, fix, or extend existing codebases.",
        CapabilityCategory.IMPLEMENTATION,
    ),
    SpecCapability.I_03: CapabilityInfo(
        "I-03",
        "Configuration Management",
        "Generate and update configuration files and infrastructure.",
        CapabilityCategory.IMPLEMENTATION,
    ),
    SpecCapability.I_04: CapabilityInfo(
        "I-04",
        "Data Transformation",
        "Parse, convert, and reshape data between formats.",
        CapabilityCategory.IMPLEMENTATION,
    ),
    SpecCapability.I_05: CapabilityInfo(
        "I-05",
        "Integration Wiring",
        "Connect APIs, services, and message bus endpoints.",
        CapabilityCategory.IMPLEMENTATION,
    ),
    # --- Verification (V) ---
    SpecCapability.V_01: CapabilityInfo(
        "V-01",
        "Unit Testing",
        "Write and execute unit tests for individual components.",
        CapabilityCategory.VERIFICATION,
    ),
    SpecCapability.V_02: CapabilityInfo(
        "V-02",
        "Integration Testing",
        "Verify interactions between multiple components or services.",
        CapabilityCategory.VERIFICATION,
    ),
    SpecCapability.V_03: CapabilityInfo(
        "V-03",
        "Output Validation",
        "Check that outputs conform to schemas and business rules.",
        CapabilityCategory.VERIFICATION,
    ),
    SpecCapability.V_04: CapabilityInfo(
        "V-04",
        "Security Scanning",
        "Run static analysis and vulnerability checks on code.",
        CapabilityCategory.VERIFICATION,
    ),
    SpecCapability.V_05: CapabilityInfo(
        "V-05",
        "Compliance Checking",
        "Verify outputs meet governance and policy constraints.",
        CapabilityCategory.VERIFICATION,
    ),
    # --- Review (R) ---
    SpecCapability.R_01: CapabilityInfo(
        "R-01",
        "Code Review",
        "Inspect code changes for quality, style, and correctness.",
        CapabilityCategory.REVIEW,
    ),
    SpecCapability.R_02: CapabilityInfo(
        "R-02",
        "Architecture Review",
        "Evaluate design decisions and structural patterns.",
        CapabilityCategory.REVIEW,
    ),
    SpecCapability.R_03: CapabilityInfo(
        "R-03",
        "Documentation Review",
        "Check documentation accuracy, completeness, and clarity.",
        CapabilityCategory.REVIEW,
    ),
    SpecCapability.R_04: CapabilityInfo(
        "R-04",
        "Performance Review",
        "Analyze runtime characteristics and optimisation opportunities.",
        CapabilityCategory.REVIEW,
    ),
    SpecCapability.R_05: CapabilityInfo(
        "R-05",
        "Security Review",
        "Audit code and configuration for security weaknesses.",
        CapabilityCategory.REVIEW,
    ),
    # --- Research (X) ---
    SpecCapability.X_01: CapabilityInfo(
        "X-01",
        "Web Search",
        "Search the web and aggregate information from multiple sources.",
        CapabilityCategory.RESEARCH,
    ),
    SpecCapability.X_02: CapabilityInfo(
        "X-02",
        "Codebase Analysis",
        "Explore and understand existing code repositories.",
        CapabilityCategory.RESEARCH,
    ),
    SpecCapability.X_03: CapabilityInfo(
        "X-03",
        "Literature Survey",
        "Review papers, docs, and technical references on a topic.",
        CapabilityCategory.RESEARCH,
    ),
    SpecCapability.X_04: CapabilityInfo(
        "X-04",
        "Competitive Analysis",
        "Compare tools, frameworks, and approaches for a problem.",
        CapabilityCategory.RESEARCH,
    ),
    SpecCapability.X_05: CapabilityInfo(
        "X-05",
        "Knowledge Synthesis",
        "Combine findings into structured summaries and recommendations.",
        CapabilityCategory.RESEARCH,
    ),
}


def get_catalog_by_category() -> dict[str, list[dict[str, str]]]:
    """Return the full catalog grouped by category for API responses."""
    result: dict[str, list[dict[str, str]]] = {}
    for _cap, info in CAPABILITY_CATALOG.items():
        cat_label = info.category.name.capitalize()
        if cat_label not in result:
            result[cat_label] = []
        result[cat_label].append(
            {
                "id": info.id,
                "name": info.name,
                "description": info.description,
            }
        )
    return result
