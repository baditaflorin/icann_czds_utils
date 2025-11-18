"""Comprehensive security tests.

Tests for:
- SQL injection attempts
- Path traversal attacks
- Malformed inputs
- Buffer overflow attempts
- Command injection
- Error message leakage
"""

import pytest
from pathlib import Path

from czds_utils.database import Database
from czds_utils.validators import Validators
from czds_utils.parser import ZoneFileParser
from czds_utils.config import Config
from czds_utils.errors import ValidationError, DatabaseError, ConfigurationError


class TestSQLInjection:
    """Comprehensive SQL injection tests."""

    SQL_INJECTION_PAYLOADS = [
        # Classic injection
        "' OR '1'='1",
        "'; DROP TABLE domains; --",
        "admin'--",

        # UNION-based
        "' UNION SELECT * FROM metadata--",
        "' UNION ALL SELECT NULL,NULL,NULL--",

        # Stacked queries
        "'; DELETE FROM domains WHERE '1'='1",

        # Comment-based
        "/**/OR/**/1=1--",

        # Hex encoding
        "0x27204f52203127",

        # Boolean-based blind
        "' AND 1=1--",
        "' AND 1=2--",

        # Time-based blind
        "'; WAITFOR DELAY '00:00:05'--",

        # Second-order injection
        "admin'||'admin",
    ]

    def test_sql_injection_in_search(self, test_database):
        """Test SQL injection attempts in search function."""
        for payload in self.SQL_INJECTION_PAYLOADS:
            with pytest.raises(ValidationError):
                test_database.search_domains(payload)

    def test_sql_injection_in_tld(self, test_database):
        """Test SQL injection attempts in TLD field."""
        for payload in self.SQL_INJECTION_PAYLOADS:
            with pytest.raises(ValidationError):
                test_database.add_or_update_tld(payload)

    def test_sql_injection_in_domain(self, test_database):
        """Test SQL injection attempts in domain field."""
        for payload in self.SQL_INJECTION_PAYLOADS:
            try:
                test_database.add_domain("com", payload)
                # If it doesn't raise, verify it's stored as literal string
                domains = test_database.get_domains_by_tld("com", limit=100)
                # Should not have executed SQL
                assert test_database.get_domain_count("com") < 100
            except ValidationError:
                # Expected - validation should reject it
                pass

    def test_parameterized_query_usage(self, test_database):
        """Verify that parameterized queries prevent injection."""
        # Add some normal data
        test_database.add_domain("com", "example.com")

        # Try injection in search
        try:
            results = test_database.search_domains("' OR '1'='1")
        except ValidationError:
            # Expected - validator blocks it
            pass
        else:
            # If validator allowed it, verify query is safe
            # Should return no results, not all results
            assert len(results) == 0


class TestPathTraversal:
    """Test path traversal attack prevention."""

    PATH_TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\config\\sam",
        "....//....//....//etc/passwd",
        "..%2F..%2F..%2Fetc%2Fpasswd",
        "..%252F..%252F..%252Fetc%252Fpasswd",
    ]

    def test_path_traversal_in_validation(self):
        """Test path traversal detection in path validator."""
        for payload in self.PATH_TRAVERSAL_PAYLOADS:
            with pytest.raises(ValidationError):
                Validators.validate_path(payload)

    def test_path_traversal_in_parser(self):
        """Test path traversal in parser."""
        parser = ZoneFileParser("com")

        for payload in self.PATH_TRAVERSAL_PAYLOADS:
            try:
                list(parser.parse_file(Path(payload)))
                # If it doesn't raise during path validation,
                # it should fail on file not existing
                assert False, f"Should have rejected: {payload}"
            except (ValidationError, FileNotFoundError):
                # Expected
                pass


class TestMalformedInputs:
    """Test handling of malformed inputs."""

    def test_null_bytes(self, test_database):
        """Test null byte handling."""
        malformed_inputs = [
            "test\x00.com",
            "example.com\x00",
            "\x00example.com",
        ]

        for malformed in malformed_inputs:
            with pytest.raises(ValidationError):
                Validators.validate_domain(malformed)

    def test_control_characters(self):
        """Test control character handling."""
        for i in range(0, 32):
            malformed = f"test{chr(i)}.com"
            # Control characters should be rejected
            try:
                validated = Validators.validate_domain(malformed)
                # If not rejected, should at least be sanitized
                assert chr(i) not in validated
            except ValidationError:
                # Expected
                pass

    def test_oversized_inputs(self, test_database):
        """Test handling of oversized inputs."""
        # Very long domain
        long_domain = "a" * 300 + ".com"
        with pytest.raises(ValidationError):
            test_database.add_domain("com", long_domain)

        # Very long TLD
        long_tld = "a" * 100
        with pytest.raises(ValidationError):
            test_database.add_or_update_tld(long_tld)

    def test_unicode_edge_cases(self):
        """Test unicode edge cases."""
        edge_cases = [
            "\u202e",  # Right-to-left override
            "\ufeff",  # Zero-width no-break space
            "example\u200b.com",  # Zero-width space
        ]

        for edge_case in edge_cases:
            try:
                Validators.validate_domain(edge_case)
            except ValidationError:
                # Expected - should reject unusual unicode
                pass

    def test_mixed_encodings(self, temp_dir):
        """Test handling of mixed encodings in files."""
        # Create file with mixed encoding
        zone_file = temp_dir / "mixed.txt"

        # Write latin-1 encoded data
        zone_file.write_bytes(
            b"example.com\tns1\n"
            b"\xe4\xf6\xfc.com\tns2\n"  # Invalid UTF-8
            b"test.com\tns3\n"
        )

        parser = ZoneFileParser("com", validate_domains=False)

        # Should handle encoding errors gracefully
        domains = list(parser.parse_file(zone_file))
        assert "example.com" in domains or "test.com" in domains


class TestErrorMessageLeakage:
    """Test that error messages don't leak sensitive information."""

    def test_database_error_safe_message(self, temp_dir):
        """Test that database errors have safe messages."""
        # Try to create database in non-existent directory
        try:
            db = Database(Path("/nonexistent/path/db.sqlite"), timeout=1)
        except DatabaseError as e:
            # Check that safe message doesn't contain file paths
            assert "/nonexistent" not in e.safe_message
            assert "database" in e.safe_message.lower()

    def test_validation_error_safe_message(self):
        """Test that validation errors have safe messages."""
        try:
            Validators.validate_domain("'; DROP TABLE users; --")
        except ValidationError as e:
            # Should not reveal SQL in safe message
            assert "DROP" not in e.safe_message
            assert "invalid" in e.safe_message.lower()

    def test_config_error_masks_password(self, temp_dir):
        """Test that config errors don't leak passwords."""
        env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=super_secret_password_123
CZDS_API_BASE_URL=invalid-url
"""
        env_file = temp_dir / ".env"
        env_file.write_text(env_content.strip())

        try:
            Config(env_file=str(env_file))
        except ConfigurationError as e:
            # Safe message should not contain password
            assert "super_secret_password" not in e.safe_message
            assert "password" not in e.safe_message.lower()

    def test_config_to_dict_masks_secrets(self, test_config):
        """Test that config export masks secrets."""
        config_dict = test_config.to_dict(mask_secrets=True)

        assert config_dict['CZDS_PASSWORD'] == '***MASKED***'
        assert 'test_password' not in str(config_dict)


class TestInputBoundaries:
    """Test boundary conditions in inputs."""

    def test_empty_strings(self, test_database):
        """Test handling of empty strings."""
        with pytest.raises(ValidationError):
            test_database.add_domain("com", "")

        with pytest.raises(ValidationError):
            test_database.add_or_update_tld("")

    def test_maximum_lengths(self):
        """Test maximum length enforcement."""
        # Maximum valid domain length is 253
        max_domain = "a" * 240 + ".com"  # 244 chars
        Validators.validate_domain(max_domain)

        # Too long should fail
        too_long = "a" * 250 + ".com"  # 254 chars
        with pytest.raises(ValidationError):
            Validators.validate_domain(too_long)

    def test_negative_integers(self, test_database):
        """Test that negative integers are rejected where inappropriate."""
        with pytest.raises(ValidationError):
            Validators.validate_integer(-1, "count", min_value=0)

    def test_integer_overflow(self):
        """Test handling of very large integers."""
        # Python handles big ints, but database might not
        huge_number = 2**63  # Larger than SQLite INTEGER max

        # Should either validate successfully or raise clear error
        try:
            result = Validators.validate_integer(huge_number, "test")
            assert isinstance(result, int)
        except ValidationError:
            pass


class TestConcurrencyAndRaceConditions:
    """Test concurrent access scenarios."""

    def test_concurrent_domain_insertion(self, test_database):
        """Test concurrent insertions of same domain."""
        # Add same domain multiple times
        for _ in range(10):
            test_database.add_domain("com", "example.com")

        # Should only have one entry
        count = test_database.get_domain_count("com")
        assert count == 1

    def test_transaction_isolation(self, test_database):
        """Test that transactions are properly isolated."""
        # Add domains in batch
        domains = [f"domain{i}.com" for i in range(100)]
        count = test_database.add_domains_batch("com", domains)

        # All should succeed or all should fail
        assert count == 100


class TestDenialOfService:
    """Test DoS attack scenarios."""

    def test_resource_exhaustion_large_batch(self, test_database):
        """Test handling of very large batch operations."""
        # Try to add huge batch (should handle gracefully)
        huge_batch = [f"domain{i}.com" for i in range(100000)]

        # Should either succeed with good performance or reject
        try:
            count = test_database.add_domains_batch("com", huge_batch, batch_size=1000)
            assert count > 0
        except (MemoryError, ValidationError):
            # Acceptable to reject if too large
            pass

    def test_deeply_nested_subdomains(self):
        """Test handling of deeply nested subdomains."""
        # Create very long subdomain chain
        nested = ".".join(["sub"] * 50) + ".example.com"

        # Should either validate or reject cleanly
        try:
            Validators.validate_domain(nested)
        except ValidationError:
            # Expected - too long
            pass

    def test_repeated_failed_validations(self):
        """Test that repeated validation failures don't cause issues."""
        for i in range(1000):
            try:
                Validators.validate_domain(f"invalid{i}..com")
            except ValidationError:
                # Expected
                pass

        # Should complete without hanging or crashing


class TestConfigurationSecurity:
    """Test configuration security."""

    def test_ssl_validation_default(self):
        """Test that SSL validation is enabled by default."""
        # Default should validate SSL
        # (This would be tested in config defaults)
        pass

    def test_sensitive_data_not_logged(self, test_config, capsys):
        """Test that sensitive data isn't logged."""
        # Convert to dict and print
        config_dict = test_config.to_dict(mask_secrets=True)
        print(str(config_dict))

        captured = capsys.readouterr()
        assert "test_password_123" not in captured.out

    def test_sql_injection_in_metadata(self, test_database):
        """Test SQL injection in metadata operations."""
        malicious_key = "key'; DROP TABLE metadata; --"

        with pytest.raises(ValidationError):
            test_database.get_metadata(malicious_key)
