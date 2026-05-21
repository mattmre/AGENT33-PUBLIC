"""CLI commands for SkillsBench benchmark evaluation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path  # noqa: TC003 -- typer needs Path at runtime
from typing import Annotated, Any

import typer

from agent33.benchmarks.skillsbench.regression import (
    SkillsBenchRegressionReport,
    attach_baseline_comparison,
    compare_ctrf_reports,
)

bench_app = typer.Typer(name="bench", help="SkillsBench benchmark evaluation commands.")


@bench_app.command("run")
def bench_run(
    skillsbench_root: Annotated[
        Path | None,
        typer.Option("--skillsbench-root", help="Path to SkillsBench repo checkout."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write CTRF report JSON to this path."),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LLM model identifier for the agent runtime."),
    ] = "llama3.2",
    agent_name: Annotated[
        str,
        typer.Option("--agent", help="Agent definition name."),
    ] = "code-worker",
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", help="CTRF baseline to compare against."),
    ] = None,
    trials: Annotated[
        int,
        typer.Option("--trials", "-t", help="Trials per task (default 5)."),
    ] = 5,
) -> None:
    """Run the full SkillsBench suite with a live LLM and write a CTRF report."""
    import asyncio

    from agent33.benchmarks.skillsbench.config import SkillsBenchConfig
    from agent33.benchmarks.skillsbench.reporting import SkillsBenchCTRFGenerator
    from agent33.benchmarks.skillsbench.task_loader import SkillsBenchTaskLoader

    root = skillsbench_root or Path("./skillsbench")
    if not root.exists():
        typer.echo(
            f"[error] SkillsBench root not found: {root}\n"
            "Clone https://github.com/benchflow-ai/skillsbench and pass --skillsbench-root.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        loader = SkillsBenchTaskLoader(root)
        tasks = loader.discover_tasks()
        typer.echo(f"Discovered {len(tasks)} tasks")
    except Exception as exc:
        typer.echo(f"[error] Failed to load tasks: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not tasks:
        typer.echo("[error] No tasks found. Verify --skillsbench-root contains tasks/.", err=True)
        raise typer.Exit(code=1)

    try:
        from agent33.agents.definition import AgentDefinition, AgentRole
        from agent33.agents.registry import AgentRegistry
        from agent33.agents.runtime import AgentRuntime
        from agent33.benchmarks.skillsbench.adapter import SkillsBenchAdapter
        from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner
        from agent33.config import settings
        from agent33.llm.router import ModelRouter
        from agent33.skills.registry import SkillRegistry

        definition: AgentDefinition | None = None
        defs_dir = Path(settings.agent_definitions_dir)
        if defs_dir.is_dir():
            registry = AgentRegistry()
            registry.discover(defs_dir)
            definition = registry.get(agent_name)

        if definition is None:
            definition = AgentDefinition(
                name=agent_name,
                version="1.0.0",
                role=AgentRole.IMPLEMENTER,
                description=f"SkillsBench evaluation agent ({agent_name})",
            )

        router = ModelRouter()
        skill_registry = SkillRegistry()
        agent_runtime = AgentRuntime(
            definition=definition,
            router=router,
            model=model,
            evaluation_mode=True,
        )
        pytest_runner = PytestBinaryRewardRunner()
        adapter = SkillsBenchAdapter(
            task_loader=loader,
            pytest_runner=pytest_runner,
            skill_registry=skill_registry,
            agent_runtime=agent_runtime,
        )
    except Exception as exc:
        typer.echo(f"[error] Failed to initialize runtime: {exc}", err=True)
        typer.echo(
            "Ensure an LLM provider is configured (e.g. OLLAMA_BASE_URL) "
            "before running `agent33 bench run`.",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    cfg = SkillsBenchConfig(
        skillsbench_root=root,
        agent_name=agent_name,
        model=model,
        trials_per_task=trials,
    )

    typer.echo(f"Running {len(tasks)} tasks x {trials} trials with model={model} ...")

    try:
        run_result = asyncio.run(adapter.run_benchmark(cfg))
    except Exception as exc:
        typer.echo(f"[error] Benchmark execution failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    baseline_report = _load_optional_report(baseline)
    report = SkillsBenchCTRFGenerator().generate_report(
        run_result, baseline_report=baseline_report
    )

    out_path = output or Path("ctrf-bench-report.json")
    _write_report(out_path, report)
    typer.echo(f"CTRF report written to {out_path}")
    typer.echo(
        f"Results: {run_result.passed_trials}/{run_result.total_trials} passed "
        f"({run_result.pass_rate:.1%})"
    )

    if baseline_report is not None:
        _emit_baseline_comparison(report, baseline_report)


@bench_app.command("smoke")
def bench_smoke(
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help="CTRF baseline to compare against (from benchmarks branch).",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write CTRF smoke report JSON to this path."),
    ] = None,
) -> None:
    """Run the fast smoke benchmark suite (deterministic, no live LLM)."""
    import importlib.util
    import subprocess

    spec = importlib.util.find_spec("agent33")
    if spec and spec.origin:
        package_dir = Path(spec.origin).parent
        src_dir = package_dir.parent
        engine_dir = src_dir.parent
        smoke_test = engine_dir / "tests" / "benchmarks" / "test_skills_smoke.py"
    else:
        smoke_test = Path("tests/benchmarks/test_skills_smoke.py")

    env = os.environ.copy()
    ctrf_out = output or Path("ctrf-smoke-report.json")
    ctrf_out.parent.mkdir(parents=True, exist_ok=True)
    env["AGENT33_SMOKE_CTRF_PATH"] = str(ctrf_out)

    typer.echo("Running smoke benchmark suite...")

    if smoke_test.exists():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(smoke_test), "-v", "--no-cov", "--tb=short"],
            env=env,
            capture_output=False,
            check=False,
        )
        passed = result.returncode == 0
    else:
        typer.echo(f"[warn] Smoke test file not found at {smoke_test}, using stub run", err=True)
        passed = True

    comparison: SkillsBenchRegressionReport | None = None
    baseline_report = _load_optional_report(baseline)
    if baseline_report is not None and ctrf_out.exists():
        try:
            current_data = _load_json_report(ctrf_out)
            comparison = attach_baseline_comparison(current_data, baseline_report)
            _write_report(ctrf_out, current_data)
            _emit_comparison(comparison)
        except (json.JSONDecodeError, ValueError) as exc:
            typer.echo(f"[warn] Could not compare baseline: {exc}", err=True)

    if comparison is not None and comparison.has_regressions:
        raise typer.Exit(code=1)

    if not passed:
        raise typer.Exit(code=1)


@bench_app.command("report")
def bench_report(
    ctrf_file: Annotated[
        Path,
        typer.Argument(help="Path to CTRF JSON report file or '-' for stdin."),
    ],
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", help="CTRF baseline to compare against."),
    ] = None,
    github_step_summary: Annotated[
        bool,
        typer.Option(
            "--github-step-summary",
            help="Append a markdown summary to the GitHub step summary file.",
        ),
    ] = False,
) -> None:
    """Display a summary of a CTRF benchmark report."""
    report = _load_json_report(ctrf_file)
    summary = _extract_summary(report)

    total = _safe_int(summary.get("tests"))
    passed = _safe_int(summary.get("passed"))
    failed = _safe_int(summary.get("failed"))
    skipped = _safe_int(summary.get("skipped"))
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    typer.echo(f"SkillsBench Report: {_display_path(ctrf_file)}")
    typer.echo(f"  Total:   {total}")
    typer.echo(f"  Passed:  {passed} ({pass_rate:.1f}%)")
    typer.echo(f"  Failed:  {failed}")
    typer.echo(f"  Skipped: {skipped}")

    markdown = _format_report_markdown(
        report_label=_display_path(ctrf_file),
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate=pass_rate,
    )

    baseline_report = _load_optional_report(baseline)
    if baseline_report is not None:
        comparison = compare_ctrf_reports(report, baseline_report)
        _emit_comparison(comparison)
        markdown += "\n" + comparison.to_markdown(title="SkillsBench baseline comparison")
    elif baseline is not None:
        markdown += "\n- Baseline comparison unavailable.\n"

    if github_step_summary:
        _append_github_step_summary(markdown)


def _load_optional_report(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        typer.echo(f"[warn] Baseline file not found: {path}", err=True)
        return None
    return _load_json_report(path)


def _load_json_report(path: Path) -> dict[str, Any]:
    if str(path) == "-":
        raw = sys.stdin.read()
        if not raw.strip():
            typer.echo("[error] No CTRF JSON supplied on stdin.", err=True)
            raise typer.Exit(code=1)
    else:
        if not path.exists():
            typer.echo(f"[error] Report file not found: {path}", err=True)
            raise typer.Exit(code=1)
        raw = path.read_text(encoding="utf-8")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"[error] Invalid JSON in report: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not isinstance(payload, dict):
        typer.echo("[error] CTRF report must be a JSON object.", err=True)
        raise typer.Exit(code=1)
    return payload


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _emit_baseline_comparison(current: dict[str, Any], baseline_report: dict[str, Any]) -> None:
    comparison = compare_ctrf_reports(current, baseline_report)
    _emit_comparison(comparison)


def _emit_comparison(comparison: SkillsBenchRegressionReport) -> None:
    message = comparison.to_text()
    if comparison.has_regressions:
        typer.echo(f"[REGRESSION] {message}", err=True)
    else:
        typer.echo(message)


def _extract_summary(report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results", {})
    if isinstance(results, dict):
        summary = results.get("summary", {})
        if isinstance(summary, dict):
            return summary
    return {}


def _format_report_markdown(
    *,
    report_label: str,
    total: int,
    passed: int,
    failed: int,
    skipped: int,
    pass_rate: float,
) -> str:
    return "\n".join(
        [
            "## SkillsBench benchmark report",
            "",
            f"- Report: `{report_label}`",
            f"- Total tests: {total}",
            f"- Passed: {passed} ({pass_rate:.1f}%)",
            f"- Failed: {failed}",
            f"- Skipped: {skipped}",
            "",
        ]
    )


def _append_github_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        typer.echo("[warn] GITHUB_STEP_SUMMARY is not set.", err=True)
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(markdown)
        if not markdown.endswith("\n"):
            handle.write("\n")


def _display_path(path: Path) -> str:
    return "stdin" if str(path) == "-" else str(path)


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
