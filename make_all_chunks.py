#!/usr/bin/env python3
"""Split a CZDS zone file into fixed-size, per-first-letter domain chunks.

Single streaming pass, O(1) memory: the zone file is sorted by owner name, so
dropping consecutive duplicates is enough (no per-letter `seen` sets, which
would need many GB for the full .com zone). The script warns if it ever sees
out-of-order names, in which case pipe the zone through `sort -u` first.

Output: <output-dir>/com-<letter>-<NN>.txt, 500,000 domains per file (the last
file of each letter may be shorter). Letters a-z get their own series; names
starting with a digit go to the `0` series. Chunk numbers start at 01.

Only second-level names are kept (example.com, never ns1.example.com).

Usage:
    python make_all_chunks.py --zone-file zone_files/com.txt.gz --output-dir com_splits
    python make_all_chunks.py --letters a b c          # subset
    python make_all_chunks.py --dry-run                # counts per letter only
"""

import argparse
import gzip
import string
import sys
import time
from pathlib import Path

BUCKETS = list(string.ascii_lowercase) + ["0"]  # "0" = names starting with a digit


def bucket_for(label: str):
    first = label[0]
    if first in string.ascii_lowercase:
        return first
    if first in string.digits:
        return "0"
    return None  # leading hyphen / other: not a valid registrable label


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def split_zone(lines, tld, letters, chunk_size, out_dir, dry_run=False):
    """Stream `lines` (zone-file format or one-domain-per-line) into chunk files.

    Returns {bucket: total_domains}. `out_dir` may be None when dry_run.
    """
    suffix = "." + tld
    counts = {b: 0 for b in letters}
    chunk_no = {b: 1 for b in letters}
    in_chunk = {b: 0 for b in letters}
    handles = {}
    prev = None
    out_of_order = 0

    def handle(b):
        if dry_run:
            return None
        if b not in handles:
            handles[b] = open(out_dir / f"{tld}-{b}-{chunk_no[b]:02d}.txt", "w")
        return handles[b]

    for line in lines:
        line = line.strip()
        if not line or line[0] in ";#":
            continue
        raw = line.split("\t", 1)[0].split(None, 1)[0].lower().rstrip(".")
        if not raw.endswith(suffix):
            continue
        label = raw[: -len(suffix)]
        if not label or "." in label:
            continue
        if prev is not None:
            if raw == prev:
                continue  # zone files list each delegation once per NS record
            if raw < prev:
                out_of_order += 1
        prev = raw

        b = bucket_for(label)
        if b is None or b not in counts:
            continue

        fh = handle(b)
        if fh is not None:
            fh.write(raw + "\n")
        counts[b] += 1
        in_chunk[b] += 1
        if in_chunk[b] >= chunk_size:
            if fh is not None:
                fh.close()
                del handles[b]
            chunk_no[b] += 1
            in_chunk[b] = 0

    for fh in handles.values():
        fh.close()
    # A rollover opens the next file lazily, so no empty trailing files exist.
    if out_of_order:
        print(
            f"WARNING: {out_of_order:,} out-of-order names; duplicates may remain. "
            "Re-run on `sort -u` output.",
            file=sys.stderr,
        )
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--zone-file", default="zone_files/com.txt.gz")
    p.add_argument("--tld", default="com")
    p.add_argument("--output-dir", default="com_splits")
    p.add_argument("--chunk-size", type=int, default=500_000)
    p.add_argument("--letters", nargs="*", default=BUCKETS)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    zone = Path(args.zone_file)
    out_dir = Path(args.output_dir)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    with open_text(zone) as f:
        counts = split_zone(
            f, args.tld, args.letters, args.chunk_size, out_dir, args.dry_run
        )

    total = sum(counts.values())
    print(f"{'bucket':<7}{'domains':>14}{'chunks':>8}")
    for b in args.letters:
        n = counts[b]
        print(f"{b:<7}{n:>14,}{-(-n // args.chunk_size):>8}")
    print(f"{'TOTAL':<7}{total:>14,}{-(-total // args.chunk_size):>8}  "
          f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
