# /e2e Command

Purpose: Generate or run end-to-end tests for critical flows.

Related docs:
- `core/packs/policy-pack-v1/EVIDENCE.md` (evidence capture)
- `core/arch/test-matrix.md` (test strategy)

---

## Command Signature

```
/e2e [action] [flow]
```

Actions: `generate`, `run`, `verify`

## Workflow

### 1. Identify Critical Flows
- Map user journeys and business flows
- Prioritize by risk and frequency
- Define test boundaries

### 2. Create Test Scenarios
- Write scenario descriptions
- Define preconditions and postconditions
- Specify expected outcomes

### 3. Generate/Run Tests
- Create test files (if generating)
- Execute test suite
- Capture results

### 4. Capture Evidence
- Document test outcomes
- Screenshot/log critical steps (if applicable)
- Update TASKS.md

---

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| action | No | generate, run, or verify (default: run) |
| flow | No | Specific flow to test |
| config | No | Test configuration override |

---

## Outputs

| Output | Description |
|--------|-------------|
| Test files | E2E test scripts (if generating) |
| Results | Test execution summary |
| Evidence | Screenshots, logs, reports |
| TASKS.md update | E2E status logged |

---

## Critical Flow Identification

Prioritize flows by:
1. **Business impact**: Revenue, user retention
2. **Frequency**: Most common user paths
3. **Risk**: Error-prone or recently changed
4. **Compliance**: Regulatory requirements

---

## Test Scenario Template

```markdown
## Scenario: <name>

### Preconditions
- User state: <logged in/guest/admin>
- Data state: <required fixtures>
- System state: <services running>

### Steps
1. <action>
2. <action>
3. <action>

### Expected Outcome
- <assertion>
- <assertion>

### Postconditions
- <cleanup actions>
```

---

## Evidence Capture

```markdown
## E2E Test Evidence

### Test Run
- Command: `<e2e-command>`
- Environment: <test/staging>
- Timestamp: <datetime>

### Results
- Total: X tests
- Passed: Y
- Failed: Z

### Failures (if any)
- Scenario: <name>
- Step: <failed step>
- Error: <message>

### Artifacts
- Report: <path-to-report>
- Logs: <path-to-logs>
```

---

## Flow Categories

| Category | Examples |
|----------|----------|
| Authentication | Login, logout, password reset |
| Core features | Main user workflows |
| Transactions | Payments, orders, submissions |
| Admin | User management, configuration |
| Integration | Third-party service interactions |

---

## Example Usage

```
/e2e generate "user registration flow"
```

Flow:
1. Analyze registration feature code
2. Identify steps: form fill, validation, confirmation
3. Generate test file with scenarios
4. Run tests against test environment
5. Capture results and evidence
