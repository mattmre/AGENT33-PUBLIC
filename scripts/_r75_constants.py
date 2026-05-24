"""scripts/_r75_constants.py — single source of truth for the R75 safety
backstop, the closed frozenset of source-tier tokens that may back a
production-tier evidence claim. Both the gate
(`scripts/check_research_sources.py`) and the validator
(`scripts/validate_pr_brutal_honesty/_shared.py`) must honour the same
backstop.

v3.7 pass-2 SYNTHESIS H-1 (CV-1; convergent finding raised
independently by reviewer R6 and reviewer R9) flagged that the frozenset
`{authoritative-spec, vendor-doc, peer-reviewed}` was defined in TWO
modules — `scripts/check_research_sources.py:153` AND
`scripts/validate_pr_brutal_honesty/_shared.py:2043`. If a maintainer
raised one (e.g. promoted `industry-report` to backable status) without
the other, defense-in-depth would degrade silently in the same hazard
shape as the closed R74 case. The R74 hazard was first mitigated by a
drift-trap test in v3.6 #119 and then structurally closed in v3.7 Lane
1+2 via `scripts/_r74_constants.py`. v3.7-final HP Lane A applies the
exact same pattern to R75: a single shared module that both the gate
and the validator import from, plus a drift-trap test that asserts
`is`-identity (object-identity, not just value-equality) across all
consumers.

Two names are exported on purpose:

  * `R75_PROD_TIER_BACKSTOP` -- the canonical, public name. New code
    should import this.
  * `_R75_PROD_TIER_BACKSTOP` -- back-compat alias. The original
    module-level constant was private (leading underscore) and several
    callers / tests historically reached in via the private name. The
    alias keeps those imports working while signalling that the name
    is no longer a single-module private.

Both names refer to the SAME Python frozenset object. Adding a new
source-tier token to the backstop requires editing this file (one
line), which automatically flows to every importer. The drift-trap
test `test_r75_prod_tier_backstop_constants_are_identical_across_modules`
(in `v3.5/tests/test_check_research_sources.py`) pins all consumers to
the same object via `is`-identity, so any future contributor who
accidentally re-introduces a local literal in a downstream module
breaks the test at CI time instead of in production.
"""

from __future__ import annotations


# The R75 production-tier backstop. A claim of `production-like-
# sanitized`, `operator-approved-release`, or `human-curated-corpus`
# evidence_tier MUST cite at least one source whose source_tier is in
# this frozenset, regardless of what the source-tier-backing-rule.yaml
# policy says. The YAML for production tiers is documentation-of-
# intent; this frozenset is load-bearing. The gate enforces the rule
# at PR-author time; the validator's R75c trips at CI time on the
# emitted ledger artifact when either prod_tier_claims_unbacked_total
# or dangling_source_id_total is non-zero.
R75_PROD_TIER_BACKSTOP: frozenset[str] = frozenset({
    "authoritative-spec",
    "vendor-doc",
    "peer-reviewed",
})


# Back-compat alias for callers / tests that import the original
# private name. The historical contract was a module-level constant
# named `_R75_PROD_TIER_BACKSTOP`; the underscore prefix signalled
# "private to this module" but in practice the constant was duplicated
# across modules and (post v3.7-final HP Lane A) is pinned by the
# drift-trap test. The alias preserves that import surface while the
# canonical name is exported without the underscore. Aliasing via
# direct assignment (not a copy) keeps `is`-identity between the two
# names AND between every consumer that imports from this module.
_R75_PROD_TIER_BACKSTOP: frozenset[str] = R75_PROD_TIER_BACKSTOP
