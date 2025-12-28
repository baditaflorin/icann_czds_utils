.PHONY: help install install-dev test test-security test-coverage lint format clean build docker-build docker-run setup

# Default target
# Default target
help:
	@echo "Available targets:"
	@echo "  make install        - Install production dependencies"
	@echo "  make install-dev    - Install development dependencies"
	@echo "  make setup          - Complete setup (venv + deps)"
	@echo "  make test           - Run all tests"
	@echo "  make test-security  - Run security-focused tests only"
	@echo "  make test-coverage  - Run tests with coverage report"
	@echo "  make lint           - Run code linters"
	@echo "  make format         - Format code with black"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make build          - Build distribution package"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make docker-run     - Run Docker container"
	@echo "  make run            - Run the application (alias for gui)"
	@echo "  make gui            - Launch GUI application"
	@echo "  make cli-help       - Show CLI help"

# Detect Python interpreter
PYTHON := ./venv/bin/python
ifeq ($(wildcard $(PYTHON)),)
	PYTHON := python3
endif

# Setup virtual environment and install dependencies
setup:
	@echo "Setting up development environment..."
	python3 -m venv venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"
	@echo "Setup complete! Activate with: source venv/bin/activate"

# Install production dependencies
install:
	$(PYTHON) -m pip install -e .

# Install development dependencies
install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

# Run all tests
test:
	$(PYTHON) -m pytest -v tests/

# Run security-focused tests
test-security:
	$(PYTHON) -m pytest -v tests/test_security.py tests/test_validators.py

# Run tests with coverage
test-coverage:
	$(PYTHON) -m pytest --cov=czds_utils --cov-report=html --cov-report=term tests/
	@echo "Coverage report generated in htmlcov/index.html"

# Run linters
lint:
	$(PYTHON) -m flake8 src/czds_utils tests/ --max-line-length=120 --exclude=venv,build,dist
	$(PYTHON) -m mypy src/czds_utils --ignore-missing-imports

# Format code
format:
	$(PYTHON) -m black src/czds_utils tests/ --line-length=120

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf data/*.db
	rm -rf logs/*.log

# Build distribution
build: clean
	$(PYTHON) setup.py sdist bdist_wheel

# Build Docker image
docker-build:
	docker build -t czds-utils:latest .

# Run Docker container
docker-run:
	docker-compose up

# Run Docker container in detached mode
docker-up:
	docker-compose up -d

# Stop Docker container
docker-down:
	docker-compose down

# Launch GUI
run: gui

# Launch GUI
gui:
	$(PYTHON) -m czds_utils.gui.main_window

# Show CLI help
cli-help:
	$(PYTHON) -m czds_utils.cli --help

# Quick security check
security-check: lint test-security
	@echo "Security checks passed!"

# Full CI pipeline
ci: install-dev lint test-coverage
	@echo "CI pipeline complete!"
