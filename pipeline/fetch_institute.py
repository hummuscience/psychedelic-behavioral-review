#!/usr/bin/env python3
"""Download PDFs through publisher text-and-data-mining (TDM) APIs from inside
the institute network, and put them in the PDF store's inbox.

Runs on a computer on the institute network (publishers grant access by IP
address), not on GitHub. It reads the open "PDFs needed" issue that the monthly
workflow maintains, fetches what a sanctioned route covers, and uploads each PDF
to the Nextcloud inbox as <pmid>.pdf, where the next workflow run picks it up.

Routes (only publisher-approved APIs; no browser scraping, which publisher
licences such as Wiley's forbid):
  - Wiley TDM API      needs WILEY_TDM_TOKEN
  - Elsevier API       needs ELSEVIER_API_KEY with full-text entitlement
                       (optional ELSEVIER_INSTTOKEN)
Papers from other publishers are reported and left for manual download.

Standard library only (Python 3.8+), so it runs on a server without installs.

    python3 pipeline/fetch_institute.py --check     # test settings and access
    python3 pipeline/fetch_institute.py --dry-run   # show what it would fetch
    python3 pipeline/fetch_institute.py             # fetch and upload

Settings come from environment variables or a KEY=VALUE file, by default
~/.config/psychedelic-review/fetch.env (keep it private: chmod 600):

    WILEY_TDM_TOKEN=...
    ELSEVIER_API_KEY=...            # optional
    ELSEVIER_INSTTOKEN=...          # optional
    STORE_WEBDAV_URL=https://<nextcloud-host>/public.php/webdav
    STORE_WEBDAV_USER=<share token>
    STORE_WEBDAV_PASSWORD=<share password>
    GITHUB_REPO=hummuscience/psychedelic-behavioral-review   # default
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "psychedelic-review" / "fetch.env"
DEFAULT_REPO = "hummuscience/psychedelic-behavioral-review"
USER_AGENT = ("psychedelic-behavioral-review-tdm/1.0 "
              "(+https://github.com/hummuscience/psychedelic-behavioral-review)")

# Endpoints (overridable for tests).
GITHUB_API = os.environ.get("GITHUB_API", "https://api.github.com")
CROSSREF_API = os.environ.get("CROSSREF_API", "https://api.crossref.org")
WILEY_API = os.environ.get("WILEY_TDM_API", "https://api.wiley.com/onlinelibrary/tdm/v1/articles/")
ELSEVIER_API = os.environ.get("ELSEVIER_API", "https://api.elsevier.com/content/article/doi/")
IP_ECHO = "https://api.ipify.org"

# Wiley documents at most 60 requests per 10 minutes, i.e. one every 10 s.
WILEY_GAP_S = float(os.environ.get("WILEY_GAP_S", 10.0))
ELSEVIER_GAP_S = float(os.environ.get("ELSEVIER_GAP_S", 2.0))
MIN_PDF_BYTES = 20_000
_last_call = {"wiley": 0.0, "elsevier": 0.0}


# ── Settings ─────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    cfg = {}
    if path.exists():
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            print(f"warning: {path} is readable by other users; run: chmod 600 {path}",
                  file=sys.stderr)
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("WILEY_TDM_TOKEN", "ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN", "STORE_WEBDAV_URL",
              "STORE_WEBDAV_USER", "STORE_WEBDAV_PASSWORD", "GITHUB_REPO"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    cfg.setdefault("GITHUB_REPO", DEFAULT_REPO)
    return cfg


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Response:
    def __init__(self, status: int, body: bytes, headers: dict):
        self.status, self.body, self.headers = status, body, headers


def http(method: str, url: str, headers: dict | None = None, data: bytes | None = None,
         timeout: int = 60) -> Response:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(r.status, r.read(), dict(r.headers))
    except urllib.error.HTTPError as e:
        return Response(e.code, e.read() or b"", dict(e.headers or {}))


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-" and len(data) >= MIN_PDF_BYTES


def _wait(route: str, gap: float) -> None:
    pause = _last_call[route] + gap - time.time()
    if pause > 0:
        time.sleep(pause)
    _last_call[route] = time.time()


# ── What to fetch ────────────────────────────────────────────────────────────

ITEM_RE = re.compile(r"^- \[ \] `(\d+)\.pdf`(.*)$")
DOI_RE = re.compile(r"https://doi\.org/(10\.\S+?)\s*$")


def parse_issue(body: str) -> list:
    """Unticked items from the "PDFs needed" issue: [{pmid, doi, label}]."""
    items = []
    for line in body.splitlines():
        m = ITEM_RE.match(line.strip())
        if not m:
            continue
        rest = m.group(2)
        d = DOI_RE.search(rest)
        items.append({"pmid": m.group(1), "doi": d.group(1).lower() if d else "",
                      "label": rest.strip(" —·")[:110]})
    return items


def needed_pdfs(repo: str) -> list:
    r = http("GET", f"{GITHUB_API}/repos/{repo}/issues?labels=pdfs-needed&state=open",
             {"Accept": "application/vnd.github+json"})
    if r.status != 200:
        raise SystemExit(f"could not read the PDFs-needed issue (HTTP {r.status})")
    issues = json.loads(r.body)
    return parse_issue(issues[0].get("body") or "") if issues else []


def publisher(doi: str) -> str:
    """'wiley', 'elsevier' or '' (other), from Crossref's record for the DOI."""
    r = http("GET", f"{CROSSREF_API}/works/{urllib.parse.quote(doi)}")
    if r.status != 200:
        return ""
    name = (json.loads(r.body).get("message", {}).get("publisher") or "").lower()
    if "wiley" in name:
        return "wiley"
    if "elsevier" in name:
        return "elsevier"
    return ""


# ── Publisher APIs ───────────────────────────────────────────────────────────

def fetch_wiley(doi: str, token: str) -> tuple:
    """(pdf bytes or None, message)."""
    _wait("wiley", WILEY_GAP_S)
    r = http("GET", WILEY_API + urllib.parse.quote(doi, safe=""),
             {"Wiley-TDM-Client-Token": token})
    if r.status == 200 and is_pdf(r.body):
        return r.body, "ok"
    if r.status == 403:
        return None, "access denied (not subscribed, or this computer isn't on the institute's IP range)"
    if r.status == 404:
        return None, "Wiley doesn't know this DOI"
    return None, f"Wiley API answered HTTP {r.status}"


def fetch_elsevier(doi: str, key: str, insttoken: str = "") -> tuple:
    _wait("elsevier", ELSEVIER_GAP_S)
    headers = {"X-ELS-APIKey": key, "Accept": "application/pdf"}
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    r = http("GET", ELSEVIER_API + urllib.parse.quote(doi, safe="/"), headers)
    if r.status == 200 and is_pdf(r.body):
        return r.body, "ok"
    if r.status in (401, 403):
        return None, (f"HTTP {r.status}: key not entitled to full text yet "
                      "(ask Elsevier API Support), or not on the institute network")
    if r.status == 429:
        return None, "Elsevier quota exceeded"
    return None, f"Elsevier API answered HTTP {r.status}"


# ── PDF store (Nextcloud share link via WebDAV) ──────────────────────────────

class Store:
    def __init__(self, url: str, user: str, password: str):
        self.base = url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.auth = {"Authorization": f"Basic {token}"}

    def _url(self, path: str) -> str:
        return f"{self.base}/{urllib.parse.quote(path)}"

    def check(self) -> str:
        r = http("PROPFIND", self._url("inbox/"), {**self.auth, "Depth": "0"})
        return "ok" if r.status in (200, 207) else f"HTTP {r.status}"

    def has(self, name: str) -> bool:
        return http("PROPFIND", self._url(f"inbox/{name}"),
                    {**self.auth, "Depth": "0"}).status in (200, 207)

    def put(self, name: str, data: bytes) -> bool:
        r = http("PUT", self._url(f"inbox/{name}"),
                 {**self.auth, "Content-Type": "application/pdf"}, data=data, timeout=300)
        return r.status in (200, 201, 204)


# ── Main ─────────────────────────────────────────────────────────────────────

def run(cfg: dict, dry_run: bool = False, limit: int = 0) -> dict:
    store = Store(cfg["STORE_WEBDAV_URL"], cfg["STORE_WEBDAV_USER"], cfg["STORE_WEBDAV_PASSWORD"])
    items = needed_pdfs(cfg["GITHUB_REPO"])
    print(f"{len(items)} PDF(s) listed in the PDFs-needed issue")
    done, failed, no_route = [], [], []
    for it in items[: limit or None]:
        if not it["doi"]:
            no_route.append({**it, "why": "no DOI"})
            continue
        pub = publisher(it["doi"])
        if pub == "wiley" and cfg.get("WILEY_TDM_TOKEN"):
            fetch = lambda d: fetch_wiley(d, cfg["WILEY_TDM_TOKEN"])
        elif pub == "elsevier" and cfg.get("ELSEVIER_API_KEY"):
            fetch = lambda d: fetch_elsevier(d, cfg["ELSEVIER_API_KEY"],
                                             cfg.get("ELSEVIER_INSTTOKEN", ""))
        else:
            no_route.append({**it, "why": pub or "other publisher"})
            continue
        name = f"{it['pmid']}.pdf"
        if store.has(name):
            print(f"  already in inbox  {name}")
            continue
        if dry_run:
            print(f"  would fetch ({pub})  {name}  {it['label'][:70]}")
            continue
        data, msg = fetch(it["doi"])
        if data is None:
            failed.append({**it, "why": f"{pub}: {msg}"})
            print(f"  failed ({pub})    {name}  {msg}")
        elif store.put(name, data):
            done.append(it)
            print(f"  uploaded ({pub})  {name}  {len(data) // 1024} KB  {it['label'][:60]}")
        else:
            failed.append({**it, "why": "upload to the PDF store failed"})
            print(f"  failed upload     {name}")
    print(f"\n{len(done)} uploaded, {len(failed)} failed, "
          f"{len(no_route)} without an API route (download those by hand)")
    return {"uploaded": done, "failed": failed, "no_route": no_route}


def check(cfg: dict) -> bool:
    ok = True
    ip = http("GET", IP_ECHO, timeout=15)
    print(f"public IP of this computer: {ip.body.decode().strip() if ip.status == 200 else '?'}"
          "  (should be an institute address)")
    for k in ("STORE_WEBDAV_URL", "STORE_WEBDAV_USER", "STORE_WEBDAV_PASSWORD"):
        if not cfg.get(k):
            print(f"missing setting: {k}")
            ok = False
    if ok:
        res = Store(cfg["STORE_WEBDAV_URL"], cfg["STORE_WEBDAV_USER"],
                    cfg["STORE_WEBDAV_PASSWORD"]).check()
        print(f"PDF store inbox: {res}")
        ok = ok and res == "ok"
    items = needed_pdfs(cfg["GITHUB_REPO"])
    print(f"PDFs-needed issue: {len(items)} item(s)")
    for route, key in (("wiley", "WILEY_TDM_TOKEN"), ("elsevier", "ELSEVIER_API_KEY")):
        if not cfg.get(key):
            print(f"{route}: no {key} set, skipped")
            continue
        sample = next((it for it in items if it["doi"] and publisher(it["doi"]) == route), None)
        if not sample:
            print(f"{route}: no {route} paper in the issue to test with")
            continue
        fetch = fetch_wiley if route == "wiley" else fetch_elsevier
        args = (cfg[key],) if route == "wiley" else (cfg[key], cfg.get("ELSEVIER_INSTTOKEN", ""))
        data, msg = fetch(sample["doi"], *args)
        print(f"{route}: test download of {sample['doi']}: "
              f"{'ok, ' + str(len(data) // 1024) + ' KB' if data else msg}")
        ok = ok and data is not None
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--check", action="store_true", help="test settings and access, upload nothing")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    ap.add_argument("--limit", type=int, default=0, help="process at most N items")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.check:
        sys.exit(0 if check(cfg) else 1)
    for k in ("STORE_WEBDAV_URL", "STORE_WEBDAV_USER", "STORE_WEBDAV_PASSWORD"):
        if not cfg.get(k):
            sys.exit(f"missing setting {k} (see --help)")
    run(cfg, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
