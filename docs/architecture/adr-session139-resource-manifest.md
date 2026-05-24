# ADR: Session 139 Resource Manifest

## Status

Accepted

## Context

AGENT33 needs a common shape for installable packs, plugins, skills, workflows, prompts, policies, evals, datasets, and environments before resource discovery and service APIs can be added.

## Decision

Define `ResourceManifest` as the canonical backend schema for installable resources. The schema includes identity, kind, entrypoint, permissions, compatibility, trust metadata, rollback metadata, and normalized tags.

## Consequences

- Resource service APIs can validate manifests before indexing or installation.
- UI and doctor flows can reason about required permissions, compatibility, trust, and rollback without resource-kind-specific parsing.
- Installation remains out of scope for this slice.
