"""Pytest configuration and fixtures."""

import pytest
import tempfile
import os
from pathlib import Path

from czds_utils.config import Config
from czds_utils.database import Database


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_env_file(temp_dir):
    """Create a test .env file."""
    env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=test_password_123
CZDS_API_BASE_URL=https://test-api.example.com
DATABASE_PATH=./test.db
LOG_LEVEL=DEBUG
"""
    env_file = temp_dir / ".env"
    env_file.write_text(env_content.strip())
    return env_file


@pytest.fixture
def test_config(test_env_file):
    """Create a test configuration."""
    return Config(env_file=str(test_env_file))


@pytest.fixture
def test_database(temp_dir):
    """Create a test database."""
    db_path = temp_dir / "test.db"
    return Database(db_path, timeout=5)


@pytest.fixture
def sample_zone_file(temp_dir):
    """Create a sample zone file for testing."""
    content = """
; Sample zone file
example.com\tns1.example.com
test.com\tns1.test.com
example.com\tns1.example.com
demo.com\tns1.demo.com
invalid..com\tns1.invalid.com
"""
    zone_file = temp_dir / "test.txt"
    zone_file.write_text(content.strip())
    return zone_file


@pytest.fixture
def sample_gzip_zone_file(temp_dir):
    """Create a sample gzipped zone file."""
    import gzip

    content = b"""
example.com\tns1.example.com
test.com\tns1.test.com
demo.com\tns1.demo.com
"""
    zone_file = temp_dir / "test.txt.gz"
    with gzip.open(zone_file, 'wb') as f:
        f.write(content.strip())

    return zone_file
