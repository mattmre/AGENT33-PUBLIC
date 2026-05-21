# Change Detection Specification

**Status**: Specification  
**Source**: CA-007 (Incrementalist DiffHelper.cs pattern)

## Overview

This document specifies how AGENT-33 detects changes in a Git repository and categorizes them for incremental processing.

## Change Sources

### 1. Staged Changes
Files added to the Git index but not yet committed.

```python
def get_staged_changes(repo: git.Repo) -> Set[Path]:
    """Get files staged for commit."""
    staged = set()
    for item in repo.index.diff("HEAD"):
        staged.add(Path(item.a_path))
    return staged
```

### 2. Unstaged Changes
Modified files in the working directory.

```python
def get_unstaged_changes(repo: git.Repo) -> Set[Path]:
    """Get modified but unstaged files."""
    unstaged = set()
    for item in repo.index.diff(None):  # None = working tree
        unstaged.add(Path(item.a_path))
    # Include untracked files
    for path in repo.untracked_files:
        unstaged.add(Path(path))
    return unstaged
```

### 3. Branch Diff
Changes between current branch and target branch.

```python
def get_branch_diff(
    repo: git.Repo, 
    target_branch: str = "main"
) -> Set[Path]:
    """Get files changed compared to target branch."""
    changed = set()
    target = repo.commit(target_branch)
    current = repo.head.commit
    
    for diff in target.diff(current):
        if diff.a_path:
            changed.add(Path(diff.a_path))
        if diff.b_path:
            changed.add(Path(diff.b_path))
    
    return changed
```

## Aggregation

All change sources are combined into a single deduplicated set:

```python
def detect_all_changes(
    repo_path: str,
    target_branch: str = "main",
    include_staged: bool = True,
    include_unstaged: bool = True,
    include_branch_diff: bool = True
) -> ChangeSet:
    """
    Aggregate changes from all sources.
    
    Returns:
        ChangeSet with deduplicated file paths and metadata
    """
    repo = git.Repo(repo_path)
    all_changes = set()
    
    if include_staged:
        all_changes.update(get_staged_changes(repo))
    
    if include_unstaged:
        all_changes.update(get_unstaged_changes(repo))
    
    if include_branch_diff:
        all_changes.update(get_branch_diff(repo, target_branch))
    
    return ChangeSet(
        files=all_changes,
        repo_root=Path(repo.working_dir),
        target_branch=target_branch,
        head_sha=repo.head.commit.hexsha[:8]
    )
```

## ChangeSet Data Structure

```python
@dataclass
class ChangeSet:
    """Represents detected changes in a repository."""
    files: Set[Path]
    repo_root: Path
    target_branch: str
    head_sha: str
    
    @property
    def count(self) -> int:
        return len(self.files)
    
    def filter_by_glob(self, patterns: List[str]) -> 'ChangeSet':
        """Return subset matching glob patterns."""
        from fnmatch import fnmatch
        filtered = {
            f for f in self.files 
            if any(fnmatch(str(f), p) for p in patterns)
        }
        return ChangeSet(
            files=filtered,
            repo_root=self.repo_root,
            target_branch=self.target_branch,
            head_sha=self.head_sha
        )
    
    def by_extension(self) -> Dict[str, List[Path]]:
        """Group files by extension."""
        groups = {}
        for f in self.files:
            ext = f.suffix or "(no extension)"
            groups.setdefault(ext, []).append(f)
        return groups
```

## Change Categories

Files are categorized for routing:

| Category | Pattern | Handler |
|----------|---------|---------|
| `framework` | `core/prompts/**`, `core/packs/**` | Full refresh |
| `workflow` | `core/workflows/**` | Dependency check |
| `agent` | `core/agents/**`, `core/orchestrator/**` | Dependency check |
| `template` | `core/templates/**` | Dependency check |
| `research` | `core/research/**` | Direct only |
| `collected` | `collected/**` | Read-only (no processing) |

```python
def categorize_changes(changes: ChangeSet) -> Dict[str, Set[Path]]:
    """Categorize changed files by artifact type."""
    categories = {
        "framework": set(),
        "workflow": set(),
        "agent": set(),
        "template": set(),
        "research": set(),
        "collected": set(),
        "other": set()
    }
    
    rules = [
        ("framework", ["core/prompts/**", "core/packs/**"]),
        ("workflow", ["core/workflows/**"]),
        ("agent", ["core/agents/**", "core/orchestrator/**"]),
        ("template", ["core/templates/**"]),
        ("research", ["core/research/**"]),
        ("collected", ["collected/**"]),
    ]
    
    for file in changes.files:
        matched = False
        for category, patterns in rules:
            if any(fnmatch(str(file), p) for p in patterns):
                categories[category].add(file)
                matched = True
                break
        if not matched:
            categories["other"].add(file)
    
    return categories
```

## CLI Integration

```bash
# Detect changes vs main branch
agent-33 detect --target main

# Detect including unstaged
agent-33 detect --target main --include-unstaged

# Output as JSON for pipeline integration
agent-33 detect --target main --format json
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Incremental system overview |
| uses | `../triggers/TRIGGER_CATALOG.md` | Trigger pattern matching |
| uses | `../filters/GLOB_PATTERNS.md` | Glob pattern filtering |
