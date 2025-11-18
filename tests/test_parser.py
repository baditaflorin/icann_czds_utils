"""Tests for zone file parser."""

import pytest
import gzip
from pathlib import Path

from czds_utils.parser import ZoneFileParser, extract_unique_domains
from czds_utils.errors import ParseError, ValidationError


class TestParserInitialization:
    """Test parser initialization."""

    def test_create_parser(self):
        """Test creating a parser."""
        parser = ZoneFileParser("com")
        assert parser.tld == "com"

    def test_invalid_tld(self):
        """Test that invalid TLDs are rejected."""
        with pytest.raises(ValidationError):
            ZoneFileParser("invalid!")


class TestFileParsing:
    """Test parsing zone files."""

    def test_parse_plain_file(self, sample_zone_file):
        """Test parsing plain text zone file."""
        parser = ZoneFileParser("com", validate_domains=False)
        domains = list(parser.parse_file(sample_zone_file))

        assert len(domains) > 0
        assert "example.com" in domains
        assert "test.com" in domains

    def test_parse_gzip_file(self, sample_gzip_zone_file):
        """Test parsing gzipped zone file."""
        parser = ZoneFileParser("com", validate_domains=False)
        domains = list(parser.parse_file(sample_gzip_zone_file))

        assert len(domains) > 0
        assert "example.com" in domains

    def test_parse_with_validation(self, sample_zone_file):
        """Test parsing with domain validation."""
        parser = ZoneFileParser("com", validate_domains=True)
        domains = list(parser.parse_file(sample_zone_file))

        # Invalid domains should be filtered out
        for domain in domains:
            assert ".." not in domain

    def test_max_domains_limit(self, sample_zone_file):
        """Test limiting number of domains parsed."""
        parser = ZoneFileParser("com", validate_domains=False)
        domains = list(parser.parse_file(sample_zone_file, max_domains=2))

        assert len(domains) <= 2

    def test_nonexistent_file(self):
        """Test that nonexistent files raise error."""
        parser = ZoneFileParser("com")

        with pytest.raises(ParseError):
            list(parser.parse_file(Path("/nonexistent/file.txt")))


class TestDomainExtraction:
    """Test domain extraction from lines."""

    def test_extract_domain_basic(self):
        """Test basic domain extraction."""
        parser = ZoneFileParser("com", validate_domains=False)

        domain = parser._extract_domain("example.com\tns1.example.com")
        assert domain == "example.com"

    def test_extract_domain_with_trailing_dot(self):
        """Test domain with trailing dot (common in zone files)."""
        parser = ZoneFileParser("com", validate_domains=False)

        domain = parser._extract_domain("example.com.\tns1.example.com")
        assert domain == "example.com"

    def test_extract_domain_whitespace(self):
        """Test domain extraction with whitespace separation."""
        parser = ZoneFileParser("com", validate_domains=False)

        domain = parser._extract_domain("example.com   ns1.example.com")
        assert domain == "example.com"

    def test_skip_comments(self):
        """Test that comments are skipped."""
        parser = ZoneFileParser("com", validate_domains=False)

        domain = parser._extract_domain("; This is a comment")
        assert domain is None

    def test_skip_empty_lines(self):
        """Test that empty lines are skipped."""
        parser = ZoneFileParser("com", validate_domains=False)

        domain = parser._extract_domain("")
        assert domain is None


class TestUniqueDomainsExtraction:
    """Test extracting unique domains."""

    def test_get_unique_domains(self, sample_zone_file):
        """Test getting set of unique domains."""
        parser = ZoneFileParser("com", validate_domains=False)
        unique = parser.get_unique_domains(sample_zone_file)

        # File has duplicate "example.com" entries
        assert isinstance(unique, set)
        assert "example.com" in unique

    def test_extract_to_file(self, sample_zone_file, temp_dir):
        """Test extracting unique domains to file."""
        output_file = temp_dir / "unique.txt"

        count = extract_unique_domains(
            sample_zone_file,
            output_file,
            "com",
            validate=False
        )

        assert count > 0
        assert output_file.exists()

        # Verify output
        content = output_file.read_text()
        assert "example.com" in content


class TestStatistics:
    """Test domain statistics generation."""

    def test_get_statistics(self, sample_zone_file):
        """Test getting domain statistics."""
        parser = ZoneFileParser("com", validate_domains=False)
        stats = parser.get_domain_statistics(sample_zone_file)

        assert 'total_domains' in stats
        assert 'unique_domains' in stats
        assert 'duplicate_count' in stats
        assert stats['total_domains'] >= stats['unique_domains']

    def test_statistics_length_info(self, sample_zone_file):
        """Test that statistics include length information."""
        parser = ZoneFileParser("com", validate_domains=False)
        stats = parser.get_domain_statistics(sample_zone_file)

        assert 'length' in stats
        assert 'min' in stats['length']
        assert 'max' in stats['length']
        assert 'avg' in stats['length']


class TestMalformedInput:
    """Test handling of malformed input."""

    def test_extremely_long_line(self, temp_dir):
        """Test handling of extremely long lines."""
        zone_file = temp_dir / "long.txt"
        zone_file.write_text("x" * 20000 + "\n" + "example.com\tns1")

        parser = ZoneFileParser("com", validate_domains=False)

        # Should not crash, but skip the long line
        domains = list(parser.parse_file(zone_file))
        assert "example.com" in domains

    def test_binary_garbage(self, temp_dir):
        """Test handling of binary garbage data."""
        zone_file = temp_dir / "garbage.txt"
        zone_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd\xfc")

        parser = ZoneFileParser("com", validate_domains=False)

        # Should handle gracefully
        try:
            domains = list(parser.parse_file(zone_file))
            # Should either get empty list or handle encoding errors
            assert isinstance(domains, list)
        except ParseError:
            # Or raise a clear parse error
            pass

    def test_too_many_invalid_lines(self, temp_dir):
        """Test that too many invalid lines raises error."""
        # Create file with many invalid lines
        zone_file = temp_dir / "invalid.txt"
        invalid_lines = [f"invalid..domain{i}.com\n" for i in range(2000)]
        zone_file.write_text("".join(invalid_lines))

        parser = ZoneFileParser("com", validate_domains=True)

        # Should raise error after too many invalid lines
        with pytest.raises(ParseError):
            list(parser.parse_file(zone_file))

    def test_malformed_gzip(self, temp_dir):
        """Test handling of malformed gzip files."""
        zone_file = temp_dir / "bad.gz"
        zone_file.write_bytes(b"Not a real gzip file")

        parser = ZoneFileParser("com")

        with pytest.raises(ParseError):
            list(parser.parse_file(zone_file))


class TestSecurityScenarios:
    """Test security-related scenarios."""

    def test_path_traversal_in_filename(self):
        """Test that path traversal in filename is blocked."""
        parser = ZoneFileParser("com")

        with pytest.raises(ParseError):
            list(parser.parse_file(Path("../../../etc/passwd")))

    def test_null_byte_in_domain(self, temp_dir):
        """Test handling of null bytes in domain names."""
        zone_file = temp_dir / "null.txt"
        zone_file.write_bytes(b"example\x00.com\tns1\n")

        parser = ZoneFileParser("com", validate_domains=True)

        # Null bytes should be rejected during validation
        domains = list(parser.parse_file(zone_file))
        for domain in domains:
            assert '\x00' not in domain

    def test_unicode_handling(self, temp_dir):
        """Test handling of unicode domain names."""
        zone_file = temp_dir / "unicode.txt"
        zone_file.write_text("例え.com\tns1.example.com\nexample.com\tns2")

        parser = ZoneFileParser("com", validate_domains=False)

        # Should handle unicode gracefully
        domains = list(parser.parse_file(zone_file))
        assert len(domains) >= 1
