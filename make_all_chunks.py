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

Two layouts:
  * per-letter series (default, for huge TLDs such as com):
        <tld>-<letter>-<NN>.txt
  * single series (--single-series, for everything else): <tld>-<NN>.txt

Batch mode (--zone-dir) slices every zone file in a folder as a single series,
one TLD at a time, and keeps going if one file is unreadable.

Usage:
    python make_all_chunks.py --zone-file zone_files/com.txt.gz --output-dir com_splits
    python make_all_chunks.py --letters a b c          # subset
    python make_all_chunks.py --dry-run                # counts per letter only
    python make_all_chunks.py --zone-dir zone_files --skip com --output-dir other_splits
"""

import argparse
import gzip
import string
import sys
import time
from pathlib import Path

BUCKETS = list(string.ascii_lowercase) + ["0"]  # "0" = names starting with a digit


SINGLE = "_"  # the one bucket used in --single-series mode


def bucket_for(label: str, single: bool = False):
    first = label[0]
    if single:
        return None if first == "-" else SINGLE
    if first in string.ascii_lowercase:
        return first
    if first in string.digits:
        return "0"
    return None  # leading hyphen / other: not a valid registrable label


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")


def split_zone(lines, tld, letters, chunk_size, out_dir, dry_run=False, single_series=False):
    """Stream `lines` (zone-file format or one-domain-per-line) into chunk files.

    Returns {bucket: total_domains}. `out_dir` may be None when dry_run.
    With single_series=True every name goes to one series (<tld>-<NN>.txt).
    """
    if single_series:
        letters = [SINGLE]
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
            stem = f"{tld}-{chunk_no[b]:02d}" if single_series else f"{tld}-{b}-{chunk_no[b]:02d}"
            handles[b] = open(out_dir / f"{stem}.txt", "w")
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

        b = bucket_for(label, single_series)
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


def n_chunks(n: int, chunk_size: int) -> int:
    return -(-n // chunk_size)


def tld_from_path(path: Path) -> str:
    name = path.name
    for ext in (".txt.gz", ".txt"):
        if name.endswith(ext):
            return name[: -len(ext)].lower()
    return path.stem.lower()


def zone_files_in(zone_dir: Path, skip, only):
    """(tld, path) for every zone file; if a TLD has both .txt.gz and .txt,
    the .gz wins and the plain copy is reported on stderr and ignored."""
    chosen = {}
    for f in sorted(zone_dir.iterdir()):
        if not f.is_file() or not (f.name.endswith(".txt.gz") or f.name.endswith(".txt")):
            continue
        tld = tld_from_path(f)
        if tld in skip or (only and tld not in only):
            continue
        if tld in chosen:
            gz, plain = (f, chosen[tld]) if f.name.endswith(".gz") else (chosen[tld], f)
            print(f"WARNING: {tld} has both {gz.name} and {plain.name}; using {gz.name}",
                  file=sys.stderr)
            chosen[tld] = gz
        else:
            chosen[tld] = f
    return sorted(chosen.items())


def run_batch(zone_dir, out_dir, chunk_size, skip, only, dry_run):
    """Slice every zone file in zone_dir as a single series. Returns (rows, errors)."""
    rows, errors = [], []
    for tld, f in zone_files_in(zone_dir, set(skip), set(only or [])):
        try:
            with open_text(f) as fh:
                counts = split_zone(fh, tld, [SINGLE], chunk_size, out_dir, dry_run, True)
        except (OSError, EOFError, ValueError) as e:  # BadGzipFile is an OSError
            errors.append((tld, f"{type(e).__name__}: {e}"))
            continue
        n = counts[SINGLE]
        rows.append((tld, n, n_chunks(n, chunk_size)))
    return rows, errors


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--zone-file", default="zone_files/com.txt.gz")
    p.add_argument("--zone-dir", help="slice every zone file in this folder as a single series")
    p.add_argument("--skip", nargs="*", default=[], help="TLDs to skip in --zone-dir mode")
    p.add_argument("--only", nargs="*", default=[], help="only these TLDs in --zone-dir mode")
    p.add_argument("--single-series", action="store_true",
                   help="one <tld>-<NN>.txt series instead of per-letter (implied by --zone-dir)")
    p.add_argument("--tld", default="com")
    p.add_argument("--output-dir", default="com_splits")
    p.add_argument("--chunk-size", type=int, default=500_000)
    p.add_argument("--letters", nargs="*", default=BUCKETS)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if args.zone_dir:
        rows, errors = run_batch(Path(args.zone_dir), out_dir, args.chunk_size,
                                 args.skip, args.only, args.dry_run)
        print(f"{'tld':<24}{'domains':>14}{'chunks':>8}")
        for tld, n, c in rows:
            print(f"{tld:<24}{n:>14,}{c:>8}")
        total, chunks = sum(r[1] for r in rows), sum(r[2] for r in rows)
        empty = sum(1 for r in rows if r[1] == 0)
        print(f"{'TOTAL':<24}{total:>14,}{chunks:>8}  "
              f"({len(rows)} TLDs, {empty} with no second-level names, "
              f"{len(errors)} failed, {time.time() - t0:.0f}s)")
        for tld, err in errors:
            print(f"FAILED {tld}: {err}", file=sys.stderr)
        sys.exit(1 if errors else 0)

    zone = Path(args.zone_file)
    with open_text(zone) as f:
        counts = split_zone(f, args.tld, args.letters, args.chunk_size, out_dir,
                            args.dry_run, args.single_series)

    total = sum(counts.values())
    print(f"{'bucket':<7}{'domains':>14}{'chunks':>8}")
    for b, n in counts.items():
        print(f"{b:<7}{n:>14,}{n_chunks(n, args.chunk_size):>8}")
    chunks = sum(n_chunks(n, args.chunk_size) for n in counts.values())
    print(f"{'TOTAL':<7}{total:>14,}{chunks:>8}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
