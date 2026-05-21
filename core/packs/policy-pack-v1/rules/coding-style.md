# Coding Style Rules

Purpose: Define code organization, structure, and documentation standards.

## Rules

### 1. File Organization (Many Small Files)

**Requirement**: Prefer many small, focused files over few large files.

**Rationale**:
- Easier to understand and navigate
- Better for version control (smaller diffs)
- Supports parallel work
- Improves testability

**Guidelines**:
- One primary concept per file (class, module, component)
- Group related files in directories
- Use clear, descriptive file names
- Follow language conventions for file organization

**Example Structure**:
```
src/
  auth/
    login.py          # Login logic
    logout.py         # Logout logic
    tokens.py         # Token management
    validation.py     # Input validation
  users/
    models.py         # User data models
    repository.py     # Database operations
    service.py        # Business logic
```

### 2. Immutability Preferences

**Requirement**: Prefer immutable data structures and patterns where practical.

**Guidelines**:
- Use `const` over `let` (JavaScript/TypeScript)
- Use `final` for variables (Java, Dart)
- Prefer `readonly` properties (C#, TypeScript)
- Return new objects rather than mutating
- Use immutable collections where available

**Benefits**:
- Easier to reason about code
- Fewer side effects
- Thread safety
- Better for testing

**Example**:
```python
# Prefer: Return new object
def update_user_name(user: User, new_name: str) -> User:
    return User(id=user.id, name=new_name, email=user.email)

# Avoid: Mutate in place
def update_user_name(user: User, new_name: str) -> None:
    user.name = new_name  # Side effect
```

### 3. File Size Limits

**Requirement**: Keep files within reasonable size limits.

**Limits**:
| File Type | Soft Limit | Hard Limit | Action |
|-----------|------------|------------|--------|
| Source code | 300 lines | 500 lines | Refactor/split |
| Test files | 400 lines | 600 lines | Split by feature |
| Config files | 100 lines | 200 lines | Split by concern |
| Documentation | 500 lines | 1000 lines | Split into sections |

**When Limits Exceeded**:
1. Review file for split opportunities
2. Extract related functions to new files
3. Document reason if split not feasible
4. Flag for future refactoring if blocked

### 4. Documentation Requirements

**Requirement**: Document code appropriately for maintainability.

**What to Document**:
| Element | Documentation Required |
|---------|------------------------|
| Public APIs | Always (purpose, params, returns) |
| Complex logic | Explain the "why" |
| Non-obvious behavior | Clarify intent |
| Workarounds | Document reason and ticket |
| Configuration | Explain options and defaults |

**What Not to Document**:
- Obvious code (self-documenting names)
- Implementation details that may change
- Comments that just repeat the code

**Documentation Format**:
- Use language-standard doc comments
- Follow project style guide if exists
- Keep docs close to code (in-file)
- Update docs when code changes

**Example**:
```python
def calculate_tax(amount: Decimal, rate: Decimal) -> Decimal:
    """
    Calculate tax amount.

    Args:
        amount: Pre-tax amount in dollars
        rate: Tax rate as decimal (e.g., 0.08 for 8%)

    Returns:
        Tax amount rounded to 2 decimal places

    Raises:
        ValueError: If rate is negative
    """
    if rate < 0:
        raise ValueError("Tax rate cannot be negative")
    return (amount * rate).quantize(Decimal("0.01"))
```

### 5. Naming Conventions

**Requirement**: Use clear, consistent naming.

**General Principles**:
- Names should reveal intent
- Avoid abbreviations (except well-known: id, url, html)
- Use domain terminology consistently
- Length proportional to scope (short for local, longer for global)

**Language-Specific**:
Follow language conventions:
- Python: `snake_case` for functions/variables, `PascalCase` for classes
- JavaScript/TypeScript: `camelCase` for functions/variables, `PascalCase` for classes
- C#: `PascalCase` for public, `_camelCase` for private fields
- Go: `PascalCase` for exported, `camelCase` for unexported

### 6. Error Handling

**Requirement**: Handle errors explicitly and consistently.

**Guidelines**:
- Don't swallow errors silently
- Use language-appropriate error types
- Log errors with context
- Fail fast on unrecoverable errors
- Provide meaningful error messages

**Example**:
```python
# Good: Explicit handling with context
try:
    result = parse_config(file_path)
except ConfigError as e:
    logger.error(f"Failed to parse config at {file_path}: {e}")
    raise

# Bad: Silent failure
try:
    result = parse_config(file_path)
except:
    pass  # What happened?
```

## Enforcement Checklist

Before committing code:

- [ ] Files are focused and within size limits
- [ ] Immutability preferred where practical
- [ ] Public APIs documented
- [ ] Naming is clear and consistent
- [ ] Errors handled explicitly

## Exceptions

| Exception | Documentation Required |
|-----------|------------------------|
| Legacy file exceeds limits | Document refactoring plan |
| Mutable state required | Document why (performance, API) |
| Generated code | Mark as generated, exclude from lint |

## Cross-References

- Evidence requirements: `core/packs/policy-pack-v1/EVIDENCE.md`
- Language instructions: `core/workflows/instructions/`
- Code execution: `core/orchestrator/CODE_EXECUTION_CONTRACT.md`
