"""Optional OpenTelemetry tracing integration."""

from __future__ import annotations

from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    _HAS_OTEL = True
except ImportError:  # pragma: no cover
    _HAS_OTEL = False


class _NoOpSpan:
    """Lightweight stand-in when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class TracingManager:
    """Thin wrapper around OpenTelemetry tracing.

    Falls back to no-ops if the ``opentelemetry`` package is not installed.
    """

    def __init__(self, service_name: str = "agent33") -> None:
        self._service_name = service_name
        self._spans: dict[str, Any] = {}

        if _HAS_OTEL:
            provider = TracerProvider()
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer(service_name)
        else:
            self._tracer = None

    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Any:
        """Start a new span and return it."""
        if self._tracer is not None:
            span = self._tracer.start_span(name, attributes=attributes or {})
            self._spans[name] = span
            return span

        noop = _NoOpSpan()
        self._spans[name] = noop
        return noop

    def end_span(self, name: str) -> None:
        """End a previously started span by name."""
        span = self._spans.pop(name, None)
        if span is not None:
            span.end()
