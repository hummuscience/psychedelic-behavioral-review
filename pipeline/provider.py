"""Provider backends for the scoring pipeline.

Two providers:
- gemini: native Gemini API with PDF upload (default)
- saia:   GWDG SAIA (OpenAI-compatible) with Docling PDF→markdown conversion

Each provider exposes `.score_pdf(pdf_path) -> dict` returning parsed scoring JSON.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from collections import deque
from abc import ABC, abstractmethod
from pathlib import Path

import requests


SAIA_BASE_URL = "https://chat-ai.academiccloud.de/v1"
DOCLING_TIMEOUT = 600  # PDF conversion can take ~100s for typical papers
SAIA_CHAT_TIMEOUT = 1200  # 20 min cap for a single chat completion call.
# SAIA allows 10 requests per user per 10 s; stay under it across all threads.
SAIA_MAX_REQUESTS_PER_10S = int(os.environ.get("SAIA_MAX_REQUESTS_PER_10S", "8"))
# Waits (s) before retrying a busy model (503 "at max capacity") or a dropped
# connection: ~16 min in all, after which the paper counts as failed.
SAIA_BUSY_WAITS = (30, 60, 120, 240, 480)
SAIA_MAX_RATE_LIMITED = 30  # 429 retries per call (each waits a few seconds)
# The v2 schema's reasoning trace + JSON response can push qwen3.5-397b past
# the old 8-min limit on long papers (~30% of qwen calls were timing out).
# 1200s is long enough for nearly all real completions to finish; if a call
# is genuinely stuck the worker wastes 20 min instead of 8, but the
# success-rate gain dominates.


class ProviderError(RuntimeError):
    """Raised when a provider call fails. The pipeline does NOT auto-fall-back —
    main() catches this and prints an instructive message."""


class Provider(ABC):
    name: str

    @abstractmethod
    def score_pdf(self, pdf_path: Path, prompt: str) -> dict:
        ...


# ---------------------------------------------------------------------------
# Gemini (existing path)
# ---------------------------------------------------------------------------

class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str, thinking_budget: int = 0):
        from google import genai
        self._genai = genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ProviderError(
                "GEMINI_API_KEY not set. Get one at https://aistudio.google.com/apikey"
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.thinking_budget = thinking_budget

    def _upload(self, pdf_path: Path):
        uploaded = self.client.files.upload(file=pdf_path)
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = self.client.files.get(name=uploaded.name)
        if uploaded.state.name == "FAILED":
            raise ProviderError(f"Gemini file upload failed for {pdf_path}")
        return uploaded

    def score_pdf(self, pdf_path: Path, prompt: str) -> dict:
        from google.genai import types
        uploaded_main = self._upload(pdf_path)
        # If a supplementary file is present, attach it too. PDFs are uploaded
        # as a second file part; DOCX is converted locally via pandoc and
        # inlined as markdown text (gemini's File API does not accept .docx).
        supp = _find_supp_pdf(pdf_path)
        uploaded_supp = None
        supp_markdown = None
        if supp is not None:
            if supp.suffix.lower() == ".pdf":
                uploaded_supp = self._upload(supp)
            else:
                supp_markdown = _pandoc_docx_to_md(supp)

        contents = [prompt, uploaded_main]
        if uploaded_supp is not None:
            contents.extend([
                "The next file is the supplementary materials for the paper above. "
                "Treat it as part of the same study when scoring.",
                uploaded_supp,
            ])
        elif supp_markdown is not None:
            contents.append(
                "The text below is the supplementary materials for the paper above "
                "(converted from .docx to markdown). Treat it as part of the same study "
                "when scoring.\n\n=== SUPPLEMENTARY MATERIALS ===\n\n"
                + supp_markdown
            )

        cfg_kwargs = {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": 65536,
        }
        if self.thinking_budget >= 0:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.thinking_budget
            )

        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**cfg_kwargs),
            )
        finally:
            for u in (uploaded_main, uploaded_supp):
                if u is None:
                    continue
                try:
                    self.client.files.delete(name=u.name)
                except Exception:
                    pass

        return json.loads(resp.text)


# ---------------------------------------------------------------------------
# SAIA (Docling PDF→markdown, then OpenAI-compatible chat)
# ---------------------------------------------------------------------------

SUPP_DIRNAME = "pdfs_supplementary"
SUPP_DELIMITER = (
    "\n\n=================================================================\n"
    "=== SUPPLEMENTARY MATERIALS (from supplementary file) ===\n"
    "=================================================================\n\n"
)
SUPP_EXTENSIONS = (".pdf", ".docx")  # supported supplementary formats


def _docling_call(pdf_path: Path, api_key: str) -> str:
    """Raw Docling conversion of a PDF (no caching)."""
    url = f"{SAIA_BASE_URL}/documents/convert"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    busy = rate_limited = 0
    while True:
        _saia_throttle()
        with pdf_path.open("rb") as fh:
            files = {"document": (pdf_path.name, fh, "application/pdf")}
            params = {"response_type": "markdown"}
            r = requests.post(url, headers=headers, params=params, files=files,
                              timeout=DOCLING_TIMEOUT)
        if r.status_code == 429 and rate_limited < SAIA_MAX_RATE_LIMITED:
            rate_limited += 1
            time.sleep(_retry_after(r) + random.uniform(0.5, 3))
        elif r.status_code in (502, 503, 504) and busy < len(SAIA_BUSY_WAITS):
            time.sleep(SAIA_BUSY_WAITS[busy] * random.uniform(0.8, 1.2))
            busy += 1
        else:
            break
    if r.status_code != 200:
        raise ProviderError(
            f"Docling conversion failed for {pdf_path.name}: "
            f"HTTP {r.status_code} {r.text[:300]}"
        )
    data = r.json()
    md = data.get("markdown")
    if not md:
        raise ProviderError(f"Docling returned no markdown for {pdf_path.name}")
    return md


def _pandoc_docx_to_md(docx_path: Path) -> str:
    """Convert a .docx to GitHub-flavoured markdown via pandoc.

    Pandoc is the local fallback for DOCX supplements — SAIA's Docling
    endpoint only handles PDFs. Requires `pandoc` on PATH.
    """
    import shutil
    import subprocess

    if shutil.which("pandoc") is None:
        raise ProviderError(
            f"Cannot convert {docx_path.name}: pandoc not found on PATH. "
            "Install pandoc or convert the .docx to .pdf manually."
        )
    try:
        result = subprocess.run(
            ["pandoc", "--from=docx", "--to=gfm",
             "--wrap=preserve", str(docx_path)],
            capture_output=True, text=True, timeout=120, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise ProviderError(
            f"pandoc failed on {docx_path.name}: {e.stderr[:300]}"
        ) from e
    md = result.stdout
    if not md.strip():
        raise ProviderError(f"pandoc produced empty markdown for {docx_path.name}")
    return md


def _convert_with_cache(doc_path: Path, api_key: str, cache: bool) -> str:
    """Convert a single document to markdown, with a side-cache.

    PDFs go through SAIA Docling; DOCX files go through local pandoc. The
    cache file sits next to the source as ``<name>.docling.md`` regardless of
    source format, so callers don't need to know which converter ran.
    """
    md_cache = doc_path.with_suffix(".docling.md")
    if cache and md_cache.exists() and md_cache.stat().st_size > 0:
        return md_cache.read_text()

    ext = doc_path.suffix.lower()
    if ext == ".pdf":
        md = _docling_call(doc_path, api_key)
    elif ext == ".docx":
        md = _pandoc_docx_to_md(doc_path)
    else:
        raise ProviderError(
            f"Unsupported document type for {doc_path.name}: {ext!r} "
            f"(expected one of {SUPP_EXTENSIONS})"
        )

    if cache:
        try:
            md_cache.write_text(md)
        except OSError:
            pass
    return md


def _find_supp_pdf(pdf_path: Path) -> Path | None:
    """Look for a supplementary document for the given main PDF.

    Accepts both ``<stem>_supp.pdf`` and ``<stem>_supp.docx`` in
    ``pdfs_supplementary/`` (sibling of the main PDF folder). PDF wins if
    both happen to exist. Name is kept for backwards compatibility — it now
    returns either format.

    Tries multiple unicode-normalisation forms of the stem so the lookup
    succeeds whether the file was dropped in via Finder (NFD) or saved from
    Zotero/the web (NFC).
    """
    import unicodedata
    supp_dir = pdf_path.parent.parent / SUPP_DIRNAME
    stem = pdf_path.stem
    variants = {stem,
                unicodedata.normalize("NFC", stem),
                unicodedata.normalize("NFD", stem)}
    for variant in variants:
        for ext in SUPP_EXTENSIONS:
            candidate = supp_dir / f"{variant}_supp{ext}"
            if candidate.exists():
                return candidate
    return None


def docling_convert(pdf_path: Path, api_key: str, cache: bool = True) -> str:
    """Convert PDF to markdown via SAIA's Docling endpoint.

    Caches markdown next to the PDF as <stem>.docling.md so reruns are fast.

    If a supplementary file is present at
    ``pdfs_supplementary/<stem>_supp.pdf`` (or ``_supp.docx``), it is also
    converted and appended after a clearly demarcated delimiter, so the LLM
    sees a single document containing both the main manuscript and the
    supplementary methods/data. The supplementary markdown is cached as
    ``<stem>_supp.docling.md`` next to the supplementary file. The main
    cache file remains main-only.
    """
    main_md = _convert_with_cache(pdf_path, api_key, cache)

    supp = _find_supp_pdf(pdf_path)
    if supp is None:
        return main_md

    supp_md = _convert_with_cache(supp, api_key, cache)
    return main_md + SUPP_DELIMITER + supp_md


_saia_lock = threading.Lock()
_saia_recent: deque = deque()


def _saia_throttle() -> None:
    """Block until a request fits in SAIA's per-user rate limit."""
    while True:
        with _saia_lock:
            now = time.monotonic()
            while _saia_recent and now - _saia_recent[0] >= 10:
                _saia_recent.popleft()
            if len(_saia_recent) < SAIA_MAX_REQUESTS_PER_10S:
                _saia_recent.append(now)
                return
            wait = 10 - (now - _saia_recent[0]) + 0.05
        time.sleep(wait)


def _retry_after(err) -> float:
    """Seconds SAIA asks us to wait after a 429 (header, else message, else 5)."""
    resp = getattr(err, "response", err)
    headers = getattr(resp, "headers", None)
    header = headers.get("retry-after") if headers is not None else None
    try:
        return float(header)
    except (TypeError, ValueError):
        m = re.search(r"[Rr]etry after (\d+(?:\.\d+)?)", getattr(err, "text", None) or str(err))
        return float(m.group(1)) if m else 5.0


def saia_chat(client, sleep=time.sleep, **kwargs):
    """chat.completions.create with SAIA's rate limit, busy models and dropped
    connections handled: waits and tries again; one retry after a timeout."""
    import openai
    busy = rate_limited = timeouts = 0
    while True:
        _saia_throttle()
        try:
            return client.chat.completions.create(**kwargs)
        except openai.RateLimitError as e:
            rate_limited += 1
            if rate_limited > SAIA_MAX_RATE_LIMITED:
                raise
            wait = _retry_after(e) + random.uniform(0.5, 3)
        except openai.APITimeoutError:
            timeouts += 1
            if timeouts > 1:
                raise
            wait = 0
        except (openai.InternalServerError, openai.APIConnectionError):
            if busy >= len(SAIA_BUSY_WAITS):
                raise
            wait = SAIA_BUSY_WAITS[busy] * random.uniform(0.8, 1.2)
            busy += 1
        sleep(wait)


class SaiaProvider(Provider):
    name = "saia"

    def __init__(self, model: str = "qwen3.5-397b-a17b"):
        from openai import OpenAI
        api_key = os.environ.get("SAIA_API_KEY")
        if not api_key:
            raise ProviderError(
                "SAIA_API_KEY not set. Request one at "
                "https://docs.hpc.gwdg.de/services/ai-services/saia/index.html"
            )
        self.api_key = api_key
        self.client = OpenAI(
            api_key=api_key, base_url=SAIA_BASE_URL,
            timeout=SAIA_CHAT_TIMEOUT, max_retries=0,
        )
        self.model = model

    def score_pdf(self, pdf_path: Path, prompt: str) -> dict:
        markdown = docling_convert(pdf_path, self.api_key)
        user_content = (
            "The following is the full text of a scientific paper, converted "
            "from PDF to markdown via Docling. Score it according to the rubric "
            "above. Respond with a single JSON object only.\n\n"
            "=== PAPER START ===\n"
            f"{markdown}\n"
            "=== PAPER END ==="
        )
        try:
            resp = saia_chat(
                self.client,
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                max_tokens=65536,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise ProviderError(f"SAIA chat completion failed: {e}") from e

        finish = resp.choices[0].finish_reason
        text = resp.choices[0].message.content or ""
        if finish == "length":
            raise ProviderError(
                f"SAIA response truncated at max_tokens for {pdf_path.name} "
                "— increase max_tokens or split the paper."
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"SAIA returned non-JSON for {pdf_path.name}: {e}"
            ) from e


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_provider(name: str, model: str | None = None,
                  thinking_budget: int = 0) -> Provider:
    if name == "gemini":
        return GeminiProvider(model=model or "gemini-2.5-flash-lite",
                              thinking_budget=thinking_budget)
    if name == "saia":
        return SaiaProvider(model=model or "qwen3.5-397b-a17b")
    raise ValueError(f"unknown provider: {name!r}")
