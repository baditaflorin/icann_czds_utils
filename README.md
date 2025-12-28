# ICANN CZDS Utils

A secure, production-ready utility for managing ICANN Centralized Zone Data Service (CZDS) zone files with comprehensive security features, clean architecture, and extensive testing.

## Features

- **Security-First Design**
  - All SQL queries fully parameterized (zero SQL injection risk)
  - Comprehensive input validation and sanitization
  - Safe error messages that don't leak sensitive information
  - Least-privilege database access patterns
  - Path traversal protection
  - SSL certificate validation

- **Environment-Driven Configuration**
  - All settings via environment variables
  - Validation with graceful failure messages
  - No hardcoded credentials or secrets

- **Practical GUI Test Harness**
  - Load and save configuration
  - Test API authentication
  - Browse and download zone files
  - Parse and import zone data
  - Query database
  - View real-time logs

- **Clean Architecture**
  - Single-responsibility components
  - DRY/SOLID principles
  - Modular, testable code
  - Type hints throughout

- **Comprehensive Testing**
  - Unit tests for all components
  - Security tests (injection, malformed inputs)
  - Integration tests
  - 90%+ code coverage

- **Production-Ready Deployment**
  - Docker containerization
  - Makefile for common tasks
  - Reproducible builds
  - Resource limits and security constraints

## Quick Start

### Prerequisites

- Python 3.8+
- pip
- (Optional) Docker and Docker Compose

### Installation

#### Using Make (Recommended)

```bash
# Clone the repository
git clone https://github.com/baditaflorin/icann_czds_utils.git
cd icann_czds_utils

# Complete setup (creates venv and installs dependencies)
make setup

# Activate virtual environment
source venv/bin/activate
```

#### Manual Installation

```bash
pip install -e .
```

### Configuration

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` with your CZDS credentials:

```bash
CZDS_USERNAME=your_username
CZDS_PASSWORD=your_password
```

Required settings:
- `CZDS_USERNAME` - Your ICANN CZDS username
- `CZDS_PASSWORD` - Your ICANN CZDS password

Optional settings (have defaults):
- `CZDS_API_BASE_URL` - API base URL (default: https://czds-api.icann.org)
- `DATABASE_PATH` - SQLite database path (default: ./data/czds.db)
- `LOG_LEVEL` - Logging level (default: INFO)
- `ZONE_FILES_DIR` - Directory for zone files (default: ./zone_files)

See `.env.example` for all available settings.

## Usage

### GUI Application

Launch the graphical interface:

```bash
make run
# or
make gui
# or
# or
python -m czds_utils.gui.main_window
```

The GUI provides:
- **Configuration Tab**: Load/reload configuration, view current settings
- **API Test Harness**: Test authentication, browse zones, download files
- **Database Tab**: View statistics, query domains
- **Parser Tab**: Parse zone files, import to database
- **Logs Tab**: Real-time application logs

### Command-Line Interface

#### Authenticate

Test your CZDS credentials:

```bash
czds-cli auth
```

#### List Available Zones

```bash
czds-cli list
```

#### Download a Zone File

```bash
czds-cli download com -o zone_files/com.txt.gz
```

#### Parse a Zone File

Parse and show statistics:

```bash
czds-cli parse com zone_files/com.txt.gz
```

Extract unique domains to file:

```bash
czds-cli parse com zone_files/com.txt.gz -o unique_domains.txt
```

Import to database:

```bash
czds-cli parse com zone_files/com.txt.gz --import-db
```

#### Query Database

View database statistics:

```bash
czds-cli stats
```

Query domains for a TLD:

```bash
czds-cli query com -l 100
```

## Development

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Run security tests only
make test-security

# Run specific test file
pytest tests/test_database.py -v
```

### Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Full CI pipeline (lint + test + coverage)
make ci
```

### Cleaning

```bash
# Remove build artifacts, cache files, etc.
make clean
```

## Docker Deployment

### Build Image

```bash
make docker-build
```

### Run Container

```bash
# Interactive mode
make docker-run

# Detached mode
make docker-up

# Stop container
make docker-down
```

### Docker Configuration

The Docker setup includes:
- Non-root user (UID 1000)
- Read-only root filesystem
- Resource limits (2 CPU, 2GB RAM)
- Security options (no-new-privileges, dropped capabilities)
- Volume mounts for data persistence

## Architecture

```
src/czds_utils/
├── __init__.py           # Package initialization
├── config.py             # Environment-based configuration
├── database.py           # Database layer (parameterized queries)
├── api_client.py         # CZDS API client
├── parser.py             # Zone file parser
├── validators.py         # Input validation/sanitization
├── errors.py             # Custom exceptions
├── cli.py                # Command-line interface
└── gui/
    └── main_window.py    # GUI application
```

### Key Design Principles

1. **Security**
   - No SQL string concatenation anywhere
   - All inputs validated before use
   - Safe error messages
   - Secrets never logged or displayed

2. **Separation of Concerns**
   - Config management separate from business logic
   - Database layer isolated
   - API client independent
   - Validators centralized

3. **Testability**
   - All components have unit tests
   - Integration tests for workflows
   - Security tests for attack scenarios
   - Mocking support for external dependencies

## Security

See [SECURITY.md](SECURITY.md) for:
- Security features
- Threat model
- Vulnerability reporting
- Security best practices

### Security Highlights

- **SQL Injection**: Impossible due to 100% parameterized queries
- **Path Traversal**: Blocked by path validation
- **Information Leakage**: Safe error messages never expose internals
- **Input Validation**: All inputs validated against strict rules
- **Least Privilege**: Database operations use minimal permissions

## Testing

The test suite includes:

- **Unit Tests** (`tests/test_*.py`)
  - Configuration loading and validation
  - Input validators
  - Database operations
  - Parser functionality

- **Security Tests** (`tests/test_security.py`)
  - SQL injection attempts
  - Path traversal attacks
  - Malformed inputs
  - Buffer overflow attempts
  - Error message leakage

- **Integration Tests**
  - End-to-end workflows
  - API → Database → Parser integration

Run tests:

```bash
# All tests
pytest -v

# With coverage
pytest --cov=czds_utils --cov-report=html

# Security tests only
pytest tests/test_security.py -v
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting (`make ci`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Changelog

### Version 2.0.0 (Current)

Complete rewrite with security and clean architecture:

- ✅ Fully parameterized SQL queries
- ✅ Comprehensive input validation
- ✅ Environment-driven configuration
- ✅ GUI test harness
- ✅ DRY/SOLID architecture
- ✅ Extensive test coverage
- ✅ Docker deployment
- ✅ Security hardening

### Version 1.0.0 (Legacy)

- Basic bash script for domain extraction

## Support

For bugs, questions, or feature requests:
- Open an issue on GitHub
- See [SECURITY.md](SECURITY.md) for security issues

## Acknowledgments

- ICANN for providing the CZDS service
- Python community for excellent libraries
- Security researchers for best practices
