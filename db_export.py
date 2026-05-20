#!/usr/bin/env python3
"""Export domains from the CZDS SQLite database to a plain text file.

Combines extraction, optional subdomain stripping, and optional DNS filtering
into a single pipeline so you can go straight from DB to a clean seed list.

Usage:
    # Export a single TLD
    python db_export.py --tld org --output /tmp/org.txt

    # Export multiple TLDs
    python db_export.py --tld net info xyz --output /tmp/combined.txt

    # Export + strip subdomains
    python db_export.py --tld org --output /tmp/org_apex.txt --strip-subdomains

    # Export + strip subdomains + DNS filter (active only)
    python db_export.py --tld org --output /tmp/org_active.txt --strip-subdomains --dns-filter

    # Export all TLDs in the database
    python db_export.py --all --output /tmp/all_domains.txt

    # List available TLDs and domain counts
    python db_export.py --list
"""

import argparse
import socket
import sqlite3
import sys
import concurrent.futures
import itertools
import time
from pathlib import Path

try:
    import tldextract
    _HAS_TLDEXTRACT = True
except ImportError:
    _HAS_TLDEXTRACT = False


DEFAULT_DB = Path(__file__).parent / "data" / "czds.db"


def parse_args():
    p = argparse.ArgumentParser(
        description="Export domains from CZDS database to a seed list file."
    )
    p.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite DB path (default: {DEFAULT_DB})")
    p.add_argument("--tld", nargs="+", metavar="TLD", help="One or more TLDs to export (e.g. org net info)")
    p.add_argument("--all", action="store_true", help="Export all TLDs in the database")
    p.add_argument("--list", action="store_true", help="List available TLDs and domain counts, then exit")
    p.add_argument("--output", "-o", help="Output file (default: stdout)")
    p.add_argument("--strip-subdomains", action="store_true", help="Keep only apex/registrable domains")
    p.add_argument("--dns-filter", action="store_true", help="Only output domains that resolve via DNS")
    p.add_argument("--dns-workers", type=int, default=300, help="DNS check concurrency (default: 300)")
    p.add_argument("--dns-timeout", type=float, default=3.0, help="DNS timeout seconds (default: 3)")
    p.add_argument("--limit", type=int, help="Max domains per TLD (useful for testing)")
    return p.parse_args()


def get_tlds(conn):
    rows = conn.execute(
        "SELECT t.tld, COUNT(d.id) FROM tlds t JOIN domains d ON d.tld_id = t.id GROUP BY t.tld ORDER BY COUNT(d.id) DESC"
    ).fetchall()
    return rows


def stream_domains(conn, tld, limit=None):
    sql = """
        SELECT d.domain FROM domains d
        JOIN tlds t ON d.tld_id = t.id
        WHERE t.tld = ?
        ORDER BY d.domain
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    for (domain,) in conn.execute(sql, (tld,)):
        yield domain


def apex(domain, parts=2):
    if _HAS_TLDEXTRACT:
        r = tldextract.extract(domain)
        if r.domain and r.suffix:
            return f"{r.domain}.{r.suffix}"
        return None
    p = domain.split(".")
    return ".".join(p[-parts:]) if len(p) >= parts else domain


def check_dns(domain, timeout):
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None, socket.AF_INET)
        return domain
    except Exception:
        return None


def dns_filter_stream(domains, workers, timeout):
    """Sliding-window DNS filter — yields only resolving domains."""
    pipeline = workers * 4
    domain_iter = iter(domains)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for domain in itertools.islice(domain_iter, pipeline):
            f = ex.submit(check_dns, domain, timeout)
            futures[f] = domain

        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for f in done:
                futures.pop(f)
                result = f.result()
                if result:
                    yield result
                try:
                    new_domain = next(domain_iter)
                    new_f = ex.submit(check_dns, new_domain, timeout)
                    futures[new_f] = new_domain
                except StopIteration:
                    pass


def main():
    args = parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    if args.list:
        rows = get_tlds(conn)
        print(f"{'TLD':<20} {'DOMAINS':>12}")
        print("-" * 34)
        for tld, count in rows:
            print(f"{tld:<20} {count:>12,}")
        print(f"\nTotal TLDs: {len(rows)}")
        conn.close()
        return

    if not args.tld and not args.all:
        print("Error: specify --tld <tld ...> or --all", file=sys.stderr)
        sys.exit(1)

    if args.all:
        tlds = [row[0] for row in get_tlds(conn)]
    else:
        tlds = args.tld

    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout

    try:
        seen = set()
        total = 0
        start = time.time()

        for tld in tlds:
            print(f"Exporting .{tld}...", file=sys.stderr)

            raw_stream = stream_domains(conn, tld, args.limit)

            if args.strip_subdomains:
                def stripped(stream):
                    for d in stream:
                        a = apex(d)
                        if a:
                            yield a
                domain_stream = stripped(raw_stream)
            else:
                domain_stream = raw_stream

            if args.dns_filter:
                if not args.strip_subdomains:
                    print(
                        "  Note: tldextract not installed" if not _HAS_TLDEXTRACT else "",
                        file=sys.stderr, end=""
                    )
                print(f"  DNS filtering with {args.dns_workers} workers...", file=sys.stderr)
                domain_stream = dns_filter_stream(domain_stream, args.dns_workers, args.dns_timeout)

            for domain in domain_stream:
                if domain not in seen:
                    seen.add(domain)
                    out.write(domain + "\n")
                    total += 1
                    if total % 100000 == 0:
                        elapsed = time.time() - start
                        print(f"  {total:,} written ({elapsed:.0f}s)", file=sys.stderr)

        elapsed = time.time() - start
        print(f"\nDone: {total:,} unique domains in {elapsed:.1f}s", file=sys.stderr)
        if args.output:
            print(f"Output: {args.output}", file=sys.stderr)

    finally:
        if out is not sys.stdout:
            out.close()
        conn.close()


if __name__ == "__main__":
    main()
