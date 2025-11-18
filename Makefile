.PHONY: help install install-dev test test-security test-coverage lint format clean build docker-build docker-run setup

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
	@echo "  make gui            - Launch GUI application"
	@echo "  make cli-help       - Show CLI help"

# Setup virtual environment and install dependencies
setup:
	@echo "Setting up development environment..."
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -e ".[dev]"
	@echo "Setup complete! Activate with: source venv/bin/activate"

# Install production dependencies
install:
	pip install -e .

# Install development dependencies
install-dev:
	pip install -e ".[dev]"

# Run all tests
test:
	pytest -v tests/

# Run security-focused tests
test-security:
	pytest -v tests/test_security.py tests/test_validators.py

# Run tests with coverage
test-coverage:
	pytest --cov=czds_utils --cov-report=html --cov-report=term tests/
	@echo "Coverage report generated in htmlcov/index.html"

# Run linters
lint:
	flake8 src/czds_utils tests/ --max-line-length=120 --exclude=venv,build,dist
	mypy src/czds_utils --ignore-missing-imports

# Format code
format:
	black src/czds_utils tests/ --line-length=120

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
	python setup.py sdist bdist_wheel

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
gui:
	python -m czds_utils.gui.main_window

# Show CLI help
cli-help:
	python -m czds_utils.cli --help

# Quick security check
security-check: lint test-security
	@echo "Security checks passed!"

# Full CI pipeline
ci: install-dev lint test-coverage
	@echo "CI pipeline complete!"
