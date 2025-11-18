"""Zone file parser with validation and sanitization.

This module safely parses CZDS zone files, extracting unique domain names
with comprehensive input validation and error handling.
"""

import gzip
import logging
from pathlib import Path
from typing import Iterator, Optional, Set
from collections import Counter

from czds_utils.errors import ParseError, ValidationError
from czds_utils.validators import Validators


class ZoneFileParser:
    """Secure parser for CZDS zone files.

    Handles both plain text and gzipped zone files with validation.
    """

    # Zone file field separator
    FIELD_SEPARATOR = '\t'

    # Maximum line length to prevent memory issues
    MAX_LINE_LENGTH = 10000

    # Maximum file size to process (in bytes)
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB

    def __init__(self, tld: str, validate_domains: bool = True):
        """Initialize zone file parser.

        Args:
            tld: TLD being parsed (validated)
            validate_domains: Whether to validate each domain

        Raises:
            ValidationError: If TLD is invalid
        """
        self.tld = Validators.validate_tld(tld, 'tld')
        self.validate_domains = validate_domains
        self._logger = logging.getLogger(__name__)

    def parse_file(
        self,
        file_path: Path,
        max_domains: Optional[int] = None
    ) -> Iterator[str]:
        """Parse a zone file and yield domain names.

        Args:
            file_path: Path to zone file (plain or gzipped)
            max_domains: Maximum number of domains to parse (for testing)

        Yields:
            Valid domain names

        Raises:
            ParseError: If parsing fails
            ValidationError: If file path is invalid
        """
        # Validate file path
        try:
            file_path = Validators.validate_path(
                str(file_path),
                'file_path',
                must_exist=True,
                must_be_file=True
            )
        except ValidationError as e:
            raise ParseError(f"Invalid file path: {e.safe_message}")

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > self.MAX_FILE_SIZE:
            raise ParseError(
                f"File too large: {file_size} bytes (max: {self.MAX_FILE_SIZE})"
            )

        # Determine if file is gzipped
        is_gzipped = file_path.suffix.lower() in ['.gz', '.gzip']

        self._logger.info(
            f"Parsing zone file: {file_path.name} "
            f"({'gzipped' if is_gzipped else 'plain text'}, {file_size:,} bytes)"
        )

        try:
            domains_parsed = 0

            if is_gzipped:
                with gzip.open(file_path, 'rt', encoding='utf-8', errors='replace') as f:
                    for domain in self._parse_stream(f):
                        yield domain
                        domains_parsed += 1

                        if max_domains and domains_parsed >= max_domains:
                            self._logger.info(f"Reached max_domains limit: {max_domains}")
                            break
            else:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    for domain in self._parse_stream(f):
                        yield domain
                        domains_parsed += 1

                        if max_domains and domains_parsed >= max_domains:
                            self._logger.info(f"Reached max_domains limit: {max_domains}")
                            break

            self._logger.info(f"Parsed {domains_parsed:,} domains from {file_path.name}")

        except gzip.BadGzipFile as e:
            raise ParseError(f"Invalid gzip file: {str(e)}")
        except IOError as e:
            raise ParseError(f"File read error: {str(e)}")
        except Exception as e:
            raise ParseError(f"Unexpected error while parsing: {str(e)}")

    def _parse_stream(self, stream) -> Iterator[str]:
        """Parse zone data from a stream.

        Args:
            stream: File-like object to read from

        Yields:
            Valid domain names

        Raises:
            ParseError: If parsing fails
        """
        line_number = 0
        invalid_count = 0
        max_invalid = 1000  # Stop if too many invalid lines

        for line in stream:
            line_number += 1

            # Security check: limit line length
            if len(line) > self.MAX_LINE_LENGTH:
                self._logger.warning(
                    f"Line {line_number} exceeds maximum length, skipping"
                )
                invalid_count += 1
                if invalid_count > max_invalid:
                    raise ParseError(
                        f"Too many invalid lines (>{max_invalid})",
                        line_number=line_number
                    )
                continue

            # Skip empty lines and comments
            line = line.strip()
            if not line or line.startswith(';') or line.startswith('#'):
                continue

            try:
                # Extract domain from line
                domain = self._extract_domain(line)

                if domain:
                    # Validate domain if enabled
                    if self.validate_domains:
                        try:
                            domain = Validators.validate_domain(domain, 'domain')
                        except ValidationError:
                            invalid_count += 1
                            if invalid_count > max_invalid:
                                raise ParseError(
                                    f"Too many invalid domains (>{max_invalid})",
                                    line_number=line_number
                                )
                            continue

                    yield domain

            except Exception as e:
                self._logger.debug(
                    f"Error parsing line {line_number}: {str(e)}"
                )
                invalid_count += 1
                if invalid_count > max_invalid:
                    raise ParseError(
                        f"Too many parse errors (>{max_invalid})",
                        line_number=line_number
                    )

    def _extract_domain(self, line: str) -> Optional[str]:
        """Extract domain name from a zone file line.

        Zone file format (tab-separated):
        domain.tld    nameserver    ...

        Args:
            line: Line from zone file

        Returns:
            Domain name or None if invalid
        """
        # Split by tab or whitespace
        parts = line.split(self.FIELD_SEPARATOR) if self.FIELD_SEPARATOR in line else line.split()

        if not parts:
            return None

        # First field is typically the domain
        domain = parts[0].strip().lower()

        # Remove trailing dot if present (common in zone files)
        if domain.endswith('.'):
            domain = domain[:-1]

        # Skip if empty after processing
        if not domain:
            return None

        # Basic sanity check
        if len(domain) < 3 or len(domain) > 253:
            return None

        return domain

    def get_unique_domains(
        self,
        file_path: Path,
        max_domains: Optional[int] = None
    ) -> Set[str]:
        """Parse file and return set of unique domains.

        Args:
            file_path: Path to zone file
            max_domains: Maximum number of domains to parse

        Returns:
            Set of unique domain names

        Raises:
            ParseError: If parsing fails
        """
        unique_domains = set()

        for domain in self.parse_file(file_path, max_domains):
            unique_domains.add(domain)

        return unique_domains

    def get_domain_statistics(self, file_path: Path) -> dict:
        """Get statistics about domains in a zone file.

        Args:
            file_path: Path to zone file

        Returns:
            Dictionary with statistics

        Raises:
            ParseError: If parsing fails
        """
        total_count = 0
        unique_domains = set()
        tld_counter = Counter()
        length_stats = []

        for domain in self.parse_file(file_path):
            total_count += 1
            unique_domains.add(domain)

            # Track domain length
            length_stats.append(len(domain))

            # Extract TLD for verification
            parts = domain.split('.')
            if len(parts) >= 2:
                tld = parts[-1]
                tld_counter[tld] += 1

        stats = {
            'total_domains': total_count,
            'unique_domains': len(unique_domains),
            'duplicate_count': total_count - len(unique_domains),
            'tld_distribution': dict(tld_counter.most_common(10)),
        }

        if length_stats:
            stats['length'] = {
                'min': min(length_stats),
                'max': max(length_stats),
                'avg': sum(length_stats) / len(length_stats)
            }

        return stats


def extract_unique_domains(
    input_file: Path,
    output_file: Path,
    tld: str,
    validate: bool = True
) -> int:
    """Extract unique domains from zone file and save to output.

    This is a convenience function for the common use case.

    Args:
        input_file: Input zone file path
        output_file: Output file path for unique domains
        tld: TLD being processed
        validate: Whether to validate domains

    Returns:
        Number of unique domains extracted

    Raises:
        ParseError: If parsing fails
        ValidationError: If inputs are invalid
    """
    # Validate output path
    if not isinstance(output_file, Path):
        output_file = Path(output_file)

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Parse and collect unique domains
    parser = ZoneFileParser(tld, validate_domains=validate)
    unique_domains = parser.get_unique_domains(input_file)

    # Write to output file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for domain in sorted(unique_domains):
                f.write(f"{domain}\n")
    except IOError as e:
        raise ParseError(f"Failed to write output file: {str(e)}")

    return len(unique_domains)
