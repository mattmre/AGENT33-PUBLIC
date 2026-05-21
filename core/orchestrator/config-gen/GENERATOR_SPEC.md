# Config Generator Specification

**Status**: Specification  
**Source**: CA-016 (Incrementalist competitive analysis)

## Overview

This document specifies the configuration file generation system for AGENT-33.

## Generator Architecture

```
User Input → Collect Answers → Apply Templates → Validate → Write Files
     │              │                │              │            │
     ▼              ▼                ▼              ▼            ▼
  CLI args    Interactive        Jinja2        JSON Schema    Output
              prompts           templates
```

## CLI Interface

### Basic Usage

```bash
# Interactive init (prompts for options)
agent-33 init

# Non-interactive with defaults
agent-33 init --yes

# Specify output directory
agent-33 init --output ./config

# Preview without writing
agent-33 init --dry-run
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--yes` | flag | false | Accept all defaults |
| `--output` | path | `.` | Output directory |
| `--dry-run` | flag | false | Preview only |
| `--only` | list | all | Generate only specific files |
| `--parallel` | flag | false | Enable parallel mode |
| `--parallel-limit` | int | 4 | Parallel limit |
| `--target-branch` | string | main | Git target branch |
| `--format` | string | json | Config format (json/yaml) |

## Interactive Prompts

When not using `--yes`, the generator prompts for configuration:

```
AGENT-33 Configuration Generator
================================

? Project name: my-project
? Target branch for change detection: main
? Enable parallel execution? Yes
? Parallel limit (1-32): 4
? Enable analytics? Yes
? Include VS Code settings? Yes

Generating configuration...
✓ Created agent33.config.json
✓ Created .agent33/triggers.yaml
✓ Created .agent33/filters.yaml
✓ Updated .vscode/settings.json

Configuration complete!
```

## Templates

### Orchestrator Config Template

```python
ORCHESTRATOR_TEMPLATE = {
    "$schema": "./core/schemas/orchestrator.schema.json",
    "version": "1.0",
    "project": {
        "name": "{{ project_name }}",
        "root": ".",
        "target_branch": "{{ target_branch }}"
    },
    "incremental": {
        "enabled": True,
        "include_staged": True,
        "include_unstaged": True,
        "include_branch_diff": True
    },
    "execution": {
        "mode": "{{ 'parallel' if parallel else 'sequential' }}",
        "parallel_limit": "{{ parallel_limit }}",
        "continue_on_error": False,
        "fail_fast": True,
        "timeout_seconds": 3600,
        "task_timeout_seconds": 300
    },
    "filters": {
        "include": ["core/**/*.md", "docs/**/*.md"],
        "exclude": ["**/README.md", "**/archived/**"]
    },
    "analytics": {
        "enabled": "{{ analytics }}",
        "include_timing": True
    },
    "logging": {
        "level": "info",
        "format": "text"
    }
}
```

### Triggers Template

```yaml
# .agent33/triggers.yaml
# Custom trigger definitions for {{ project_name }}

full_refresh_patterns:
  # Add patterns that should trigger full refresh
  - "core/prompts/SYSTEM.md"
  - "core/packs/**"

category_triggers:
  # Add category-specific triggers
  - patterns:
      - "core/orchestrator/**"
    categories:
      - "orchestrator"
```

### Filters Template

```yaml
# .agent33/filters.yaml
# Include/exclude patterns for {{ project_name }}

include:
  - "core/**/*.md"
  - "docs/**/*.md"

exclude:
  - "**/README.md"
  - "**/archived/**"
  - "**/*.draft.md"
  - "**/node_modules/**"
  - "**/.git/**"
```

### VS Code Settings Template

```json
{
  "json.schemas": [
    {
      "fileMatch": ["agent33.config.json"],
      "url": "./core/schemas/orchestrator.schema.json"
    },
    {
      "fileMatch": ["**/agents/*.json"],
      "url": "./core/schemas/agent.schema.json"
    },
    {
      "fileMatch": ["**/workflows/*.json"],
      "url": "./core/schemas/workflow.schema.json"
    }
  ]
}
```

## Implementation

```python
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import yaml

@dataclass
class GeneratorConfig:
    """Configuration for the generator."""
    project_name: str = "my-project"
    target_branch: str = "main"
    parallel: bool = False
    parallel_limit: int = 4
    analytics: bool = True
    include_vscode: bool = True
    output_dir: Path = Path(".")
    format: str = "json"  # json or yaml

class ConfigGenerator:
    """Generates AGENT-33 configuration files."""
    
    def __init__(self, config: GeneratorConfig):
        self.config = config
    
    def generate_all(self, dry_run: bool = False) -> List[Path]:
        """Generate all configuration files."""
        files = []
        
        # Main config
        main_config = self._render_orchestrator_config()
        files.append(self._write_file(
            "agent33.config.json",
            main_config,
            dry_run
        ))
        
        # Triggers
        triggers = self._render_triggers()
        files.append(self._write_file(
            ".agent33/triggers.yaml",
            triggers,
            dry_run,
            format="yaml"
        ))
        
        # Filters
        filters = self._render_filters()
        files.append(self._write_file(
            ".agent33/filters.yaml",
            filters,
            dry_run,
            format="yaml"
        ))
        
        # VS Code settings
        if self.config.include_vscode:
            vscode = self._render_vscode_settings()
            files.append(self._write_file(
                ".vscode/settings.json",
                vscode,
                dry_run
            ))
        
        return files
    
    def _render_orchestrator_config(self) -> Dict[str, Any]:
        """Render main orchestrator configuration."""
        return {
            "$schema": "./core/schemas/orchestrator.schema.json",
            "version": "1.0",
            "project": {
                "name": self.config.project_name,
                "root": ".",
                "target_branch": self.config.target_branch
            },
            "incremental": {
                "enabled": True,
                "include_staged": True,
                "include_unstaged": True,
                "include_branch_diff": True
            },
            "execution": {
                "mode": "parallel" if self.config.parallel else "sequential",
                "parallel_limit": self.config.parallel_limit,
                "continue_on_error": False,
                "fail_fast": True
            },
            "analytics": {
                "enabled": self.config.analytics
            }
        }
    
    def _render_triggers(self) -> Dict[str, Any]:
        """Render triggers configuration."""
        return {
            "full_refresh_patterns": [
                "core/prompts/SYSTEM.md",
                "core/packs/**"
            ],
            "category_triggers": []
        }
    
    def _render_filters(self) -> Dict[str, Any]:
        """Render filters configuration."""
        return {
            "include": [
                "core/**/*.md",
                "docs/**/*.md"
            ],
            "exclude": [
                "**/README.md",
                "**/archived/**"
            ]
        }
    
    def _render_vscode_settings(self) -> Dict[str, Any]:
        """Render VS Code settings."""
        return {
            "json.schemas": [
                {
                    "fileMatch": ["agent33.config.json"],
                    "url": "./core/schemas/orchestrator.schema.json"
                }
            ]
        }
    
    def _write_file(
        self,
        path: str,
        content: Dict[str, Any],
        dry_run: bool,
        format: str = "json"
    ) -> Path:
        """Write file (or preview in dry run mode)."""
        full_path = self.config.output_dir / path
        
        if dry_run:
            print(f"[DRY RUN] Would create: {full_path}")
            return full_path
        
        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content
        with open(full_path, "w") as f:
            if format == "yaml":
                yaml.dump(content, f, default_flow_style=False)
            else:
                json.dump(content, f, indent=2)
        
        print(f"✓ Created {full_path}")
        return full_path
```

## Migration Support

### Upgrade from v0.x

```bash
# Upgrade existing config
agent-33 init --upgrade

# This will:
# 1. Read existing configuration
# 2. Map to new format
# 3. Preserve custom settings
# 4. Add new required fields
# 5. Update schema references
```

### Migration Rules

| Old Field | New Field | Notes |
|-----------|-----------|-------|
| `parallel_limit` | `execution.parallel_limit` | Nested now |
| `timeout` | `execution.timeout_seconds` | Renamed |
| `include` | `filters.include` | Nested now |
| N/A | `analytics.enabled` | New field |

## Validation

Generated configs are validated against schemas:

```python
def validate_generated(config_path: Path, schema_path: Path) -> bool:
    """Validate generated config against schema."""
    import jsonschema
    
    with open(config_path) as f:
        config = json.load(f)
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    try:
        jsonschema.validate(config, schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"Validation failed: {e.message}")
        return False
```

## Relationships

| Type | Target | Notes |
|------|--------|-------|
| parent | `README.md` | Config generation overview |
| uses | `../../schemas/orchestrator.schema.json` | Validation |
| uses | `../triggers/TRIGGER_CATALOG.md` | Default triggers |
| uses | `../filters/GLOB_PATTERNS.md` | Default filters |
