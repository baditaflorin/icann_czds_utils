#!/usr/bin/env python3
"""End-to-end pipeline: DB export → DNS filter → deploy to domainscope server.

For each TLD (or merged batch):
  1. Export apex domains from the local CZDS SQLite database
  2. DNS-filter to active-only domains
  3. Create /opt/go-domainscope-{name}-icann-domains/ on the server
  4. Upload Dockerfile, docker-compose.yml, main.go, domains.txt
  5. Build and start the Docker container

Usage:
    python deploy_tld.py net
    python deploy_tld.py net info xyz app dev          # one container per TLD
    python deploy_tld.py net info xyz --merge          # one combined container
    python deploy_tld.py net --no-dns-filter           # skip DNS check
    python deploy_tld.py net --dry-run                 # local only, no upload
    python deploy_tld.py net --workers 400 --timeout 2
"""

import argparse
import itertools
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import concurrent.futures
import time
import sqlite3
from pathlib import Path

# Auto-load .env from the project root (safe: .env is gitignored)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    import tldextract
    _HAS_TLDEXTRACT = True
except ImportError:
    _HAS_TLDEXTRACT = False

# ── server config (set via environment variables) ────────────────────────────
JUMP_HOST   = os.environ.get("DEPLOY_JUMP_HOST", "")
TARGET_USER = os.environ.get("DEPLOY_USER", "ubuntu_vm")
TARGET_HOST = os.environ.get("DEPLOY_HOST", "")
REMOTE_BASE = os.environ.get("DEPLOY_REMOTE_BASE", "/opt")

DEFAULT_DB  = Path(__file__).parent / "data" / "czds.db"
CONCURRENCY = 13
DELAY_MS    = 2000
MAX_RETRIES = 0

# ── Dockerfile / main.go templates ───────────────────────────────────────────
DOCKERFILE = """\
FROM golang:1.23-alpine

RUN apk add --no-cache ca-certificates tzdata && update-ca-certificates

WORKDIR /app
COPY main.go .

RUN go build -o processor main.go

CMD ["./processor"]
"""

MAIN_GO = """\
package main

import (
\t"bufio"
\t"bytes"
\t"encoding/json"
\t"fmt"
\t"io"
\t"log"
\t"net/http"
\t"os"
\t"strconv"
\t"sync"
\t"time"
)

type CategorizeRequest struct {
\tURL string `json:"url"`
}

type CategorizeResponse struct {
\tURL      string `json:"url"`
\tCategory string `json:"category"`
}

type DomainJob struct {
\tID     int
\tDomain string
}

func main() {
\tstartID, err := strconv.Atoi(os.Getenv("START_ID"))
\tif err != nil {
\t\tlog.Fatalf("Invalid START_ID: %v", err)
\t}
\tendID, err := strconv.Atoi(os.Getenv("END_ID"))
\tif err != nil {
\t\tlog.Fatalf("Invalid END_ID: %v", err)
\t}
\tconcurrency := 1
\tif v := os.Getenv("CONCURRENCY"); v != "" {
\t\tconcurrency, err = strconv.Atoi(v)
\t\tif err != nil {
\t\t\tlog.Fatalf("Invalid CONCURRENCY: %v", err)
\t\t}
\t}
\tdelayMs := 500
\tif v := os.Getenv("DELAY_MS"); v != "" {
\t\tdelayMs, err = strconv.Atoi(v)
\t\tif err != nil {
\t\t\tlog.Fatalf("Invalid DELAY_MS: %v", err)
\t\t}
\t}
\tmaxRetries := 0
\tif v := os.Getenv("MAX_RETRIES"); v != "" {
\t\tmaxRetries, err = strconv.Atoi(v)
\t\tif err != nil {
\t\t\tlog.Fatalf("Invalid MAX_RETRIES: %v", err)
\t\t}
\t}
\tdomainFile := os.Getenv("DOMAIN_FILE")
\tif domainFile == "" {
\t\tdomainFile = "domains.txt"
\t}
\tif startID < 1 || endID < startID {
\t\tlog.Fatalf("Invalid range: START_ID=%d, END_ID=%d", startID, endID)
\t}
\tlog.Printf("Starting: START_ID=%d END_ID=%d CONCURRENCY=%d DELAY_MS=%d MAX_RETRIES=%d FILE=%s",
\t\tstartID, endID, concurrency, delayMs, maxRetries, domainFile)

\tf, err := os.Open(domainFile)
\tif err != nil {
\t\tlog.Fatalf("Failed to open domain file: %v", err)
\t}
\tdefer f.Close()

\tsemaphore := make(chan struct{}, concurrency)
\tjobs := make(chan DomainJob, concurrency*2)
\tvar wg sync.WaitGroup
\tclient := &http.Client{Timeout: 30 * time.Second}
\trateLimiter := time.NewTicker(time.Duration(delayMs) * time.Millisecond)
\tdefer rateLimiter.Stop()

\tfor i := 0; i < concurrency; i++ {
\t\twg.Add(1)
\t\tgo worker(client, jobs, semaphore, rateLimiter, maxRetries, &wg)
\t}

\tscanner := bufio.NewScanner(f)
\tcurrentID := 0
\tjobCount := 0
\tfor scanner.Scan() {
\t\tcurrentID++
\t\tif currentID < startID {
\t\t\tcontinue
\t\t}
\t\tif currentID > endID {
\t\t\tbreak
\t\t}
\t\tdomain := scanner.Text()
\t\tif domain == "" {
\t\t\tcontinue
\t\t}
\t\tjobs <- DomainJob{ID: currentID, Domain: domain}
\t\tjobCount++
\t}
\tif err := scanner.Err(); err != nil {
\t\tlog.Printf("Error reading domain file: %v", err)
\t}
\tclose(jobs)
\twg.Wait()
\tlog.Printf("Completed %d domains (lines %d to %d)", jobCount, startID, endID)
}

func worker(client *http.Client, jobs <-chan DomainJob, semaphore chan struct{}, rateLimiter *time.Ticker, maxRetries int, wg *sync.WaitGroup) {
\tdefer wg.Done()
\tfor job := range jobs {
\t\tsemaphore <- struct{}{}
\t\t<-rateLimiter.C
\t\tlog.Printf("Processing ID %d: %s", job.ID, job.Domain)
\t\tvar lastErr error
\t\tfor attempt := 0; attempt <= maxRetries; attempt++ {
\t\t\tif attempt > 0 {
\t\t\t\tbackoff := time.Duration(attempt) * 2 * time.Second
\t\t\t\tlog.Printf("Retry %d/%d for %s after %v", attempt, maxRetries, job.Domain, backoff)
\t\t\t\ttime.Sleep(backoff)
\t\t\t}
\t\t\terr := categorizeDomain(client, job.Domain)
\t\t\tif err == nil {
\t\t\t\tbreak
\t\t\t}
\t\t\tlastErr = err
\t\t}
\t\tif lastErr != nil {
\t\t\tlog.Printf("Failed after %d attempts for %s (ID %d): %v", maxRetries+1, job.Domain, job.ID, lastErr)
\t\t}
\t\t<-semaphore
\t}
}

func categorizeDomain(client *http.Client, domain string) error {
\tjsonData, err := json.Marshal(CategorizeRequest{URL: domain})
\tif err != nil {
\t\treturn fmt.Errorf("failed to marshal request: %w", err)
\t}
\treq, err := http.NewRequest("POST", "https://domainscope.scrapetheworld.org/api/v1/categorize", bytes.NewBuffer(jsonData))
\tif err != nil {
\t\treturn fmt.Errorf("failed to create request: %w", err)
\t}
\treq.Header.Set("Content-Type", "application/json")
\tresp, err := client.Do(req)
\tif err != nil {
\t\treturn fmt.Errorf("failed to make request: %w", err)
\t}
\tdefer resp.Body.Close()
\tbody, err := io.ReadAll(resp.Body)
\tif err != nil {
\t\treturn fmt.Errorf("failed to read response: %w", err)
\t}
\tif resp.StatusCode != http.StatusOK {
\t\treturn fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
\t}
\tlog.Printf("Success for %s: %s", domain, string(body))
\treturn nil
}
"""

# ── helpers ───────────────────────────────────────────────────────────────────

def ssh(cmd, capture=False):
    full = ["ssh", "-J", JUMP_HOST, f"{TARGET_USER}@{TARGET_HOST}", cmd]
    if capture:
        return subprocess.check_output(full, text=True).strip()
    subprocess.check_call(full)


def scp(local, remote):
    subprocess.check_call([
        "scp", "-J", JUMP_HOST,
        local, f"{TARGET_USER}@{TARGET_HOST}:{remote}"
    ])


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


def dns_filter(domains, workers, timeout):
    pipeline = workers * 4
    domain_iter = iter(domains)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for d in itertools.islice(domain_iter, pipeline):
            futures[ex.submit(check_dns, d, timeout)] = d
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                futures.pop(f)
                result = f.result()
                if result:
                    yield result
                try:
                    nd = next(domain_iter)
                    futures[ex.submit(check_dns, nd, timeout)] = nd
                except StopIteration:
                    pass


def export_from_db(db_path, tld):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT d.domain FROM domains d JOIN tlds t ON d.tld_id = t.id WHERE t.tld = ? ORDER BY d.domain",
            (tld,)
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ── main pipeline ─────────────────────────────────────────────────────────────

def collect_domains(tld, args, shared_seen=None):
    """Export, strip subdomains, and optionally DNS-filter one TLD.

    shared_seen: if provided (a set), domains already in it are skipped —
                 used by --merge to deduplicate across TLDs.
    Returns list of final domains, or None on error.
    """
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"  ERROR: DB not found at {db_path}")
        return None

    print(f"  Exporting .{tld} from database...")
    t0 = time.time()
    raw = export_from_db(db_path, tld)
    if not raw:
        print(f"  ERROR: no domains found for .{tld} in DB")
        return None
    print(f"    {len(raw):,} raw rows ({time.time()-t0:.1f}s)")

    print(f"  Stripping subdomains...")
    seen = shared_seen if shared_seen is not None else set()
    apex_domains = []
    for d in raw:
        a = apex(d)
        if a and a not in seen:
            seen.add(a)
            apex_domains.append(a)
    print(f"    {len(apex_domains):,} unique apex domains")

    if args.skip_dns_filter:
        print(f"  DNS filter skipped")
        return apex_domains

    print(f"  DNS filtering ({args.workers} workers, {args.timeout}s timeout)...")
    t0 = time.time()
    final = list(dns_filter(apex_domains, args.workers, args.timeout))
    elapsed = time.time() - t0
    pct = len(final) / len(apex_domains) * 100 if apex_domains else 0
    print(f"    {len(final):,} active ({pct:.1f}%) in {elapsed:.0f}s")
    return final


def deploy(name, final_domains, args):
    """Write files locally and deploy a single container for the given domain list."""
    tmpdir = tempfile.mkdtemp()

    domains_file = os.path.join(tmpdir, "domains.txt")
    with open(domains_file, "w") as f:
        for d in final_domains:
            f.write(d + "\n")

    if args.dry_run:
        print(f"\n  DRY RUN — {len(final_domains):,} domains written to {tmpdir}")
        return True

    remote_dir = f"{REMOTE_BASE}/go-domainscope-{name}-icann-domains"
    print(f"  Deploying to {remote_dir}...")

    ssh(f"sudo mkdir -p {remote_dir} && sudo chown {TARGET_USER}:{TARGET_USER} {remote_dir}")

    compose = f"""\
services:
  domain-processor:
    build: .
    environment:
      - START_ID=1
      - END_ID={len(final_domains)}
      - CONCURRENCY={args.concurrency}
      - DELAY_MS={args.delay}
      - MAX_RETRIES={MAX_RETRIES}
      - DOMAIN_FILE=/app/domains.txt
    volumes:
      - ./domains.txt:/app/domains.txt
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
"""
    for fname, content in [("Dockerfile", DOCKERFILE), ("main.go", MAIN_GO), ("docker-compose.yml", compose)]:
        path = os.path.join(tmpdir, fname)
        with open(path, "w") as f:
            f.write(content)

    for fname in ["Dockerfile", "main.go", "docker-compose.yml", "domains.txt"]:
        print(f"    uploading {fname}...")
        scp(os.path.join(tmpdir, fname), f"{remote_dir}/{fname}")

    shutil.rmtree(tmpdir)

    print(f"    building and starting container...")
    ssh(f"cd {remote_dir} && docker compose down 2>/dev/null || true && docker compose build && docker compose up -d")

    print(f"\n  Done: {len(final_domains):,} domains live at {remote_dir}")
    print(f"  Logs: ssh -J {JUMP_HOST} {TARGET_USER}@{TARGET_HOST} \"cd {remote_dir} && docker compose logs -f domain-processor\"")
    return True


def parse_args():
    p = argparse.ArgumentParser(description="Deploy one or more TLDs to the domainscope processing server.")
    p.add_argument("tlds", nargs="*", metavar="TLD", help="One or more TLDs (e.g. net info xyz)")
    p.add_argument("--from-file", metavar="FILE",
                   help="Use a pre-filtered domain list file instead of exporting from DB (requires --name)")
    p.add_argument("--merge", action="store_true",
                   help="Merge all TLDs into one deduplicated container instead of one per TLD")
    p.add_argument("--name", help="Override container name (used as go-domainscope-{name}-icann-domains)")
    p.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite DB path (default: {DEFAULT_DB})")
    p.add_argument("--skip-dns-filter", action="store_true", help="Skip DNS resolution check (not recommended)")
    p.add_argument("--workers", type=int, default=300, help="DNS check workers (default: 300)")
    p.add_argument("--timeout", type=float, default=3.0, help="DNS timeout seconds (default: 3)")
    p.add_argument("--dry-run", action="store_true", help="Export and filter locally, skip upload")
    p.add_argument("--concurrency", type=int, default=CONCURRENCY,
                   help=f"CONCURRENCY env var for the container (default: {CONCURRENCY})")
    p.add_argument("--delay", type=int, default=DELAY_MS,
                   help=f"DELAY_MS env var for the container in ms (default: {DELAY_MS})")
    return p.parse_args()


def main():
    args = parse_args()

    # ── --from-file mode: skip DB export entirely ────────────────────────────
    if args.from_file:
        if not args.name:
            print("Error: --from-file requires --name <container-name>")
            sys.exit(1)
        src = Path(args.from_file)
        if not src.exists():
            print(f"Error: file not found: {src}")
            sys.exit(1)
        with open(src) as f:
            domains = [line.strip() for line in f if line.strip()]
        if not domains:
            print(f"Error: no domains found in {src}")
            sys.exit(1)
        print(f"\n{'='*60}")
        print(f"  FROM FILE: {src}  ({len(domains):,} domains)")
        print(f"  Container: go-domainscope-{args.name}-icann-domains")
        print(f"{'='*60}\n")
        if not args.dry_run:
            missing = [v for v, k in [("DEPLOY_JUMP_HOST", JUMP_HOST), ("DEPLOY_HOST", TARGET_HOST)] if not k]
            if missing:
                print(f"Error: set env vars: {', '.join(missing)}")
                sys.exit(1)
        ok = deploy(args.name, domains, args)
        print(f"\n{'='*60}")
        print(f"  {'OK' if ok else 'FAILED'}: {args.name}")
        print(f"{'='*60}")
        return

    tlds = [t.lower().strip(".") for t in args.tlds]
    if not tlds:
        print("Error: specify one or more TLDs, or use --from-file FILE --name NAME")
        sys.exit(1)

    if not args.dry_run:
        missing = [v for v, k in [("DEPLOY_JUMP_HOST", JUMP_HOST), ("DEPLOY_HOST", TARGET_HOST)] if not k]
        if missing:
            print(f"Error: set these environment variables before deploying: {', '.join(missing)}")
            print("  export DEPLOY_JUMP_HOST=root@yourjumphost.com")
            print("  export DEPLOY_HOST=10.x.x.x")
            print("  export DEPLOY_USER=your_user   # default: ubuntu_vm")
            print("  export DEPLOY_REMOTE_BASE=/opt # default: /opt")
            sys.exit(1)

    if args.merge:
        # ── merged mode: one container, all TLDs deduplicated ──────────────
        name = args.name if args.name else "-".join(tlds)
        if not args.name and len(name) > 50:
            print(f"WARNING: auto-generated name is {len(name)} chars long.")
            print(f"  Use --name <short-name> to avoid naming issues.")
            print(f"  Auto name: {name}\n")
        print(f"\n{'='*60}")
        print(f"  MERGED: {', '.join(f'.{t}' for t in tlds)}")
        print(f"  Container name: go-domainscope-{name}-icann-domains")
        print(f"{'='*60}\n")

        shared_seen = set()
        all_domains = []
        for tld in tlds:
            print(f"\n--- .{tld} ---")
            domains = collect_domains(tld, args, shared_seen=shared_seen)
            if domains:
                all_domains.extend(domains)
                print(f"    running total: {len(all_domains):,}")

        if not all_domains:
            print("ERROR: no domains collected")
            sys.exit(1)

        print(f"\n  Total merged: {len(all_domains):,} unique domains")
        ok = deploy(name, all_domains, args)
        print(f"\n{'='*60}")
        print(f"  {'OK' if ok else 'FAILED'}: {name}")
        print(f"{'='*60}")

    else:
        # ── default: one container per TLD ──────────────────────────────────
        if args.name and len(tlds) > 1:
            print("WARNING: --name is ignored when deploying multiple TLDs without --merge")
        results = {}
        for tld in tlds:
            name = args.name if (args.name and len(tlds) == 1) else tld
            print(f"\n{'='*60}")
            print(f"  TLD: .{tld}  →  go-domainscope-{name}-icann-domains")
            print(f"{'='*60}\n")
            domains = collect_domains(tld, args)
            if domains:
                ok = deploy(name, domains, args)
            else:
                ok = False
            results[tld] = ok

        print(f"\n{'='*60}")
        print("  Summary")
        print(f"{'='*60}")
        for tld, ok in results.items():
            print(f"  .{tld:<15} {'OK' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
