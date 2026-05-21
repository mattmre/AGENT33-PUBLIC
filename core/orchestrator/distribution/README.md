# Distribution & Sync

Phase 9 of the AGENT-33 orchestration framework. This module defines how canonical orchestration assets are distributed to downstream repositories and kept in sync.

---

## Documents

| Document | Description |
|----------|-------------|
| [DISTRIBUTION_SYNC_SPEC.md](DISTRIBUTION_SYNC_SPEC.md) | Full specification for sync architecture, rules, validation, conflict resolution, and monitoring |

## Related Docs

| Document | Description |
|----------|-------------|
| [RELEASE_CADENCE.md](../RELEASE_CADENCE.md) | Release cadence, versioning strategy, and rollback procedures |
| [CONTINUOUS_IMPROVEMENT.md](../CONTINUOUS_IMPROVEMENT.md) | Research intake and continuous improvement processes |
| [GENERATOR_SPEC.md](../config-gen/GENERATOR_SPEC.md) | Configuration generation specification |

## Quick Reference

- **Sync direction:** AGENT-33 to downstream only (one-way)
- **Sync rules:** Defined per downstream repo in `rules/` directory
- **Override mechanism:** Downstream customizations go in `.agent33-overrides/`
- **Validation:** Five checks run before every sync PR (checksum, links, schema, secrets, version)
- **Monitoring:** Staleness tracking, drift detection, failure alerts
