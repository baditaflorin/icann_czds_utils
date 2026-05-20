"""Command-line interface for CZDS Utils."""

import argparse
import logging
import sys
from pathlib import Path

from czds_utils.config import get_config
from czds_utils.database import Database
from czds_utils.api_client import CZDSClient
from czds_utils.parser import ZoneFileParser
from czds_utils.errors import CZDSError


def setup_logging(verbose: bool = False):
    """Setup logging configuration.

    Args:
        verbose: Enable verbose (DEBUG) logging
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def cmd_authenticate(args):
    """Test authentication with CZDS API."""
    config = get_config()

    client = CZDSClient(
        config.CZDS_API_BASE_URL,
        config.CZDS_USERNAME,
        config.CZDS_PASSWORD,
        auth_url=config.CZDS_AUTH_URL,
        timeout=config.REQUEST_TIMEOUT,
        max_retries=config.MAX_RETRIES,
        validate_ssl=config.VALIDATE_SSL
    )

    token = client.authenticate()
    print(f"✓ Authentication successful!")
    print(f"Token: {token[:50]}...")


def cmd_list_zones(args):
    """List available zone files."""
    config = get_config()

    client = CZDSClient(
        config.CZDS_API_BASE_URL,
        config.CZDS_USERNAME,
        config.CZDS_PASSWORD,
        auth_url=config.CZDS_AUTH_URL,
        timeout=config.REQUEST_TIMEOUT,
        max_retries=config.MAX_RETRIES,
        validate_ssl=config.VALIDATE_SSL
    )

    links = client.get_zone_links()
    print(f"\n✓ Found {len(links)} available zone files:\n")

    for link in sorted(links):
        # Extract TLD from link
        tld = link.split('/')[-1].split('.')[0]
        print(f"  • {tld:<10} {link}")


def cmd_download(args):
    """Download a zone file."""
    config = get_config()

    client = CZDSClient(
        config.CZDS_API_BASE_URL,
        config.CZDS_USERNAME,
        config.CZDS_PASSWORD,
        auth_url=config.CZDS_AUTH_URL,
        timeout=config.REQUEST_TIMEOUT,
        max_retries=config.MAX_RETRIES,
        validate_ssl=config.VALIDATE_SSL
    )

    # Get zone info
    zone_info = client.get_zone_info(args.tld)
    if not zone_info:
        print(f"✗ Zone file for .{args.tld} not found")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = config.ZONE_FILES_DIR / f"{args.tld}.txt.gz"

    print(f"Downloading zone file for .{args.tld}...")

    def progress_callback(downloaded, total, percent):
        print(f"\r  Progress: {percent:.1f}% ({downloaded:,} / {total:,} bytes)", end='')

    stats = client.download_zone_file(
        zone_info['download_url'],
        output_path,
        chunk_size=config.CHUNK_SIZE,
        progress_callback=progress_callback if not args.quiet else None
    )

    print(f"\n\n✓ Download complete!")
    print(f"  File: {stats['file_path']}")
    print(f"  Size: {stats['bytes_downloaded']:,} bytes")
    print(f"  Time: {stats['download_time_seconds']:.2f}s")
    print(f"  Speed: {stats['download_speed_mbps']:.2f} MB/s")


def cmd_parse(args):
    """Parse a zone file."""
    config = get_config()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ File not found: {input_path}")
        sys.exit(1)

    print(f"Parsing zone file: {input_path}")

    parser = ZoneFileParser(args.tld, validate_domains=not args.no_validate)

    if args.import_db:
        # Import to database
        db = Database(config.DATABASE_PATH, config.DATABASE_TIMEOUT)

        batch = []
        batch_size = 1000
        total_imported = 0

        for domain in parser.parse_file(input_path):
            batch.append(domain)

            if len(batch) >= batch_size:
                count = db.add_domains_batch(args.tld, batch)
                total_imported += count
                batch = []

                if not args.quiet:
                    print(f"\r  Imported: {total_imported:,} domains", end='')

        # Import remaining
        if batch:
            count = db.add_domains_batch(args.tld, batch)
            total_imported += count

        print(f"\n\n✓ Import complete: {total_imported:,} domains")

    elif args.output:
        # Extract unique domains to file
        unique_domains = parser.get_unique_domains(input_path)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            for domain in sorted(unique_domains):
                f.write(f"{domain}\n")

        print(f"\n✓ Extracted {len(unique_domains):,} unique domains to {output_path}")

    else:
        # Just show statistics
        stats = parser.get_domain_statistics(input_path)

        print(f"\n✓ Parse complete!")
        print(f"  Total domains: {stats['total_domains']:,}")
        print(f"  Unique domains: {stats['unique_domains']:,}")
        print(f"  Duplicates: {stats['duplicate_count']:,}")

        if 'length' in stats:
            print(f"\n  Domain length statistics:")
            print(f"    Min: {stats['length']['min']}")
            print(f"    Max: {stats['length']['max']}")
            print(f"    Avg: {stats['length']['avg']:.1f}")


def cmd_db_stats(args):
    """Show database statistics."""
    config = get_config()
    db = Database(config.DATABASE_PATH, config.DATABASE_TIMEOUT)

    stats = db.get_statistics()

    print("\nDatabase Statistics:")
    print(f"  Total TLDs: {stats['total_tlds']:,}")
    print(f"  Total Domains: {stats['total_domains']:,}")
    print(f"  Total Downloads: {stats['total_downloads']:,}")
    print(f"  Successful Downloads: {stats['successful_downloads']:,}")
    print(f"  Database Size: {stats['database_size_bytes']:,} bytes")

    # Show TLDs
    if args.verbose:
        print("\nTLDs in database:")
        tlds = db.get_all_tlds()
        for tld_info in tlds:
            print(f"  • {tld_info['tld']:<10} {tld_info['total_domains']:>10,} domains")


def cmd_db_query(args):
    """Query domains from database."""
    config = get_config()
    db = Database(config.DATABASE_PATH, config.DATABASE_TIMEOUT)

    total_count = db.get_domain_count(args.tld)
    print(f"\nTotal domains for .{args.tld}: {total_count:,}")

    domains = db.get_domains_by_tld(args.tld, limit=args.limit)

    print(f"Showing first {len(domains)} domains:\n")
    for domain_info in domains:
        print(f"  {domain_info['domain']}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='ICANN CZDS Utils - Secure zone file management'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress progress output'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Authenticate command
    subparsers.add_parser(
        'auth',
        help='Test authentication with CZDS API'
    )

    # List zones command
    subparsers.add_parser(
        'list',
        help='List available zone files'
    )

    # Download command
    download_parser = subparsers.add_parser(
        'download',
        help='Download a zone file'
    )
    download_parser.add_argument('tld', help='TLD to download')
    download_parser.add_argument('-o', '--output', help='Output file path')

    # Parse command
    parse_parser = subparsers.add_parser(
        'parse',
        help='Parse a zone file'
    )
    parse_parser.add_argument('tld', help='TLD being parsed')
    parse_parser.add_argument('input', help='Input zone file')
    parse_parser.add_argument('-o', '--output', help='Output file for unique domains')
    parse_parser.add_argument('--import-db', action='store_true', help='Import to database')
    parse_parser.add_argument('--no-validate', action='store_true', help='Skip domain validation')

    # DB stats command
    stats_parser = subparsers.add_parser(
        'stats',
        help='Show database statistics'
    )

    # DB query command
    query_parser = subparsers.add_parser(
        'query',
        help='Query domains from database'
    )
    query_parser.add_argument('tld', help='TLD to query')
    query_parser.add_argument('-l', '--limit', type=int, default=100, help='Max results')

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Execute command
    try:
        if args.command == 'auth':
            cmd_authenticate(args)
        elif args.command == 'list':
            cmd_list_zones(args)
        elif args.command == 'download':
            cmd_download(args)
        elif args.command == 'parse':
            cmd_parse(args)
        elif args.command == 'stats':
            cmd_db_stats(args)
        elif args.command == 'query':
            cmd_db_query(args)
        else:
            parser.print_help()
            sys.exit(1)

    except CZDSError as e:
        print(f"\n✗ Error: {e.safe_message}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(130)


if __name__ == '__main__':
    main()
