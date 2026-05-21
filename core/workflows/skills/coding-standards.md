# coding-standards Skill

Purpose: Provide consistent coding standards and best practices across projects.

Related docs:
- `core/workflows/commands/refactor.md` (refactor command)
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture)

---

## Skill Signature

```
invoke: coding-standards
inputs: language, context
outputs: applicable-standards, checklist
```

---

## File Organization

### Directory Structure Principles
- Group by feature/domain, not by type
- Keep related files close together
- Limit directory depth (prefer flat over deep)
- Use consistent naming for common directories

### File Naming
- Use lowercase with separators (kebab-case or snake_case)
- Be descriptive but concise
- Include type suffix when helpful (e.g., `.test.`, `.config.`)
- Avoid special characters except `-` and `_`

### File Size
- Prefer smaller, focused files
- Split when file exceeds ~300-500 lines
- Extract reusable components

---

## Naming Conventions

### General Principles
- Names should reveal intent
- Avoid abbreviations (except well-known ones)
- Be consistent within project
- Avoid encodings (Hungarian notation, etc.)

### Specific Patterns

| Element | Pattern | Examples |
|---------|---------|----------|
| Variables | Descriptive nouns | `userCount`, `isEnabled` |
| Functions | Verb + noun | `getUserById`, `validateInput` |
| Classes | Noun phrases | `UserRepository`, `PaymentService` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Booleans | is/has/can prefix | `isValid`, `hasPermission`, `canEdit` |

---

## Error Handling Patterns

### Principles
- Fail fast and explicitly
- Provide actionable error messages
- Log errors with context
- Don't swallow exceptions silently

### Error Message Format
```
What happened: <description>
Why it happened: <cause if known>
What to do: <suggested action>
```

### Exception Handling
- Catch specific exceptions, not generic
- Re-throw with context when wrapping
- Use custom exceptions for domain errors
- Log at appropriate level

---

## Documentation Requirements

### Code Comments
- Explain "why", not "what"
- Document non-obvious decisions
- Keep comments current with code
- Use standard doc formats (JSDoc, docstrings, etc.)

### Function/Method Documentation
- Purpose/description
- Parameters and types
- Return value and type
- Exceptions thrown
- Usage example (for public APIs)

### README Requirements
- Project purpose
- Quick start instructions
- Prerequisites
- Configuration options
- Common tasks

---

## Code Review Checklist

### Readability
- [ ] Code is self-explanatory
- [ ] Names are clear and consistent
- [ ] Functions are focused (single responsibility)
- [ ] Complexity is manageable

### Correctness
- [ ] Logic is sound
- [ ] Edge cases are handled
- [ ] Error paths are covered
- [ ] Tests verify behavior

### Maintainability
- [ ] No code duplication
- [ ] Dependencies are reasonable
- [ ] Changes are isolated
- [ ] Future extension is possible

### Performance
- [ ] No obvious inefficiencies
- [ ] Resource cleanup is proper
- [ ] Loops and recursion are bounded

---

## Language-Neutral Best Practices

### Control Flow
- Prefer early returns over deep nesting
- Use guard clauses
- Keep conditionals simple
- Avoid negative conditionals when possible

### Functions
- Keep functions short (< 20 lines ideal)
- Limit parameters (< 4 ideal)
- Return early, return often
- Avoid side effects where possible

### Data
- Prefer immutability when practical
- Initialize close to use
- Validate at boundaries
- Transform early, use typed data internally

---

## Evidence Capture

```markdown
## Coding Standards Review

### Scope
- Files reviewed: `<file-list>`
- Standards applied: <language-specific>

### Findings
- [ ] <file>: <issue> - <recommendation>

### Metrics
- Naming consistency: X%
- Documentation coverage: Y%
- Complexity score: Z
```
