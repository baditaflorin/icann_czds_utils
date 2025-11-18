"""Tests for configuration management."""

import pytest
import os
from pathlib import Path

from czds_utils.config import Config
from czds_utils.errors import ConfigurationError


class TestConfigLoading:
    """Test configuration loading."""

    def test_load_from_env_file(self, test_env_file):
        """Test loading configuration from .env file."""
        config = Config(env_file=str(test_env_file))

        assert config.CZDS_USERNAME == "test_user"
        assert config.CZDS_PASSWORD == "test_password_123"
        assert config.CZDS_API_BASE_URL == "https://test-api.example.com"

    def test_missing_required_setting(self, temp_dir):
        """Test that missing required settings raise error."""
        env_file = temp_dir / ".env"
        env_file.write_text("LOG_LEVEL=INFO")

        with pytest.raises(ConfigurationError) as exc_info:
            Config(env_file=str(env_file))

        assert "CZDS_USERNAME" in str(exc_info.value)

    def test_invalid_url(self, temp_dir):
        """Test that invalid URLs are rejected."""
        env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=test_pass
CZDS_API_BASE_URL=not-a-valid-url
"""
        env_file = temp_dir / ".env"
        env_file.write_text(env_content.strip())

        with pytest.raises(ConfigurationError):
            Config(env_file=str(env_file))

    def test_invalid_integer_setting(self, temp_dir):
        """Test that invalid integer settings are rejected."""
        env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=test_pass
CZDS_API_BASE_URL=https://example.com
DATABASE_TIMEOUT=not_a_number
"""
        env_file = temp_dir / ".env"
        env_file.write_text(env_content.strip())

        with pytest.raises(ConfigurationError):
            Config(env_file=str(env_file))

    def test_integer_out_of_range(self, temp_dir):
        """Test that out-of-range integers are rejected."""
        env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=test_pass
CZDS_API_BASE_URL=https://example.com
MAX_RETRIES=99999
"""
        env_file = temp_dir / ".env"
        env_file.write_text(env_content.strip())

        with pytest.raises(ConfigurationError):
            Config(env_file=str(env_file))


class TestConfigAccess:
    """Test configuration access methods."""

    def test_attribute_access(self, test_config):
        """Test accessing config via attributes."""
        assert test_config.CZDS_USERNAME == "test_user"

    def test_get_method(self, test_config):
        """Test accessing config via get() method."""
        assert test_config.get("CZDS_USERNAME") == "test_user"
        assert test_config.get("NONEXISTENT", "default") == "default"

    def test_to_dict(self, test_config):
        """Test exporting config as dictionary."""
        config_dict = test_config.to_dict(mask_secrets=True)

        assert "CZDS_USERNAME" in config_dict
        assert config_dict["CZDS_PASSWORD"] == "***MASKED***"

    def test_to_dict_without_masking(self, test_config):
        """Test exporting config without masking."""
        config_dict = test_config.to_dict(mask_secrets=False)

        assert config_dict["CZDS_PASSWORD"] == "test_password_123"


class TestConfigValidation:
    """Test runtime configuration validation."""

    def test_validate_runtime_value(self, test_config):
        """Test runtime value validation."""
        validated = test_config.validate_runtime_value(
            "CZDS_USERNAME",
            "newuser"
        )
        assert validated == "newuser"

    def test_update_config(self, test_config):
        """Test updating configuration values."""
        test_config.update("MAX_RETRIES", 5)
        assert test_config.MAX_RETRIES == 5

    def test_update_invalid_value(self, test_config):
        """Test that invalid updates are rejected."""
        with pytest.raises(ConfigurationError):
            test_config.update("DATABASE_TIMEOUT", -1)


class TestConfigDefaults:
    """Test default configuration values."""

    def test_defaults_applied(self, test_config):
        """Test that default values are applied."""
        assert test_config.MAX_RETRIES == 3
        assert test_config.CHUNK_SIZE == 8192

    def test_boolean_settings(self, test_config):
        """Test boolean setting parsing."""
        # VALIDATE_SSL defaults to 'true'
        assert test_config.VALIDATE_SSL is True
