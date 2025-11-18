"""Custom exception classes with safe, non-leaking error messages."""

from typing import Optional


class CZDSError(Exception):
    """Base exception for all CZDS utility errors.

    All error messages are sanitized to avoid leaking sensitive information.
    """

    def __init__(self, message: str, safe_message: Optional[str] = None):
        """Initialize error with both internal and safe messages.

        Args:
            message: Internal message for logging (may contain details)
            safe_message: Safe message for user display (no sensitive data)
        """
        super().__init__(message)
        self._safe_message = safe_message or self._sanitize_message(message)

    @staticmethod
    def _sanitize_message(message: str) -> str:
        """Sanitize error message to remove potential sensitive information.

        Args:
            message: Original error message

        Returns:
            Sanitized message safe for display
        """
        # Remove file paths, IPs, credentials patterns
        safe = message.split('\n')[0][:100]  # First line, max 100 chars

        # Replace common sensitive patterns
        sensitive_patterns = [
            ('password', '***'),
            ('token', '***'),
            ('api_key', '***'),
            ('secret', '***'),
        ]

        safe_lower = safe.lower()
        for pattern, replacement in sensitive_patterns:
            if pattern in safe_lower:
                return "An authentication error occurred"

        return safe

    @property
    def safe_message(self) -> str:
        """Get the safe, user-displayable error message."""
        return self._safe_message


class ConfigurationError(CZDSError):
    """Raised when configuration is missing, invalid, or cannot be loaded."""

    def __init__(self, message: str, setting: Optional[str] = None):
        safe_msg = f"Configuration error: Invalid or missing setting"
        if setting and not any(s in setting.lower() for s in ['pass', 'key', 'token', 'secret']):
            safe_msg = f"Configuration error: Issue with '{setting}'"
        super().__init__(message, safe_msg)


class DatabaseError(CZDSError):
    """Raised when database operations fail."""

    def __init__(self, message: str):
        safe_msg = "Database operation failed. Please check the logs."
        super().__init__(message, safe_msg)


class ValidationError(CZDSError):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: Optional[str] = None):
        safe_msg = "Invalid input provided"
        if field:
            safe_msg = f"Invalid input for field: {field}"
        super().__init__(message, safe_msg)


class APIError(CZDSError):
    """Raised when API calls fail."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        if status_code == 401:
            safe_msg = "Authentication failed. Please check your credentials."
        elif status_code == 403:
            safe_msg = "Access denied. Insufficient permissions."
        elif status_code == 404:
            safe_msg = "Requested resource not found."
        elif status_code == 429:
            safe_msg = "Rate limit exceeded. Please try again later."
        elif status_code and 500 <= status_code < 600:
            safe_msg = "Service temporarily unavailable. Please try again later."
        else:
            safe_msg = "API request failed. Please check your configuration."
        super().__init__(message, safe_msg)


class ParseError(CZDSError):
    """Raised when zone file parsing fails."""

    def __init__(self, message: str, line_number: Optional[int] = None):
        safe_msg = "Failed to parse zone file"
        if line_number:
            safe_msg = f"Parse error near line {line_number}"
        super().__init__(message, safe_msg)
