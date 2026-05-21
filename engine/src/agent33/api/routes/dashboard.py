"""Dashboard API routes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from agent33.observability.alerts import AlertManager
from agent33.observability.lineage import ExecutionLineage
from agent33.observability.metrics import MetricsCollector

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])
prometheus_router = APIRouter(tags=["dashboard"])

# Module-level singletons; replaced at app startup if needed.
_metrics = MetricsCollector()
_alerts = AlertManager(_metrics)
_lineage = ExecutionLineage()

_DASHBOARD_FILE = "dashboard.html"
_DEFAULT_METRICS: dict[str, Any] = {
    "active_workflows": 0,
    "error_count": 0,
    "token_usage": 0,
    "request_latency": {
        "count": 0,
        "sum": 0.0,
        "avg": 0.0,
        "min": 0.0,
        "max": 0.0,
    },
    "effort_routing_high_effort_total": 0,
}


@lru_cache(maxsize=1)
def _resolve_template_path() -> Path | None:
    module_path = Path(__file__).resolve()
    parents = module_path.parents
    root_like = parents[4] if len(parents) > 4 else Path("/")
    site_pkg_like = parents[3] if len(parents) > 3 else Path("/")
    candidates = [
        root_like / "templates" / _DASHBOARD_FILE,
        site_pkg_like / "templates" / _DASHBOARD_FILE,
        Path.cwd() / "templates" / _DASHBOARD_FILE,
        Path("/app/templates") / _DASHBOARD_FILE,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def set_metrics(collector: MetricsCollector) -> None:
    """Swap the global metrics collector (called during app init)."""
    global _metrics
    _metrics = collector


def set_lineage(lineage: ExecutionLineage) -> None:
    """Swap the global lineage tracker (called during app init)."""
    global _lineage
    _lineage = lineage


def set_alert_manager(manager: AlertManager) -> None:
    """Swap the global alert manager (called during app init)."""
    global _alerts
    _alerts = manager


@router.get("/", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    """Serve the HTML dashboard."""
    template_path = _resolve_template_path()
    if template_path is not None:
        content = template_path.read_text(encoding="utf-8")
    else:
        content = "<html><body><h1>AGENT-33 Dashboard</h1><p>Template not found.</p></body></html>"
    return HTMLResponse(content=content)


@router.get("/metrics")
async def dashboard_metrics() -> dict[str, Any]:
    """Return current metrics summary as JSON."""
    summary = _metrics.get_summary()
    return summary if summary else _DEFAULT_METRICS


@prometheus_router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> PlainTextResponse:
    """Return Prometheus-format metrics for scrape targets."""
    return PlainTextResponse(
        _metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/alerts")
async def dashboard_alerts() -> list[dict[str, Any]]:
    """Return currently triggered alerts."""
    return [alert.__dict__ for alert in _alerts.check_all()]


@router.get("/lineage/{workflow_id}")
async def dashboard_lineage(workflow_id: str) -> list[dict[str, Any]]:
    """Return lineage records for a workflow."""
    records = _lineage.query(workflow_id)
    return [
        {
            "workflow_id": r.workflow_id,
            "step_id": r.step_id,
            "action": r.action,
            "inputs_hash": r.inputs_hash,
            "outputs_hash": r.outputs_hash,
            "parent_id": r.parent_id,
            "timestamp": r.timestamp,
        }
        for r in records
    ]
