# backend-patterns Skill

Purpose: Provide consistent backend development patterns and best practices.

Related docs:
- `core/workflows/skills/security-review.md` (security considerations)
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture)

---

## Skill Signature

```
invoke: backend-patterns
inputs: pattern-type, context
outputs: applicable-patterns, implementation-guidance
```

---

## API Design Patterns

### REST Conventions

| Method | Purpose | Response Codes |
|--------|---------|----------------|
| GET | Retrieve resource(s) | 200, 404 |
| POST | Create resource | 201, 400, 409 |
| PUT | Replace resource | 200, 201, 404 |
| PATCH | Partial update | 200, 404 |
| DELETE | Remove resource | 204, 404 |

### URL Structure
```
/api/v1/<resource>              # Collection
/api/v1/<resource>/<id>         # Single resource
/api/v1/<resource>/<id>/<sub>   # Sub-resource
```

### API Response Format

#### Success Response
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "ISO-8601",
    "requestId": "uuid"
  }
}
```

#### Error Response
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": [ ... ]
  },
  "meta": {
    "timestamp": "ISO-8601",
    "requestId": "uuid"
  }
}
```

### Pagination
```json
{
  "data": [ ... ],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 100,
    "totalPages": 5
  }
}
```

---

## Database Access Patterns

### Repository Pattern
- Encapsulate data access logic
- Provide collection-like interface
- Enable testability with mock implementations
- Keep domain logic separate from persistence

### Repository Interface
```
interface Repository<T>:
  findById(id) -> T | null
  findAll(criteria?) -> T[]
  save(entity) -> T
  delete(id) -> void
```

### Query Patterns
- Use parameterized queries (never string concatenation)
- Limit result sets with pagination
- Use indexes for frequently queried fields
- Log slow queries

### Transaction Patterns
- Keep transactions short
- Define clear transaction boundaries
- Handle rollback scenarios
- Avoid distributed transactions when possible

---

## Caching Strategies

### Cache Patterns

| Pattern | Use Case | Trade-offs |
|---------|----------|------------|
| Cache-aside | Read-heavy, tolerate stale | Complexity, potential inconsistency |
| Write-through | Consistency critical | Higher latency on writes |
| Write-behind | High write volume | Potential data loss |
| Refresh-ahead | Predictable access | Wasted refreshes |

### Cache Key Design
```
<namespace>:<entity>:<id>:<version?>
example: users:profile:12345
```

### Cache Invalidation
- Set appropriate TTLs
- Invalidate on write operations
- Use versioning for complex invalidation
- Monitor hit/miss ratios

---

## Authentication Patterns

### Token-Based Authentication

1. **Access tokens**: Short-lived, carries claims
2. **Refresh tokens**: Long-lived, secure storage
3. **Token rotation**: Issue new refresh on use

### Session Patterns
- Store minimal data in session
- Use secure session IDs
- Implement session timeout
- Support concurrent session limits

### API Authentication
- Use Authorization header
- Validate token signature
- Check token expiration
- Verify audience/issuer claims

---

## Error Handling

### Error Categories

| Category | HTTP Code | Retry |
|----------|-----------|-------|
| Client error | 4xx | No |
| Server error | 5xx | Maybe |
| Rate limit | 429 | Yes, with backoff |
| Unavailable | 503 | Yes, with backoff |

### Error Codes
- Use consistent error code format
- Include machine-readable code
- Provide human-readable message
- Add context-specific details

---

## Logging Patterns

### Log Levels

| Level | Use For |
|-------|---------|
| ERROR | Failures requiring attention |
| WARN | Unexpected but handled situations |
| INFO | Significant business events |
| DEBUG | Development troubleshooting |

### Log Structure
```json
{
  "timestamp": "ISO-8601",
  "level": "INFO",
  "message": "User logged in",
  "context": {
    "userId": "123",
    "requestId": "abc"
  }
}
```

---

## Evidence Capture

```markdown
## Backend Patterns Review

### Patterns Applied
- API Design: REST conventions followed
- Database: Repository pattern implemented
- Caching: Cache-aside with TTL

### Compliance
- [ ] Endpoints follow REST conventions
- [ ] Error responses are consistent
- [ ] Data access is encapsulated
- [ ] Caching strategy is documented
```
