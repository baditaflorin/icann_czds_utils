#!/usr/bin/env python3
"""Strip subdomains, keeping only the registrable apex domain.

Uses tldextract (public suffix list) if installed, otherwise falls back
to a configurable parts count.

Usage:
    python strip_subdomains.py input.txt output.txt
    python strip_subdomains.py input.txt output.txt --parts 2
    cat domains.txt | python strip_subdomains.py - output.txt
    python strip_subdomains.py input.txt -          # stdout
"""

import argparse
import sys

try:
    import tldextract
    _HAS_TLDEXTRACT = True
except ImportError:
    _HAS_TLDEXTRACT = False


def parse_args():
    p = argparse.ArgumentParser(
        description="Strip subdomains, output unique apex domains."
    )
    p.add_argument("input", help="Input file (one domain per line) or - for stdin")
    p.add_argument("output", help="Output file or - for stdout")
    p.add_argument(
        "--parts", type=int, default=2,
        help="Number of domain parts to keep when tldextract is unavailable (default: 2 → example.org)"
    )
    p.add_argument(
        "--no-tldextract", action="store_true",
        help="Force simple parts-based extraction even if tldextract is installed"
    )
    p.add_argument(
        "--keep-empty", action="store_true",
        help="Keep lines where extraction produced an empty result"
    )
    return p.parse_args()


def apex_tldextract(domain):
    r = tldextract.extract(domain)
    if not r.domain or not r.suffix:
        return None
    return f"{r.domain}.{r.suffix}"


def apex_parts(domain, n):
    parts = domain.split(".")
    if len(parts) <= n:
        return domain  # already at or below the target depth
    return ".".join(parts[-n:])


def stream_input(path):
    if path == "-":
        for line in sys.stdin:
            yield line.strip()
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                yield line.strip()


def open_output(path):
    if path == "-":
        return sys.stdout
    return open(path, "w", encoding="utf-8")


def main():
    args = parse_args()

    use_tldextract = _HAS_TLDEXTRACT and not args.no_tldextract
    if use_tldextract:
        extract_fn = apex_tldextract
        print(f"Using tldextract (public suffix list)", file=sys.stderr)
    else:
        extract_fn = lambda d: apex_parts(d, args.parts)
        if not _HAS_TLDEXTRACT and not args.no_tldextract:
            print(
                f"tldextract not found — using last {args.parts} parts. "
                f"Install with: pip install tldextract",
                file=sys.stderr
            )

    seen = set()
    total = kept = skipped = 0

    out = open_output(args.output)
    try:
        for raw in stream_input(args.input):
            if not raw:
                continue
            total += 1

            apex = extract_fn(raw)

            if not apex and not args.keep_empty:
                skipped += 1
                continue

            if apex not in seen:
                seen.add(apex)
                out.write(apex + "\n")
                kept += 1

    finally:
        if out is not sys.stdout:
            out.close()

    print(
        f"Done: {total:,} input → {kept:,} unique apex domains "
        f"({skipped:,} skipped empty)",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()
