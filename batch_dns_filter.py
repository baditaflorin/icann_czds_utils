#!/usr/bin/env python3
"""Stream a zone file in 5M-domain batches, DNS-filter each batch,
and append clean results to a running output file.

Designed for huge zone files (.com, .net) where you want usable
results fast — each batch produces output as soon as it finishes,
so you can start feeding the residential proxy before the full file
is processed.

Usage:
    # From a zone file (streams directly, no DB import needed)
    python batch_dns_filter.py zone_files/com.txt.gz --output /tmp/com_clean.txt

    # From DB
    python batch_dns_filter.py --db-tld com --output /tmp/com_clean.txt

    # Custom batch size / concurrency
    python batch_dns_filter.py zone_files/com.txt.gz --output /tmp/com_clean.txt \
        --batch-size 5000000 --workers 400 --timeout 2

    # Resume after interruption (skips already-written domains)
    python batch_dns_filter.py zone_files/com.txt.gz --output /tmp/com_clean.txt --resume
"""

import argparse
import concurrent.futures
import gzip
import itertools
import os
import signal
import socket
import sqlite3
import sys
import time
from pathlib import Path

try:
    import tldextract
    _HAS_TLDEXTRACT = True
except ImportError:
    _HAS_TLDEXTRACT = False

DEFAULT_DB   = Path(__file__).parent / "data" / "czds.db"
_stop        = False
_kill_count  = 0


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch DNS-filter a zone file and stream clean domains to output."
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("zone_file", nargs="?", help="Zone file path (.txt or .txt.gz)")
    src.add_argument("--db-tld", metavar="TLD", help="Read from DB instead of zone file")

    p.add_argument("--output",     "-o", required=True, help="Output file (appended per batch)")
    p.add_argument("--db",         default=str(DEFAULT_DB))
    p.add_argument("--batch-size", type=int, default=5_000_000, help="Domains per batch (default: 5M)")
    p.add_argument("--workers",    type=int, default=400,        help="DNS workers (default: 400)")
    p.add_argument("--timeout",    type=float, default=2.0,      help="DNS timeout seconds (default: 2)")
    p.add_argument("--resume",     action="store_true",          help="Skip domains already in output")
    p.add_argument("--strip-subdomains", action="store_true",    help="Keep only apex domains")
    return p.parse_args()


# ── signal handling ────────────────────────────────────────────────────────────

def setup_signals():
    def handler(sig, frame):
        global _stop, _kill_count
        _kill_count += 1
        if _kill_count == 1:
            print("\n\nCtrl+C — finishing current batch then stopping (press again to force quit)...", flush=True)
            _stop = True
        else:
            print("\nForce killed.", flush=True)
            os._exit(130)
    signal.signal(signal.SIGINT, handler)


# ── domain streaming ───────────────────────────────────────────────────────────

def stream_zone_file(path):
    """Yield raw domain names from a zone file (plain or gzipped)."""
    path = Path(path)
    opener = gzip.open if path.suffix in (".gz", ".gzip") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            if not parts:
                continue
            domain = parts[0].strip().lower().rstrip(".")
            if 3 <= len(domain) <= 253:
                yield domain


def stream_db(db_path, tld):
    conn = sqlite3.connect(str(db_path))
    try:
        for (domain,) in conn.execute(
            "SELECT d.domain FROM domains d JOIN tlds t ON d.tld_id = t.id WHERE t.tld = ? ORDER BY d.domain",
            (tld,)
        ):
            yield domain
    finally:
        conn.close()


def to_apex(domain):
    if _HAS_TLDEXTRACT:
        r = tldextract.extract(domain)
        return f"{r.domain}.{r.suffix}" if r.domain and r.suffix else None
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


# ── DNS filtering ──────────────────────────────────────────────────────────────

def check_dns(domain, timeout):
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None, socket.AF_INET)
        return domain
    except Exception:
        return None


def dns_filter_batch(domains, workers, timeout):
    """Sliding-window DNS filter over a list. Yields active domains."""
    pipeline = workers * 4
    it = iter(domains)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for d in itertools.islice(it, pipeline):
            futures[ex.submit(check_dns, d, timeout)] = d
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
                    nd = next(it)
                    futures[ex.submit(check_dns, nd, timeout)] = nd
                except StopIteration:
                    pass


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    setup_signals()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Load already-written domains if resuming
    already_done = set()
    if args.resume and output.exists():
        print(f"Loading already-written domains for resume...", flush=True)
        with open(output) as f:
            already_done = {line.strip() for line in f if line.strip()}
        print(f"  Skipping {len(already_done):,} already done", flush=True)

    # Set up domain source
    if args.db_tld:
        raw_stream = stream_db(Path(args.db), args.db_tld)
        source_label = f"DB:.{args.db_tld}"
    else:
        raw_stream = stream_zone_file(args.zone_file)
        source_label = Path(args.zone_file).name

    # Dedup seen set (across all batches in this run)
    seen = set(already_done)

    print(f"\nSource  : {source_label}")
    print(f"Output  : {output}  ({'append/resume' if args.resume else 'overwrite'})")
    print(f"Batch   : {args.batch_size:,} domains")
    print(f"Workers : {args.workers}  Timeout: {args.timeout}s")
    print(f"Apex    : {'yes (tldextract)' if args.strip_subdomains and _HAS_TLDEXTRACT else 'yes (parts)' if args.strip_subdomains else 'no'}")
    print()

    file_mode = "a" if args.resume else "w"
    session_start = time.time()
    total_written = len(already_done)
    batch_num = 0

    with open(output, file_mode, encoding="utf-8") as out:

        while not _stop:
            # ── collect next batch ──────────────────────────────────────────
            batch_num += 1
            batch = []
            batch_seen = set()

            print(f"{'─'*60}")
            print(f"Batch {batch_num} — reading up to {args.batch_size:,} domains...", flush=True)
            read_start = time.time()

            for raw in raw_stream:
                if _stop:
                    break

                domain = to_apex(raw) if args.strip_subdomains else raw
                if not domain:
                    continue
                if domain in seen:
                    continue

                seen.add(domain)
                batch.append(domain)

                if len(batch) >= args.batch_size:
                    break

            if not batch:
                print(f"No more domains. Done.")
                break

            print(f"  Read   : {len(batch):,} domains in {time.time()-read_start:.1f}s", flush=True)

            # ── DNS filter ─────────────────────────────────────────────────
            print(f"  Filtering DNS ({args.workers} workers, {args.timeout}s timeout)...", flush=True)
            dns_start = time.time()
            active = 0
            checked = 0
            batch_total = len(batch)

            for domain in dns_filter_batch(batch, args.workers, args.timeout):
                out.write(domain + "\n")
                active += 1
                total_written += 1
                checked += 1

                if checked % 50_000 == 0:
                    elapsed = time.time() - dns_start
                    rate = checked / elapsed if elapsed > 0 else 0
                    remaining = (batch_total - checked) / rate if rate > 0 else 0
                    print(
                        f"    [{checked:>8,} / {batch_total:,}]  "
                        f"active: {active:,}  "
                        f"rate: {rate:,.0f}/s  "
                        f"eta: {remaining/60:.1f}m",
                        flush=True
                    )

            # flush after every batch so output is immediately usable
            out.flush()

            dns_elapsed = time.time() - dns_start
            pct = active / batch_total * 100 if batch_total else 0
            session_elapsed = time.time() - session_start

            print(f"\n  ✓ Batch {batch_num} done in {dns_elapsed:.0f}s")
            print(f"    Active  : {active:,} / {batch_total:,}  ({pct:.1f}%)")
            print(f"    Running total in {output.name}: {total_written:,}")
            print(f"    Session elapsed: {session_elapsed/60:.1f}m")
            print()

            if _stop:
                break

    print(f"\n{'='*60}")
    print(f"Finished. Total clean domains in {output}: {total_written:,}")
    print(f"Feed this file to your residential proxy:")
    print(f"  {output.resolve()}")


if __name__ == "__main__":
    main()
