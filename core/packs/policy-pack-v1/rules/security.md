# Security Rules

Purpose: Define security requirements and constraints for agent-generated code and operations.

## Rules

### 1. No Hardcoded Secrets

**Requirement**: Never embed secrets, credentials, API keys, or tokens directly in code.

**Applies To**:
- Source code files
- Configuration files (except `.example` templates)
- Documentation (except sanitized examples)
- Commit messages and PR descriptions

**Enforcement**:
- Scan diffs for common secret patterns before commit
- Flag any string resembling credentials for human review
- Use environment variables or secrets managers

**Example Violations**:
```python
# BAD: Hardcoded API key
api_key = "sk-1234567890abcdef"

# GOOD: Environment variable
api_key = os.environ.get("API_KEY")
```

### 2. Input Validation Requirements

**Requirement**: All external input must be validated before use.

**Applies To**:
- User input (forms, CLI arguments, API requests)
- File contents from untrusted sources
- Data from external APIs or services
- Configuration from user-provided files

**Enforcement**:
- Validate type, length, format, and range
- Reject invalid input early (fail fast)
- Log validation failures for audit
- Use allowlists over denylists where possible

**Example**:
```python
# Validate before use
def process_user_id(user_id: str) -> int:
    if not user_id.isdigit():
        raise ValueError("User ID must be numeric")
    id_int = int(user_id)
    if id_int <= 0 or id_int > MAX_USER_ID:
        raise ValueError("User ID out of valid range")
    return id_int
```

### 3. Parameterized Queries

**Requirement**: Use parameterized queries or prepared statements for all database operations.

**Applies To**:
- SQL databases
- NoSQL databases with query languages
- Any data store with injection risk

**Enforcement**:
- Never concatenate user input into queries
- Use ORM query builders or prepared statements
- Review raw query construction for injection risk

**Example**:
```python
# BAD: SQL injection risk
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")

# GOOD: Parameterized query
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### 4. CSRF Protection

**Requirement**: Implement CSRF protection for state-changing operations in web applications.

**Applies To**:
- Form submissions
- AJAX requests that modify state
- API endpoints accepting browser requests

**Enforcement**:
- Use framework-provided CSRF tokens
- Validate origin/referer headers
- Implement SameSite cookie attributes

### 5. XSS Prevention

**Requirement**: Sanitize and escape output to prevent cross-site scripting.

**Applies To**:
- HTML output
- JavaScript string embedding
- URL construction with user data

**Enforcement**:
- Use framework auto-escaping
- Apply context-appropriate encoding (HTML, JS, URL)
- Validate and sanitize rich text input

**Example**:
```python
# BAD: XSS risk
return f"<div>{user_input}</div>"

# GOOD: Escaped output
from markupsafe import escape
return f"<div>{escape(user_input)}</div>"
```

### 6. Security Review Triggers

**Requirement**: Changes matching these patterns require security-focused review.

**Triggers**:
- Authentication or authorization logic changes
- Cryptographic code (hashing, encryption, signing)
- Session management modifications
- Input parsing for untrusted data
- File upload or download handling
- External service integration
- Permission or access control changes

**Process**:
1. Flag the change as security-relevant in PR description
2. Request review from security-aware reviewer
3. Document security considerations in DECISIONS
4. Run security-focused tests (if available)

## Exceptions

Valid reasons to deviate from these rules:

| Exception | Documentation Required |
|-----------|------------------------|
| Legacy code retrofit | Document plan to remediate |
| Test fixtures with fake secrets | Mark clearly as test data |
| Security research/demonstration | Isolate from production code |

## Enforcement Checklist

Before committing security-relevant changes:

- [ ] No hardcoded secrets in diff
- [ ] User input validated at entry points
- [ ] Database queries use parameters
- [ ] Output properly escaped for context
- [ ] Security review triggered if applicable

## Cross-References

- Risk triggers: `core/packs/policy-pack-v1/RISK_TRIGGERS.md`
- Security hardening: `core/orchestrator/SECURITY_HARDENING.md`
- Evidence capture: `core/packs/policy-pack-v1/EVIDENCE.md`
- Two-layer review: `core/orchestrator/TWO_LAYER_REVIEW.md`
