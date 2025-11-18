"""Environment-based configuration management with validation."""

import os
import logging
from pathlib import Path
from typing import Optional, Any, Dict
from dotenv import load_dotenv

from czds_utils.errors import ConfigurationError
from czds_utils.validators import Validators


class Config:
    """Application configuration loaded from environment variables.

    All settings are validated on load with graceful failure messages.
    """

    # Required settings (must be present)
    REQUIRED_SETTINGS = [
        'CZDS_USERNAME',
        'CZDS_PASSWORD',
    ]

    # Default values for optional settings
    DEFAULTS = {
        'CZDS_API_BASE_URL': 'https://czds-api.icann.org',
        'DATABASE_PATH': './data/czds.db',
        'DATABASE_TIMEOUT': '30',
        'LOG_LEVEL': 'INFO',
        'LOG_FILE': './logs/czds_utils.log',
        'MAX_RETRIES': '3',
        'REQUEST_TIMEOUT': '30',
        'ZONE_FILES_DIR': './zone_files',
        'MAX_FILE_SIZE_MB': '5000',
        'CHUNK_SIZE': '8192',
        'VALIDATE_SSL': 'true',
        'MAX_INPUT_LENGTH': '1000',
        'GUI_THEME': 'default',
        'WINDOW_WIDTH': '1000',
        'WINDOW_HEIGHT': '700',
    }

    def __init__(self, env_file: Optional[str] = '.env', auto_load: bool = True):
        """Initialize configuration.

        Args:
            env_file: Path to .env file (None to skip loading)
            auto_load: Whether to automatically load and validate config

        Raises:
            ConfigurationError: If configuration is invalid or incomplete
        """
        self._config: Dict[str, Any] = {}
        self._logger = logging.getLogger(__name__)

        if env_file and auto_load:
            self.load(env_file)

    def load(self, env_file: str = '.env') -> None:
        """Load configuration from environment file.

        Args:
            env_file: Path to .env file

        Raises:
            ConfigurationError: If configuration cannot be loaded or is invalid
        """
        # Load .env file if it exists (but don't require it)
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path)
            self._logger.info(f"Loaded configuration from {env_file}")
        else:
            self._logger.info(f"No {env_file} file found, using environment variables")

        # Validate and load all settings
        try:
            self._load_required_settings()
            self._load_optional_settings()
            self._validate_configuration()
        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load configuration: {str(e)}",
                "configuration"
            )

    def _load_required_settings(self) -> None:
        """Load and validate required settings.

        Raises:
            ConfigurationError: If any required setting is missing
        """
        missing = []
        for setting in self.REQUIRED_SETTINGS:
            value = os.getenv(setting)
            if not value:
                missing.append(setting)
            else:
                self._config[setting] = value

        if missing:
            raise ConfigurationError(
                f"Missing required configuration: {', '.join(missing)}",
                f"Required settings: {', '.join(missing)}"
            )

    def _load_optional_settings(self) -> None:
        """Load optional settings with defaults."""
        for setting, default in self.DEFAULTS.items():
            value = os.getenv(setting, default)
            self._config[setting] = value

    def _validate_configuration(self) -> None:
        """Validate all configuration values.

        Raises:
            ConfigurationError: If any setting is invalid
        """
        # Validate username
        try:
            Validators.validate_username(
                self._config['CZDS_USERNAME'],
                'CZDS_USERNAME'
            )
        except Exception as e:
            raise ConfigurationError(str(e), 'CZDS_USERNAME')

        # Validate password (just check it's not empty, no pattern matching)
        if not self._config['CZDS_PASSWORD']:
            raise ConfigurationError(
                "CZDS_PASSWORD cannot be empty",
                "CZDS_PASSWORD"
            )

        # Validate API base URL
        try:
            Validators.validate_url(
                self._config['CZDS_API_BASE_URL'],
                'CZDS_API_BASE_URL'
            )
        except Exception as e:
            raise ConfigurationError(str(e), 'CZDS_API_BASE_URL')

        # Validate integer settings
        int_settings = {
            'DATABASE_TIMEOUT': (1, 300),
            'MAX_RETRIES': (0, 10),
            'REQUEST_TIMEOUT': (1, 300),
            'MAX_FILE_SIZE_MB': (1, 10000),
            'CHUNK_SIZE': (1024, 1048576),
            'MAX_INPUT_LENGTH': (100, 10000),
            'WINDOW_WIDTH': (400, 3840),
            'WINDOW_HEIGHT': (300, 2160),
        }

        for setting, (min_val, max_val) in int_settings.items():
            try:
                value = Validators.validate_integer(
                    self._config[setting],
                    setting,
                    min_value=min_val,
                    max_value=max_val
                )
                self._config[setting] = value
            except Exception as e:
                raise ConfigurationError(str(e), setting)

        # Validate paths (create directories if needed)
        path_settings = ['DATABASE_PATH', 'LOG_FILE', 'ZONE_FILES_DIR']
        for setting in path_settings:
            try:
                path_str = self._config[setting]
                path = Path(path_str)

                # Create parent directories if they don't exist
                if setting in ['DATABASE_PATH', 'LOG_FILE']:
                    path.parent.mkdir(parents=True, exist_ok=True)
                else:  # ZONE_FILES_DIR
                    path.mkdir(parents=True, exist_ok=True)

                self._config[setting] = path
            except Exception as e:
                raise ConfigurationError(
                    f"Invalid path for {setting}: {str(e)}",
                    setting
                )

        # Validate boolean settings
        bool_settings = ['VALIDATE_SSL']
        for setting in bool_settings:
            value = self._config[setting].lower() in ['true', '1', 'yes', 'on']
            self._config[setting] = value

        # Validate log level
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        log_level = self._config['LOG_LEVEL'].upper()
        if log_level not in valid_log_levels:
            raise ConfigurationError(
                f"Invalid LOG_LEVEL: {log_level}. Must be one of {valid_log_levels}",
                'LOG_LEVEL'
            )
        self._config['LOG_LEVEL'] = log_level

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)

    def __getattr__(self, name: str) -> Any:
        """Allow attribute-style access to configuration.

        Args:
            name: Configuration key

        Returns:
            Configuration value

        Raises:
            AttributeError: If key not found
        """
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        if name in self._config:
            return self._config[name]

        raise AttributeError(f"Configuration key '{name}' not found")

    def to_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        """Export configuration as dictionary.

        Args:
            mask_secrets: Whether to mask sensitive values

        Returns:
            Configuration dictionary
        """
        config_copy = self._config.copy()

        if mask_secrets:
            secret_keys = ['CZDS_PASSWORD']
            for key in secret_keys:
                if key in config_copy:
                    config_copy[key] = '***MASKED***'

        # Convert Path objects to strings for serialization
        for key, value in config_copy.items():
            if isinstance(value, Path):
                config_copy[key] = str(value)

        return config_copy

    def validate_runtime_value(self, key: str, value: Any) -> Any:
        """Validate a runtime configuration value.

        Args:
            key: Configuration key
            value: Value to validate

        Returns:
            Validated value

        Raises:
            ConfigurationError: If value is invalid
        """
        # This allows updating config values at runtime with validation
        if key == 'CZDS_USERNAME':
            return Validators.validate_username(value, key)
        elif key == 'CZDS_API_BASE_URL':
            return Validators.validate_url(value, key)
        elif key in ['DATABASE_TIMEOUT', 'MAX_RETRIES', 'REQUEST_TIMEOUT']:
            return Validators.validate_integer(value, key, min_value=1, max_value=300)
        else:
            # For other keys, just return as-is
            return value

    def update(self, key: str, value: Any) -> None:
        """Update a configuration value with validation.

        Args:
            key: Configuration key
            value: New value

        Raises:
            ConfigurationError: If value is invalid
        """
        validated_value = self.validate_runtime_value(key, value)
        self._config[key] = validated_value


# Global configuration instance
_config_instance: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Get the global configuration instance.

    Args:
        reload: Whether to reload configuration from environment

    Returns:
        Global Config instance

    Raises:
        ConfigurationError: If configuration cannot be loaded
    """
    global _config_instance

    if _config_instance is None or reload:
        _config_instance = Config()

    return _config_instance
