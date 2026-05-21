#!/usr/bin/env python3
"""WebSocket streaming load profile script for AGENT-33.

Standalone tool for running WebSocket load tests against a live AGENT-33
server instance.  Reports connection success rate, message latency
percentiles, and throughput statistics.

Usage:
    python scripts/ws-load-profile.py --help
    python scripts/ws-load-profile.py --url ws://localhost:8000 --token <JWT>
    python scripts/ws-load-profile.py --url ws://localhost:8000 --token <JWT> \
        --concurrency 50 --messages 20 --agent-id code-worker

Environment:
    WS_LOAD_URL     Base WebSocket URL (default: ws://localhost:8000)
    WS_LOAD_TOKEN   JWT token for authentication
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field


@dataclass
class ConnectionResult:
    """Result of a single WebSocket connection attempt."""

    connection_id: int
    connected: bool
    connect_latency_ms: float = 0.0
    messages_sent: int = 0
    messages_received: int = 0
    message_latencies_ms: list[float] = field(default_factory=list)
    events_by_type: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class LoadTestReport:
    """Aggregated report from a load test run."""

    concurrency: int
    target_messages: int
    total_connections: int
    successful_connections: int
    failed_connections: int
    total_messages_sent: int
    total_messages_received: int
    connect_latencies_ms: list[float]
    message_latencies_ms: list[float]
    duration_ms: float
    errors: list[str]

    @property
    def connection_success_rate(self) -> float:
        if self.total_connections == 0:
            return 0.0
        return self.successful_connections / self.total_connections * 100

    def format(self) -> str:
        """Format the report as a human-readable string."""
        lines = [
            "",
            "=" * 60,
            "  AGENT-33 WebSocket Load Test Report",
            "=" * 60,
            "",
            f"  Concurrency:         {self.concurrency}",
            f"  Messages/conn:       {self.target_messages}",
            f"  Total duration:      {self.duration_ms:.0f} ms",
            "",
            "  -- Connections --",
            f"  Total:               {self.total_connections}",
            f"  Successful:          {self.successful_connections}",
            f"  Failed:              {self.failed_connections}",
            f"  Success rate:        {self.connection_success_rate:.1f}%",
        ]

        if self.connect_latencies_ms:
            lines += [
                "",
                "  -- Connect Latency --",
                f"  Min:                 {min(self.connect_latencies_ms):.1f} ms",
                f"  Avg:                 {statistics.mean(self.connect_latencies_ms):.1f} ms",
                f"  Median:              {statistics.median(self.connect_latencies_ms):.1f} ms",
                f"  P95:                 {_percentile(self.connect_latencies_ms, 0.95):.1f} ms",
                f"  P99:                 {_percentile(self.connect_latencies_ms, 0.99):.1f} ms",
                f"  Max:                 {max(self.connect_latencies_ms):.1f} ms",
            ]

        lines += [
            "",
            "  -- Messages --",
            f"  Sent:                {self.total_messages_sent}",
            f"  Received:            {self.total_messages_received}",
        ]

        if self.message_latencies_ms:
            throughput = (
                self.total_messages_received / (self.duration_ms / 1000)
                if self.duration_ms > 0
                else 0
            )
            lines += [
                "",
                "  -- Message Latency --",
                f"  Min:                 {min(self.message_latencies_ms):.1f} ms",
                f"  Avg:                 {statistics.mean(self.message_latencies_ms):.1f} ms",
                f"  Median:              {statistics.median(self.message_latencies_ms):.1f} ms",
                f"  P95:                 {_percentile(self.message_latencies_ms, 0.95):.1f} ms",
                f"  P99:                 {_percentile(self.message_latencies_ms, 0.99):.1f} ms",
                f"  Max:                 {max(self.message_latencies_ms):.1f} ms",
                f"  Throughput:          {throughput:.1f} msg/s",
            ]

        if self.errors:
            lines += [
                "",
                f"  -- Errors ({len(self.errors)}) --",
            ]
            # Show first 10 unique errors
            seen: set[str] = set()
            for err in self.errors:
                if err not in seen and len(seen) < 10:
                    seen.add(err)
                    lines.append(f"    - {err}")
            if len(self.errors) > len(seen):
                lines.append(f"    ... and {len(self.errors) - len(seen)} more")

        lines += ["", "=" * 60, ""]
        return "\n".join(lines)


def _percentile(data: list[float], pct: float) -> float:
    """Compute the given percentile from a sorted-on-the-fly list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


async def _run_single_connection(
    url: str,
    token: str,
    agent_id: str,
    connection_id: int,
    message_count: int,
) -> ConnectionResult:
    """Run a single WebSocket connection: connect, send messages, collect events."""
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        return ConnectionResult(
            connection_id=connection_id,
            connected=False,
            error="websockets library not installed",
        )

    result = ConnectionResult(connection_id=connection_id, connected=False)
    ws_url = f"{url}/v1/stream/agent/{agent_id}?token={token}"

    overall_start = time.monotonic()

    try:
        connect_start = time.monotonic()
        async with connect(ws_url) as ws:
            result.connect_latency_ms = (time.monotonic() - connect_start) * 1000
            result.connected = True

            for msg_idx in range(message_count):
                payload = {
                    "input": f"Load test message {msg_idx} from connection {connection_id}",
                    "context": {"connection_id": connection_id, "msg_idx": msg_idx},
                }
                send_start = time.monotonic()
                await ws.send(json.dumps(payload))
                result.messages_sent += 1

                # Read all events until "done"
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        try:
                            event = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            continue

                        result.messages_received += 1
                        event_type = event.get("event", "unknown")
                        result.events_by_type[event_type] = (
                            result.events_by_type.get(event_type, 0) + 1
                        )

                        if event_type == "done":
                            latency_ms = (time.monotonic() - send_start) * 1000
                            result.message_latencies_ms.append(latency_ms)
                            break
                except Exception:
                    # Server may close after done event
                    pass

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    result.duration_ms = (time.monotonic() - overall_start) * 1000
    return result


async def run_load_test(
    url: str,
    token: str,
    agent_id: str,
    concurrency: int,
    messages_per_connection: int,
) -> LoadTestReport:
    """Run a concurrent WebSocket load test and return the report."""
    print(
        f"Starting load test: {concurrency} connections, "
        f"{messages_per_connection} messages each, agent={agent_id}"
    )
    print(f"Target: {url}")
    print()

    start = time.monotonic()

    tasks = [
        _run_single_connection(url, token, agent_id, i, messages_per_connection)
        for i in range(concurrency)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    duration_ms = (time.monotonic() - start) * 1000

    # Aggregate results
    connection_results: list[ConnectionResult] = []
    errors: list[str] = []

    for r in results:
        if isinstance(r, Exception):
            errors.append(f"{type(r).__name__}: {r}")
        elif isinstance(r, ConnectionResult):
            connection_results.append(r)
            if r.error:
                errors.append(r.error)

    connect_latencies = [r.connect_latency_ms for r in connection_results if r.connected]
    all_message_latencies: list[float] = []
    for r in connection_results:
        all_message_latencies.extend(r.message_latencies_ms)

    return LoadTestReport(
        concurrency=concurrency,
        target_messages=messages_per_connection,
        total_connections=len(connection_results),
        successful_connections=sum(1 for r in connection_results if r.connected),
        failed_connections=sum(1 for r in connection_results if not r.connected),
        total_messages_sent=sum(r.messages_sent for r in connection_results),
        total_messages_received=sum(r.messages_received for r in connection_results),
        connect_latencies_ms=connect_latencies,
        message_latencies_ms=all_message_latencies,
        duration_ms=duration_ms,
        errors=errors,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="AGENT-33 WebSocket streaming load profiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("WS_LOAD_URL", "ws://localhost:8000"),
        help="WebSocket base URL (default: ws://localhost:8000 or WS_LOAD_URL env)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("WS_LOAD_TOKEN", ""),
        help="JWT authentication token (or WS_LOAD_TOKEN env)",
    )
    parser.add_argument(
        "--agent-id",
        default="orchestrator",
        help="Agent ID to invoke (default: orchestrator)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent WebSocket connections (default: 10)",
    )
    parser.add_argument(
        "--messages",
        type=int,
        default=1,
        help="Number of messages to send per connection (default: 1)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON instead of human-readable text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the load profiler."""
    args = parse_args(argv)

    if not args.token:
        print(
            "Error: --token is required (or set WS_LOAD_TOKEN environment variable)",
            file=sys.stderr,
        )
        return 1

    report = asyncio.run(
        run_load_test(
            url=args.url,
            token=args.token,
            agent_id=args.agent_id,
            concurrency=args.concurrency,
            messages_per_connection=args.messages,
        )
    )

    if args.json_output:
        output = {
            "concurrency": report.concurrency,
            "target_messages": report.target_messages,
            "total_connections": report.total_connections,
            "successful_connections": report.successful_connections,
            "failed_connections": report.failed_connections,
            "connection_success_rate_pct": round(report.connection_success_rate, 2),
            "total_messages_sent": report.total_messages_sent,
            "total_messages_received": report.total_messages_received,
            "duration_ms": round(report.duration_ms, 1),
            "errors": report.errors[:20],
        }

        if report.connect_latencies_ms:
            output["connect_latency_ms"] = {
                "min": round(min(report.connect_latencies_ms), 1),
                "avg": round(statistics.mean(report.connect_latencies_ms), 1),
                "median": round(statistics.median(report.connect_latencies_ms), 1),
                "p95": round(_percentile(report.connect_latencies_ms, 0.95), 1),
                "p99": round(_percentile(report.connect_latencies_ms, 0.99), 1),
                "max": round(max(report.connect_latencies_ms), 1),
            }

        if report.message_latencies_ms:
            output["message_latency_ms"] = {
                "min": round(min(report.message_latencies_ms), 1),
                "avg": round(statistics.mean(report.message_latencies_ms), 1),
                "median": round(statistics.median(report.message_latencies_ms), 1),
                "p95": round(_percentile(report.message_latencies_ms, 0.95), 1),
                "p99": round(_percentile(report.message_latencies_ms, 0.99), 1),
                "max": round(max(report.message_latencies_ms), 1),
            }

        print(json.dumps(output, indent=2))
    else:
        print(report.format())

    return 0 if report.failed_connections == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
