# Security Policy

## Security Features

This application implements multiple layers of security to protect against common vulnerabilities and attacks.

### 1. SQL Injection Prevention

**Implementation:**
- 100% parameterized queries using SQLite's parameter binding
- Zero string concatenation for SQL query construction
- Input validation before database operations
- SQL injection pattern detection in validators

**Testing:**
- Comprehensive SQL injection test suite (`tests/test_security.py`)
- Tests for classic injection, UNION-based, stacked queries, comment-based, and boolean-based blind injection
- All tests verify that malicious inputs are rejected

**Example:**
```python
# SECURE - Parameterized query
cursor.execute(
    "SELECT * FROM domains WHERE domain = ?",
    (user_input,)
)

# NEVER DONE - String concatenation
# cursor.execute(f"SELECT * FROM domains WHERE domain = '{user_input}'")  # ❌ VULNERABLE
```

### 2. Input Validation and Sanitization

**All inputs are validated:**
- Domain names: Format validation, length limits (max 253 chars)
- TLDs: Lowercase letters only, 2-63 characters
- URLs: Scheme validation (http/https only), proper format
- File paths: Path traversal detection, character validation
- Integers: Range validation, type checking
- Strings: Length limits, encoding validation

**Validators detect and block:**
- SQL injection patterns
- Path traversal attempts (`../`, `..\\`, encoded variants)
- Null bytes and control characters
- Oversized inputs
- Invalid formats

### 3. Error Message Safety

**Safe error messages:**
- User-facing messages never contain internal details
- Passwords and tokens never logged or displayed
- File paths sanitized in error messages
- Stack traces only in debug mode

**Implementation:**
```python
class CZDSError(Exception):
    def __init__(self, message: str, safe_message: Optional[str] = None):
        super().__init__(message)
        self._safe_message = safe_message or self._sanitize_message(message)
```

All exceptions inherit from `CZDSError` and provide both internal and safe messages.

### 4. Configuration Security

**Secure configuration management:**
- Credentials loaded from environment variables only
- No hardcoded secrets
- Configuration validation on load
- Secrets masked when exported (`to_dict(mask_secrets=True)`)
- SSL validation enabled by default

**Environment variables:**
- `CZDS_PASSWORD` - Masked in all outputs
- `CZDS_USERNAME` - Validated format
- `CZDS_API_BASE_URL` - URL validation

### 5. File System Security

**Path security:**
- Path traversal detection and blocking
- Paths resolved to absolute before use
- Directory creation with proper permissions
- File size limits enforced
- Extension validation for zone files

**Blocked patterns:**
- `../` and `..\` (including URL-encoded)
- Null bytes in paths
- Control characters

### 6. Network Security

**API client security:**
- SSL certificate validation enabled by default
- Timeout enforcement (prevents hanging)
- Retry limits (prevents DoS)
- Request size limits
- Safe header handling

**Configuration:**
```python
VALIDATE_SSL=true          # SSL cert validation
REQUEST_TIMEOUT=30         # Request timeout in seconds
MAX_RETRIES=3             # Maximum retry attempts
```

### 7. Database Security

**Least-privilege access:**
- Read-only access where possible
- Foreign key constraints enforced
- Unique constraints prevent duplicates
- WAL mode for better concurrency
- Transaction isolation

**Security features:**
- Parameterized queries only
- Input validation before queries
- Error handling without information leakage
- Prepared statements for all operations

### 8. Container Security

**Docker security:**
- Non-root user (UID 1000)
- Read-only root filesystem
- Dropped all capabilities
- No new privileges
- Resource limits (CPU, memory)
- Minimal base image (python:3.11-slim)

**docker-compose.yml:**
```yaml
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
user: "1000:1000"
read_only: true
```

## Threat Model

### Threats Addressed

1. **SQL Injection** - ✅ Prevented by parameterized queries
2. **Path Traversal** - ✅ Prevented by path validation
3. **Information Disclosure** - ✅ Prevented by safe error messages
4. **Command Injection** - ✅ No shell command execution
5. **Credential Theft** - ✅ Credentials stored in environment only
6. **DoS Attacks** - ✅ Resource limits, timeouts, validation
7. **XSS** (in GUI) - ✅ Input sanitization, no HTML rendering
8. **Buffer Overflow** - ✅ Input length limits
9. **Race Conditions** - ✅ Database transactions, proper locking

### Threats Not Addressed

1. **Physical Access** - Not in scope (OS-level security)
2. **Memory Inspection** - Not in scope (Python runtime)
3. **Supply Chain** - Mitigated by pinned dependencies, not eliminated

## Security Testing

### Test Coverage

Run security tests:

```bash
# All security tests
make test-security

# Specific test categories
pytest tests/test_security.py::TestSQLInjection -v
pytest tests/test_security.py::TestPathTraversal -v
pytest tests/test_security.py::TestMalformedInputs -v
```

### Test Categories

1. **SQL Injection** (`TestSQLInjection`)
   - Classic injection patterns
   - UNION-based injection
   - Stacked queries
   - Comment-based injection
   - Boolean-based blind injection

2. **Path Traversal** (`TestPathTraversal`)
   - Unix path traversal (`../`)
   - Windows path traversal (`..\`)
   - URL-encoded variants
   - Double-encoded variants

3. **Malformed Inputs** (`TestMalformedInputs`)
   - Null bytes
   - Control characters
   - Oversized inputs
   - Unicode edge cases
   - Mixed encodings

4. **Error Message Leakage** (`TestErrorMessageLeakage`)
   - Database errors
   - Validation errors
   - Configuration errors
   - Stack trace leakage

## Best Practices for Users

### 1. Credential Management

```bash
# ✅ DO: Use environment variables
export CZDS_USERNAME="your_username"
export CZDS_PASSWORD="your_password"

# ✅ DO: Use .env file (add to .gitignore)
echo "CZDS_USERNAME=your_username" > .env
echo "CZDS_PASSWORD=your_password" >> .env

# ❌ DON'T: Hardcode credentials
# CZDS_PASSWORD="secret123" in code
```

### 2. File Permissions

```bash
# Secure .env file
chmod 600 .env

# Secure database
chmod 600 data/czds.db

# Secure log files
chmod 640 logs/*.log
```

### 3. Docker Security

```bash
# Use provided docker-compose.yml (has security settings)
docker-compose up

# Don't override security settings
# Don't run as root in container
```

### 4. Network Security

```bash
# ✅ DO: Keep SSL validation enabled
VALIDATE_SSL=true

# ❌ DON'T: Disable SSL validation in production
# VALIDATE_SSL=false  # Only for testing!
```

### 5. Updates

```bash
# Keep dependencies updated
pip install --upgrade -r requirements.txt

# Check for security advisories
pip-audit  # Install: pip install pip-audit
```

## Vulnerability Reporting

### Reporting a Vulnerability

If you discover a security vulnerability:

1. **DO NOT** open a public issue
2. Email the maintainer privately (see GitHub profile)
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

### Response Timeline

- **24 hours**: Initial response
- **7 days**: Vulnerability assessment
- **30 days**: Fix development and testing
- **After fix**: Public disclosure

### Responsible Disclosure

We follow responsible disclosure practices:
- Private notification to maintainers
- Coordinated public disclosure
- Credit to reporter (if desired)

## Security Audit

Last security audit: 2024 (internal)

Audit scope:
- Code review for common vulnerabilities
- Dependency security scan
- SQL injection testing
- Input validation testing
- Error handling review
- Container security review

## Compliance

This application follows security best practices from:
- OWASP Top 10
- CWE Top 25
- Python Security Best Practices
- Docker Security Best Practices

## Security Checklist

For developers:

- [ ] All SQL queries use parameterized statements
- [ ] All user inputs validated before use
- [ ] Error messages don't leak sensitive information
- [ ] Credentials never hardcoded
- [ ] File paths validated for traversal
- [ ] SSL validation enabled
- [ ] Resource limits enforced
- [ ] Tests include security scenarios
- [ ] Dependencies up to date
- [ ] Docker runs as non-root user

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [SQLite Security](https://www.sqlite.org/security.html)
- [Docker Security](https://docs.docker.com/engine/security/)

## Contact

For security concerns: See GitHub repository for contact information
