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


# ---- single series + batch mode -------------------------------------------

def _zone(tld, names):
    return "\n".join(
        [f"{tld}.\t900\tin\tsoa\tx. y. 1 1 1 1 1"]
        + [f"{n}.{tld}.\t172800\tin\tns\tns1.x.net." for n in names]
    ) + "\n"


def test_single_series_names_and_rollover(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    lines = _zone("org", ["alpha", "beta", "beta", "ns.sub", "-bad", "9lives", "zed"]).splitlines()
    counts = mac.split_zone(lines, "org", [], 2, out, single_series=True)
    assert counts == {mac.SINGLE: 4}                     # alpha, beta, 9lives, zed
    assert read(out / "org-01.txt") == ["alpha.org", "beta.org"]
    assert read(out / "org-02.txt") == ["9lives.org", "zed.org"]
    assert not (out / "org-03.txt").exists()


def test_batch_slices_every_tld_and_survives_bad_files(tmp_path):
    zdir = tmp_path / "zones"
    zdir.mkdir()
    with gzip.open(zdir / "aaa.txt.gz", "wt") as f:
        f.write(_zone("aaa", ["one", "two", "three"]))
    (zdir / "plain.txt").write_text(_zone("plain", ["x1"]))
    with gzip.open(zdir / "empty.txt.gz", "wt") as f:
        f.write(_zone("empty", []))
    (zdir / "broken.txt.gz").write_bytes(b"this is not gzip data")
    (zdir / "com.txt.gz").write_bytes(b"skipped, never opened")
    (zdir / "notes.md").write_text("ignored")
    out = tmp_path / "out"
    out.mkdir()

    rows, errors = mac.run_batch(zdir, out, 2, skip=["com"], only=[], dry_run=False)

    assert {r[0]: (r[1], r[2]) for r in rows} == {
        "aaa": (3, 2), "empty": (0, 0), "plain": (1, 1)}
    assert [e[0] for e in errors] == ["broken"]
    assert read(out / "aaa-01.txt") == ["one.aaa", "two.aaa"]
    assert read(out / "aaa-02.txt") == ["three.aaa"]
    assert read(out / "plain-01.txt") == ["x1.plain"]
    assert not list(out.glob("empty-*")) and not list(out.glob("com-*"))


def test_only_filter_and_tld_from_path():
    assert mac.tld_from_path(Path("xn--p1ai.txt.gz")) == "xn--p1ai"
    assert mac.tld_from_path(Path("tech.txt")) == "tech"


def test_total_chunks_is_sum_of_per_bucket_ceilings():
    # 600k in one bucket (2 chunks) + 100k in another (1 chunk) = 3, not ceil(700k/500k)=2
    assert mac.n_chunks(600_000, 500_000) + mac.n_chunks(100_000, 500_000) == 3
    assert mac.n_chunks(0, 500_000) == 0


def test_duplicate_tld_prefers_gz_and_counts_once(tmp_path, capsys):
    zdir = tmp_path / "zones"
    zdir.mkdir()
    with gzip.open(zdir / "tech.txt.gz", "wt") as f:
        f.write(_zone("tech", ["a", "b"]))
    (zdir / "tech.txt").write_text(_zone("tech", ["a", "b"]))
    out = tmp_path / "out"
    out.mkdir()
    rows, errors = mac.run_batch(zdir, out, 10, skip=[], only=[], dry_run=False)
    assert rows == [("tech", 2, 1)] and not errors
    assert "using tech.txt.gz" in capsys.readouterr().err


def test_failed_tld_leaves_no_partial_output(tmp_path):
    import io
    zdir = tmp_path / "zones"
    zdir.mkdir()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as g:
        g.write(_zone("trunc", [f"name{i}" for i in range(500)]).encode())
    (zdir / "trunc.txt.gz").write_bytes(buf.getvalue()[:-30])      # chop the trailer
    with gzip.open(zdir / "ok.txt.gz", "wt") as f:
        f.write(_zone("ok", ["fine"]))
    # a different TLD whose name shares the prefix must survive the cleanup
    out = tmp_path / "out"
    out.mkdir()
    (out / "trunc-extra-01.txt").write_text("keep.trunc-extra\n")

    rows, errors = mac.run_batch(zdir, out, 100, skip=[], only=[], dry_run=False)

    assert [r[0] for r in rows] == ["ok"]
    assert [e[0] for e in errors] == ["trunc"] and "removed" in errors[0][1]
    assert not (out / "trunc-01.txt").exists()
    assert (out / "trunc-extra-01.txt").exists() and (out / "ok-01.txt").exists()


def test_out_of_order_warning_names_the_tld(capsys):
    mac.split_zone(["b.net.\t1\tin\tns\tx.", "a.net.\t1\tin\tns\tx."], "net",
                   [], 10, None, dry_run=True, single_series=True)
    assert "WARNING: net: 1 out-of-order" in capsys.readouterr().err
