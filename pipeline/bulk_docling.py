"""Bulk-convert all PDFs in pdfs/ to Docling markdown via the SAIA endpoint.

Caches each paper as <stem>.docling.md alongside the PDF. Skips already-cached.
Sequential; retries each file up to 3 times with backoff.

Usage:
    SAIA_API_KEY=... uv run python bulk_docling.py --pdf-dir ./pdfs
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from provider import docling_convert, ProviderError

MAX_RETRIES = 3
BACKOFF_BASE = 15  # seconds


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--max-files", type=int, default=None,
                    help="Stop after this many files (for testing)")
    args = ap.parse_args()

    api_key = os.environ.get("SAIA_API_KEY")
    if not api_key:
        sys.exit("SAIA_API_KEY not set")

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs in {args.pdf_dir}")

    n_skipped = 0
    n_done = 0
    n_failed = 0
    failed_files: list[str] = []
    t_start = time.time()

    for i, pdf in enumerate(pdfs, 1):
        if args.max_files and (n_done + n_failed) >= args.max_files:
            print(f"--max-files={args.max_files} reached; stopping.")
            break

        md_cache = pdf.with_suffix(".docling.md")
        if md_cache.exists() and md_cache.stat().st_size > 0:
            n_skipped += 1
            continue

        attempt_ok = False
        for attempt in range(1, MAX_RETRIES + 1):
            t0 = time.time()
            try:
                md = docling_convert(pdf, api_key, cache=True)
                dt = time.time() - t0
                elapsed = time.time() - t_start
                processed = n_done + 1
                avg = elapsed / processed if processed else 0
                remaining = len(pdfs) - i
                eta_min = remaining * avg / 60 if avg else 0
                print(
                    f"[{i:3d}/{len(pdfs)}] {pdf.name}  "
                    f"{len(md):,} chars  {dt:.1f}s  "
                    f"(avg {avg:.1f}s  ETA {eta_min:.0f}m)",
                    flush=True,
                )
                n_done += 1
                attempt_ok = True
                break
            except ProviderError as e:
                print(
                    f"[{i:3d}/{len(pdfs)}] {pdf.name}  "
                    f"attempt {attempt}/{MAX_RETRIES} FAILED: {e}",
                    flush=True,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE * attempt)
            except Exception as e:
                print(
                    f"[{i:3d}/{len(pdfs)}] {pdf.name}  "
                    f"unexpected error attempt {attempt}/{MAX_RETRIES}: {e}",
                    flush=True,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE * attempt)

        if not attempt_ok:
            n_failed += 1
            failed_files.append(pdf.name)

    print()
    print(f"Total: {len(pdfs)}")
    print(f"  skipped (already cached): {n_skipped}")
    print(f"  converted: {n_done}")
    print(f"  failed: {n_failed}")
    if failed_files:
        print("  failed files:")
        for f in failed_files:
            print(f"    {f}")


if __name__ == "__main__":
    main()
