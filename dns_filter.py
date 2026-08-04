#!/usr/bin/env python3
"""Filter a domain list to only those with active DNS resolution.

Usage:
    python dns_filter.py input.txt output.txt
    python dns_filter.py input.txt output.txt --workers 300 --timeout 3
    python dns_filter.py input.txt output.txt --resume
    cat domains.txt | python dns_filter.py - output.txt
"""

import argparse
import itertools
import os
import signal
import socket
import sys
import concurrent.futures
import time
from pathlib import Path

_stop = False
_kill_count = 0


def parse_args():
    p = argparse.ArgumentParser(
        description="Filter domains to those that resolve via DNS."
    )
    p.add_argument("input", help="Input file (one domain per line) or - for stdin")
    p.add_argument("output", help="Output file for active domains")
    p.add_argument("--workers", type=int, default=300, help="Concurrent DNS workers (default: 300)")
    p.add_argument("--timeout", type=float, default=3.0, help="DNS timeout per query in seconds (default: 3)")
    p.add_argument("--resume", action="store_true", help="Skip domains already in output file")
    p.add_argument("--batch", type=int, default=10000, help="Progress report interval (default: 10000)")
    return p.parse_args()


def load_domains(path):
    if path == "-":
        return [line.strip() for line in sys.stdin if line.strip()]
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_already_done(path):
    p = Path(path)
    if not p.exists():
        return set()
    with open(p, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def check_domain(domain, timeout):
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None, socket.AF_INET)
        return domain
    except Exception:
        return None


def main():
    global _stop, _kill_count

    args = parse_args()

    def handle_sigint(sig, frame):
        global _stop, _kill_count
        _kill_count += 1
        if _kill_count == 1:
            print("\nCtrl+C — finishing in-flight queries (press again to force quit)...", flush=True)
            _stop = True
        else:
            print("\nForce killed.", flush=True)
            os._exit(130)

    signal.signal(signal.SIGINT, handle_sigint)

    print(f"Loading domains from {args.input}...")
    domains = load_domains(args.input)
    total = len(domains)
    print(f"  Loaded {total:,} domains")

    if args.resume:
        done = load_already_done(args.output)
        before = total
        domains = [d for d in domains if d not in done]
        total = len(domains)
        print(f"  Resuming: skipping {before - total:,} already done, {total:,} remaining")

    if not domains:
        print("Nothing to check.")
        return

    # Sliding window: keep exactly `pipeline` futures in flight at all times.
    # When one finishes, immediately submit the next — workers are never idle.
    pipeline = args.workers * 4
    domain_iter = iter(domains)

    checked = 0
    active = 0
    start = time.time()
    last_flush = 0

    def progress():
        elapsed = time.time() - start
        rate = checked / elapsed if elapsed > 0 else 0
        remaining = (total - checked) / rate if rate > 0 else 0
        print(
            f"  [{checked:>10,} / {total:,}]  "
            f"active: {active:,}  "
            f"rate: {rate:,.0f}/s  "
            f"eta: {remaining/60:.1f}m"
        )

    mode = "a" if args.resume else "w"
    print(f"\nChecking DNS with {args.workers} workers, {args.timeout}s timeout...\n")

    with open(args.output, mode, encoding="utf-8") as out:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            # Seed the pipeline
            futures = {}
            for domain in itertools.islice(domain_iter, pipeline):
                f = ex.submit(check_domain, domain, args.timeout)
                futures[f] = domain

            while futures and not _stop:
                # Block until at least one future completes
                done, _ = concurrent.futures.wait(
                    futures,
                    return_when=concurrent.futures.FIRST_COMPLETED
                )

                for f in done:
                    futures.pop(f)
                    result = f.result()
                    checked += 1

                    if result:
                        out.write(result + "\n")
                        active += 1

                    # Immediately refill pipeline
                    try:
                        new_domain = next(domain_iter)
                        new_f = ex.submit(check_domain, new_domain, args.timeout)
                        futures[new_f] = new_domain
                    except StopIteration:
                        pass

                    if checked % args.batch == 0:
                        out.flush()
                        progress()

    elapsed = time.time() - start
    pct = f"{active/checked*100:.1f}%" if checked else "n/a"
    print(f"\n{'Stopped early' if _stop else 'Done'} in {elapsed:.1f}s")
    print(f"  Checked : {checked:,}")
    print(f"  Active  : {active:,}  ({pct})")
    print(f"  Inactive: {checked - active:,}")
    print(f"  Output  : {args.output}")


if __name__ == "__main__":
    main()
