# Glob-Based Artifact Filtering

**Status**: Specification  
**Source**: CA-013 (Incrementalist GlobFilter.cs pattern)  
**Priority**: Medium

## Overview

Glob-based filtering enables precise control over which artifacts are processed through include and exclude patterns. This follows a two-phase approach: whitelist (include) then blacklist (exclude).

## Entry Points

- `GLOB_PATTERNS.md` - Pattern syntax and examples

## Core Concept

Filtering uses two phases:

```
All Artifacts → Include Filter → Exclude Filter → Final Set
      │               │                │              │
      ▼               ▼                ▼              ▼
   1000           200 match        180 remain      180 process
```

### Phase 1: Include (Whitelist)

If include patterns are specified, only matching artifacts proceed:
- Empty include = include all
- Patterns use OR logic (match any)

### Phase 2: Exclude (Blacklist)

After inclusion, exclude patterns remove artifacts:
- Patterns use OR logic (exclude if any match)
- Exclude overrides include

## Quick Example

```python
from orchestrator.filters import filter_artifacts

artifacts = find_all_artifacts()

filtered = filter_artifacts(
    artifacts,
    include=["core/**/*.md", "docs/**/*.md"],
    exclude=["**/README.md", "**/_*.md"]
)
# Includes all .md in core/ and docs/
# Excludes all README.md and files starting with _
```

## CLI Integration

```bash
# Include specific paths
agent-33 run --include "core/orchestrator/**"

# Exclude patterns
agent-33 run --exclude "**/test/**" --exclude "**/*.draft.md"

# Combine
agent-33 run --include "core/**" --exclude "**/archived/**"
```

## Configuration

```yaml
filters:
  include:
    - "core/**/*.md"
    - "docs/**/*.md"
  exclude:
    - "**/README.md"
    - "**/archived/**"
    - "**/*.draft.md"
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| depends-on | `GLOB_PATTERNS.md` | Pattern syntax |
| uses | `../incremental/CHANGE_DETECTION.md` | Filter changed files |
| implements | CA-013 | Incrementalist competitive analysis |
