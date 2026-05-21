# Glob Pattern Syntax

**Status**: Specification  
**Source**: CA-013 (Incrementalist competitive analysis)

## Overview

This document defines the glob pattern syntax used throughout AGENT-33 for artifact filtering, trigger matching, and file selection.

## Pattern Syntax

### Basic Patterns

| Pattern | Matches | Does Not Match |
|---------|---------|----------------|
| `*.md` | `README.md` | `src/README.md` |
| `**/*.md` | `README.md`, `src/doc.md` | `file.txt` |
| `core/*` | `core/README.md` | `core/sub/file.md` |
| `core/**` | `core/README.md`, `core/sub/file.md` | `docs/file.md` |

### Wildcards

| Wildcard | Meaning | Example |
|----------|---------|---------|
| `*` | Any characters in single segment | `*.md` matches `file.md` |
| `**` | Any characters across segments | `**/*.md` matches `a/b/c.md` |
| `?` | Single character | `file?.md` matches `file1.md` |
| `[abc]` | Character class | `file[123].md` matches `file2.md` |
| `[!abc]` | Negated class | `file[!0-9].md` matches `fileA.md` |

### Brace Expansion

| Pattern | Expands To |
|---------|------------|
| `*.{md,txt}` | `*.md`, `*.txt` |
| `{core,docs}/**` | `core/**`, `docs/**` |
| `file{1..3}.md` | `file1.md`, `file2.md`, `file3.md` |

## Implementation

```python
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Set

def glob_match(path: str, pattern: str) -> bool:
    """
    Check if path matches glob pattern.
    
    Handles ** for recursive matching.
    """
    # Normalize separators
    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    
    # Handle ** patterns
    if "**" in pattern:
        # Split on ** and match recursively
        parts = pattern.split("**")
        if len(parts) == 2:
            prefix, suffix = parts
            # Remove leading/trailing slashes
            prefix = prefix.rstrip("/")
            suffix = suffix.lstrip("/")
            
            # Check prefix
            if prefix and not path.startswith(prefix):
                return False
            
            # Check suffix
            if suffix:
                remaining = path[len(prefix):].lstrip("/")
                return any(
                    fnmatch(remaining[i:], suffix)
                    for i in range(len(remaining) + 1)
                    if i == 0 or remaining[i-1] == "/"
                )
            return True
    
    return fnmatch(path, pattern)

def filter_with_globs(
    items: List[str],
    include_patterns: List[str],
    exclude_patterns: List[str]
) -> List[str]:
    """
    Filter items using include/exclude glob patterns.
    
    Phase 1: Include only matching items (whitelist)
    Phase 2: Exclude matching items (blacklist)
    """
    result = items
    
    # Phase 1: Whitelist (if patterns specified)
    if include_patterns:
        result = [
            item for item in result
            if any(glob_match(item, p) for p in include_patterns)
        ]
    
    # Phase 2: Blacklist
    if exclude_patterns:
        result = [
            item for item in result
            if not any(glob_match(item, p) for p in exclude_patterns)
        ]
    
    return result
```

## Common Patterns

### By File Type

```yaml
# All markdown files
include: ["**/*.md"]

# All YAML/JSON config files
include: ["**/*.{yaml,yml,json}"]

# All Python files
include: ["**/*.py"]
```

### By Directory

```yaml
# Core only
include: ["core/**"]

# Exclude collected
exclude: ["collected/**"]

# Specific directories
include: ["core/orchestrator/**", "core/agents/**"]
```

### By Convention

```yaml
# Exclude private files (starting with _)
exclude: ["**/_*"]

# Exclude draft files
exclude: ["**/*.draft.md", "**/*.wip.md"]

# Exclude tests
exclude: ["**/*_test.md", "**/test/**"]
```

### Combined Examples

```yaml
# Process core markdown, exclude READMEs and archived
include: ["core/**/*.md"]
exclude:
  - "**/README.md"
  - "**/archived/**"
  - "**/*.draft.md"

# Orchestrator files only, exclude handoff
include: ["core/orchestrator/**/*.md"]
exclude: ["core/orchestrator/handoff/**"]
```

## Precedence

1. **Exclude wins** - If both include and exclude match, exclude wins
2. **More specific wins** - Longer patterns are more specific
3. **Later wins** - Later patterns in the same list override earlier

## Debugging Patterns

```bash
# Test pattern matching
agent-33 filter --test "core/orchestrator/README.md" \
  --include "core/**/*.md" \
  --exclude "**/README.md"
# Output: EXCLUDED (matched exclude: **/README.md)

# List what would be processed
agent-33 filter --list \
  --include "core/**/*.md" \
  --exclude "**/archived/**"

# Explain matches
agent-33 filter --explain "core/agents/worker.md"
# Output:
# - Matches include: core/**/*.md ✓
# - Does not match exclude: **/archived/** ✓
# - Result: INCLUDED
```

## Performance

For large artifact sets, patterns are optimized:

1. **Compile patterns** - Patterns are compiled once
2. **Directory pruning** - Exclude patterns prune directory traversal
3. **Short-circuit evaluation** - Stop on first match

```python
class CompiledFilter:
    """Pre-compiled filter for performance."""
    
    def __init__(
        self,
        include_patterns: List[str],
        exclude_patterns: List[str]
    ):
        # Pre-compile patterns
        self._include = [re.compile(glob_to_regex(p)) for p in include_patterns]
        self._exclude = [re.compile(glob_to_regex(p)) for p in exclude_patterns]
    
    def matches(self, path: str) -> bool:
        # Short-circuit on exclude
        if any(p.match(path) for p in self._exclude):
            return False
        
        # Check include (if specified)
        if self._include:
            return any(p.match(path) for p in self._include)
        
        return True
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Filters overview |
| used-by | `../triggers/TRIGGER_CATALOG.md` | Trigger patterns |
| used-by | `../incremental/CHANGE_DETECTION.md` | Change filtering |
| used-by | `../../packs/mdc-rules/*.mdc` | Rule globs |
