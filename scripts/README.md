# Scripts

Utility scripts for AGENT-33 orchestration maintenance and diagnostics.

## warmup-pin.ps1

Keeps an Ollama model loaded ("hot") in memory by sending periodic requests.

### Purpose

Ollama unloads models from GPU memory after a period of inactivity (default 5 minutes). This script prevents that by:

1. Sending an initial warmup request to load the model
2. Pinging the model at regular intervals to keep it active
3. Logging timestamps and response times for verification

### Usage

```powershell
# Default: 35 minutes, ping every 5 minutes, localhost:11435
.\warmup-pin.ps1

# Custom duration and interval
.\warmup-pin.ps1 -DurationMinutes 60 -PingIntervalMinutes 3

# Different Ollama endpoint or model
.\warmup-pin.ps1 -OllamaUrl "http://localhost:11434" -Model "codellama:7b"
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-OllamaUrl` | `http://localhost:11435` | Ollama API base URL |
| `-Model` | `qwen2.5-coder:14b` | Model name to keep warm |
| `-DurationMinutes` | `35` | Total runtime (30+ for T2 verification) |
| `-PingIntervalMinutes` | `5` | Minutes between keep-alive pings |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success - model stayed hot for the full duration |
| `1` | Failure - connection error or too many failed pings |

### Verification (T2)

To verify the script works correctly:

1. Start Ollama with the target model
2. Run `.\warmup-pin.ps1 -DurationMinutes 35`
3. Observe response times remain low (< 2s) indicating model stays in memory
4. Script exits with code 0 on success

## validate-orchestration.ps1

Validates the orchestration index and cross-references in core documentation.

### Usage

```powershell
# Text output (human-readable)
.\scripts\validate-orchestration.ps1

# JSON output (machine-readable)
.\scripts\validate-orchestration.ps1 -Json

# Custom repo root
.\scripts\validate-orchestration.ps1 -RepoRoot "C:\path\to\repo"
```

### What It Checks

1. **Index File Existence**: Verifies all files listed in `core/ORCHESTRATION_INDEX.md` exist
2. **Cross-Reference Validation**: Checks markdown links `[text](path.md)` in core docs resolve to existing files
3. **Orphaned Files**: Reports `.md` files in `core/` not listed in the orchestration index

### Exit Codes

- `0`: All validations pass (healthy)
- `1`: One or more issues found

### Output Fields (JSON)

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp of validation run |
| `orchestrationIndex` | Path to the index file checked |
| `totalFiles` | Count of files referenced in index |
| `existingFiles` | Count of files that exist |
| `missingFiles` | Array of missing file paths |
| `brokenCrossRefs` | Array of `{source, target}` broken links |
| `orphanedFiles` | Array of files not in index |
| `healthy` | Boolean overall health status |
