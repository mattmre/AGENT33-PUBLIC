"""scripts/_r76_constants.py — single source of truth for the v3.7.1
R76 / R77 / R78 gate-skip-loophole closure constants.

v3.7.1 closes the EDCStampClipper "100/100 candidate self-audit"
loophole observed downstream: a session declared work `100/100` with
no PR, no Tier B, and an unset `REFERENCE_CORPUS_URL` (gate did not
actually run). Three new validator rules (`R76`, `R77`, `R78`) defend
against the pattern; each rule reads its substring / token tables
from this module so the validator and any future co-author tool
(linter, pre-commit hook, etc.) resolve the SAME Python objects.

This module follows the v3.7 #2 / v3.7-final HP Lane A precedent set
by `scripts/_r74_constants.py` and `scripts/_r75_constants.py`: the
load-bearing closed sets live in ONE module so a maintainer who
extends the pattern table (e.g. adds `awaiting credential` to the
R76 skip-implying substrings) edits ONE place and every importer
sees the update atomically. The R76/R77/R78 tables do not (yet) have
a drift-trap test pinning `is`-identity across modules. R79's
severity-cap constants live in `scripts/validate_pr_brutal_honesty/
_r79_logic.py` and R80's threshold + token tables live in
`_r80_logic.py`; the v4.0 closeout partition reclaimed R79 and R80
into v3.7.1 from the original deferral list (v4.0 is a complete
platform rewrite with no landing surface for deferred work).

Exported sets:

  * `_R76_SKIP_PATTERNS` -- substrings that imply a gate skipped
    in SMOKE / EVIDENCE prose. Matched case-insensitively against
    the field value. Closed set per charter §1.3 R76.
  * `_R76_EMPTY_SKIPPED_GATES_TOKENS` -- the SKIPPED_GATES values
    that the validator treats as "empty disclosure" (the R76 FAIL
    fires only when SKIP_PATTERNS appears AND SKIPPED_GATES is in
    this token set).
  * `_R78_HUNDRED_TOKENS` -- substrings declaring a 100/100 score.
    R78 FAILs only when one of these AND one of the candidate
    tokens appears in the body.
  * `_R78_CANDIDATE_TOKENS` -- substrings declaring "candidate" /
    "self-audit" / "pending tier b" language. R78's second prong.
  * `_R77_INLINE_SUBSTRING_TOKENS` -- substrings that trip R77
    regardless of whether the enum file is present on disk. The
    enum file (`v3.5/docs/conventions/brutal-honesty-kit/v3.5/
    enums/tier-b-sentinel-rejected.txt`, written by v3.7.1 Agent
    B) holds the full closed set; this inline list is the
    back-compat floor so R77 still fires on the most common
    sentinels even in a checkout that pre-dates the enum file.

All sets are `frozenset[str]` with all-lowercase contents (the
validator lower-cases the field value before membership check).
"""

from __future__ import annotations


# R76 -- substrings that imply a gate skipped in SMOKE / EVIDENCE
# prose. The R76 FAIL fires when ANY of these substrings appears in
# SMOKE: or EVIDENCE: (case-insensitive) AND the SKIPPED_GATES: field
# is empty / placeholder. See charter §1.3 R76 for the closed-set
# rationale.
_R76_SKIP_PATTERNS: frozenset[str] = frozenset({
    "unset",
    "not set",
    "env var missing",
    "credential missing",
    "skipped",
    "fell back",
    "fallback",
    "not applicable",
    "n/a — env",  # en-dash form
    "n/a - env",       # ASCII hyphen variant
    "n/a env",
    "awaiting fixture",
})


# R76 -- the SKIPPED_GATES values the validator treats as "empty
# disclosure". When SKIPPED_GATES is in this set AND SMOKE / EVIDENCE
# contains a `_R76_SKIP_PATTERNS` substring, R76 fires. The empty
# string is included so a SKIPPED_GATES field present with no value
# is also caught.
_R76_EMPTY_SKIPPED_GATES_TOKENS: frozenset[str] = frozenset({
    "",
    "_none_",
    "_none yet_",
    "none",
    "n/a",
})


# R78 -- substrings declaring a 100/100 score. R78's first prong.
# All lowercase; the validator lower-cases the body text before scan.
_R78_HUNDRED_TOKENS: frozenset[str] = frozenset({
    "100/100",
    "bhs_official: 100",
    "bhs_official=100",
    "bhs = 100",
    "bhs: 100",
})


# R78 -- substrings declaring candidate / self-audit / pending Tier B
# language. R78's second prong. R78 FAILs when the body contains
# ANY `_R78_HUNDRED_TOKENS` substring AND ANY `_R78_CANDIDATE_TOKENS`
# substring (case-insensitive).
_R78_CANDIDATE_TOKENS: frozenset[str] = frozenset({
    "candidate",
    "self-audit",
    "pending tier b",
    "awaiting tier b",
    "tier b pending",
    "tier b tbd",
})


# R77 -- inline substring tokens that trip R77 regardless of whether
# the enum file `tier-b-sentinel-rejected.txt` is present on disk.
# The validator loads the full closed set from the enum file at
# module import time; this inline list is the back-compat floor so
# R77 still fires on the common sentinels even in a checkout that
# pre-dates the enum file. Matched as substrings against the
# normalized BHS_TIER_B_AGENT value.
_R77_INLINE_SUBSTRING_TOKENS: frozenset[str] = frozenset({
    "self-audit",
    "candidate self",
    "pending tier b",
    "awaiting tier b",
    "(none yet)",
    "tbd",
    "same agent",
})


# Bottom-of-file invariants. These run at import time so any
# accidental future edit that drops a frozenset to a list/set, or
# slips a non-string into a table, breaks at import (not at the
# first failing test). The lowercase invariant pins the contract
# that the validator lower-cases the field value before membership
# check; a future maintainer who adds a mixed-case substring would
# silently degrade R76/R77/R78 sensitivity without this assert.
assert isinstance(_R76_SKIP_PATTERNS, frozenset)
assert isinstance(_R76_EMPTY_SKIPPED_GATES_TOKENS, frozenset)
assert isinstance(_R78_HUNDRED_TOKENS, frozenset)
assert isinstance(_R78_CANDIDATE_TOKENS, frozenset)
assert isinstance(_R77_INLINE_SUBSTRING_TOKENS, frozenset)
assert all(isinstance(x, str) for x in _R76_SKIP_PATTERNS)
assert all(isinstance(x, str) for x in _R76_EMPTY_SKIPPED_GATES_TOKENS)
assert all(isinstance(x, str) for x in _R78_HUNDRED_TOKENS)
assert all(isinstance(x, str) for x in _R78_CANDIDATE_TOKENS)
assert all(isinstance(x, str) for x in _R77_INLINE_SUBSTRING_TOKENS)
assert all(x == x.lower() for x in _R76_SKIP_PATTERNS)
assert all(x == x.lower() for x in _R76_EMPTY_SKIPPED_GATES_TOKENS)
assert all(x == x.lower() for x in _R78_HUNDRED_TOKENS)
assert all(x == x.lower() for x in _R78_CANDIDATE_TOKENS)
assert all(x == x.lower() for x in _R77_INLINE_SUBSTRING_TOKENS)
