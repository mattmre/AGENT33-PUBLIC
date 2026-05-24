# AGENT-33 Benchmarks

This directory contains benchmark run metadata for the `main` branch.

## SkillsBench Results

Full SkillsBench results are stored on the [`benchmarks`](https://github.com/mattmre/AGENT33/tree/benchmarks) branch to avoid polluting `main` git history with large JSON files.

### Viewing Results

```bash
# List available runs
git fetch origin benchmarks
git show origin/benchmarks:README.md

# Get the latest baseline
git show origin/benchmarks:baselines/ctrf-baseline-latest.json | agent33 bench report -
```

### Running Benchmarks

```bash
# Full run (requires SkillsBench checkout + live LLM)
agent33 bench run --skillsbench-root ./skillsbench --output ctrf-report.json --model llama3.2

# Quick smoke suite (deterministic, no LLM required)
agent33 bench smoke --output ctrf-smoke.json

# Compare against baseline and emit a GitHub job summary when running in CI
agent33 bench report ctrf-report.json --baseline ctrf-baseline.json --github-step-summary
```

### CI Integration

- **Smoke suite**: Runs on every PR via `benchmark-smoke` CI job (`continue-on-error: true`)
- **Baseline comparison**: Current CTRF artifacts embed overall/task/category regression details in `results.extra.skillsbench.baseline_comparison`
- **PR/check visibility**: `agent33 bench report --github-step-summary` writes a markdown summary for smoke and weekly benchmark jobs
- **Thresholds**: overall pass-rate drop >5pp, task pass-rate drop ≥20pp (one failed trial on the standard 5-trial suite), category drop ≥5pp
- **Full run**: Runs weekly via scheduled workflow; results committed to `benchmarks` branch

### Baseline Files

| File | Description |
|---|---|
| `baselines/ctrf-baseline-latest.json` | Latest committed baseline (from most recent full run) |
| `baselines/ctrf-baseline-YYYY-MM-DD.json` | Historical baselines by date |
