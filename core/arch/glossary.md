# Architecture & Planning Glossary

- finding: A single validated issue requiring remediation or defer decision.
- tier: Severity grouping (Critical, High, Medium, Low).
- blocked: Item cannot proceed without external dependency; requires an unblock plan.
- deferred: Item intentionally postponed with target date and exit criteria.
- unblock plan: Documented steps to remove a blocker with owner and target date.
- phase summary: Short recap after a PR or tier step (closed, remaining, next).
- cycle-id: Unique identifier for a remediation cycle (format `AEP-YYYYMMDD-N`, with N as a global increment).
- cycle: Scope lock + backlog + tracker + remediation loop for one cycle-id.
