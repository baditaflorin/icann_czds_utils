import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_all_chunks as mac  # noqa: E402

ZONE = [
    "com.\t900\tin\tsoa\ta.gtld-servers.net. nstld.verisign-grs.com. 1 1800 900 604800 900",
    "0-1.com.\t172800\tin\tns\tns1.x.com.",
    "alpha.com.\t172800\tin\tns\tns1.a.com.",
    "alpha.com.\t172800\tin\tns\tns2.a.com.",      # duplicate delegation
    "ns1.alpha.com.\t172800\tin\ta\t1.2.3.4",      # subdomain: dropped
    "Apex.com.\t172800\tin\tns\tns1.a.com.",       # case folded
    "apple.com.\t172800\tin\tns\tns1.a.com.",
    "bravo.net.\t172800\tin\tns\tns1.b.com.",      # other TLD: dropped
    "bravo.com.\t172800\tin\tns\tns1.b.com.",
    "-bad.com.\t172800\tin\tns\tns1.b.com.",       # leading hyphen: dropped
]


def run(tmp_path, chunk_size, letters=None):
    zone = tmp_path / "com.txt.gz"
    with gzip.open(zone, "wt") as f:
        f.write("\n".join(ZONE) + "\n")
    out = tmp_path / "out"
    out.mkdir()
    with mac.open_text(zone) as f:
        counts = mac.split_zone(f, "com", letters or mac.BUCKETS, chunk_size, out)
    return counts, out


def read(path):
    return path.read_text().split()


def test_buckets_dedup_and_filters(tmp_path):
    counts, out = run(tmp_path, chunk_size=100)
    assert counts["0"] == 1
    assert counts["a"] == 3          # alpha, apex, apple (deduped, lowercased)
    assert counts["b"] == 1          # bravo.com only
    assert sum(counts.values()) == 5
    assert read(out / "com-a-01.txt") == ["alpha.com", "apex.com", "apple.com"]
    assert read(out / "com-0-01.txt") == ["0-1.com"]
    assert read(out / "com-b-01.txt") == ["bravo.com"]


def test_rollover_numbers_chunks_and_leaves_no_empty_file(tmp_path):
    counts, out = run(tmp_path, chunk_size=2, letters=["a"])
    assert counts["a"] == 3
    assert read(out / "com-a-01.txt") == ["alpha.com", "apex.com"]
    assert read(out / "com-a-02.txt") == ["apple.com"]
    assert not (out / "com-a-03.txt").exists()


def test_exact_multiple_of_chunk_size_creates_no_trailing_file(tmp_path):
    counts, out = run(tmp_path, chunk_size=3, letters=["a"])
    assert read(out / "com-a-01.txt") == ["alpha.com", "apex.com", "apple.com"]
    assert not (out / "com-a-02.txt").exists()


def test_dry_run_writes_nothing(tmp_path):
    zone = tmp_path / "z.txt"
    zone.write_text("\n".join(ZONE) + "\n")
    out = tmp_path / "out"
    with mac.open_text(zone) as f:
        counts = mac.split_zone(f, "com", mac.BUCKETS, 100, out, dry_run=True)
    assert counts["a"] == 3 and not out.exists()
