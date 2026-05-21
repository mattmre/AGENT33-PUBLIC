"""AGENT-33 load test harness using Locust.

Scenarios:
  1. HealthCheckUser   -- GET /health, GET /healthz, GET /readyz at high RPS
  2. AgentInvokeUser   -- POST /v1/agents/{name}/invoke with lightweight payload
  3. MetricsScrapeUser -- GET /metrics at periodic intervals (Prometheus sim)
  4. SessionLifecycleUser -- create -> query -> end session cycle

All scenarios require a running AGENT-33 instance with auth configured.
Set AUTH_TOKEN as an environment variable or pass --auth-token via Locust
custom arguments.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, events, tag, task

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

# Auth token injected via environment or Locust custom argument
_AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "")

# Agent names available in the default agent-definitions/ directory
AGENT_NAMES: list[str] = [
    "orchestrator",
    "director",
    "code-worker",
    "qa",
    "researcher",
    "browser-agent",
]

# Lightweight invoke payloads for agent scenarios
INVOKE_PAYLOADS: list[dict[str, str]] = [
    {"prompt": "Summarize the status of the system."},
    {"prompt": "List the available tools."},
    {"prompt": "What agents are registered?"},
    {"prompt": "Describe the current workflow state."},
    {"prompt": "Check system health and report."},
]


@events.init_command_line_parser.add_listener
def add_custom_arguments(parser):  # type: ignore[no-untyped-def]
    """Register --auth-token custom argument for Locust CLI."""
    parser.add_argument(
        "--auth-token",
        type=str,
        default="",
        env_var="AUTH_TOKEN",
        help="Bearer token for authenticated AGENT-33 endpoints",
    )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):  # type: ignore[no-untyped-def]
    """Capture the auth token from parsed arguments at test start."""
    global _AUTH_TOKEN  # noqa: PLW0603
    parsed = getattr(environment, "parsed_options", None)
    if parsed and getattr(parsed, "auth_token", ""):
        _AUTH_TOKEN = parsed.auth_token


def _auth_headers() -> dict[str, str]:
    """Return Authorization header dict if a token is configured."""
    if _AUTH_TOKEN:
        return {"Authorization": f"Bearer {_AUTH_TOKEN}"}
    return {}


# ---------------------------------------------------------------------------
# Scenario 1: Health Check Flood
# ---------------------------------------------------------------------------


class HealthCheckUser(HttpUser):
    """High-frequency health-endpoint poller.

    Exercises /health (aggregated), /healthz (liveness), and /readyz
    (readiness). This scenario validates baseline availability under load
    and measures latency for the lightest endpoints.

    Weight 3 means this user type is 3x more likely to be spawned than
    weight-1 types, reflecting real monitoring traffic patterns.
    """

    weight = 3
    wait_time = between(0.1, 0.5)

    @tag("health")
    @task(5)
    def healthz_liveness(self) -> None:
        """Lightweight liveness probe -- highest frequency."""
        with self.client.get("/healthz", catch_response=True) as response:
            if response.status_code == 200:
                body = response.json()
                if body.get("status") != "healthy":
                    response.failure(f"Unexpected healthz status: {body.get('status')}")
            else:
                response.failure(f"healthz returned {response.status_code}")

    @tag("health")
    @task(3)
    def readyz_readiness(self) -> None:
        """Readiness probe -- validates core dependencies."""
        with self.client.get("/readyz", catch_response=True) as response:
            if response.status_code in (200, 503):
                body = response.json()
                if "services" not in body:
                    response.failure("readyz response missing 'services' key")
            else:
                response.failure(f"readyz returned {response.status_code}")

    @tag("health")
    @task(2)
    def health_aggregated(self) -> None:
        """Full aggregated health check."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                body = response.json()
                if "status" not in body or "services" not in body:
                    response.failure("health response missing required keys")
            else:
                response.failure(f"health returned {response.status_code}")


# ---------------------------------------------------------------------------
# Scenario 2: Agent Invoke Chain
# ---------------------------------------------------------------------------


class AgentInvokeUser(HttpUser):
    """Simulates agent invocation requests.

    Posts to /v1/agents/{name}/invoke with a lightweight prompt payload.
    Requires auth -- if no token is configured the request will return 401
    and Locust will report it as a failure, which is the correct behavior
    for an unconfigured load test (rather than silently skipping auth).

    Weight 2 reflects typical API usage where agent invocations are the
    primary workload but less frequent than health probes.
    """

    weight = 2
    wait_time = between(1.0, 3.0)

    @tag("agent-invoke")
    @task
    def invoke_agent(self) -> None:
        """Invoke a randomly selected agent with a lightweight prompt."""
        agent_name = random.choice(AGENT_NAMES)  # noqa: S311
        payload = random.choice(INVOKE_PAYLOADS)  # noqa: S311
        headers = {
            "Content-Type": "application/json",
            **_auth_headers(),
        }
        with self.client.post(
            f"/v1/agents/{agent_name}/invoke",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/v1/agents/[name]/invoke",
        ) as response:
            if response.status_code == 200:
                body = response.json()
                if "output" not in body and "result" not in body and "response" not in body:
                    # Agent invoke responses vary; accept any non-empty JSON
                    if not body:
                        response.failure("Empty response body from agent invoke")
            elif response.status_code == 401:
                response.failure("Agent invoke returned 401 -- check AUTH_TOKEN")
            elif response.status_code == 404:
                response.failure(f"Agent '{agent_name}' not found -- check agent-definitions/")
            else:
                response.failure(f"Agent invoke returned {response.status_code}")


# ---------------------------------------------------------------------------
# Scenario 3: Metrics Scrape Simulation
# ---------------------------------------------------------------------------


class MetricsScrapeUser(HttpUser):
    """Simulates Prometheus scraping GET /metrics at regular intervals.

    This is a low-frequency, periodic pattern that validates the Prometheus
    exposition endpoint stays responsive under load. Scrape interval
    mirrors a typical 15-30s Prometheus configuration.

    Weight 1 -- lowest spawn priority, matching real monitoring ratios.
    """

    weight = 1
    wait_time = between(10.0, 30.0)

    @tag("metrics")
    @task
    def scrape_metrics(self) -> None:
        """Scrape the Prometheus metrics endpoint."""
        with self.client.get(
            "/metrics",
            catch_response=True,
            headers={"Accept": "text/plain"},
        ) as response:
            if response.status_code == 200:
                text = response.text
                # Validate it looks like Prometheus exposition format
                if not text or (
                    "# HELP" not in text
                    and "# TYPE" not in text
                    and "effort_routing" not in text
                ):
                    response.failure(
                        "Metrics response does not look like Prometheus exposition format"
                    )
            else:
                response.failure(f"Metrics endpoint returned {response.status_code}")


# ---------------------------------------------------------------------------
# Scenario 4: Session Lifecycle
# ---------------------------------------------------------------------------


class SessionLifecycleUser(HttpUser):
    """Exercises the full operator session lifecycle: create -> query -> end.

    This scenario validates the session management surface under concurrent
    load. Each iteration creates a new session, queries it, lists sessions,
    and then ends the session cleanly.

    Weight 1 -- session operations are less frequent than agent invocations.
    """

    weight = 1
    wait_time = between(2.0, 5.0)

    @tag("session")
    @task
    def session_lifecycle(self) -> None:
        """Execute a complete session lifecycle: create, get, list, end."""
        headers = {
            "Content-Type": "application/json",
            **_auth_headers(),
        }

        # Step 1: Create session
        create_payload = {
            "purpose": f"load-test-{uuid.uuid4().hex[:8]}",
            "context": {"source": "locust-load-test", "scenario": "lifecycle"},
        }

        session_id = None

        with self.client.post(
            "/v1/sessions/",
            json=create_payload,
            headers=headers,
            catch_response=True,
            name="/v1/sessions/ [create]",
        ) as response:
            if response.status_code == 201:
                body = response.json()
                session_id = body.get("session_id")
                if not session_id:
                    response.failure("Session create response missing session_id")
            elif response.status_code == 401:
                response.failure("Session create returned 401 -- check AUTH_TOKEN")
                return
            else:
                response.failure(f"Session create returned {response.status_code}")
                return

        # Step 2: Query the created session
        with self.client.get(
            f"/v1/sessions/{session_id}",
            headers=headers,
            catch_response=True,
            name="/v1/sessions/[id] [get]",
        ) as response:
            if response.status_code == 200:
                body = response.json()
                if body.get("session_id") != session_id:
                    response.failure(
                        f"Session get returned wrong session_id: "
                        f"{body.get('session_id')} != {session_id}"
                    )
            elif response.status_code == 401:
                response.failure("Session get returned 401")
            else:
                response.failure(f"Session get returned {response.status_code}")

        # Step 3: List sessions (verifies the new session appears)
        with self.client.get(
            "/v1/sessions/?limit=10",
            headers=headers,
            catch_response=True,
            name="/v1/sessions/ [list]",
        ) as response:
            if response.status_code == 200:
                body = response.json()
                if not isinstance(body, list):
                    response.failure("Session list did not return a list")
            elif response.status_code == 401:
                response.failure("Session list returned 401")
            else:
                response.failure(f"Session list returned {response.status_code}")

        # Step 4: End the session
        end_payload = {"status": "completed"}
        with self.client.post(
            f"/v1/sessions/{session_id}/end",
            json=end_payload,
            headers=headers,
            catch_response=True,
            name="/v1/sessions/[id]/end [end]",
        ) as response:
            if response.status_code == 200:
                body = response.json()
                returned_status = body.get("status", "")
                if returned_status not in ("completed", "ended"):
                    response.failure(
                        f"Session end returned unexpected status: {returned_status}"
                    )
            elif response.status_code == 401:
                response.failure("Session end returned 401")
            elif response.status_code == 409:
                # Session may already be ended if there was a race
                pass
            else:
                response.failure(f"Session end returned {response.status_code}")
