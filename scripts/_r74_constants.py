"""scripts/_r74_constants.py — single source of truth for the R74 safety
backstop, the maximum-cost-USD cap that the gate and the validator must
both honour.

v3.6 #119 (cluster G LOW spillover) flagged that the literal `100.00`
was defined in TWO modules — `scripts/check_external_policy.py` AND
`scripts/validate_pr_brutal_honesty.py`. If a maintainer raised one
without the other, defense-in-depth degraded silently. The v3.6 patch
shipped a drift-trap test
(`tests/test_validator_r74.py::test_r74_cost_cap_backstop_constants_are_identical_across_modules`)
pinning the two literals together so silent drift breaks at CI time.
v3.7 carry #2 is the structural fix: a single shared module that both
the gate and the validator import from. The drift-trap test continues
to pass after the migration because both modules end up resolving the
same Python object.

Two names are exported on purpose:

  * `R74_COST_USD_CAP_BACKSTOP` -- the canonical, public name. New
    code should import this.
  * `_R74_COST_USD_CAP_BACKSTOP` -- back-compat alias. The original
    module-level constant was private (leading underscore) and several
    callers / tests historically reached in via the private name. The
    alias keeps those imports working while signalling that the name
    is no longer a single-module private.

Both names refer to the same Python float object. Raising the
backstop requires editing this file (one line), which automatically
flows to every importer. Lane 2 of v3.7 wires the gate side; the
validator side is wired in v3.7 lane 1 (this commit's sibling).
"""

from __future__ import annotations


# The R74 cost-USD safety backstop. The effective cap is
# `min(recorded cost_usd_cap, R74_COST_USD_CAP_BACKSTOP)` -- the gate
# and the validator both apply this min to ensure a permissive YAML
# policy cannot loosen the safety floor.
R74_COST_USD_CAP_BACKSTOP: float = 100.00


# Back-compat alias for callers / tests that import the original
# private name. The historical contract was a module constant named
# `_R74_COST_USD_CAP_BACKSTOP`; the underscore prefix signalled
# "private to this module" but in practice the constant was duplicated
# across modules and pinned by the v3.6 drift-trap test. The alias
# preserves that import surface while the canonical name is exported
# without the underscore.
_R74_COST_USD_CAP_BACKSTOP: float = R74_COST_USD_CAP_BACKSTOP
