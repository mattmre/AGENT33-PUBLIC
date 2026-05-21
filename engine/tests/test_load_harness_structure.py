"""Structural validation for the P1.5 load-test harness.

These tests validate that the load-test harness is correctly structured,
contains the required scenarios, and defines the expected user classes.
They run as part of the standard engine test suite and do not require a
running AGENT-33 instance or Locust execution.

The locustfile is validated via AST parsing rather than runtime import
because locust's gevent monkey-patching interacts badly with pytest's
assertion rewriting on some Python/SSL configurations. AST analysis is
sufficient for structural validation and avoids environmental fragility.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOAD_TESTS_DIR = REPO_ROOT / "load-tests"
SCENARIOS_DIR = LOAD_TESTS_DIR / "scenarios"
PROFILES_DIR = LOAD_TESTS_DIR / "profiles"

EXPECTED_SCENARIO_FILES = ["light.yaml", "standard.yaml", "stress.yaml"]
EXPECTED_USER_CLASSES = [
    "HealthCheckUser",
    "AgentInvokeUser",
    "MetricsScrapeUser",
    "SessionLifecycleUser",
]

# Scenario parameter requirements
REQUIRED_SCENARIO_KEYS = {"users", "spawn-rate", "run-time"}

# Traffic profile per scenario
EXPECTED_SCENARIO_PARAMS = {
    "light.yaml": {"users": 10, "spawn-rate": 2, "run-time": "60s"},
    "standard.yaml": {"users": 50, "spawn-rate": 5, "run-time": "120s"},
    "stress.yaml": {"users": 200, "spawn-rate": 10, "run-time": "180s"},
}


# ---------------------------------------------------------------------------
# AST-based locustfile analysis
# ---------------------------------------------------------------------------


def _parse_locustfile() -> dict[str, Any]:
    """Parse the locustfile via AST and extract structural metadata.

    Returns a dict with:
      - "classes": dict mapping class name -> {
            "bases": list of base class names,
            "methods": list of method names,
            "attributes": dict of name -> value for simple assignments
        }
      - "constants": dict mapping constant name -> value for module-level
        assignments that can be evaluated via ast.literal_eval
      - "source": the raw source text
    """
    locustfile_path = LOAD_TESTS_DIR / "locustfile.py"
    source = locustfile_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(locustfile_path))

    classes: dict[str, dict[str, Any]] = {}
    constants: dict[str, Any] = {}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(ast.dump(base))

            methods: list[str] = []
            attributes: dict[str, Any] = {}

            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    methods.append(item.name)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            try:
                                attributes[target.id] = ast.literal_eval(item.value)
                            except (ValueError, TypeError):
                                # Non-literal value (e.g., function call)
                                attributes[target.id] = "<non-literal>"

            classes[node.name] = {
                "bases": bases,
                "methods": methods,
                "attributes": attributes,
            }

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        constants[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        constants[target.id] = "<non-literal>"

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            # Type-annotated assignments: e.g., AGENT_NAMES: list[str] = [...]
            if node.value is not None:
                try:
                    constants[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    constants[node.target.id] = "<non-literal>"

    return {"classes": classes, "constants": constants, "source": source}


# Module-level cache for parsed locustfile
_parsed_cache: dict[str, Any] | None = None


def _get_parsed() -> dict[str, Any]:
    """Return cached AST parse results for the locustfile."""
    global _parsed_cache  # noqa: PLW0603
    if _parsed_cache is None:
        _parsed_cache = _parse_locustfile()
    return _parsed_cache


# ---------------------------------------------------------------------------
# Directory structure tests
# ---------------------------------------------------------------------------


class TestLoadTestDirectoryStructure:
    """Validate that the load-test directory tree exists with required files."""

    def test_load_tests_directory_exists(self) -> None:
        assert LOAD_TESTS_DIR.is_dir(), f"load-tests/ directory not found at {LOAD_TESTS_DIR}"

    def test_locustfile_exists(self) -> None:
        locustfile = LOAD_TESTS_DIR / "locustfile.py"
        assert locustfile.is_file(), f"locustfile.py not found at {locustfile}"

    def test_scenarios_directory_exists(self) -> None:
        assert SCENARIOS_DIR.is_dir(), f"scenarios/ directory not found at {SCENARIOS_DIR}"

    def test_profiles_directory_exists(self) -> None:
        assert PROFILES_DIR.is_dir(), f"profiles/ directory not found at {PROFILES_DIR}"

    def test_readme_exists(self) -> None:
        readme = LOAD_TESTS_DIR / "README.md"
        assert readme.is_file(), f"README.md not found at {readme}"

    def test_readme_has_meaningful_content(self) -> None:
        readme = LOAD_TESTS_DIR / "README.md"
        content = readme.read_text(encoding="utf-8")
        # Must contain usage instructions, not just a title
        assert len(content) > 500, "README.md is too short to contain real usage instructions"
        assert "locust" in content.lower(), "README.md does not mention locust"
        assert "AUTH_TOKEN" in content, "README.md does not document AUTH_TOKEN configuration"
        assert "scenarios/" in content, "README.md does not reference scenario files"

    def test_baseline_profile_exists(self) -> None:
        profile = PROFILES_DIR / "single-instance-baseline.md"
        assert profile.is_file(), f"single-instance-baseline.md not found at {profile}"

    def test_baseline_profile_has_meaningful_content(self) -> None:
        profile = PROFILES_DIR / "single-instance-baseline.md"
        content = profile.read_text(encoding="utf-8")
        assert len(content) > 1000, "Baseline profile is too short to contain real criteria"
        # Must document acceptance criteria, not just placeholder text
        assert "p95" in content.lower(), "Baseline profile does not mention p95 latency targets"
        assert "healthz" in content.lower(), "Baseline profile does not cover healthz endpoint"
        assert "single-instance" in content.lower() or "single instance" in content.lower(), (
            "Baseline profile does not mention single-instance deployment"
        )


# ---------------------------------------------------------------------------
# Scenario YAML validation tests
# ---------------------------------------------------------------------------


class TestScenarioYAMLFiles:
    """Validate that each scenario YAML file exists and contains required parameters."""

    def test_all_expected_scenario_files_exist(self) -> None:
        for filename in EXPECTED_SCENARIO_FILES:
            path = SCENARIOS_DIR / filename
            assert path.is_file(), f"Expected scenario file not found: {path}"

    def test_light_scenario_is_valid_yaml(self) -> None:
        self._validate_scenario_yaml("light.yaml")

    def test_standard_scenario_is_valid_yaml(self) -> None:
        self._validate_scenario_yaml("standard.yaml")

    def test_stress_scenario_is_valid_yaml(self) -> None:
        self._validate_scenario_yaml("stress.yaml")

    def test_light_scenario_parameters(self) -> None:
        self._validate_scenario_params("light.yaml")

    def test_standard_scenario_parameters(self) -> None:
        self._validate_scenario_params("standard.yaml")

    def test_stress_scenario_parameters(self) -> None:
        self._validate_scenario_params("stress.yaml")

    def test_scenario_progression_users_increase(self) -> None:
        """Verify that user counts increase across light -> standard -> stress."""
        configs = {}
        for filename in EXPECTED_SCENARIO_FILES:
            path = SCENARIOS_DIR / filename
            with open(path, encoding="utf-8") as f:
                configs[filename] = yaml.safe_load(f)

        light_users = configs["light.yaml"]["users"]
        standard_users = configs["standard.yaml"]["users"]
        stress_users = configs["stress.yaml"]["users"]

        assert light_users < standard_users < stress_users, (
            f"User counts should increase: light={light_users}, "
            f"standard={standard_users}, stress={stress_users}"
        )

    def test_scenario_progression_spawn_rates_increase(self) -> None:
        """Verify that spawn rates increase across light -> standard -> stress."""
        configs = {}
        for filename in EXPECTED_SCENARIO_FILES:
            path = SCENARIOS_DIR / filename
            with open(path, encoding="utf-8") as f:
                configs[filename] = yaml.safe_load(f)

        light_rate = configs["light.yaml"]["spawn-rate"]
        standard_rate = configs["standard.yaml"]["spawn-rate"]
        stress_rate = configs["stress.yaml"]["spawn-rate"]

        assert light_rate < standard_rate < stress_rate, (
            f"Spawn rates should increase: light={light_rate}, "
            f"standard={standard_rate}, stress={stress_rate}"
        )

    def _validate_scenario_yaml(self, filename: str) -> None:
        """Parse a scenario YAML and verify it contains required keys."""
        path = SCENARIOS_DIR / filename
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert isinstance(config, dict), f"{filename} did not parse as a YAML mapping"

        missing = REQUIRED_SCENARIO_KEYS - set(config.keys())
        assert not missing, f"{filename} is missing required keys: {missing}"

    def _validate_scenario_params(self, filename: str) -> None:
        """Verify scenario parameters match expected values."""
        path = SCENARIOS_DIR / filename
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        expected = EXPECTED_SCENARIO_PARAMS[filename]
        for key, expected_value in expected.items():
            actual_value = config.get(key)
            assert actual_value == expected_value, (
                f"{filename}: {key} expected {expected_value!r}, got {actual_value!r}"
            )


# ---------------------------------------------------------------------------
# Locustfile structural tests (AST-based)
# ---------------------------------------------------------------------------


class TestLocustfileContent:
    """Validate the locustfile structure via AST parsing.

    These tests use AST analysis to verify the locustfile defines the
    required classes, methods, and constants. This avoids runtime import
    issues caused by locust's gevent monkey-patching conflicting with
    pytest's assertion rewriting.
    """

    def test_locustfile_is_valid_python(self) -> None:
        """Verify the locustfile parses as valid Python without syntax errors."""
        locustfile_path = LOAD_TESTS_DIR / "locustfile.py"
        source = locustfile_path.read_text(encoding="utf-8")
        # ast.parse raises SyntaxError if the file has syntax errors
        tree = ast.parse(source, filename=str(locustfile_path))
        assert tree is not None, "Locustfile did not parse as valid Python"

    def test_locustfile_importable_outside_pytest(self) -> None:
        """Verify the locustfile can be imported in a clean subprocess.

        Runs the import in a subprocess to avoid pytest/gevent conflicts.
        """
        locustfile_path = LOAD_TESTS_DIR / "locustfile.py"
        script = (
            "import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location("
            f"'locustfile', r'{locustfile_path}'); "
            "mod = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(mod); "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.stdout.strip() == "OK", (
            f"Locustfile import failed in subprocess.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_locustfile_defines_all_user_classes(self) -> None:
        """Verify the locustfile defines all four required user classes."""
        parsed = _get_parsed()
        for class_name in EXPECTED_USER_CLASSES:
            assert class_name in parsed["classes"], (
                f"Locustfile does not define user class: {class_name}. "
                f"Found classes: {list(parsed['classes'].keys())}"
            )

    def test_user_classes_inherit_from_http_user(self) -> None:
        """Verify each user class lists HttpUser as a base class."""
        parsed = _get_parsed()
        for class_name in EXPECTED_USER_CLASSES:
            cls_info = parsed["classes"][class_name]
            assert "HttpUser" in cls_info["bases"], (
                f"{class_name} does not inherit from HttpUser. Found bases: {cls_info['bases']}"
            )

    def test_health_check_user_has_tasks(self) -> None:
        """Verify HealthCheckUser defines health check task methods."""
        parsed = _get_parsed()
        methods = parsed["classes"]["HealthCheckUser"]["methods"]
        assert "healthz_liveness" in methods, "HealthCheckUser missing healthz_liveness task"
        assert "readyz_readiness" in methods, "HealthCheckUser missing readyz_readiness task"
        assert "health_aggregated" in methods, "HealthCheckUser missing health_aggregated task"

    def test_agent_invoke_user_has_invoke_task(self) -> None:
        """Verify AgentInvokeUser defines an invoke_agent task method."""
        parsed = _get_parsed()
        methods = parsed["classes"]["AgentInvokeUser"]["methods"]
        assert "invoke_agent" in methods, "AgentInvokeUser missing invoke_agent task"

    def test_metrics_scrape_user_has_scrape_task(self) -> None:
        """Verify MetricsScrapeUser defines a scrape_metrics task method."""
        parsed = _get_parsed()
        methods = parsed["classes"]["MetricsScrapeUser"]["methods"]
        assert "scrape_metrics" in methods, "MetricsScrapeUser missing scrape_metrics task"

    def test_session_lifecycle_user_has_lifecycle_task(self) -> None:
        """Verify SessionLifecycleUser defines a session_lifecycle task method."""
        parsed = _get_parsed()
        methods = parsed["classes"]["SessionLifecycleUser"]["methods"]
        assert "session_lifecycle" in methods, (
            "SessionLifecycleUser missing session_lifecycle task"
        )

    def test_user_classes_have_wait_time(self) -> None:
        """Verify each user class defines a wait_time attribute."""
        parsed = _get_parsed()
        for class_name in EXPECTED_USER_CLASSES:
            attrs = parsed["classes"][class_name]["attributes"]
            assert "wait_time" in attrs, (
                f"{class_name} does not define wait_time. Found attributes: {list(attrs.keys())}"
            )

    def test_user_classes_have_positive_integer_weights(self) -> None:
        """Verify each user class has a weight attribute that is a positive integer."""
        parsed = _get_parsed()
        for class_name in EXPECTED_USER_CLASSES:
            attrs = parsed["classes"][class_name]["attributes"]
            assert "weight" in attrs, (
                f"{class_name} does not define weight. Found attributes: {list(attrs.keys())}"
            )
            weight = attrs["weight"]
            assert isinstance(weight, int), f"{class_name}.weight is not an int: {weight!r}"
            assert weight > 0, f"{class_name}.weight must be positive, got {weight}"

    def test_health_check_user_has_highest_weight(self) -> None:
        """Verify HealthCheckUser has the highest weight (most spawned)."""
        parsed = _get_parsed()
        weights = {}
        for class_name in EXPECTED_USER_CLASSES:
            attrs = parsed["classes"][class_name]["attributes"]
            weights[class_name] = attrs["weight"]

        assert weights["HealthCheckUser"] == max(weights.values()), (
            f"HealthCheckUser should have the highest weight. Actual weights: {weights}"
        )

    def test_locustfile_defines_agent_names(self) -> None:
        """Verify the locustfile contains the standard agent definition names."""
        parsed = _get_parsed()
        assert "AGENT_NAMES" in parsed["constants"], "Locustfile missing AGENT_NAMES constant"
        agent_names = parsed["constants"]["AGENT_NAMES"]
        assert isinstance(agent_names, list), "AGENT_NAMES should be a list"
        assert len(agent_names) >= 3, "AGENT_NAMES should contain at least 3 agents"
        # Verify at least some of the standard agent names are present
        expected_subset = {"orchestrator", "qa", "researcher"}
        actual_set = set(agent_names)
        missing = expected_subset - actual_set
        assert not missing, f"AGENT_NAMES is missing expected agents: {missing}"

    def test_locustfile_defines_invoke_payloads(self) -> None:
        """Verify the locustfile contains non-empty invoke payloads."""
        parsed = _get_parsed()
        assert "INVOKE_PAYLOADS" in parsed["constants"], (
            "Locustfile missing INVOKE_PAYLOADS constant"
        )
        payloads = parsed["constants"]["INVOKE_PAYLOADS"]
        assert isinstance(payloads, list), "INVOKE_PAYLOADS should be a list"
        assert len(payloads) >= 3, "INVOKE_PAYLOADS should contain at least 3 entries"
        for i, payload in enumerate(payloads):
            assert isinstance(payload, dict), f"INVOKE_PAYLOADS[{i}] should be a dict"
            assert "prompt" in payload, f"INVOKE_PAYLOADS[{i}] missing 'prompt' key"
            assert len(payload["prompt"]) > 10, (
                f"INVOKE_PAYLOADS[{i}] prompt is too short to be a real prompt"
            )

    def test_locustfile_source_references_real_endpoints(self) -> None:
        """Verify the locustfile source code references actual AGENT-33 endpoints."""
        parsed = _get_parsed()
        source = parsed["source"]

        # These are the actual AGENT-33 endpoint paths that must appear in
        # the locustfile to confirm it exercises real endpoints
        required_endpoints = [
            "/healthz",
            "/health",
            "/readyz",
            "/metrics",
            "/v1/agents/",
            "/invoke",
            "/v1/sessions/",
        ]
        for endpoint in required_endpoints:
            assert endpoint in source, f"Locustfile source does not reference endpoint: {endpoint}"

    def test_locustfile_uses_catch_response(self) -> None:
        """Verify tasks use catch_response=True for meaningful validation.

        This ensures the load test validates response content, not just
        HTTP status codes. Without catch_response, Locust only checks
        for 2xx status, which would miss malformed responses.
        """
        parsed = _get_parsed()
        source = parsed["source"]
        # Count occurrences of catch_response=True
        count = source.count("catch_response=True")
        # We expect at least one per user class (4 minimum)
        assert count >= 4, (
            f"Expected at least 4 catch_response=True usages (one per user class), "
            f"found {count}. Tasks should validate response content."
        )

    def test_locustfile_validates_response_bodies(self) -> None:
        """Verify the locustfile inspects response JSON/text, not just status codes.

        This catches the anti-pattern of load tests that only check HTTP
        status but never verify the response content.
        """
        parsed = _get_parsed()
        source = parsed["source"]
        # Must call response.json() or response.text to inspect content
        assert "response.json()" in source, (
            "Locustfile does not call response.json() -- tasks should validate response content"
        )
        assert "response.failure(" in source, (
            "Locustfile does not call response.failure() -- "
            "tasks should report meaningful failures"
        )
