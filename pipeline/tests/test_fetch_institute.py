"""Offline test of fetch_institute.py against a local stand-in for GitHub,
Crossref, the Wiley and Elsevier APIs and the Nextcloud WebDAV share."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
ISSUE = (Path(__file__).parent / "fixtures" / "pdfs_needed_issue.md").read_text()
PDF = b"%PDF-1.7\n" + b"x" * 30_000
SHARE_AUTH = "Basic " + base64.b64encode(b"sharetoken:sharepass").decode()
PUBLISHERS = {"10.1177": "SAGE Publications", "10.1016": "Elsevier BV",
              "10.1002": "Wiley", "10.1111": "Wiley"}


class Fake(BaseHTTPRequestHandler):
    inbox: dict = {}
    wiley_calls: list = []

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.unquote(self.path)
        if path.startswith("/gh/repos/"):
            return self._send(200, json.dumps([{"body": ISSUE}]).encode())
        if path.startswith("/crossref/works/"):
            doi = path[len("/crossref/works/"):]
            pub = PUBLISHERS.get(doi.split("/")[0], "Other")
            return self._send(200, json.dumps({"message": {"publisher": pub}}).encode())
        if path.startswith("/wiley/"):
            doi = path[len("/wiley/"):]
            Fake.wiley_calls.append(doi)
            if self.headers.get("Wiley-TDM-Client-Token") != "good-token":
                return self._send(403)
            if doi == "10.1002/npr2.70152":
                return self._send(200, PDF, "application/pdf")
            return self._send(403)  # not subscribed
        if path.startswith("/elsevier/"):
            return self._send(403)  # key without full-text entitlement
        self._send(404)

    def do_PROPFIND(self):
        if self.headers.get("Authorization") != SHARE_AUTH:
            return self._send(401)
        name = urllib.parse.unquote(self.path).split("/dav/inbox/")[-1]
        self._send(207 if (name == "" or name in Fake.inbox) else 404)

    def do_PUT(self):
        if self.headers.get("Authorization") != SHARE_AUTH:
            return self._send(401)
        name = urllib.parse.unquote(self.path).split("/dav/inbox/")[-1]
        Fake.inbox[name] = self.rfile.read(int(self.headers["Content-Length"]))
        self._send(201)


@pytest.fixture
def server():
    Fake.inbox, Fake.wiley_calls = {}, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def run(base: str, tmp_path: Path, *args: str, **extra_env: str) -> str:
    env = {**os.environ, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
           "GITHUB_API": f"{base}/gh", "CROSSREF_API": f"{base}/crossref",
           "WILEY_TDM_API": f"{base}/wiley/", "ELSEVIER_API": f"{base}/elsevier/",
           "WILEY_GAP_S": "0", "ELSEVIER_GAP_S": "0",
           "STORE_WEBDAV_URL": f"{base}/dav", "STORE_WEBDAV_USER": "sharetoken",
           "STORE_WEBDAV_PASSWORD": "sharepass", "WILEY_TDM_TOKEN": "good-token", **extra_env}
    for k in ("ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"):
        if k not in extra_env:
            env.pop(k, None)
    out = subprocess.run([sys.executable, str(PIPELINE / "fetch_institute.py"),
                          "--config", str(tmp_path / "none.env"), *args],
                         env=env, capture_output=True, text=True, check=True)
    return out.stdout


def test_fetches_wiley_and_uploads_to_inbox(server, tmp_path):
    out = run(server, tmp_path)
    assert Fake.inbox == {"42379141.pdf": PDF}          # subscribed Wiley paper
    assert "failed (wiley)    42144970.pdf  access denied" in out
    assert "3 without an API route" in out                # SAGE, Elsevier (no key), no DOI
    assert "1 uploaded, 1 failed" in out
    # Second run: the paper is already in the inbox, so Wiley isn't asked again.
    calls = len(Fake.wiley_calls)
    out = run(server, tmp_path)
    assert "already in inbox  42379141.pdf" in out
    assert len(Fake.wiley_calls) == calls + 1             # only the denied one retried


def test_elsevier_without_entitlement_is_reported(server, tmp_path):
    out = run(server, tmp_path, ELSEVIER_API_KEY="key-without-fulltext")
    assert "failed (elsevier)" in out and "not entitled" in out
    assert "42994673.pdf" not in Fake.inbox


def test_dry_run_uploads_nothing(server, tmp_path):
    out = run(server, tmp_path, "--dry-run")
    assert "would fetch (wiley)  42379141.pdf" in out
    assert Fake.inbox == {} and Fake.wiley_calls == []


def test_wrong_share_password_fails_upload(server, tmp_path):
    out = run(server, tmp_path, STORE_WEBDAV_PASSWORD="wrong")
    assert Fake.inbox == {}
    assert "0 uploaded" in out
