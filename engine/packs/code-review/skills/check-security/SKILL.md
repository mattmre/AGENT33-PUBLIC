---
name: check-security
version: 1.0.0
description: Scan code for security vulnerabilities and unsafe patterns with remediation guidance.
allowed_tools:
  - file_ops
  - shell
tags:
  - security
  - code-review
  - vulnerability
---

# Check Security

Perform a targeted security review of code changes or files. Identify exploitable
vulnerabilities, unsafe library usage, and insecure configuration patterns.

## Vulnerability Categories to Check

1. **Injection** — SQL injection, command injection, LDAP injection, XPath injection.
   Look for string concatenation in queries, use of `eval`, `exec`, `os.system`.
2. **Authentication / Authorization** — hardcoded credentials, missing auth checks,
   privilege escalation paths, JWT verification bypass patterns.
3. **Cryptography** — use of deprecated algorithms (MD5, SHA-1 for security, DES),
   hardcoded keys or IVs, insufficient entropy in secrets generation.
4. **Input Validation** — unvalidated or unsanitized user input passed to parsers,
   file paths, or external calls. Path traversal risks (`../`).
5. **Dependency Risk** — use of known-vulnerable library versions flagged in
   CHANGELOG or CVE databases; use of unmaintained packages.
6. **Secret Leakage** — API keys, passwords, tokens committed to code or logged.
7. **Resource Management** — unbounded loops or memory allocations on user-controlled
   input; missing rate limiting; unclosed file handles or connections.

## Procedure

1. Obtain the code to review (file path or diff). Use `file_ops` to read files.
2. Scan each file for the vulnerability categories above.
3. For each finding, record:
   - **CVE/CWE reference** if applicable (e.g., CWE-89 for SQL injection)
   - File and line number
   - Vulnerability category
   - Severity: `[BLOCKING]` (for critical/high impact) or `[ADVISORY]` (for medium/low impact)
   - A clear explanation of how this could be exploited
   - A concrete remediation step
4. Summarize total findings by severity.

## Output Format

```
## Security Review: <scope>

### Findings

**[BLOCKING] — File.py:88 — SQL Injection (CWE-89)**
Risk: User input is concatenated directly into a SQL query string, allowing an
attacker to alter query logic or exfiltrate the database.
Fix: Use parameterized queries: `cursor.execute("SELECT * FROM t WHERE id = %s", (user_id,))`

**[ADVISORY] — config.py:12 — Hardcoded Default Secret**
Risk: The default SECRET_KEY value is a weak placeholder; if not overridden in
production it is trivially guessable.
Fix: Remove the default; raise ValueError if SECRET_KEY is not set via environment.

### Summary
[BLOCKING]: 1  [ADVISORY]: 1
```

## Quality Rules

- Report every finding, not just the most severe.
- Never mark a hardcoded credential as [ADVISORY]; credentials are always [BLOCKING].
- Provide a concrete fix for every finding, not just "sanitize this input."
- If no security issues are found, state "No security issues identified." explicitly.
