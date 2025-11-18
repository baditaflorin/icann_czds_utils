"""Tests for input validation and sanitization."""

import pytest
from czds_utils.validators import Validators
from czds_utils.errors import ValidationError


class TestStringValidation:
    """Test string validation."""

    def test_valid_string(self):
        """Test valid string input."""
        result = Validators.validate_string("hello", "test")
        assert result == "hello"

    def test_string_stripping(self):
        """Test that strings are stripped."""
        result = Validators.validate_string("  hello  ", "test")
        assert result == "hello"

    def test_empty_string_not_allowed(self):
        """Test that empty strings are rejected by default."""
        with pytest.raises(ValidationError):
            Validators.validate_string("", "test")

    def test_empty_string_allowed(self):
        """Test that empty strings can be allowed."""
        result = Validators.validate_string("", "test", allow_empty=True)
        assert result == ""

    def test_max_length(self):
        """Test maximum length enforcement."""
        with pytest.raises(ValidationError):
            Validators.validate_string("x" * 1001, "test", max_length=1000)

    def test_not_string_type(self):
        """Test that non-string types are rejected."""
        with pytest.raises(ValidationError):
            Validators.validate_string(123, "test")


class TestDomainValidation:
    """Test domain name validation."""

    def test_valid_domain(self):
        """Test valid domain names."""
        valid_domains = [
            "example.com",
            "test.co.uk",
            "sub.domain.example.com",
            "a.b.c.d.e.com",
        ]
        for domain in valid_domains:
            result = Validators.validate_domain(domain)
            assert result == domain.lower()

    def test_domain_lowercase(self):
        """Test that domains are converted to lowercase."""
        result = Validators.validate_domain("EXAMPLE.COM")
        assert result == "example.com"

    def test_invalid_domains(self):
        """Test invalid domain names."""
        invalid_domains = [
            "",
            ".",
            "..",
            "example..com",
            "-example.com",
            "example-.com",
            "example.com-",
            "a" * 254,  # Too long
        ]
        for domain in invalid_domains:
            with pytest.raises(ValidationError):
                Validators.validate_domain(domain)


class TestTLDValidation:
    """Test TLD validation."""

    def test_valid_tld(self):
        """Test valid TLDs."""
        valid_tlds = ["com", "uk", "info", "museum"]
        for tld in valid_tlds:
            result = Validators.validate_tld(tld)
            assert result == tld.lower()

    def test_tld_lowercase(self):
        """Test that TLDs are converted to lowercase."""
        result = Validators.validate_tld("COM")
        assert result == "com"

    def test_invalid_tlds(self):
        """Test invalid TLDs."""
        invalid_tlds = [
            "",
            "a",  # Too short
            "com1",  # Contains number
            "co-m",  # Contains hyphen
            "a" * 64,  # Too long
        ]
        for tld in invalid_tlds:
            with pytest.raises(ValidationError):
                Validators.validate_tld(tld)


class TestURLValidation:
    """Test URL validation."""

    def test_valid_urls(self):
        """Test valid URLs."""
        valid_urls = [
            "https://example.com",
            "http://example.com/path",
            "https://api.example.com:8080/endpoint",
        ]
        for url in valid_urls:
            result = Validators.validate_url(url)
            assert result == url

    def test_invalid_urls(self):
        """Test invalid URLs."""
        invalid_urls = [
            "",
            "not-a-url",
            "ftp://example.com",  # Wrong scheme
            "example.com",  # Missing scheme
        ]
        for url in invalid_urls:
            with pytest.raises(ValidationError):
                Validators.validate_url(url)


class TestIntegerValidation:
    """Test integer validation."""

    def test_valid_integer(self):
        """Test valid integer input."""
        result = Validators.validate_integer(42, "test")
        assert result == 42

    def test_string_to_integer(self):
        """Test string conversion to integer."""
        result = Validators.validate_integer("42", "test")
        assert result == 42

    def test_invalid_integer(self):
        """Test invalid integer input."""
        with pytest.raises(ValidationError):
            Validators.validate_integer("not-a-number", "test")

    def test_min_value(self):
        """Test minimum value enforcement."""
        with pytest.raises(ValidationError):
            Validators.validate_integer(5, "test", min_value=10)

    def test_max_value(self):
        """Test maximum value enforcement."""
        with pytest.raises(ValidationError):
            Validators.validate_integer(15, "test", max_value=10)


class TestSQLInjectionDetection:
    """Test SQL injection pattern detection."""

    def test_clean_input(self):
        """Test that clean input passes."""
        Validators.check_sql_injection("example.com", "test")

    def test_sql_injection_patterns(self):
        """Test that SQL injection patterns are detected."""
        malicious_inputs = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "admin'--",
            "1' UNION SELECT * FROM users--",
            "'; DELETE FROM domains; --",
        ]
        for malicious in malicious_inputs:
            with pytest.raises(ValidationError):
                Validators.check_sql_injection(malicious, "test")


class TestPathValidation:
    """Test file path validation."""

    def test_valid_path(self, temp_dir):
        """Test valid path."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        result = Validators.validate_path(
            str(test_file),
            must_exist=True,
            must_be_file=True
        )
        assert result.exists()

    def test_path_traversal_blocked(self):
        """Test that path traversal is blocked."""
        with pytest.raises(ValidationError):
            Validators.validate_path("../../../etc/passwd")

    def test_control_characters_blocked(self):
        """Test that control characters are blocked."""
        with pytest.raises(ValidationError):
            Validators.validate_path("test\x00file.txt")


class TestSanitization:
    """Test output sanitization."""

    def test_sanitize_for_display(self):
        """Test string sanitization for display."""
        result = Validators.sanitize_for_display("x" * 200)
        assert len(result) <= 103  # 100 + "..."

    def test_sanitize_control_characters(self):
        """Test that control characters are removed."""
        result = Validators.sanitize_for_display("test\x00\x01\x02data")
        assert "\x00" not in result
        assert "\x01" not in result
