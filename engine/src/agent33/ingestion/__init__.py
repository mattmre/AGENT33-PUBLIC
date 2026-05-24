"""Ingestion: governed candidate lifecycle for external and community assets.

This module implements AGENT33's candidate asset intake and promotion pipeline.
It is the primary implementation home for the Evolver clean-room adaptation
wave (Sprints 1–5 of the strategic follow-on roadmap).

WHAT THIS MODULE IMPLEMENTS
============================

The ``ingestion`` module manages the lifecycle of assets that originate outside
the AGENT33 first-party pack tree — community submissions, externally sourced
skills, workflows, and tools.  The canonical lifecycle is:

    candidate -> validated -> published -> revoked

Each stage has defined confidence/trust labels, transition rules, and required
operator authorizations.  The governing architectural decisions are:

- **Decision #17** (PHASE-PLAN-POST-P72-2026.md): "Evolver ingestion boundary:
  concept-only clean-room adaptation; do not reuse Evolver code or prose
  directly while license ambiguity or obfuscated-source concerns remain."
- **Decision #18** (PHASE-PLAN-POST-P72-2026.md): "Imported-asset lifecycle:
  ``candidate -> validated -> published -> revoked``, with confidence/trust
  labels layered onto those states."

Full design contract: ``docs/research/evolver-clean-room-guardrails.md``

CLEAN-ROOM RESTRICTION
=======================

**No Evolver-derived code is allowed in this module.**

This module, and all sub-modules under ``agent33.ingestion``, must be
implemented entirely from first principles using AGENT33-native design
decisions.  Specifically:

- No function, class, variable name, or comment may originate from the
  EvoMap/Evolver JavaScript source tree.
- No Evolver protocol prose or documentation text may be reproduced or
  paraphrased in docstrings or comments.
- All design rationale must be citable from AGENT33's own architectural
  decisions (#17, #18) without referencing Evolver as the authority.

This restriction exists because Evolver's repository presents conflicting
license signals (``GPL-3.0`` in package metadata; ``MIT`` in SKILL.md).
Until that inconsistency is resolved upstream, AGENT33 must treat the GPL
constraints as binding and produce only clean-room implementations.

SPRINT ROADMAP
==============

Sprint 0 (current)
    Stub module, ``CandidateAsset`` type model, and guardrails document.

Sprint 1
    Full lifecycle schema: validation rules, non-executability policy,
    provenance and decision journal schema.

Sprint 2
    Intake, validation, publication, and revocation workflows with
    append-only evidence journaling and operator-triggered transitions.

Sprint 3
    Thin coordination boundary (mailbox/heartbeat pilot) with local
    runtime remaining authoritative.

Sprint 4
    Lifecycle verbs (ingest / validate / report / promote / export) as
    first-class API and CLI operations with operator UX surfaces.

Sprint 5
    Detect-only skills doctor with dry-run repair proposals and
    explicit operator-triggered remediation.
"""

from __future__ import annotations

__all__: list[str] = []
