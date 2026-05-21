"""AI/LLM security scanning for AGENT-33.

Provides prompt injection detection, tool definition poisoning checks
(OWASP MCP-01), and integration points for LLM Guard and Garak.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, cast

import structlog

from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
)
from agent33.security.injection import ScanResult, scan_input, scan_inputs_recursive

logger = structlog.get_logger()
_LOGGED_DEBUG_EVENTS: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

_LLMGuardScan = Callable[..., Any]
_LLMGUARD_BOOTSTRAPPED = False
_GARAK_BOOTSTRAPPED = False
_HAS_LLMGUARD = False
_HAS_GARAK = False
_llmguard_scan_prompt: _LLMGuardScan | None = None
_llmguard_scan_output: _LLMGuardScan | None = None
PromptInjection: type[Any] | None = None
Toxicity: type[Any] | None = None
InvisibleText: type[Any] | None = None
Sensitive: type[Any] | None = None
NoRefusal: type[Any] | None = None

_GARAK_MODULE = None

# OWASP MCP Top 10 category mapping
# See: https://owasp.org/www-project-top-10-for-large-language-model-applications/
OWASP_MCP_CATEGORIES: dict[str, tuple[str, FindingCategory]] = {
    "MCP-01": ("Tool Poisoning", FindingCategory.TOOL_POISONING),
    "MCP-02": ("Excessive Agency", FindingCategory.AUTHORIZATION_BYPASS),
    "MCP-03": ("Tool Shadowing", FindingCategory.TOOL_POISONING),
    "MCP-04": ("Rug Pull", FindingCategory.SUPPLY_CHAIN),
    "MCP-05": ("Server Compromise", FindingCategory.SUPPLY_CHAIN),
    "MCP-06": ("Indirect Prompt Injection", FindingCategory.PROMPT_INJECTION),
    "MCP-07": ("Resource Exhaustion", FindingCategory.CONFIGURATION_ISSUE),
    "MCP-08": ("Consent & Data Privacy", FindingCategory.MODEL_SECURITY),
    "MCP-09": ("Supply Chain Attack", FindingCategory.SUPPLY_CHAIN),
    "MCP-10": ("Authentication Bypass", FindingCategory.AUTHENTICATION_WEAKNESS),
}

# Suspicious patterns in tool descriptions that indicate poisoning (MCP-01)
_POISONING_PATTERNS: list[tuple[str, str]] = [
    ("ignore previous", "Tool description attempts to override system instructions"),
    ("disregard", "Tool description contains instruction override attempt"),
    ("you must", "Tool description contains coercive instruction"),
    ("do not tell", "Tool description attempts to hide behavior from user"),
    ("secret", "Tool description references hidden behavior"),
    ("always call this tool first", "Tool description demands priority execution"),
    ("before any other tool", "Tool description demands priority execution"),
    ("<system>", "Tool description contains system prompt delimiter"),
    ("[SYSTEM]", "Tool description contains system prompt delimiter"),
    ("```system", "Tool description contains system prompt code block"),
]

# Suspicious patterns in tool input schemas that indicate shadowing (MCP-03)
_SHADOWING_PATTERNS: list[tuple[str, str]] = [
    ("override", "Schema property name suggests override behavior"),
    ("hidden", "Schema property name suggests hidden behavior"),
    ("system_prompt", "Schema exposes system prompt manipulation"),
    ("inject", "Schema property name suggests injection vector"),
]


def _log_debug_once(event: str, **fields: object) -> None:
    key = (event, tuple(sorted((name, repr(value)) for name, value in fields.items())))
    if key in _LOGGED_DEBUG_EVENTS:
        return
    _LOGGED_DEBUG_EVENTS.add(key)
    logger.debug(event, **fields)


def _ensure_llm_guard_loaded() -> None:
    global _LLMGUARD_BOOTSTRAPPED, _HAS_LLMGUARD
    global _llmguard_scan_prompt, _llmguard_scan_output
    global PromptInjection, Toxicity, InvisibleText, Sensitive, NoRefusal
    if _LLMGUARD_BOOTSTRAPPED:
        return
    if (
        _HAS_LLMGUARD
        or _llmguard_scan_prompt is not None
        or _llmguard_scan_output is not None
        or any(
            scanner is not None
            for scanner in (
                PromptInjection,
                Toxicity,
                InvisibleText,
                Sensitive,
                NoRefusal,
            )
        )
    ):
        _LLMGUARD_BOOTSTRAPPED = True
        return
    _LLMGUARD_BOOTSTRAPPED = True
    try:
        llmguard_module = importlib.import_module("llm_guard")
        input_scanners = importlib.import_module("llm_guard.input_scanners")
        output_scanners = importlib.import_module("llm_guard.output_scanners")
    except ImportError:  # pragma: no cover - optional dependency
        _HAS_LLMGUARD = False
        return
    _llmguard_scan_prompt = cast(
        "_LLMGuardScan | None",
        getattr(llmguard_module, "scan_prompt", None),
    )
    _llmguard_scan_output = cast(
        "_LLMGuardScan | None",
        getattr(llmguard_module, "scan_output", None),
    )
    PromptInjection = cast(
        "type[Any] | None",
        getattr(input_scanners, "PromptInjection", None),
    )
    Toxicity = cast("type[Any] | None", getattr(input_scanners, "Toxicity", None))
    InvisibleText = cast(
        "type[Any] | None",
        getattr(input_scanners, "InvisibleText", None),
    )
    Sensitive = cast("type[Any] | None", getattr(output_scanners, "Sensitive", None))
    NoRefusal = cast("type[Any] | None", getattr(output_scanners, "NoRefusal", None))
    _HAS_LLMGUARD = True


def _ensure_garak_loaded() -> None:
    global _GARAK_BOOTSTRAPPED, _GARAK_MODULE, _HAS_GARAK
    if _GARAK_BOOTSTRAPPED:
        return
    if _HAS_GARAK or _GARAK_MODULE is not None:
        _GARAK_BOOTSTRAPPED = True
        return
    _GARAK_BOOTSTRAPPED = True
    try:
        _GARAK_MODULE = importlib.import_module("garak")
    except ImportError:  # pragma: no cover - optional dependency
        _HAS_GARAK = False
        return
    _HAS_GARAK = True


def _is_numeric_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce_score(value: Any) -> float:
    if _is_numeric_score(value):
        return float(value)
    if isinstance(value, dict):
        for key in ("score", "risk_score", "max_score"):
            candidate = value.get(key)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                return float(candidate)
        return 0.0
    if isinstance(value, (list, tuple)):
        numeric_values = [float(item) for item in value if _is_numeric_score(item)]
        if numeric_values:
            return max(numeric_values)
    return 0.0


def _score_to_severity(score: float) -> FindingSeverity:
    if score >= 0.9:
        return FindingSeverity.CRITICAL
    if score >= 0.7:
        return FindingSeverity.HIGH
    if score >= 0.5:
        return FindingSeverity.MEDIUM
    return FindingSeverity.LOW


def _llm_guard_input_defaults_available() -> bool:
    _ensure_llm_guard_loaded()
    return (
        _HAS_LLMGUARD
        and callable(_llmguard_scan_prompt)
        and isinstance(PromptInjection, type)
        and isinstance(Toxicity, type)
        and isinstance(InvisibleText, type)
    )


def _llm_guard_output_defaults_available() -> bool:
    _ensure_llm_guard_loaded()
    return (
        _HAS_LLMGUARD
        and callable(_llmguard_scan_output)
        and isinstance(Sensitive, type)
        and isinstance(NoRefusal, type)
    )


def _llm_guard_input_runtime_available() -> bool:
    _ensure_llm_guard_loaded()
    return _HAS_LLMGUARD and callable(_llmguard_scan_prompt)


def _llm_guard_output_runtime_available() -> bool:
    _ensure_llm_guard_loaded()
    return _HAS_LLMGUARD and callable(_llmguard_scan_output)


def _garak_runtime_available() -> bool:
    _ensure_garak_loaded()
    return _HAS_GARAK and callable(getattr(_GARAK_MODULE, "run_probe", None))


class LLMSecurityScanner:
    """Scans for AI/LLM-specific security threats.

    Integrates with existing prompt injection detection from
    agent33.security.injection and adds tool definition scanning
    per OWASP MCP Top 10 guidelines.
    """

    def __init__(
        self,
        *,
        llm_guard_adapter: LLMGuardAdapter | None = None,
        garak_adapter: GarakAdapter | None = None,
    ) -> None:
        self._llm_guard_adapter = llm_guard_adapter or LLMGuardAdapter()
        self._garak_adapter = garak_adapter or GarakAdapter()

    def scan_prompt_safety(
        self,
        text: str,
        *,
        run_id: str = "",
        source: str = "user_input",
    ) -> list[SecurityFinding]:
        """Scan text for prompt injection threats.

        Wraps the existing scan_input() function and converts results
        to SecurityFinding format.

        Args:
            text: Text to scan for injection attempts.
            run_id: Security run ID to associate findings with.
            source: Description of where the text came from.

        Returns:
            List of SecurityFindings for detected threats.
        """
        result = scan_input(text)
        findings = self._scan_result_to_findings(result, run_id=run_id, source=source, text=text)
        findings.extend(self._llm_guard_adapter.scan_input(text, run_id=run_id))
        return findings

    def scan_nested_inputs(
        self,
        data: object,
        *,
        run_id: str = "",
        source: str = "structured_input",
    ) -> list[SecurityFinding]:
        """Scan nested data structures for prompt injection.

        Wraps scan_inputs_recursive() and converts results.

        Args:
            data: Nested dict/list/string structure to scan.
            run_id: Security run ID to associate findings with.
            source: Description of where the data came from.

        Returns:
            List of SecurityFindings for detected threats.
        """
        result = scan_inputs_recursive(data)
        return self._scan_result_to_findings(
            result, run_id=run_id, source=source, text=str(data)[:200]
        )

    def scan_tool_definitions(
        self,
        tools: list[dict[str, Any]],
        *,
        run_id: str = "",
    ) -> list[SecurityFinding]:
        """Check tool definitions for poisoning/shadowing patterns.

        Implements OWASP MCP-01 (Tool Poisoning) and MCP-03 (Tool Shadowing)
        detection by scanning tool names, descriptions, and input schemas
        for suspicious patterns.

        Args:
            tools: List of tool definition dicts, each with 'name',
                   'description', and optionally 'input_schema'/'parameters'.
            run_id: Security run ID to associate findings with.

        Returns:
            List of SecurityFindings for detected threats.
        """
        findings: list[SecurityFinding] = []

        for tool in tools:
            tool_name = tool.get("name", "unknown")
            description = tool.get("description", "")
            schema = tool.get("input_schema") or tool.get("parameters", {})

            # Check description for poisoning patterns (MCP-01)
            desc_lower = description.lower()
            for pattern, reason in _POISONING_PATTERNS:
                if pattern.lower() in desc_lower:
                    findings.append(
                        SecurityFinding(
                            run_id=run_id,
                            severity=FindingSeverity.HIGH,
                            category=FindingCategory.TOOL_POISONING,
                            title=f"Tool poisoning detected in '{tool_name}'",
                            description=(
                                f"OWASP MCP-01: {reason}. "
                                f"Pattern '{pattern}' found in tool description."
                            ),
                            tool="llm-security",
                            remediation=(
                                "Review and sanitize tool description. "
                                "Remove any instruction override attempts."
                            ),
                        )
                    )
                    break  # One finding per tool for description

            # Run injection scanner on description
            desc_result = scan_input(description)
            if not desc_result.is_safe:
                findings.append(
                    SecurityFinding(
                        run_id=run_id,
                        severity=FindingSeverity.CRITICAL,
                        category=FindingCategory.TOOL_POISONING,
                        title=f"Injection in tool description: '{tool_name}'",
                        description=(
                            f"OWASP MCP-01: Tool description contains prompt "
                            f"injection patterns: {', '.join(desc_result.threats)}"
                        ),
                        tool="llm-security",
                        remediation=(
                            "Remove injection payloads from tool description. "
                            "This tool definition should not be trusted."
                        ),
                    )
                )

            # Check schema for shadowing patterns (MCP-03)
            if isinstance(schema, dict):
                properties = schema.get("properties", {})
                for prop_name in properties:
                    prop_lower = prop_name.lower()
                    for pattern, reason in _SHADOWING_PATTERNS:
                        if pattern in prop_lower:
                            findings.append(
                                SecurityFinding(
                                    run_id=run_id,
                                    severity=FindingSeverity.MEDIUM,
                                    category=FindingCategory.TOOL_POISONING,
                                    title=(f"Suspicious schema in '{tool_name}'"),
                                    description=(
                                        f"OWASP MCP-03: {reason}. "
                                        f"Property '{prop_name}' in tool "
                                        f"'{tool_name}'."
                                    ),
                                    tool="llm-security",
                                    remediation=(
                                        "Review tool schema properties. "
                                        "Rename or remove suspicious parameters."
                                    ),
                                )
                            )
                            break  # One finding per property

        logger.info(
            "llm_security_tool_scan_complete",
            tools_scanned=len(tools),
            findings_count=len(findings),
        )
        return findings

    def _scan_result_to_findings(
        self,
        result: ScanResult,
        *,
        run_id: str,
        source: str,
        text: str,
    ) -> list[SecurityFinding]:
        """Convert injection ScanResult to SecurityFindings."""
        if result.is_safe:
            return []

        findings: list[SecurityFinding] = []
        for threat in result.threats:
            severity = self._threat_severity(threat)
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=severity,
                    category=FindingCategory.PROMPT_INJECTION,
                    title=f"Prompt injection detected: {threat}",
                    description=(
                        f"Detected '{threat}' in {source}. Input preview: {text[:100]}..."
                    ),
                    tool="llm-security",
                    remediation=(
                        "Sanitize or reject this input. Do not pass it "
                        "directly to LLM system prompts."
                    ),
                )
            )
        return findings

    def scan_model_behavior(
        self,
        model_name: str,
        *,
        run_id: str = "",
    ) -> list[SecurityFinding]:
        """Run optional model-probe checks when a target model is known."""
        if not model_name:
            return []
        return self._garak_adapter.run_probes(model_name, run_id=run_id)

    @staticmethod
    def _threat_severity(threat: str) -> FindingSeverity:
        """Map threat type to severity."""
        if threat in {"system_prompt_override", "encoded_payload"}:
            return FindingSeverity.CRITICAL
        if threat in {"delimiter_injection", "instruction_override"}:
            return FindingSeverity.HIGH
        return FindingSeverity.MEDIUM


class LLMGuardAdapter:
    """Adapter for Protect AI's LLM Guard integration.

    LLM Guard (MIT, 4.5k+ stars) provides input/output scanners for:
    - Prompt injection detection
    - Toxicity filtering
    - PII detection and anonymization
    - Invisible text detection

    Adapter behavior is optional-dependency-safe: when llm-guard is not
    installed, scan methods return no findings.
    """

    def __init__(
        self,
        *,
        input_scanners: list[Any] | None = None,
        output_scanners: list[Any] | None = None,
    ) -> None:
        self._input_scanners = (
            list(input_scanners)
            if input_scanners is not None
            else self._build_default_input_scanners()
        )
        self._output_scanners = (
            list(output_scanners)
            if output_scanners is not None
            else self._build_default_output_scanners()
        )

    @staticmethod
    def is_available() -> bool:
        """Check if llm-guard runtime and default scanners are available."""
        return _llm_guard_input_defaults_available() or _llm_guard_output_defaults_available()

    @staticmethod
    def _build_default_input_scanners() -> list[Any]:
        if not _llm_guard_input_defaults_available():
            return []
        return [
            cast("type[Any]", PromptInjection)(),
            cast("type[Any]", Toxicity)(),
            cast("type[Any]", InvisibleText)(),
        ]

    @staticmethod
    def _build_default_output_scanners() -> list[Any]:
        if not _llm_guard_output_defaults_available():
            return []
        return [cast("type[Any]", Sensitive)(), cast("type[Any]", NoRefusal)()]

    def scan_input(self, text: str, *, run_id: str = "") -> list[SecurityFinding]:
        """Scan input text using LLM Guard scanners."""
        if not self._input_scanners:
            _log_debug_once("llm_guard_input_scan_skipped", reason="no_scanners_configured")
            return []
        if not _llm_guard_input_runtime_available():
            reason = "dependency_unavailable" if not _HAS_LLMGUARD else "scan_prompt_unavailable"
            _log_debug_once("llm_guard_input_scan_skipped", reason=reason)
            return []
        try:
            valid, score = self._run_scan(
                cast("_LLMGuardScan", _llmguard_scan_prompt),
                self._input_scanners,
                text,
            )
        except Exception:
            logger.warning("llm_guard_input_scan_failed", exc_info=True)
            return []
        if valid:
            return []
        return [
            SecurityFinding(
                run_id=run_id,
                severity=_score_to_severity(score),
                category=FindingCategory.MODEL_SECURITY,
                title="LLM Guard flagged unsafe prompt input",
                description=(
                    "LLM Guard input scanners reported a potentially unsafe prompt. "
                    f"Scanners: {', '.join(self._scanner_names(self._input_scanners))}. "
                    f"Score: {score:.2f}"
                ),
                tool="llm-guard",
                remediation=("Review the prompt for injection, toxicity, or hidden-text attacks."),
            )
        ]

    def scan_output(
        self,
        text: str,
        *,
        prompt: str = "",
        run_id: str = "",
    ) -> list[SecurityFinding]:
        """Scan LLM output using LLM Guard scanners and optional prompt context."""
        if not self._output_scanners:
            _log_debug_once("llm_guard_output_scan_skipped", reason="no_scanners_configured")
            return []
        if not _llm_guard_output_runtime_available():
            reason = "dependency_unavailable" if not _HAS_LLMGUARD else "scan_output_unavailable"
            _log_debug_once("llm_guard_output_scan_skipped", reason=reason)
            return []
        try:
            valid, score = self._run_scan(
                cast("_LLMGuardScan", _llmguard_scan_output),
                self._output_scanners,
                prompt,
                text,
            )
        except Exception:
            logger.warning("llm_guard_output_scan_failed", exc_info=True)
            return []
        if valid:
            return []
        return [
            SecurityFinding(
                run_id=run_id,
                severity=_score_to_severity(score),
                category=FindingCategory.MODEL_SECURITY,
                title="LLM Guard flagged unsafe model output",
                description=(
                    "LLM Guard output scanners reported a potentially unsafe model response. "
                    f"Scanners: {', '.join(self._scanner_names(self._output_scanners))}. "
                    f"Score: {score:.2f}"
                ),
                tool="llm-guard",
                remediation=(
                    "Review the response for sensitive content or unsafe refusal handling."
                ),
            )
        ]

    @staticmethod
    def _run_scan(scan_fn: Any, scanners: list[Any], *payload: Any) -> tuple[bool, float]:
        result = scan_fn(scanners, *payload)
        return LLMGuardAdapter._normalize_scan_result(result)

    @staticmethod
    def _normalize_scan_result(result: Any) -> tuple[bool, float]:
        if isinstance(result, tuple):
            if len(result) >= 3:
                return bool(result[1]), _coerce_score(result[2])
            if len(result) == 2:
                return bool(result[1]), 0.0 if result[1] else 1.0
        if isinstance(result, dict):
            valid = bool(result.get("is_valid", True))
            score = _coerce_score(result.get("score", result.get("risk_score", 0.0)))
            return valid, score
        if isinstance(result, bool):
            return result, 0.0 if result else 1.0
        return True, 0.0

    @staticmethod
    def _scanner_names(scanners: list[Any]) -> list[str]:
        return [scanner.__class__.__name__ for scanner in scanners]


class GarakAdapter:
    """Adapter for NVIDIA's Garak LLM vulnerability scanner.

    Garak (Apache-2.0, 3k+ stars) provides:
    - Prompt injection probes
    - Data leakage detection
    - Hallucination testing
    - Toxicity generation testing

    Adapter behavior is optional-dependency-safe: when garak is not
    installed, probe execution returns no findings.
    """

    DEFAULT_PROBES = ["promptinject", "encoding", "dan", "leakreplay"]

    @staticmethod
    def is_available() -> bool:
        """Check if garak runtime can execute probes."""
        return _garak_runtime_available()

    def __init__(self, *, probe_runner: Any | None = None) -> None:
        self._uses_default_probe_runner = probe_runner is None
        self._probe_runner = probe_runner or self._run_probe

    def _can_run_probes(self) -> bool:
        if not self._uses_default_probe_runner:
            return callable(self._probe_runner)
        return _garak_runtime_available()

    def run_probes(
        self,
        model_name: str,
        *,
        run_id: str = "",
        probe_types: list[str] | None = None,
    ) -> list[SecurityFinding]:
        """Run Garak probes against a model."""
        if not self._can_run_probes():
            if not _HAS_GARAK:
                reason = "dependency_unavailable"
            elif not self._uses_default_probe_runner:
                reason = "probe_runner_unavailable"
            else:
                reason = "probe_runner_unavailable"
            _log_debug_once("garak_probe_skipped", reason=reason)
            return []
        selected_probes = probe_types or list(self.DEFAULT_PROBES)
        findings: list[SecurityFinding] = []
        for probe_name in selected_probes:
            try:
                result = self._probe_runner(model_name, probe_name)
            except Exception:
                logger.warning("garak_probe_failed", probe=probe_name, exc_info=True)
                continue
            findings.extend(self._result_to_findings(result, run_id=run_id, probe_name=probe_name))
        return findings

    @staticmethod
    def _run_probe(model_name: str, probe_name: str) -> Any:
        if _GARAK_MODULE is None:
            return []
        runner = getattr(_GARAK_MODULE, "run_probe", None)
        if callable(runner):
            return runner(model_name=model_name, probe_name=probe_name)
        logger.debug("garak_runtime_probe_runner_missing", probe=probe_name)
        return []

    @staticmethod
    def _result_to_findings(
        result: Any,
        *,
        run_id: str,
        probe_name: str,
    ) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        for item in GarakAdapter._normalize_results(result, probe_name):
            score = _coerce_score(item.get("score", 0.0))
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=_score_to_severity(score),
                    category=FindingCategory.MODEL_SECURITY,
                    title=item.get(
                        "title",
                        f"Garak probe '{probe_name}' reported a potential model vulnerability",
                    ),
                    description=item.get(
                        "description",
                        (
                            f"Garak probe '{probe_name}' returned a non-zero risk score "
                            f"({score:.2f})."
                        ),
                    ),
                    tool="garak",
                    remediation=item.get(
                        "remediation",
                        "Review the affected model and tighten prompt and output controls.",
                    ),
                )
            )
        return findings

    @staticmethod
    def _normalize_results(result: Any, probe_name: str) -> list[dict[str, Any]]:
        if result is None:
            return []
        if result is True:
            return []
        if result is False:
            return [{"score": 1.0, "description": f"Garak probe '{probe_name}' failed"}]
        if isinstance(result, dict):
            return [result] if GarakAdapter._result_has_issue(result) else []
        if isinstance(result, (list, tuple)):
            normalized: list[dict[str, Any]] = []
            for item in result:
                normalized.extend(GarakAdapter._normalize_results(item, probe_name))
            return normalized
        if _is_numeric_score(result) and float(result) > 0:
            return [
                {
                    "score": float(result),
                    "description": f"Garak probe '{probe_name}' flagged risk",
                }
            ]
        return []

    @staticmethod
    def _result_has_issue(result: dict[str, Any]) -> bool:
        if result.get("finding") is True:
            return True
        score = result.get("score", result.get("risk_score", 0.0))
        return _coerce_score(score) > 0
