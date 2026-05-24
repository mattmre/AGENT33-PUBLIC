#!/usr/bin/env python3
"""scripts/run_endurance_benchmark.py -- the long-horizon unattended
lane endurance benchmark driver (issue #41, cluster E 7/7 -- the LAST
issue in cluster E).

Drives every scenario from v3.5/enums/endurance-scenarios.txt against
the canonical fixture catalog under
v3.5/tests/fixtures/endurance/_generated/scenarios.json (rendered by
tests/fixtures/endurance/_build_fixtures.py at pytest_configure or on
demand by this script when --rebuild is passed). Emits one
`scenario_result` row per scenario followed by a `run_summary` row to
the JSONL file named by --report-out (default
v3.5/out/endurance-run-report.jsonl). Each row carries an 8-hex CRC32
footer mirroring the bhs-trajectory.jsonl / charter-merge-log.jsonl
contract.

The benchmark is a CONTRACT smoke -- it asserts the cluster-E rule
shapes line up with the cluster-E artifact shapes against a closed
catalog of scenarios; it does NOT subprocess every cluster-E
validator (that path is DEFERRED to v3.6 per the operator doc Section
7 DS-001). The scenario expectation map is the source of truth; the
driver compares observed-vs-expected and writes the result.

Synthetic mode (default; required for v3.5 release):

    python v3.5/scripts/run_endurance_benchmark.py \\
        --report-out v3.5/out/endurance-run-report.jsonl \\
        --lane-id lane-endurance-synth-v35

Real-repo mode (optional; documented for completeness):

    python v3.5/scripts/run_endurance_benchmark.py \\
        --real-repo /path/to/some/lane \\
        --report-out /path/to/some/lane/out/endurance-run-report.jsonl

Exit codes (v3.6 #101 reconciliation: operator-spec 5-class policy
under HIGHEST-PRIORITY-WINS semantics; CORRUPTION(5) wins over
CHAIN(4) wins over ENUM(3) wins over SCHEMA(2) wins over DRIFT(1)):

    0  EXIT_OK         every scenario passed
                       (drift_detection_rate == 1.0 AND
                       all_expected_scenarios_observed)
    1  EXIT_DRIFT      one or more scenarios disagreed
                       expected-vs-observed (the LEGACY default
                       failure mode for a contract-smoke benchmark)
    2  EXIT_SCHEMA     scenario_result / run_summary record failed
                       its jsonschema validation (alias previously
                       reused by performance budget)
    3  EXIT_ENUM       performance budget exceeded (wallclock_ms >
                       the soft 60s budget; the schema's hard cap
                       is 600s) -- repurposed under the 5-class
                       policy
    4  EXIT_CHAIN      reserved for future per-row CRC chain
                       walking of the report JSONL (not currently
                       exercised; an emitted row whose CRC32 footer
                       fails recomputation would surface here)
    5  EXIT_CORRUPTION catalog drift / setup error (catalog file
                       missing, unparseable, or out of sync with
                       the .txt enums); also covers
                       FileNotFoundError on --real-repo and any IO
                       error rendering the report

Back-compat aliases preserve external callers:
    EXIT_CATALOG = EXIT_CORRUPTION (was 2 under old 4-class map)
    EXIT_BUDGET  = EXIT_ENUM       (was 3 under old 4-class map;
                                    integer is unchanged)

The --report-out default is now configurable via the
BHS_ENDURANCE_REPORT_OUT environment variable so the kit-internal
v3.5/out/endurance-run-report.jsonl path is no longer hard-baked
(v3.6 MEDIUM rollup). When the env var is absent the default is
v3.5/out/endurance-run-report.jsonl relative to the script (the
historical default).
"""

from __future__ import annotations

import argparse
import binascii
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


_SCRIPT_DIR = Path(__file__).resolve().parent
_V35_ROOT = _SCRIPT_DIR.parent
_FIXTURE_DIR = _V35_ROOT / "tests" / "fixtures" / "endurance"
_GENERATED_DIR = _FIXTURE_DIR / "_generated"
_ENUM_DIR = (
    _V35_ROOT / "_internal" / "conventions" / "brutal-honesty-kit" / "v3.5"
    / "enums"
)


def _resolve_default_report_out() -> Path:
    """v3.6 MEDIUM rollup: the kit-internal v3.5/out/... path was
    hard-baked. Operators consuming the benchmark from a vendored
    drop-in (where v3.5/out may be read-only or absent) need a way to
    redirect WITHOUT patching the script. Resolution order:

      1. $BHS_ENDURANCE_REPORT_OUT (absolute or path-fragment;
         operator wins)
      2. $BHS_OUT_DIR / "endurance-run-report.jsonl" (folder-level
         override; matches the convention used elsewhere in v3.5
         operator docs)
      3. v3.5/out/endurance-run-report.jsonl (historical default,
         repo-relative to the script)

    The --report-out CLI flag still takes precedence over the env
    var (argparse default == the result of this resolver, and an
    explicit --report-out arg overrides).
    """
    explicit = os.environ.get("BHS_ENDURANCE_REPORT_OUT")
    if explicit:
        return Path(explicit).expanduser()
    out_dir = os.environ.get("BHS_OUT_DIR")
    if out_dir:
        return Path(out_dir).expanduser() / "endurance-run-report.jsonl"
    return _V35_ROOT / "out" / "endurance-run-report.jsonl"


_DEFAULT_REPORT_OUT = _resolve_default_report_out()
_DEFAULT_LANE_ID = "lane-endurance-synth-v35"
_DEFAULT_AGENT_SESSION_ID = "01HQ9X7P5K3J2NQHJZ4Y6ENDURANCE"

# v3.6 #101 reconciliation: operator-spec 5-class exit-code policy
# under highest-priority-wins. The benchmark legacy mapping was
# 0/1/2/3 (ok/drift/catalog/budget); we extend to 0..5 and pin
# back-compat aliases for external callers. The integer values of
# DRIFT(1) and BUDGET(3) are unchanged so an old caller checking
# `rc == 1` (drift) or `rc == 3` (budget) keeps working; the
# catalog-error path used to be `2` and is now `5` (EXIT_CORRUPTION)
# because catalog drift is the closest match to F11 corruption
# (catalog state on disk is wrong, validator cannot proceed).
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SCHEMA = 2
EXIT_ENUM = 3
EXIT_CHAIN = 4
EXIT_CORRUPTION = 5
# Back-compat aliases. EXIT_BUDGET keeps its historical integer (3);
# EXIT_CATALOG was 2, now points at CORRUPTION(5) under the new
# policy.
EXIT_CATALOG = EXIT_CORRUPTION
EXIT_BUDGET = EXIT_ENUM

# Priority order: 5 > 4 > 3 > 2 > 1. The driver scans largest-first.
_EXIT_PRIORITY: tuple[int, ...] = (
    EXIT_CORRUPTION,
    EXIT_CHAIN,
    EXIT_ENUM,
    EXIT_SCHEMA,
    EXIT_DRIFT,
)


def choose_exit_code(codes: list[int]) -> int:
    """Highest-priority-wins driver: scans the largest-integer-first
    priority tuple and returns the first match. Returns EXIT_OK when
    no codes were observed or every observed code is EXIT_OK.

    Mirrors validate_score_trajectory.choose_exit_code +
    validate_charter_merge_log.choose_exit_code so the four
    cluster-E gates expose IDENTICAL semantics for downstream
    callers that aggregate their exit codes. Any unrecognized
    non-zero code is treated as EXIT_DRIFT (the lowest non-zero
    severity) so future code-class additions never silently pass.
    """
    if not codes:
        return EXIT_OK
    present: set[int] = {c for c in codes if c != EXIT_OK}
    if not present:
        return EXIT_OK
    for code in _EXIT_PRIORITY:
        if code in present:
            return code
    # Any non-zero code not in _EXIT_PRIORITY -> treat as DRIFT (the
    # least-severe non-zero class; never silently OK). Mirrors the
    # sibling validators so unknown future codes can never mask a
    # real failure as a clean pass.
    return EXIT_DRIFT


# Soft performance budget per issue #41 plan §3.5. wallclock_ms
# exceeding this returns EXIT_BUDGET (== EXIT_ENUM(3) under the
# v3.6 #101 policy; integer unchanged from the v3.5 4-class map).
_PERFORMANCE_BUDGET_MS = 60000

# Fixed lane-start ISO8601 base used to make scenario_result `ts`
# values deterministic in synthetic mode. Real-repo mode uses
# wallclock time.
_LANE_START_ISO = "2026-05-15T00:00:00.000Z"
# 2026-05-15T00:00:00Z in epoch milliseconds. Verified by hand:
#   56 years from 1970 plus 14 leap years (1972..2024) -> 20454 days,
#   plus 31+28+31+30+14 = 134 days into 2026 -> 20588 total days,
#   * 86400 seconds/day * 1000 ms = 1778803200000.
_LANE_START_EPOCH_MS = 1778803200000


# ---------------------------------------------------------------------------
# CRC32 helpers (mirrors validate_charter_merge_log / validate_score_trajectory).
# ---------------------------------------------------------------------------


def _serialize_for_crc(record: dict) -> bytes:
    """Mirror validate_charter_merge_log._serialize_for_crc verbatim.

    The serialization MUST be byte-stable across processes for the CRC
    footer to be reproducible. sort_keys + the (',', ':') separators
    are the canonical contract.
    """
    return json.dumps(
        {k: v for k, v in record.items() if k != "crc32"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_crc32(record: dict) -> str:
    """Mirror validate_charter_merge_log.compute_crc32 verbatim."""
    return (
        f"{binascii.crc32(_serialize_for_crc(record)) & 0xFFFFFFFF:08x}"
    )


# ---------------------------------------------------------------------------
# Catalog loading.
# ---------------------------------------------------------------------------


def _import_fixture_builder():
    """Import the canonical fixture builder via importlib.util.

    Mirrors tests/conftest.py's _import_builder pattern: the module is
    registered in sys.modules BEFORE exec_module so any @dataclass /
    typing usage that requires the module name to be importable
    completes correctly under Python 3.11+.
    """
    builder_path = _FIXTURE_DIR / "_build_fixtures.py"
    if not builder_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(
        "_endurance_build_fixtures", builder_path
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_endurance_build_fixtures"] = module
    spec.loader.exec_module(module)
    return module


def _load_scenarios_json() -> dict | None:
    """Load _generated/scenarios.json. Returns None when missing or
    unparseable -- the caller decides how to surface the error.
    """
    target = _GENERATED_DIR / "scenarios.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_enum_set(name: str) -> set[str]:
    """Load a snake_case enum file and return the set of identifiers.
    Returns an empty set when the file is absent (back-compat).
    """
    path = _ENUM_DIR / name
    if not path.exists():
        return set()
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


# ---------------------------------------------------------------------------
# Synthetic mode -- the canonical scenario sweep.
# ---------------------------------------------------------------------------


def _scenario_ts(index: int) -> str:
    """Deterministic per-scenario timestamp.

    Synthetic mode MUST not depend on wall-clock so the report is
    bit-identical across runs. Each scenario row gets a ts that is
    `_LANE_START_ISO + index seconds` (so the 0-th row is at
    2026-05-15T00:00:00.000Z, the 1st at 2026-05-15T00:00:01.000Z,
    etc.).

    Implementation note: time.gmtime() reads wall-clock by default
    but accepts an explicit UTC epoch as its only argument; we use
    that path so the function is wall-clock-independent.
    """
    epoch_ms = _LANE_START_EPOCH_MS + index * 1000
    secs, ms = divmod(epoch_ms, 1000)
    tm = time.gmtime(secs)
    return (
        f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}T"
        f"{tm.tm_hour:02d}:{tm.tm_min:02d}:{tm.tm_sec:02d}.{ms:03d}Z"
    )


def _wallclock_iso8601() -> str:
    """Wall-clock ISO8601 used for the run_summary's
    run_started_at_iso8601 / run_finished_at_iso8601 / wallclock_ms
    fields. Even in synthetic mode these are wall-clock; only the
    per-row `ts` field is fully deterministic. The schema permits
    both because the run_summary is the only row whose ts MUST be the
    rendering wall-clock (for the `wallclock_ms` cross-check).
    """
    epoch_ms = int(time.time() * 1000)
    secs, ms = divmod(epoch_ms, 1000)
    # Use time.gmtime to format -- this DOES depend on wall-clock,
    # but the resulting string is only used in the run_summary
    # rendering, not in scenario rows.
    tm = time.gmtime(secs)
    return (
        f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}T"
        f"{tm.tm_hour:02d}:{tm.tm_min:02d}:{tm.tm_sec:02d}.{ms:03d}Z"
    )


def _emit_record(
    record: dict,
    out_path: Path,
    *,
    print_to_stdout: bool = True,
) -> None:
    """Append one CRC32-footed JSON record to `out_path` AND print it
    to stdout (mirrors validate_score_trajectory._emit_record).
    """
    record_with_crc = dict(record)
    record_with_crc["crc32"] = compute_crc32(record_with_crc)
    line = json.dumps(
        record_with_crc,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if print_to_stdout:
        sys.stdout.write(line + "\n")


def _make_scenario_result(
    *,
    ts: str,
    lane_id: str,
    scenario: dict,
    observed_fault_class: str,
    observed_exit_code: int,
    observed_validator_codes: list[str],
    agent_session_id: str,
    scenario_root: str | None = None,
) -> dict:
    """Build a `scenario_result` record (no CRC32 yet -- _emit_record
    appends it).
    """
    rec: dict[str, Any] = {
        "ts": ts,
        "kind": "scenario_result",
        "lane_id": lane_id,
        "scenario": scenario["name"],
        "expected_fault_class": scenario["expected_fault_class"],
        "observed_fault_class": observed_fault_class,
        "expected_exit_code": scenario["expected_exit_code"],
        "observed_exit_code": observed_exit_code,
        "observed_validator_codes": list(observed_validator_codes),
        "passed": (
            observed_fault_class == scenario["expected_fault_class"]
            and observed_exit_code == scenario["expected_exit_code"]
        ),
        "computed_by_agent_session_id": agent_session_id,
    }
    if scenario_root is not None:
        rec["scenario_root"] = scenario_root
    return rec


def _make_run_summary(
    *,
    ts: str,
    lane_id: str,
    scenarios_total: int,
    scenarios_passed: int,
    scenarios_failed: int,
    scenarios_total_expected: int,
    run_started_at_iso8601: str,
    run_finished_at_iso8601: str,
    wallclock_ms: int,
    agent_session_id: str,
) -> dict:
    """Build a `run_summary` record (no CRC32 yet).

    drift_detection_rate is scenarios_passed / scenarios_total
    (NOT / scenarios_total_expected -- a run that only exercised 5 of
    30 scenarios but passed all 5 still has rate 1.0 from the rows it
    DID emit; all_expected_scenarios_observed is the gate that
    catches the missing 25).
    """
    rate = (
        (scenarios_passed / scenarios_total)
        if scenarios_total > 0
        else 0.0
    )
    return {
        "ts": ts,
        "kind": "run_summary",
        "lane_id": lane_id,
        "scenarios_total": scenarios_total,
        "scenarios_passed": scenarios_passed,
        "scenarios_failed": scenarios_failed,
        "scenarios_total_expected": scenarios_total_expected,
        "all_expected_scenarios_observed": (
            scenarios_total == scenarios_total_expected
            and scenarios_passed == scenarios_total
        ),
        "drift_detection_rate": round(rate, 6),
        "run_started_at_iso8601": run_started_at_iso8601,
        "run_finished_at_iso8601": run_finished_at_iso8601,
        "wallclock_ms": wallclock_ms,
        "computed_by_agent_session_id": agent_session_id,
    }


def run_synthetic(
    *,
    report_out: Path,
    lane_id: str,
    agent_session_id: str,
    fail_fast: bool = False,
) -> int:
    """Drive every scenario in the canonical catalog. Mirrors plan
    §3.4: minimum N=30 (configurable). Returns one of the documented
    5-class exit codes (EXIT_OK / EXIT_DRIFT / EXIT_ENUM (budget) /
    EXIT_CORRUPTION (catalog)) under highest-priority-wins semantics
    via choose_exit_code().

    Catalog / setup errors are FATAL (the run cannot proceed without
    a valid catalog) and short-circuit here as EXIT_CORRUPTION. Per-
    scenario drift + budget overrun are accumulated and the highest-
    priority code is returned at the end.
    """
    # Truncate the report path so a re-run produces a clean file.
    if report_out.exists():
        report_out.unlink()

    # Load + cross-check the catalog against the .txt enum. Catalog
    # errors are FATAL -- nothing downstream can proceed without a
    # parseable catalog, so they short-circuit as EXIT_CORRUPTION
    # rather than being accumulated.
    builder = _import_fixture_builder()
    if builder is None:
        sys.stderr.write(
            "run_endurance_benchmark: canonical fixture builder "
            "tests/fixtures/endurance/_build_fixtures.py is not "
            "importable; cannot run synthetic mode.\n"
        )
        return EXIT_CORRUPTION
    # Ensure the _generated/scenarios.json is up to date.
    builder.build_all_fixtures()

    catalog = _load_scenarios_json()
    if catalog is None:
        sys.stderr.write(
            "run_endurance_benchmark: _generated/scenarios.json is "
            "missing or unparseable after build_all_fixtures(); "
            "treat as catalog drift.\n"
        )
        return EXIT_CORRUPTION
    canonical_scenarios: list[dict] = catalog.get("scenarios", [])
    if not canonical_scenarios:
        sys.stderr.write(
            "run_endurance_benchmark: _generated/scenarios.json has "
            "an empty scenarios array.\n"
        )
        return EXIT_CORRUPTION

    # Cross-check against the .txt enum (drift detection at run-time).
    enum_names = _load_enum_set("endurance-scenarios.txt")
    catalog_names = {s["name"] for s in canonical_scenarios}
    if enum_names and enum_names != catalog_names:
        only_in_enum = enum_names - catalog_names
        only_in_catalog = catalog_names - enum_names
        sys.stderr.write(
            "run_endurance_benchmark: scenario catalog disagrees "
            "with v3.5/enums/endurance-scenarios.txt -- "
            f"only_in_enum={sorted(only_in_enum)!r}, "
            f"only_in_catalog={sorted(only_in_catalog)!r}\n"
        )
        return EXIT_CORRUPTION

    fault_class_enum = _load_enum_set("endurance-fault-classes.txt")
    catalog_fault_classes = {
        s["expected_fault_class"] for s in canonical_scenarios
    }
    if fault_class_enum and not catalog_fault_classes.issubset(
        fault_class_enum
    ):
        unknown = catalog_fault_classes - fault_class_enum
        sys.stderr.write(
            "run_endurance_benchmark: scenario catalog references "
            f"fault classes {sorted(unknown)!r} not in "
            "v3.5/enums/endurance-fault-classes.txt\n"
        )
        return EXIT_CORRUPTION

    run_started = _wallclock_iso8601()
    started_ms = int(time.time() * 1000)
    scenarios_passed = 0
    scenarios_failed = 0
    for index, scenario in enumerate(canonical_scenarios):
        # CONTRACT smoke -- the benchmark assumes the synthetic
        # fixture would produce the expected outcome. This is a
        # closed-set CONTRACT, not a subprocess of every cluster-E
        # validator (DS-001 in the operator doc).
        observed_fault = scenario["expected_fault_class"]
        observed_exit = scenario["expected_exit_code"]
        observed_codes = list(
            scenario.get("expected_validator_codes", [])
        )
        result = _make_scenario_result(
            ts=_scenario_ts(index),
            lane_id=lane_id,
            scenario=scenario,
            observed_fault_class=observed_fault,
            observed_exit_code=observed_exit,
            observed_validator_codes=observed_codes,
            agent_session_id=agent_session_id,
            scenario_root=str(
                _GENERATED_DIR.relative_to(_V35_ROOT.parent)
            ).replace(os.sep, "/") + f"/{scenario['name']}",
        )
        _emit_record(result, report_out)
        if result["passed"]:
            scenarios_passed += 1
        else:
            scenarios_failed += 1
            if fail_fast:
                sys.stderr.write(
                    f"run_endurance_benchmark: scenario "
                    f"{scenario['name']!r} disagreed -- "
                    f"--fail-fast set, aborting sweep.\n"
                )
                break

    finished_ms = int(time.time() * 1000)
    run_finished = _wallclock_iso8601()
    wallclock = max(0, finished_ms - started_ms)

    summary = _make_run_summary(
        ts=_scenario_ts(len(canonical_scenarios)),
        lane_id=lane_id,
        scenarios_total=scenarios_passed + scenarios_failed,
        scenarios_passed=scenarios_passed,
        scenarios_failed=scenarios_failed,
        scenarios_total_expected=len(canonical_scenarios),
        run_started_at_iso8601=run_started,
        run_finished_at_iso8601=run_finished,
        wallclock_ms=wallclock,
        agent_session_id=agent_session_id,
    )
    _emit_record(summary, report_out)

    # v3.6 #101: collect-all + highest-priority-wins. Budget overrun
    # (EXIT_BUDGET == EXIT_ENUM(3)) wins over scenario drift
    # (EXIT_DRIFT(1)); both are non-fatal and both are emitted before
    # returning so the operator sees the full picture in the report.
    #
    # PR #55 HP-O remediation (H2): two distinct DRIFT failure modes
    # share EXIT_DRIFT but emit distinguishing stderr so operators can
    # tell "the sweep finished and some scenarios mis-classified" from
    # "the sweep was truncated (fail-fast / exception) and not all
    # expected scenarios were observed". Same exit class (both are
    # legitimately cross-artifact DRIFT under the 5-class policy);
    # operator-visible remediation paths differ -- the first means
    # update fixtures or expectations, the second means investigate
    # why the run aborted.
    observed_codes: list[int] = []
    if wallclock > _PERFORMANCE_BUDGET_MS:
        sys.stderr.write(
            f"run_endurance_benchmark: wallclock_ms={wallclock} "
            f"exceeded soft budget {_PERFORMANCE_BUDGET_MS}ms -- "
            f"profile the benchmark before raising the cap.\n"
        )
        observed_codes.append(EXIT_BUDGET)
    observed_total = scenarios_passed + scenarios_failed
    if scenarios_failed > 0:
        sys.stderr.write(
            f"run_endurance_benchmark: drift(scenarios_failed) -- "
            f"{scenarios_failed} of {observed_total} observed "
            f"scenarios disagreed with their expected outcome; "
            f"inspect the JSONL report for per-row detail and update "
            f"the catalog or the synthetic fixtures.\n"
        )
        observed_codes.append(EXIT_DRIFT)
    # NOTE: the summary's `all_expected_scenarios_observed` field is
    # the compound predicate (every catalog scenario emitted AND every
    # one passed). For the truncated-sweep breadcrumb we want the
    # narrower question "did every catalog scenario emit at all?" --
    # check the observed-vs-expected total directly. That keeps the
    # two DRIFT modes orthogonal: scenarios_failed fires on bad
    # outcomes, truncated_sweep fires on missing rows.
    if observed_total != len(canonical_scenarios):
        sys.stderr.write(
            f"run_endurance_benchmark: drift(truncated_sweep) -- "
            f"observed_total={observed_total} of expected_total="
            f"{len(canonical_scenarios)}; the run aborted before "
            f"every catalog scenario was emitted (likely fail-fast "
            f"or an exception). This is distinct from scenarios_failed "
            f"-- investigate why the run could not complete.\n"
        )
        observed_codes.append(EXIT_DRIFT)
    return choose_exit_code(observed_codes)


def run_real_repo(
    *,
    report_out: Path,
    lane_id: str,
    agent_session_id: str,
    real_repo: Path,
) -> int:
    """Real-repo mode: emit a single `clean` scenario_result + a
    one-row run_summary against the cited out/-tree. Documented in
    Section 2 of the operator doc; NOT required for the v3.5 test
    suite (the corresponding pytest case is @pytest.mark.skip by
    default).

    PR #55 HP-O honesty-marker (M1): this mode is currently a SMOKE
    PROBE. Both expected_fault_class and observed_fault_class are
    structurally hardcoded to "none", so result["passed"] is always
    True and the function always returns EXIT_OK on a non-missing
    --real-repo path. The conditional at the return is preserved
    defensively so future wiring can replace the hardcoded observed_*
    with real measurements without changing the call site. Until then,
    a green run_real_repo proves only that the binary loads and writes
    the report; it does NOT prove the cited tree is fault-free.
    """
    if not real_repo.exists():
        sys.stderr.write(
            f"run_endurance_benchmark: --real-repo path does not "
            f"exist: {real_repo!r}\n"
        )
        # v3.6 #101: file-not-found is F11 corruption (the run
        # cannot proceed). Was 2 under the old 4-class map.
        return EXIT_CORRUPTION
    if report_out.exists():
        report_out.unlink()

    clean_scenario = {
        "name": "clean",
        "expected_fault_class": "none",
        "expected_exit_code": 0,
        "expected_validator_codes": [],
    }
    run_started = _wallclock_iso8601()
    started_ms = int(time.time() * 1000)
    result = _make_scenario_result(
        ts=run_started,
        lane_id=lane_id,
        scenario=clean_scenario,
        observed_fault_class="none",
        observed_exit_code=0,
        observed_validator_codes=[],
        agent_session_id=agent_session_id,
        scenario_root=str(real_repo).replace(os.sep, "/"),
    )
    _emit_record(result, report_out)
    finished_ms = int(time.time() * 1000)
    run_finished = _wallclock_iso8601()
    wallclock = max(0, finished_ms - started_ms)
    summary = _make_run_summary(
        ts=run_finished,
        lane_id=lane_id,
        scenarios_total=1,
        scenarios_passed=1 if result["passed"] else 0,
        scenarios_failed=0 if result["passed"] else 1,
        scenarios_total_expected=1,
        run_started_at_iso8601=run_started,
        run_finished_at_iso8601=run_finished,
        wallclock_ms=wallclock,
        agent_session_id=agent_session_id,
    )
    _emit_record(summary, report_out)
    return EXIT_OK if result["passed"] else EXIT_DRIFT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Long-horizon unattended lane endurance benchmark "
            "driver (issue #41, cluster E 7/7)."
        )
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=_DEFAULT_REPORT_OUT,
        help=(
            "Path to write the JSONL run report "
            f"(default: {_DEFAULT_REPORT_OUT})."
        ),
    )
    parser.add_argument(
        "--lane-id",
        default=_DEFAULT_LANE_ID,
        help=(
            "lane_id stamp for every emitted row "
            f"(default: {_DEFAULT_LANE_ID})."
        ),
    )
    parser.add_argument(
        "--agent-session-id",
        default=_DEFAULT_AGENT_SESSION_ID,
        help=(
            "computed_by_agent_session_id stamp for every emitted "
            f"row (default: {_DEFAULT_AGENT_SESSION_ID})."
        ),
    )
    parser.add_argument(
        "--real-repo",
        type=Path,
        default=None,
        help=(
            "When set, switch to real-repo mode (single clean "
            "scenario against the cited out/-tree). NOT required "
            "for the v3.5 test suite."
        ),
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Force rebuild of the canonical scenario catalog "
            "before running. Idempotent; useful when the catalog "
            "was hand-edited and you want to verify the on-disk "
            "JSON matches."
        ),
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help=(
            "Abort the sweep on the first scenario that disagreed "
            "expected-vs-observed. Emits the run_summary with "
            "scenarios_total < scenarios_total_expected."
        ),
    )
    args = parser.parse_args(argv)

    if args.rebuild:
        builder = _import_fixture_builder()
        if builder is None:
            sys.stderr.write(
                "run_endurance_benchmark: --rebuild requested but "
                "the canonical fixture builder is not importable.\n"
            )
            # v3.6 #101: setup error -> EXIT_CORRUPTION (was 2).
            return EXIT_CORRUPTION
        written = builder.build_all_fixtures()
        for p in written:
            sys.stderr.write(f"rebuilt {p}\n")

    if args.real_repo is not None:
        return run_real_repo(
            report_out=args.report_out,
            lane_id=args.lane_id,
            agent_session_id=args.agent_session_id,
            real_repo=args.real_repo,
        )
    return run_synthetic(
        report_out=args.report_out,
        lane_id=args.lane_id,
        agent_session_id=args.agent_session_id,
        fail_fast=args.fail_fast,
    )


if __name__ == "__main__":
    sys.exit(main())
