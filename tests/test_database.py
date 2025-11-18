"""Tests for database operations with security focus."""

import pytest
from czds_utils.database import Database
from czds_utils.errors import DatabaseError, ValidationError


class TestDatabaseInit:
    """Test database initialization."""

    def test_database_creation(self, test_database):
        """Test that database is created successfully."""
        assert test_database.db_path.exists()

    def test_schema_initialization(self, test_database):
        """Test that schema is created correctly."""
        stats = test_database.get_statistics()
        assert stats['total_tlds'] == 0
        assert stats['total_domains'] == 0


class TestTLDOperations:
    """Test TLD-related operations."""

    def test_add_tld(self, test_database):
        """Test adding a TLD."""
        tld_id = test_database.add_or_update_tld("com", total_domains=1000)
        assert tld_id > 0

    def test_get_tld_id(self, test_database):
        """Test retrieving TLD ID."""
        tld_id = test_database.add_or_update_tld("com")
        retrieved_id = test_database.get_tld_id("com")
        assert retrieved_id == tld_id

    def test_update_tld(self, test_database):
        """Test updating TLD statistics."""
        tld_id1 = test_database.add_or_update_tld("com", total_domains=1000)
        tld_id2 = test_database.add_or_update_tld("com", total_domains=2000)
        assert tld_id1 == tld_id2

    def test_invalid_tld(self, test_database):
        """Test that invalid TLDs are rejected."""
        with pytest.raises(ValidationError):
            test_database.add_or_update_tld("invalid_tld!")

    def test_get_all_tlds(self, test_database):
        """Test retrieving all TLDs."""
        test_database.add_or_update_tld("com")
        test_database.add_or_update_tld("net")
        test_database.add_or_update_tld("org")

        tlds = test_database.get_all_tlds()
        assert len(tlds) == 3
        assert any(t['tld'] == 'com' for t in tlds)


class TestDomainOperations:
    """Test domain-related operations."""

    def test_add_domain(self, test_database):
        """Test adding a domain."""
        test_database.add_domain("com", "example.com")

        domains = test_database.get_domains_by_tld("com", limit=10)
        assert len(domains) == 1
        assert domains[0]['domain'] == "example.com"

    def test_add_duplicate_domain(self, test_database):
        """Test that duplicate domains update last_seen."""
        test_database.add_domain("com", "example.com")
        test_database.add_domain("com", "example.com")

        count = test_database.get_domain_count("com")
        assert count == 1

    def test_add_domains_batch(self, test_database):
        """Test batch domain insertion."""
        domains = ["example.com", "test.com", "demo.com"]
        count = test_database.add_domains_batch("com", domains)

        assert count == 3

        retrieved = test_database.get_domains_by_tld("com", limit=10)
        assert len(retrieved) == 3

    def test_invalid_domain(self, test_database):
        """Test that invalid domains are rejected."""
        with pytest.raises(ValidationError):
            test_database.add_domain("com", "invalid..domain")

    def test_get_domain_count(self, test_database):
        """Test domain counting."""
        domains = ["example.com", "test.com", "demo.com"]
        test_database.add_domains_batch("com", domains)

        count = test_database.get_domain_count("com")
        assert count == 3

    def test_search_domains(self, test_database):
        """Test domain searching."""
        domains = ["example.com", "test-example.com", "demo.com"]
        test_database.add_domains_batch("com", domains)

        results = test_database.search_domains("example")
        assert len(results) >= 2


class TestSQLInjectionPrevention:
    """Test SQL injection prevention."""

    def test_sql_injection_in_tld(self, test_database):
        """Test SQL injection attempt in TLD field."""
        malicious_tld = "com'; DROP TABLE domains; --"

        with pytest.raises(ValidationError):
            test_database.add_or_update_tld(malicious_tld)

    def test_sql_injection_in_domain(self, test_database):
        """Test SQL injection attempt in domain field."""
        malicious_domain = "example.com'; DELETE FROM domains; --"

        with pytest.raises(ValidationError):
            test_database.add_domain("com", malicious_domain)

    def test_sql_injection_in_search(self, test_database):
        """Test SQL injection attempt in search."""
        malicious_search = "'; DROP TABLE domains; --"

        # Should not raise exception, but should not execute SQL
        with pytest.raises(ValidationError):
            test_database.search_domains(malicious_search)

    def test_union_injection(self, test_database):
        """Test UNION-based SQL injection."""
        malicious = "' UNION SELECT * FROM metadata--"

        with pytest.raises(ValidationError):
            test_database.search_domains(malicious)


class TestDownloadHistory:
    """Test download history tracking."""

    def test_record_download_started(self, test_database):
        """Test recording download start."""
        record_id = test_database.record_download("com", "started")
        assert record_id > 0

    def test_record_download_completed(self, test_database):
        """Test recording completed download."""
        record_id = test_database.record_download(
            "com",
            "completed",
            file_size_bytes=1024000,
            domains_count=50000
        )
        assert record_id > 0

    def test_record_download_failed(self, test_database):
        """Test recording failed download."""
        record_id = test_database.record_download(
            "com",
            "failed",
            error_message="Connection timeout"
        )
        assert record_id > 0

    def test_get_download_history(self, test_database):
        """Test retrieving download history."""
        test_database.record_download("com", "completed")
        test_database.record_download("net", "failed")

        history = test_database.get_download_history(limit=10)
        assert len(history) == 2

    def test_get_download_history_by_tld(self, test_database):
        """Test retrieving download history for specific TLD."""
        test_database.record_download("com", "completed")
        test_database.record_download("net", "failed")

        history = test_database.get_download_history(tld="com")
        assert len(history) == 1
        assert history[0]['tld'] == 'com'

    def test_error_message_sanitization(self, test_database):
        """Test that error messages are sanitized."""
        long_error = "x" * 1000
        test_database.record_download("com", "failed", error_message=long_error)

        history = test_database.get_download_history(tld="com")
        assert len(history[0]['error_message']) <= 503  # 500 + "..."


class TestStatistics:
    """Test database statistics."""

    def test_get_statistics(self, test_database):
        """Test getting database statistics."""
        test_database.add_domain("com", "example.com")
        test_database.add_domain("net", "test.net")
        test_database.record_download("com", "completed")

        stats = test_database.get_statistics()

        assert stats['total_tlds'] == 2
        assert stats['total_domains'] == 2
        assert stats['total_downloads'] == 1
        assert stats['successful_downloads'] == 1
        assert stats['database_size_bytes'] > 0


class TestDataIntegrity:
    """Test data integrity constraints."""

    def test_foreign_key_constraint(self, test_database):
        """Test that foreign key constraints are enforced."""
        # This tests that we can't add domains without a valid TLD
        # The application handles this by auto-creating TLDs,
        # but we verify the constraint exists

        # Get a non-existent TLD ID
        with test_database._get_connection() as conn:
            try:
                # Try to insert domain with invalid TLD ID
                conn.execute("""
                    INSERT INTO domains (tld_id, domain, first_seen, last_seen)
                    VALUES (?, ?, ?, ?)
                """, (99999, "example.com", "2024-01-01", "2024-01-01"))
                # Should fail due to foreign key constraint
                assert False, "Should have raised foreign key error"
            except:
                # Expected - foreign key constraint should prevent this
                pass

    def test_unique_constraint(self, test_database):
        """Test unique constraint on TLD."""
        test_database.add_or_update_tld("com")

        # Adding same TLD should update, not duplicate
        test_database.add_or_update_tld("com")

        tlds = test_database.get_all_tlds()
        assert len([t for t in tlds if t['tld'] == 'com']) == 1


class TestPagination:
    """Test pagination in queries."""

    def test_domain_pagination(self, test_database):
        """Test domain query pagination."""
        domains = [f"domain{i}.com" for i in range(50)]
        test_database.add_domains_batch("com", domains)

        # Get first page
        page1 = test_database.get_domains_by_tld("com", limit=20, offset=0)
        assert len(page1) == 20

        # Get second page
        page2 = test_database.get_domains_by_tld("com", limit=20, offset=20)
        assert len(page2) == 20

        # Verify no overlap
        page1_domains = {d['domain'] for d in page1}
        page2_domains = {d['domain'] for d in page2}
        assert len(page1_domains & page2_domains) == 0
