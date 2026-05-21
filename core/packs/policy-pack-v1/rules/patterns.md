# patterns.md (Rules)

Purpose: Define common patterns for consistency across the codebase.

Related docs:
- `core/workflows/skills/backend-patterns.md` (backend patterns skill)
- `core/workflows/skills/coding-standards.md` (coding standards)

---

## API Response Format Standards

### Success Response Structure
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "timestamp": "2024-01-01T00:00:00Z",
    "requestId": "uuid",
    "version": "1.0"
  }
}
```

### Error Response Structure
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": [
      {
        "field": "email",
        "issue": "Invalid format"
      }
    ]
  },
  "meta": {
    "timestamp": "2024-01-01T00:00:00Z",
    "requestId": "uuid"
  }
}
```

### Standard Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| VALIDATION_ERROR | 400 | Invalid input |
| UNAUTHORIZED | 401 | Authentication required |
| FORBIDDEN | 403 | Permission denied |
| NOT_FOUND | 404 | Resource not found |
| CONFLICT | 409 | State conflict |
| RATE_LIMITED | 429 | Too many requests |
| INTERNAL_ERROR | 500 | Server error |

---

## Error Handling Conventions

### Exception Hierarchy
```
BaseError
├── ValidationError (client input issues)
├── AuthenticationError (identity issues)
├── AuthorizationError (permission issues)
├── NotFoundError (resource missing)
├── ConflictError (state conflicts)
└── InternalError (system failures)
```

### Error Handling Rules
1. Catch specific exceptions, not generic
2. Log errors with full context
3. Return user-safe messages externally
4. Include correlation IDs for tracing
5. Never expose stack traces in production

### Error Logging Format
```
[ERROR] <timestamp> [<requestId>] <error-code>: <message>
  Context: <relevant-context>
  Stack: <stack-trace> (internal logs only)
```

---

## Logging Patterns

### Log Levels Usage

| Level | When to Use | Examples |
|-------|-------------|----------|
| ERROR | System failures, unhandled exceptions | Database down, critical failure |
| WARN | Handled but unexpected conditions | Retry succeeded, fallback used |
| INFO | Business events, significant actions | User login, order placed |
| DEBUG | Development diagnostics | Function entry/exit, variable values |

### Structured Logging Format
```json
{
  "timestamp": "ISO-8601",
  "level": "INFO",
  "service": "user-service",
  "requestId": "correlation-id",
  "message": "User authenticated",
  "context": {
    "userId": "123",
    "method": "oauth"
  }
}
```

### What to Log
- Request entry and exit
- Business events
- Error conditions
- Performance metrics
- Security events

### What NOT to Log
- Sensitive data (passwords, tokens)
- PII without masking
- Full request/response bodies in production
- High-frequency debug in production

---

## Configuration Management

### Configuration Sources (Priority Order)
1. Command-line arguments (highest)
2. Environment variables
3. Configuration files
4. Default values (lowest)

### Configuration Patterns
```
config/
├── default.yaml      # Base defaults
├── development.yaml  # Dev overrides
├── production.yaml   # Prod overrides
└── local.yaml        # Local (gitignored)
```

### Configuration Rules
- Never commit secrets to config files
- Use environment variables for sensitive values
- Validate configuration at startup
- Fail fast on missing required config
- Document all configuration options

### Environment Variable Naming
```
<APP>_<SECTION>_<KEY>
Example: MYAPP_DATABASE_HOST
```

---

## Evidence Capture

```markdown
## Patterns Compliance

### API Responses
- [ ] Success format matches standard
- [ ] Error format matches standard
- [ ] Error codes are from approved list

### Error Handling
- [ ] Exceptions follow hierarchy
- [ ] Errors are logged with context
- [ ] User messages are safe

### Logging
- [ ] Log levels are appropriate
- [ ] Structured format is used
- [ ] No sensitive data logged

### Configuration
- [ ] Follows priority order
- [ ] No secrets in files
- [ ] Validated at startup
```
