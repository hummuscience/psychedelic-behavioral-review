"""Private file store for PDFs and other unpublishable files, via rclone.

The PDFs, Docling markdown and per-model candidate scores can't go in the public
repo, but the monthly run needs them to persist between runs. When STORE_REMOTE
is set (an rclone remote path such as "store:psychedelic-review"), the run pulls
what it needs into WORK_DIR and pushes new files back. When it isn't set,
WORK_DIR itself is the store (for running on your own machine).

Layout on the remote mirrors WORK_DIR:

    inbox/                      PDFs you add by hand: <pmid>.pdf, <pmid>_supp.pdf
    pdfs/                       <stem>.pdf and <stem>.docling.md
    pdfs_supplementary/         <stem>_supp.pdf / .docx
    results_v2_full_compare/    <model>/<stem>.json candidate scores

rclone reads the remote's settings from RCLONE_CONFIG_<NAME>_* environment
variables; the GitHub workflow sets these from repository secrets.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from paths import WORK_DIR

REMOTE = os.environ.get("STORE_REMOTE", "").rstrip("/")


def enabled() -> bool:
    return bool(REMOTE)


def _remote(sub: str) -> str:
    """Join a sub-path onto the remote ("store:" + "inbox" -> "store:inbox")."""
    return f"{REMOTE}{sub}" if REMOTE.endswith(":") else f"{REMOTE}/{sub}"


def _rclone(*args: str) -> None:
    subprocess.run(["rclone", *args], check=True)


def _copy_filtered(src: str, dst: str, patterns: list[str]) -> None:
    if not patterns:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(patterns) + "\n")
        flist = f.name
    try:
        _rclone("copy", src, dst, "--include-from", flist)
    finally:
        os.unlink(flist)


def _stem_patterns(stems: list[str]) -> list[str]:
    pats = []
    for s in stems:
        pats += [f"/pdfs/{s}.pdf", f"/pdfs/{s}.docling.md",
                 f"/pdfs_supplementary/{s}_supp.*",
                 f"/results_v2_full_compare/*/{s}.json"]
    return pats


def pull_inbox() -> None:
    if enabled():
        (WORK_DIR / "inbox").mkdir(parents=True, exist_ok=True)
        _rclone("copy", _remote("inbox"), str(WORK_DIR / "inbox"))


def pull_stems(stems: list[str]) -> None:
    """Fetch the files of papers still being processed from earlier runs."""
    if enabled():
        _copy_filtered(REMOTE, str(WORK_DIR), _stem_patterns(stems))


def push_stems(stems: list[str]) -> None:
    """Save every file belonging to these papers."""
    if enabled():
        _copy_filtered(str(WORK_DIR), REMOTE, _stem_patterns(stems))


def clear_inbox(pmids: list[str]) -> None:
    """Remove inbox files that have been filed under a stem (after push)."""
    for pmid in pmids:
        for name in (f"{pmid}.pdf", f"{pmid}_supp.pdf", f"{pmid}_supp.docx"):
            local = WORK_DIR / "inbox" / name
            if enabled():
                subprocess.run(["rclone", "deletefile", _remote(f"inbox/{name}")],
                               check=False, capture_output=True)
            if local.exists():
                local.unlink()
