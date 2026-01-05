"""Database layer with fully parameterized queries and secure access patterns.

This module implements strict security practices:
- All queries use parameterized statements (no string concatenation)
- Input validation before database operations
- Least-privilege access patterns
- Safe error handling without leaking information
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from czds_utils.errors import DatabaseError, ValidationError
from czds_utils.validators import Validators


class Database:
    """Secure database interface for CZDS data storage.

    All operations use parameterized queries to prevent SQL injection.
    """

    # Schema version for migrations
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path, timeout: int = 30):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
            timeout: Connection timeout in seconds

        Raises:
            DatabaseError: If database initialization fails
        """
        self.db_path = db_path
        self.timeout = timeout
        self._logger = logging.getLogger(__name__)

        try:
            # Ensure parent directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)

            # Initialize database
            self._init_database()
            self._logger.info("Database initialized successfully")
        except Exception as e:
            self._logger.error(f"Database initialization failed: {str(e)}")
            raise DatabaseError(f"Failed to initialize database: {str(e)}")

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection

        Raises:
            DatabaseError: If connection fails
        """
        conn = None
        try:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=self.timeout,
                isolation_level='DEFERRED'
            )
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            # Use WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode = WAL")
            # Return rows as dictionaries
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            self._logger.error(f"Database connection error: {str(e)}")
            raise DatabaseError(f"Database operation failed: {str(e)}")
        finally:
            if conn:
                conn.close()

    @contextmanager
    def get_connection_context(self):
        """Public context manager for database connections (wraps _get_connection)."""
        with self._get_connection() as conn:
            yield conn

    def _init_database(self) -> None:
        """Initialize database schema.

        Raises:
            DatabaseError: If schema creation fails
        """
        with self._get_connection() as conn:
            # Metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # TLD tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tlds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tld TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    total_domains INTEGER DEFAULT 0,
                    file_size_bytes INTEGER DEFAULT 0,
                    CONSTRAINT tld_valid CHECK (length(tld) > 0 AND length(tld) <= 63)
                )
            """)

            # Create index on TLD for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tlds_tld ON tlds(tld)
            """)

            # Domain table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tld_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    FOREIGN KEY (tld_id) REFERENCES tlds(id) ON DELETE CASCADE,
                    CONSTRAINT domain_valid CHECK (length(domain) > 0 AND length(domain) <= 253),
                    UNIQUE(tld_id, domain)
                )
            """)

            # Create indexes for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_domains_tld_id ON domains(tld_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain)
            """)

            # Download history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tld TEXT NOT NULL,
                    download_started TEXT NOT NULL,
                    download_completed TEXT,
                    status TEXT NOT NULL,
                    file_size_bytes INTEGER,
                    domains_count INTEGER,
                    error_message TEXT,
                    CONSTRAINT status_valid CHECK (status IN ('started', 'completed', 'failed'))
                )
            """)

            # Create index on download history
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_download_history_tld
                ON download_history(tld, download_started DESC)
            """)

            # Set schema version
            self._set_metadata('schema_version', str(self.SCHEMA_VERSION))

    def _set_metadata(self, key: str, value: str) -> None:
        """Set metadata key-value pair (internal use).

        Args:
            key: Metadata key
            value: Metadata value

        Raises:
            DatabaseError: If operation fails
        """
        with self._get_connection() as conn:
            # Fully parameterized query - no string concatenation
            conn.execute("""
                INSERT OR REPLACE INTO metadata (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.utcnow().isoformat()))

    def get_metadata(self, key: str) -> Optional[str]:
        """Get metadata value by key.

        Args:
            key: Metadata key (validated)

        Returns:
            Metadata value or None if not found

        Raises:
            DatabaseError: If operation fails
            ValidationError: If key is invalid
        """
        # Validate input
        key = Validators.validate_string(key, 'metadata_key', max_length=100)
        Validators.check_sql_injection(key, 'metadata_key')

        with self._get_connection() as conn:
            # Parameterized query
            cursor = conn.execute(
                "SELECT value FROM metadata WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            return row['value'] if row else None

    def add_or_update_tld(
        self,
        tld: str,
        total_domains: int = 0,
        file_size_bytes: int = 0
    ) -> int:
        """Add or update a TLD record.

        Args:
            tld: TLD name (validated)
            total_domains: Total number of domains
            file_size_bytes: Zone file size in bytes

        Returns:
            TLD ID

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        tld = Validators.validate_tld(tld, 'tld')
        total_domains = Validators.validate_integer(
            total_domains, 'total_domains', min_value=0
        )
        file_size_bytes = Validators.validate_integer(
            file_size_bytes, 'file_size_bytes', min_value=0
        )

        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            # Parameterized INSERT OR REPLACE
            cursor = conn.execute("""
                INSERT INTO tlds (tld, created_at, last_updated, total_domains, file_size_bytes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tld) DO UPDATE SET
                    last_updated = excluded.last_updated,
                    total_domains = excluded.total_domains,
                    file_size_bytes = excluded.file_size_bytes
            """, (tld, now, now, total_domains, file_size_bytes))

            # Get the TLD ID
            tld_id = cursor.lastrowid
            if tld_id == 0:  # Was an update, not insert
                cursor = conn.execute(
                    "SELECT id FROM tlds WHERE tld = ?",
                    (tld,)
                )
                row = cursor.fetchone()
                tld_id = row['id'] if row else None

            if tld_id is None:
                raise DatabaseError("Failed to get TLD ID after insert/update")

            return tld_id

    def get_tld_id(self, tld: str) -> Optional[int]:
        """Get TLD ID by name.

        Args:
            tld: TLD name (validated)

        Returns:
            TLD ID or None if not found

        Raises:
            DatabaseError: If operation fails
            ValidationError: If TLD is invalid
        """
        # Validate input
        tld = Validators.validate_tld(tld, 'tld')

        with self._get_connection() as conn:
            # Parameterized query
            cursor = conn.execute(
                "SELECT id FROM tlds WHERE tld = ?",
                (tld,)
            )
            row = cursor.fetchone()
            return row['id'] if row else None

    def delete_tld(self, tld: str) -> bool:
        """Delete all data for a specific TLD.

        Args:
            tld: TLD name (validated)

        Returns:
            True if TLD was found and deleted, False otherwise

        Raises:
            DatabaseError: If operation fails
            ValidationError: If TLD is invalid
        """
        # Validate input
        tld = Validators.validate_tld(tld, 'tld')

        with self._get_connection() as conn:
            # Parameterized DELETE
            # Because of ON DELETE CASCADE, this will also delete all domains
            cursor = conn.execute(
                "DELETE FROM tlds WHERE tld = ?",
                (tld,)
            )
            return cursor.rowcount > 0

    def add_domain(self, tld: str, domain: str) -> None:
        """Add a domain to the database.

        Args:
            tld: TLD name (validated)
            domain: Full domain name (validated)

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        tld = Validators.validate_tld(tld, 'tld')
        domain = Validators.validate_domain(domain, 'domain')

        # Get or create TLD
        tld_id = self.get_tld_id(tld)
        if tld_id is None:
            tld_id = self.add_or_update_tld(tld)

        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            # Parameterized INSERT OR REPLACE
            conn.execute("""
                INSERT INTO domains (tld_id, domain, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tld_id, domain) DO UPDATE SET
                    last_seen = excluded.last_seen
            """, (tld_id, domain, now, now))

    def add_domains_batch(self, tld: str, domains: List[str], batch_size: int = 1000, conn=None) -> int:
        """Add multiple domains in batches for efficiency.

        Args:
            tld: TLD name (validated)
            domains: List of domain names (validated)
            batch_size: Number of domains per transaction
            conn: Optional existing database connection to reuse

        Returns:
            Number of domains added/updated

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate TLD
        tld = Validators.validate_tld(tld, 'tld')

        # Get or create TLD
        tld_id = self.get_tld_id(tld)
        if tld_id is None:
            tld_id = self.add_or_update_tld(tld)

        now = datetime.utcnow().isoformat()
        total_added = 0

        # Process in batches
        for i in range(0, len(domains), batch_size):
            batch = domains[i:i + batch_size]

            # Validate all domains in batch
            validated_batch = []
            for domain in batch:
                try:
                    validated_domain = Validators.validate_domain(domain, 'domain')
                    validated_batch.append(validated_domain)
                except ValidationError as e:
                    self._logger.warning(f"Skipping invalid domain: {e.safe_message}")
                    continue

            if not validated_batch:
                continue

            if not validated_batch:
                continue
            
            # Use provided connection or create new one context
            if conn:
                # Use existing connection
                conn.executemany("""
                    INSERT INTO domains (tld_id, domain, first_seen, last_seen)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(tld_id, domain) DO UPDATE SET
                        last_seen = excluded.last_seen
                """, [(tld_id, domain, now, now) for domain in validated_batch])
                total_added += len(validated_batch)
                # Commit if it's our responsibility? 
                # If we passed a connection, the caller likely manages the transaction/commit scope
                # But sqlite3 context manager commits on exit. 
                # If `conn` is passed, we assume it's an open connection.
                # Just executing is fine, but we should probably commit to be safe unless we are in a transaction block.
                # However, for batch performance, we WANT to hold commit.
                # Let's assume caller manages commit if they pass conn?
                # Actually, `sqlite3` connection object doesn't auto-commit on execute.
                # So we should call commit() if we want to confirm, OR rely on caller.
                # For `sqlite3.connect` with `DEFERRED`, we need to commit.
                conn.commit()
            
            else:
                with self._get_connection() as local_conn:
                    # Parameterized executemany for batch insert
                    local_conn.executemany("""
                        INSERT INTO domains (tld_id, domain, first_seen, last_seen)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(tld_id, domain) DO UPDATE SET
                            last_seen = excluded.last_seen
                    """, [(tld_id, domain, now, now) for domain in validated_batch])
                    
                    total_added += len(validated_batch)

        return total_added

    def get_domains_by_tld(self, tld: str, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """Get domains for a specific TLD with pagination.

        Args:
            tld: TLD name (validated)
            limit: Maximum number of results
            offset: Result offset for pagination

        Returns:
            List of domain records

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        tld = Validators.validate_tld(tld, 'tld')
        limit = Validators.validate_integer(limit, 'limit', min_value=1, max_value=10000)
        offset = Validators.validate_integer(offset, 'offset', min_value=0)

        with self._get_connection() as conn:
            # Parameterized query with JOIN
            cursor = conn.execute("""
                SELECT d.domain, d.first_seen, d.last_seen
                FROM domains d
                JOIN tlds t ON d.tld_id = t.id
                WHERE t.tld = ?
                ORDER BY d.domain
                LIMIT ? OFFSET ?
            """, (tld, limit, offset))

            return [dict(row) for row in cursor.fetchall()]

    def get_domain_count(self, tld: str) -> int:
        """Get total number of domains for a TLD.

        Args:
            tld: TLD name (validated)

        Returns:
            Domain count

        Raises:
            DatabaseError: If operation fails
            ValidationError: If TLD is invalid
        """
        # Validate input
        tld = Validators.validate_tld(tld, 'tld')

        with self._get_connection() as conn:
            # Parameterized query
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM domains d
                JOIN tlds t ON d.tld_id = t.id
                WHERE t.tld = ?
            """, (tld,))

            row = cursor.fetchone()
            return row['count'] if row else 0

    def get_all_tlds(self) -> List[Dict[str, Any]]:
        """Get all TLDs with statistics.

        Returns:
            List of TLD records with statistics

        Raises:
            DatabaseError: If operation fails
        """
        with self._get_connection() as conn:
            # Parameterized query (no user input)
            cursor = conn.execute("""
                SELECT
                    tld,
                    created_at,
                    last_updated,
                    total_domains,
                    file_size_bytes
                FROM tlds
                ORDER BY tld
            """)

            return [dict(row) for row in cursor.fetchall()]

    def record_download(
        self,
        tld: str,
        status: str,
        file_size_bytes: Optional[int] = None,
        domains_count: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> int:
        """Record a download attempt.

        Args:
            tld: TLD name (validated)
            status: Download status (validated)
            file_size_bytes: File size if successful
            domains_count: Number of domains if successful
            error_message: Error message if failed (sanitized)

        Returns:
            Download record ID

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        tld = Validators.validate_tld(tld, 'tld')

        valid_statuses = ['started', 'completed', 'failed']
        if status not in valid_statuses:
            raise ValidationError(
                f"Invalid status: {status}. Must be one of {valid_statuses}",
                'status'
            )

        now = datetime.utcnow().isoformat()
        completed = now if status == 'completed' else None

        # Sanitize error message if present
        if error_message:
            error_message = Validators.sanitize_for_display(error_message, max_length=500)

        with self._get_connection() as conn:
            # Parameterized INSERT
            cursor = conn.execute("""
                INSERT INTO download_history
                (tld, download_started, download_completed, status, file_size_bytes, domains_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (tld, now, completed, status, file_size_bytes, domains_count, error_message))

            return cursor.lastrowid

    def get_download_history(self, tld: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get download history, optionally filtered by TLD.

        Args:
            tld: Optional TLD to filter by (validated if provided)
            limit: Maximum number of results

        Returns:
            List of download records

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate limit
        limit = Validators.validate_integer(limit, 'limit', min_value=1, max_value=1000)

        with self._get_connection() as conn:
            if tld:
                # Validate TLD
                tld = Validators.validate_tld(tld, 'tld')

                # Parameterized query with WHERE clause
                cursor = conn.execute("""
                    SELECT *
                    FROM download_history
                    WHERE tld = ?
                    ORDER BY download_started DESC
                    LIMIT ?
                """, (tld, limit))
            else:
                # Parameterized query without filter
                cursor = conn.execute("""
                    SELECT *
                    FROM download_history
                    ORDER BY download_started DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def search_domains(self, pattern: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Search for domains matching a pattern.

        Args:
            pattern: Search pattern (validated, SQL-safe)
            limit: Maximum number of results

        Returns:
            List of matching domain records

        Raises:
            DatabaseError: If operation fails
            ValidationError: If inputs are invalid
        """
        # Validate and sanitize pattern
        pattern = Validators.validate_string(pattern, 'pattern', max_length=100)
        Validators.check_sql_injection(pattern, 'pattern')

        limit = Validators.validate_integer(limit, 'limit', min_value=1, max_value=1000)

        # Use parameterized LIKE query
        search_pattern = f"%{pattern}%"

        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT d.domain, t.tld, d.first_seen, d.last_seen
                FROM domains d
                JOIN tlds t ON d.tld_id = t.id
                WHERE d.domain LIKE ?
                ORDER BY d.domain
                LIMIT ?
            """, (search_pattern, limit))

            return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall database statistics.

        Returns:
            Dictionary with statistics

        Raises:
            DatabaseError: If operation fails
        """
        with self._get_connection() as conn:
            # Total TLDs
            cursor = conn.execute("SELECT COUNT(*) as count FROM tlds")
            total_tlds = cursor.fetchone()['count']

            # Total domains
            cursor = conn.execute("SELECT COUNT(*) as count FROM domains")
            total_domains = cursor.fetchone()['count']

            # Total downloads
            cursor = conn.execute("SELECT COUNT(*) as count FROM download_history")
            total_downloads = cursor.fetchone()['count']

            # Successful downloads
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM download_history
                WHERE status = ?
            """, ('completed',))
            successful_downloads = cursor.fetchone()['count']

            # Database file size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            return {
                'total_tlds': total_tlds,
                'total_domains': total_domains,
                'total_downloads': total_downloads,
                'successful_downloads': successful_downloads,
                'database_size_bytes': db_size,
            }
