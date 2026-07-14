"""Input validation and sanitization functions."""

import re
from pathlib import Path
from typing import Optional, Any
from urllib.parse import urlparse

from czds_utils.errors import ValidationError


class Validators:
    """Collection of input validation and sanitization methods."""

    # Security limits
    MAX_STRING_LENGTH = 1000
    MAX_DOMAIN_LENGTH = 253
    MAX_USERNAME_LENGTH = 100
    MAX_PATH_LENGTH = 4096

    # Regex patterns
    DOMAIN_PATTERN = re.compile(
        r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*'
        r'[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
    )
    # Matches standard TLDs (letters only) and punycode IDN TLDs (xn-- prefix with alphanumeric/hyphens)
    TLD_PATTERN = re.compile(r'^(?:xn--[a-z0-9][a-z0-9\-]{0,58}[a-z0-9]|xn--[a-z0-9]|[a-z]{2,63})$')

    # Dangerous patterns to block
    SQL_INJECTION_PATTERNS = [
        r"(\bUNION\b|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b)",
        r"(;|\-\-|\/\*|\*\/|\|\|)",  # Added ||
        r"(\bOR\b\s+[\d'\"]+\s*=\s*[\d'\"]+)",
        r"(0x[0-9a-fA-F]+)",  # Hex encoding
    ]

    PATH_TRAVERSAL_PATTERNS = [
        r"\.\.",
        r"[\x00-\x1f]",  # Control characters
    ]

    @classmethod
    def validate_string(
        cls,
        value: Any,
        field_name: str,
        max_length: Optional[int] = None,
        allow_empty: bool = False,
        pattern: Optional[re.Pattern] = None
    ) -> str:
        """Validate and sanitize a string input.

        Args:
            value: Input value to validate
            field_name: Name of field for error messages
            max_length: Maximum allowed length (default: MAX_STRING_LENGTH)
            allow_empty: Whether empty strings are allowed
            pattern: Optional regex pattern the string must match

        Returns:
            Validated and sanitized string

        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(value, str):
            raise ValidationError(
                f"{field_name} must be a string, got {type(value).__name__}",
                field_name
            )

        value = value.strip()

        if not value and not allow_empty:
            raise ValidationError(f"{field_name} cannot be empty", field_name)

        max_len = max_length or cls.MAX_STRING_LENGTH
        if len(value) > max_len:
            raise ValidationError(
                f"{field_name} exceeds maximum length of {max_len}",
                field_name
            )

        if pattern and not pattern.match(value):
            raise ValidationError(
                f"{field_name} does not match required format",
                field_name
            )

        return value

    @classmethod
    def validate_domain(cls, domain: str, field_name: str = "domain") -> str:
        """Validate a domain name.

        Args:
            domain: Domain name to validate
            field_name: Name of field for error messages

        Returns:
            Validated domain name (lowercase)

        Raises:
            ValidationError: If domain is invalid
        """
        domain = cls.validate_string(
            domain,
            field_name,
            max_length=cls.MAX_DOMAIN_LENGTH
        ).lower()

        if not cls.DOMAIN_PATTERN.match(domain):
            raise ValidationError(
                f"Invalid domain format: {domain}",
                field_name
            )

        return domain

    @classmethod
    def validate_tld(cls, tld: str, field_name: str = "tld") -> str:
        """Validate a TLD (top-level domain).

        Args:
            tld: TLD to validate
            field_name: Name of field for error messages

        Returns:
            Validated TLD (lowercase)

        Raises:
            ValidationError: If TLD is invalid
        """
        tld = cls.validate_string(
            tld,
            field_name,
            max_length=63
        ).lower()

        if not cls.TLD_PATTERN.match(tld):
            raise ValidationError(
                f"Invalid TLD format: {tld}",
                field_name
            )

        return tld

    @classmethod
    def validate_username(cls, username: str, field_name: str = "username") -> str:
        """Validate a username.

        Args:
            username: Username to validate
            field_name: Name of field for error messages

        Returns:
            Validated username

        Raises:
            ValidationError: If username is invalid
        """
        return cls.validate_string(
            username,
            field_name,
            max_length=cls.MAX_USERNAME_LENGTH
        )

    @classmethod
    def validate_url(cls, url: str, field_name: str = "url") -> str:
        """Validate a URL.

        Args:
            url: URL to validate
            field_name: Name of field for error messages

        Returns:
            Validated URL

        Raises:
            ValidationError: If URL is invalid
        """
        url = cls.validate_string(url, field_name)

        try:
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                raise ValidationError(
                    f"Invalid URL format: {url}",
                    field_name
                )
            if parsed.scheme not in ['http', 'https']:
                raise ValidationError(
                    f"URL must use http or https scheme",
                    field_name
                )
        except Exception as e:
            raise ValidationError(
                f"Invalid URL: {str(e)}",
                field_name
            )

        return url

    @classmethod
    def validate_path(
        cls,
        path: str,
        field_name: str = "path",
        must_exist: bool = False,
        must_be_file: bool = False,
        must_be_dir: bool = False
    ) -> Path:
        """Validate a file system path.

        Args:
            path: Path to validate
            field_name: Name of field for error messages
            must_exist: Whether path must exist
            must_be_file: Whether path must be a file
            must_be_dir: Whether path must be a directory

        Returns:
            Validated Path object

        Raises:
            ValidationError: If path is invalid
        """
        path_str = cls.validate_string(
            path,
            field_name,
            max_length=cls.MAX_PATH_LENGTH
        )

        # Check for path traversal attempts
        for pattern in cls.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path_str):
                raise ValidationError(
                    f"Invalid path: contains illegal characters",
                    field_name
                )

        try:
            path_obj = Path(path_str).resolve()
        except Exception as e:
            raise ValidationError(
                f"Invalid path: {str(e)}",
                field_name
            )

        if must_exist and not path_obj.exists():
            raise ValidationError(
                f"Path does not exist",
                field_name
            )

        if must_be_file and not path_obj.is_file():
            raise ValidationError(
                f"Path must be a file",
                field_name
            )

        if must_be_dir and not path_obj.is_dir():
            raise ValidationError(
                f"Path must be a directory",
                field_name
            )

        return path_obj

    @classmethod
    def validate_integer(
        cls,
        value: Any,
        field_name: str,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None
    ) -> int:
        """Validate an integer value.

        Args:
            value: Value to validate
            field_name: Name of field for error messages
            min_value: Minimum allowed value
            max_value: Maximum allowed value

        Returns:
            Validated integer

        Raises:
            ValidationError: If validation fails
        """
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                f"{field_name} must be an integer",
                field_name
            )

        if min_value is not None and int_value < min_value:
            raise ValidationError(
                f"{field_name} must be at least {min_value}",
                field_name
            )

        if max_value is not None and int_value > max_value:
            raise ValidationError(
                f"{field_name} must be at most {max_value}",
                field_name
            )

        return int_value

    @classmethod
    def check_sql_injection(cls, value: str, field_name: str) -> None:
        """Check for potential SQL injection patterns.

        Args:
            value: String to check
            field_name: Name of field for error messages

        Raises:
            ValidationError: If suspicious patterns detected
        """
        value_upper = value.upper()
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if re.search(pattern, value_upper, re.IGNORECASE):
                raise ValidationError(
                    f"Invalid characters detected in {field_name}",
                    field_name
                )

    @classmethod
    def sanitize_for_display(cls, value: str, max_length: int = 100) -> str:
        """Sanitize a string for safe display in UI or logs.

        Args:
            value: String to sanitize
            max_length: Maximum length to display

        Returns:
            Sanitized string
        """
        if not isinstance(value, str):
            value = str(value)

        # Remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)

        # Truncate if needed
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."

        return sanitized
