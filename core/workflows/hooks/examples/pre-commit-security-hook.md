# pre-commit-security-hook

Purpose: Security scan before commit to prevent secrets and sensitive data exposure.

Related docs:
- `core/workflows/skills/security-review.md` (security checklist)
- `core/packs/policy-pack-v1/RISK_TRIGGERS.md` (risk triggers)

---

## Hook Configuration

```yaml
hook:
  name: pre-commit-security
  trigger: pre-commit
  scope: staged-files
  blocking: true
  severity-threshold: high
```

---

## Checks Performed

### 1. Hardcoded Secrets Detection
- API keys (pattern: `[A-Za-z0-9_]{20,}`)
- Private keys (pattern: `-----BEGIN.*PRIVATE KEY-----`)
- AWS credentials (pattern: `AKIA[0-9A-Z]{16}`)
- Connection strings with passwords
- JWT tokens
- Password assignments

### 2. Sensitive File Validation
- `.env` files should not be staged
- `.pem`, `.key` files should not be staged
- Credential files (*.credentials, *.secret)
- Configuration with embedded secrets

### 3. Common Patterns to Block
```
password\s*=\s*['"][^'"]+['"]
secret\s*=\s*['"][^'"]+['"]
api[_-]?key\s*=\s*['"][^'"]+['"]
token\s*=\s*['"][^'"]+['"]
```

---

## Pseudo-code Implementation

```pseudo
function preCommitSecurityHook():
    stagedFiles = getStagedFiles()
    findings = []
    
    for file in stagedFiles:
        # Check for sensitive file types
        if isSensitiveFileType(file.path):
            findings.append({
                file: file.path,
                severity: "critical",
                issue: "Sensitive file type should not be committed"
            })
            continue
        
        content = getFileContent(file)
        
        # Check for hardcoded secrets
        secretPatterns = loadSecretPatterns()
        for pattern in secretPatterns:
            matches = findMatches(content, pattern.regex)
            for match in matches:
                findings.append({
                    file: file.path,
                    line: match.lineNumber,
                    severity: pattern.severity,
                    issue: pattern.description,
                    matched: mask(match.text)
                })
    
    # Evaluate findings
    criticalFindings = filter(findings, f => f.severity == "critical")
    highFindings = filter(findings, f => f.severity == "high")
    
    if len(criticalFindings) > 0 or len(highFindings) > 0:
        reportFindings(findings)
        return BLOCK_COMMIT
    
    if len(findings) > 0:
        reportFindings(findings)
        logWarning("Commit allowed with warnings")
    
    return ALLOW_COMMIT

function isSensitiveFileType(path):
    sensitiveExtensions = [".pem", ".key", ".p12", ".pfx"]
    sensitiveNames = [".env", ".env.local", "credentials", "secrets"]
    
    return path.extension in sensitiveExtensions or
           path.basename in sensitiveNames

function mask(text):
    if len(text) <= 8:
        return "***"
    return text[0:4] + "..." + text[-4:]
```

---

## Output Format

### On Block
```
🚫 COMMIT BLOCKED - Security Issues Found

CRITICAL:
- src/config.js:15 - Hardcoded API key detected: "sk-p..."

HIGH:
- .env.local - Sensitive file should not be committed

Remove sensitive data and try again.
See: core/workflows/skills/security-review.md
```

### On Warning
```
⚠️ COMMIT ALLOWED WITH WARNINGS

MEDIUM:
- src/utils.js:42 - Possible hardcoded token (review recommended)

Consider moving to environment variables.
```

---

## Integration Notes

- Hook runs on staged files only
- Respects .gitignore patterns
- Can be bypassed with `--no-verify` (logged as risk)
- False positives can be allowlisted in `.security-allowlist`
