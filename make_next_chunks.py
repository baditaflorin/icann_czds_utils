#!/usr/bin/env python3
"""Extract the next N-line chunk for each letter from com.txt.gz, continuing
from the last domain already deployed.

Single pass over the zone file — handles all letters simultaneously.

Usage:
    python make_next_chunks.py              # produces a-13 b-13 c-13 d-13
    python make_next_chunks.py --chunk-size 500000
    python make_next_chunks.py --output-dir /tmp/splits
    python make_next_chunks.py --dry-run    # count only
"""

import argparse
import gzip
import os
import time
from pathlib import Path

# Auto-load .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _, _v = _l.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

ZONE_FILE   = Path(__file__).parent / "zone_files" / "com.txt.gz"
DEFAULT_OUT = Path(__file__).parent / "com_splits"
CHUNK_SIZE  = 500_000

# Last domain in the current max chunk on the server.
# Update these after each round of deployments.
BOUNDARIES = {
    # Update after each round. d and e are complete.
    "a": ("applecarports.com",   14),
    "b": ("brentwoodrc.com",     14),
    "c": ("coinsins.com",        14),
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--zone-file",   default=str(ZONE_FILE))
    p.add_argument("--output-dir",  default=str(DEFAULT_OUT))
    p.add_argument("--chunk-size",  type=int, default=CHUNK_SIZE)
    p.add_argument("--dry-run",     action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    zone  = Path(args.zone_file)
    out   = Path(args.output_dir)
    N     = args.chunk_size

    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)

    # State per letter: (boundary_domain, chunk_number, past_boundary, collected, file_handle)
    state = {}
    for letter, (boundary, chunk_num) in BOUNDARIES.items():
        fname = out / f"com-{letter}-{chunk_num:02d}.txt"
        state[letter] = {
            "boundary":     boundary,
            "chunk_num":    chunk_num,
            "past":         False,         # have we passed the boundary?
            "collected":    0,
            "done":         False,
            "fh":           open(fname, "w") if not args.dry_run else None,
            "fname":        fname,
        }

    seen = {l: set() for l in state}     # per-letter dedup
    total_lines = 0
    t0 = time.time()

    print(f"Zone : {zone}  ({zone.stat().st_size/1e9:.1f} GB)")
    print(f"Mode : {'DRY RUN' if args.dry_run else 'WRITING'}")
    for l, (b, n) in BOUNDARIES.items():
        print(f"  {l}: resume after '{b}' → chunk {n:02d}  ({state[l]['fname'].name})")
    print()

    with gzip.open(zone, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            # Stop early if all letters are done
            if all(s["done"] for s in state.values()):
                break

            line = line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue

            parts = line.split("\t") if "\t" in line else line.split()
            if not parts:
                continue

            raw = parts[0].strip().lower().rstrip(".")
            if not raw.endswith(".com"):
                continue
            domain = raw  # keep full domain e.g. example.com

            label = domain[:-4]           # strip .com for letter check
            if not label or "." in label:
                continue

            first = label[0]
            if first not in state:
                continue

            s = state[first]
            if s["done"]:
                continue

            # Dedup
            if domain in seen[first]:
                continue
            seen[first].add(domain)

            total_lines += 1

            # Check boundary
            if not s["past"]:
                if domain == s["boundary"]:
                    s["past"] = True
                continue  # still before/at boundary

            # Past boundary — collect
            s["collected"] += 1
            if not args.dry_run:
                s["fh"].write(domain + "\n")

            if s["collected"] >= N:
                s["done"] = True
                if s["fh"]:
                    s["fh"].close()
                    s["fh"] = None
                print(f"  [{first}] chunk {s['chunk_num']:02d} complete — {s['collected']:,} domains → {s['fname'].name}")

    # Flush any incomplete chunks (letter with fewer than N remaining domains)
    for letter, s in state.items():
        if s["fh"]:
            s["fh"].close()
        if not s["done"] and s["collected"] > 0:
            print(f"  [{letter}] chunk {s['chunk_num']:02d} partial — {s['collected']:,} domains (end of letter) → {s['fname'].name}")
        elif not s["past"] and s["collected"] == 0:
            print(f"  [{letter}] WARNING: boundary domain '{s['boundary']}' not found in zone file")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s")
    if not args.dry_run:
        print("\nDeploy commands:")
        for letter, s in state.items():
            if s["collected"] > 0:
                n = s["chunk_num"]
                print(f"  python deploy_tld.py --from-file {s['fname']} --name com-{letter}-{n:02d} --skip-dns-filter")


if __name__ == "__main__":
    main()
