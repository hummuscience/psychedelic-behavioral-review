"""Offline tests for the monthly-update pipeline (no network, no API keys).

Run:  uv run python -m pytest pipeline/tests/
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
sys.path.insert(0, str(PIPELINE))

from classify_compounds import classify, decision  # noqa: E402
from fetch_pdfs import assign_stem  # noqa: E402


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "data", tmp_path / "data")
    return tmp_path


def run(script: str, root: Path, *args: str) -> None:
    env = {**os.environ, "DATA_DIR": str(root / "data"), "WORK_DIR": str(root / "work")}
    subprocess.run([sys.executable, str(PIPELINE / script), *args], env=env, check=True,
                   capture_output=True)


# ── Published data is reproduced exactly ─────────────────────────────────────

def test_prisma_rebuild_matches_published(data_copy: Path) -> None:
    run("build_prisma_accounting.py", data_copy)
    assert ((data_copy / "data/prisma_accounting.csv").read_bytes()
            == (REPO / "data/prisma_accounting.csv").read_bytes())


def test_catalog_add_leaves_published_entries_alone(data_copy: Path) -> None:
    results = data_copy / "data/results"
    run("build_assay_catalog.py", data_copy, "--add", "no_such_paper2099")
    for f in ("paper_assays.json", "assay_catalog.json"):
        assert (results / f).read_bytes() == (REPO / "data/results" / f).read_bytes()

    cons = data_copy / "data/results_v2_full_consensus"
    shutil.copy(cons / "zhang2025.json", cons / "newpaper2026.json")
    before = {e["canonical"]: e["count"] for e in json.loads((results / "assay_catalog.json").read_text())}
    run("build_assay_catalog.py", data_copy, "--add", "newpaper2026")
    after = {e["canonical"]: e["count"] for e in json.loads((results / "assay_catalog.json").read_text())}
    added = {r["canonical"] for r in json.loads((results / "paper_assays.json").read_text())["newpaper2026"]}
    assert {k for k in after if after[k] != before.get(k, 0)} == added
    assert all(after[k] == before[k] + 1 for k in added)


# ── New records never borrow an existing paper's PDF ─────────────────────────

def test_update_rows_do_not_surname_match_corpus(data_copy: Path) -> None:
    csv_path = data_copy / "data/pubmed_expansion.csv"
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            ["99999999", "A new psilocybin study in mice.", "Allen J et al.", "2026",
             "Some journal", "10.9999/new.2026", "update:2026-12-03", "no",
             "Psilocybin/Psilocin"])
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    new = rows["99999999"]
    assert new["stem"] == "" and new["on_disk"] == "False"
    assert new["disposition"] == "pdf_unavailable_relevant"
    # and every published record is unchanged
    published = list(csv.DictReader(open(REPO / "data/prisma_accounting.csv", encoding="utf-8")))
    assert all(rows.get(r["pmid"], r) == r for r in published if r["pmid"])


# ── Classifier ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, label", [
    ("Psilocybin restores social behaviour in mice.", "Psilocybin/Psilocin"),
    ("Lysergic acid diethylamide alters sleep in rats.", "LSD"),
    ("Effects of N, N-Dimethyltryptamine on rat behaviour.", "DMT"),
    ("The serotonergic psychedelic DOI impairs deviance detection.",
     "DOI (2,5-dimethoxy-4-iodoamphetamine); Psychedelic (general)"),
    ("Attenuation of ecstasy-induced neurotoxicity by N-acetylcysteine.", "MDMA"),
    ("Prophylactic effects of arketamine in mice.", "Unclassified/possible false positive"),
    ("Norpsilocin analogues in mice.", "Unclassified/possible false positive"),
])
def test_classifier_labels(title: str, label: str) -> None:
    assert classify(title) == label


def test_decisions() -> None:
    assert decision("Psilocybin/Psilocin; Ketamine") == "relevant"
    assert decision("Mescaline") == "relevant"
    assert decision("MDMA") == "mdma_only"
    assert decision("Ketamine") == "off_topic"
    assert decision("Unclassified/possible false positive") == "false_positive"


# ── Stems ────────────────────────────────────────────────────────────────────

def test_stems_never_collide() -> None:
    taken = {"gattuso2025", "gattuso20251", "fleury2026", "fleury2026b"}
    assert assign_stem("Gattuso JJ et al.", "2025", taken) == "gattuso2025b"
    assert assign_stem("Fleury S et al.", "2026", taken) == "fleury2026c"
    assert assign_stem("Wawrzczak-Bargieła A et al.", "2026", taken) == "wawrzczakbargiela2026"
    assert assign_stem("De Souza CP & Lee K", "2026", taken) == "desouza2026"
    assert assign_stem("De Souza CP & Lee K", "2026", taken) == "desouza2026b"


def test_duplicate_detection() -> None:
    from search_pubmed import find_duplicate
    registry = json.loads((REPO / "data/paper_registry.json").read_text())
    rec = {"doi": "10.1038/new-journal-version",
           "title": registry["lu2025"]["title"].replace("’", "'")}
    assert find_duplicate(rec, registry) == "lu2025"
    assert find_duplicate({"doi": "", "title": "An unrelated title about rats."}, registry) is None


# ── A new paper never changes an old record (Cavallaro 2026 case) ────────────

def _add_monthly_paper(root: Path, stem: str, pmid: str, doi: str, authors: str) -> None:
    """Simulate fetch_pdfs.py having added a paper (CSV row, registry, inventory)."""
    with open(root / "data/pubmed_expansion.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            [pmid, "Mescaline alters something in awake rats.", authors, "2026",
             "Some journal", doi, "update:2026-12-03", "no", "Mescaline"])
    reg_path = root / "data/paper_registry.json"
    reg = json.loads(reg_path.read_text())
    reg[stem] = {"stem": stem, "doi": doi, "pmid": pmid, "match_via": "monthly_update"}
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    with open(root / "data/pdf_inventory.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow([stem, "pdfs", "True", "False"])


def test_new_paper_with_an_old_records_stem_changes_nothing(data_copy: Path) -> None:
    # The original search has "Cavallaro N et al." 2026 (stem cavallaro2026,
    # no PDF). A different Cavallaro 2026 paper arrives under the same stem.
    _add_monthly_paper(data_copy, "cavallaro2026", "99999998", "10.9999/cav.2026",
                       "Cavallaro N et al.")
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    published = list(csv.DictReader(open(REPO / "data/prisma_accounting.csv", encoding="utf-8")))
    assert all(rows[r["pmid"]] == r for r in published if r["pmid"])
    assert rows["99999998"]["disposition"] == "pending_scoring"


def test_taken_stems_cover_original_search_records() -> None:
    from fetch_pdfs import taken_stems
    taken = taken_stems()
    assert "cavallaro2026" in taken  # only a PRISMA record, no PDF
    assert assign_stem("Cavallaro N et al.", "2026", taken) == "cavallaro2026b"


# ── Reviews, news, letters: excluded before a PDF is fetched ────────────────

def test_non_primary_types() -> None:
    from search_pubmed import non_primary_type
    assert non_primary_type(["Journal Article"]) is None
    assert non_primary_type(["Journal Article", "Review"]) == "Review"
    assert non_primary_type(["News"]) == "News"
    assert non_primary_type(["Letter", "Comment"]) == "Comment"


def test_recheck_excludes_records_tagged_later(data_copy: Path) -> None:
    # A relevant record from an earlier run, still waiting for its PDF...
    with open(data_copy / "data/pubmed_expansion.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            ["99999997", "Psilocybin and the brain.", "Doe J et al.", "2026", "J",
             "10.9999/review.2026", "update:2026-12-03", "no", "Psilocybin/Psilocin"])
    # ...that PubMed has since tagged as a Review (PubMed call faked).
    script = f"""
import sys; sys.path.insert(0, {str(PIPELINE)!r})
import pubmed, search_pubmed
pubmed.efetch = lambda ids: [{{"pmid": "99999997", "doi": "10.9999/review.2026",
    "title": "Psilocybin and the brain.", "publication_types": ["Journal Article", "Review"]}}]
print(len(search_pubmed.recheck_publication_types()))
"""
    env = {**os.environ, "DATA_DIR": str(data_copy / "data"), "WORK_DIR": str(data_copy / "work")}
    out = subprocess.run([sys.executable, "-c", script], env=env, check=True,
                         capture_output=True, text=True).stdout.strip()
    assert out == "1"
    dec = json.loads((data_copy / "data/manual_decisions.json").read_text())
    assert dec["10.9999/review.2026"]["disposition"] == "excluded_not_primary_research"
    # PRISMA records it as such, and the PDF step no longer asks for it.
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    assert rows["99999997"]["disposition"] == "excluded_not_primary_research"
    script = f"""
import sys, json; sys.path.insert(0, {str(PIPELINE)!r})
import fetch_pdfs as fp
from paths import REGISTRY_JSON, MANUAL_DECISIONS_JSON
p = fp.pending(fp._load_rows(), json.loads(REGISTRY_JSON.read_text()),
               json.loads(MANUAL_DECISIONS_JSON.read_text()))
print(any(r["pmid"] == "99999997" for r in p))
"""
    out = subprocess.run([sys.executable, "-c", script], env=env, check=True,
                         capture_output=True, text=True).stdout.strip()
    assert out == "False"


# ── An expired SAIA key is reported, not silently skipped ───────────────────

def test_saia_key_check(monkeypatch) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import monthly_update

    class Saia(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            good = self.headers.get("Authorization") == "Bearer good"
            body = b'{"data": []}' if good else b'{"detail":"API key has expired"}'
            self.send_response(200 if good else 401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Saia)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    try:
        monkeypatch.setenv("SAIA_API_KEY", "good")
        assert monthly_update.saia_key_problem(base) == ""
        monkeypatch.setenv("SAIA_API_KEY", "expired")
        assert "API key has expired" in monthly_update.saia_key_problem(base)
        monkeypatch.delenv("SAIA_API_KEY")
        assert monthly_update.saia_key_problem(base) == "SAIA_API_KEY is not set"
    finally:
        srv.shutdown()


# ── Judge request shape for current Claude models (no API calls) ────────────

class _FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


def _fake_message(stop_reason="end_turn", text='{"assays": []}', category=None):
    from types import SimpleNamespace as NS
    return NS(stop_reason=stop_reason,
              stop_details=NS(category=category) if stop_reason == "refusal" else None,
              content=[NS(type="thinking", thinking=""), NS(type="text", text=text)],
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                       cache_creation_input_tokens=0))


class _FakeClient:
    def __init__(self, replies):
        self.calls, self.replies = [], dict(replies)
        from types import SimpleNamespace as NS
        self.messages = NS(stream=self._stream)

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeStream(self.replies[kwargs["model"]])


def test_judge_request_has_no_temperature_and_explicit_effort(monkeypatch):
    import judge_consensus as jc
    monkeypatch.setattr(jc, "JUDGE_EFFORT", "high")
    client = _FakeClient({"claude-opus-5-5": _fake_message()})
    text, usage = jc.call_judge(client, "foundry", "claude-opus-5-5",
                                [{"type": "text", "text": "sys"}], "paper")
    call = client.calls[0]
    assert "temperature" not in call
    assert call["output_config"] == {"effort": "high"}
    assert call["max_tokens"] == 64000
    assert text == '{"assays": []}' and usage["served_by"] == "claude-opus-5-5"


def test_judge_refusal_falls_back_and_is_recorded(monkeypatch):
    import judge_consensus as jc
    monkeypatch.setattr(jc, "JUDGE_FALLBACK_MODEL", "claude-opus-5")
    client = _FakeClient({"claude-opus-5-5": _fake_message("refusal", category="bio"),
                          "claude-opus-5": _fake_message()})
    text, usage = jc.call_judge(client, "foundry", "claude-opus-5-5",
                                [{"type": "text", "text": "sys"}], "paper")
    assert [c["model"] for c in client.calls] == ["claude-opus-5-5", "claude-opus-5"]
    assert usage["served_by"] == "claude-opus-5"
    declined = usage["fallback_from"]
    assert declined["model"] == "claude-opus-5-5" and declined["category"] == "bio"
    assert {"explanation", "request_id", "output_tokens"} <= set(declined)


def test_judge_cut_off_output_is_an_error(monkeypatch):
    import judge_consensus as jc
    client = _FakeClient({"claude-opus-5-5": _fake_message("max_tokens")})
    with pytest.raises(RuntimeError, match="max_tokens"):
        jc.call_judge(client, "foundry", "claude-opus-5-5",
                      [{"type": "text", "text": "sys"}], "paper")


def test_saia_check_reports_models_it_no_longer_offers(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import monthly_update

    class Saia(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"data": [{"id": "qwen3.5-397b-a17b"},
                                        {"id": "glm-5.3-flash"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Saia)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setenv("SAIA_API_KEY", "good")
    try:
        monkeypatch.setattr(monthly_update, "CANDIDATE_MODELS", "qwen,glm53")
        assert monthly_update.saia_key_problem(base) == ""
        monkeypatch.setattr(monthly_update, "CANDIDATE_MODELS", "qwen,glm,gptoss")
        msg = monthly_update.saia_key_problem(base)
        assert "glm-4.7" in msg and "openai-gpt-oss-120b" in msg
        monkeypatch.setattr(monthly_update, "CANDIDATE_MODELS", "qwen,nosuch")
        assert "unknown model tag" in monthly_update.saia_key_problem(base)
    finally:
        srv.shutdown()


# ── Bridge test comparison reproduces the paper's validation ────────────────

def test_bridge_comparison_matches_published_validation(data_copy: Path) -> None:
    sys.path.insert(0, str(REPO / "figures"))
    import rater_lib as rl
    work = data_copy / "work" / "bridge"
    (work / "consensus").mkdir(parents=True)
    for s in rl.PAPER_STEMS:  # "new" scores = the published ones
        res = json.loads((REPO / "data/results_v2_full_consensus" / f"{s}.json").read_text())
        res["judge_input_models"] = ["qwen", "glm53", "deepseek4"]
        (work / "consensus" / f"{s}.json").write_text(json.dumps(res))
        for t in ("qwen", "glm53", "deepseek4"):
            (work / "candidates" / t).mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / "data/results_v2_full_consensus" / f"{s}.json", work / "candidates" / t)
    run("bridge_test.py", data_copy, "--compare-only", "--candidates", "qwen,glm53,deepseek4",
        "--choose-from", "deepseek4", "--ensemble", "")
    report = next((data_copy / "data/calibration").glob("bridge_*.json"))
    res = json.loads(report.read_text())["assay_agreement"]
    # Same numbers as figures/plot_three_way.py for rater 2 vs the published LLM
    assert res["rater 2 vs published LLM"]["B"]["n"] == 49
    assert round(res["rater 2 vs published LLM"]["B"]["icc"], 2) == 0.92
    assert all(res["published LLM vs new LLM"][d]["pct"] == 100 for d in "BED")

    payload = json.loads(report.read_text())
    assert payload["complete"] and all(p["judged"] for p in payload["papers"].values())


def test_bridge_flags_incomplete_runs(data_copy: Path) -> None:
    """Missing candidate scores, or verdicts judged from other models, fail the run."""
    sys.path.insert(0, str(REPO / "figures"))
    import rater_lib as rl
    work = data_copy / "work" / "bridge"
    (work / "consensus").mkdir(parents=True)
    for i, s in enumerate(rl.PAPER_STEMS):
        res = json.loads((REPO / "data/results_v2_full_consensus" / f"{s}.json").read_text())
        res["judge_input_models"] = ["gemma4"]  # judged from one model only
        (work / "consensus" / f"{s}.json").write_text(json.dumps(res))
        for t in ("qwen", "glm53", "gemma4"):
            if t == "glm53" and i >= 5:
                continue  # glm53 scored only 5 papers
            (work / "candidates" / t).mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / "data/results_v2_full_consensus" / f"{s}.json", work / "candidates" / t)
    env = {**os.environ, "DATA_DIR": str(data_copy / "data"), "WORK_DIR": str(data_copy / "work")}
    r = subprocess.run([sys.executable, str(PIPELINE / "bridge_test.py"), "--compare-only",
                        "--candidates", "qwen,glm53,gemma4", "--choose-from", "gemma4",
                        "--ensemble", ""],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 1
    assert "::error::Bridge test incomplete: `glm53` scored 5 of 20 papers" in r.stdout
    payload = json.loads(next((data_copy / "data/calibration").glob("bridge_*.json")).read_text())
    assert not payload["complete"]
    assert not any(p["judged"] for p in payload["papers"].values())
    md = next((data_copy / "data/calibration").glob("bridge_*.md")).read_text()
    assert "Incomplete run" in md


# ── SAIA client: waits out rate limits and busy models ──────────────────────

def _saia_error(cls, status: int, msg: str, headers: dict | None = None):
    import httpx
    req = httpx.Request("POST", "https://chat-ai.academiccloud.de/v1/chat/completions")
    return cls(msg, response=httpx.Response(status, request=req, headers=headers or {}), body=None)


def test_saia_chat_retries_rate_limits_and_busy_models(monkeypatch) -> None:
    import openai
    import provider
    monkeypatch.setattr(provider, "_saia_throttle", lambda: None)
    errors = [
        _saia_error(openai.RateLimitError, 429, "Rate limit exceeded. Retry after 1 seconds."),
        _saia_error(openai.InternalServerError, 503,
                    "All instances of service 'qwen3.5-397b-a17b' are at max capacity."),
    ]

    class Completions:
        calls = 0

        def create(self, **kw):
            Completions.calls += 1
            if errors:
                raise errors.pop(0)
            return "ok"

    client = type("C", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    waits: list[float] = []
    assert provider.saia_chat(client, sleep=waits.append, model="m") == "ok"
    assert Completions.calls == 3
    assert 1.5 <= waits[0] <= 4      # Retry-After from the message, plus jitter
    assert 24 <= waits[1] <= 36      # first busy-model wait (30 s ± 20%)


def test_saia_chat_gives_up_on_client_errors(monkeypatch) -> None:
    import openai
    import provider
    monkeypatch.setattr(provider, "_saia_throttle", lambda: None)

    class Completions:
        def create(self, **kw):
            raise _saia_error(openai.AuthenticationError, 401, "invalid key")

    client = type("C", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    with pytest.raises(openai.AuthenticationError):
        provider.saia_chat(client, sleep=lambda s: pytest.fail("should not wait"), model="m")


def test_saia_throttle_caps_requests_per_10s(monkeypatch) -> None:
    import provider
    clock = {"t": 1000.0}
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(provider.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(provider, "_saia_recent", provider.deque())
    for _ in range(provider.SAIA_MAX_REQUESTS_PER_10S + 1):
        provider._saia_throttle()
    assert clock["t"] >= 1010  # the extra request waited for the window to clear


# ── Judge: malformed replies ────────────────────────────────────────────────

def test_judge_json_extraction() -> None:
    from judge_consensus import _extract_json
    assert _extract_json('```json\n{"a": 1}\n```', "x", {}) == {"a": 1}
    assert _extract_json('Here you go:\n{"a": {"b": 2}}\nDone.', "x", {}) == {"a": {"b": 2}}
    with pytest.raises(ValueError, match="could not parse"):
        _extract_json('{"a": 1 "b": 2}', "x", {})
    with pytest.raises(ValueError, match="empty response"):
        _extract_json("```\n```", "x", {})


def test_saia_skips_a_model_that_keeps_failing(monkeypatch) -> None:
    """504s ("Inference registry error") twice in a row: the model is skipped after."""
    import openai
    import provider
    monkeypatch.setattr(provider, "_saia_throttle", lambda: None)
    monkeypatch.setattr(provider, "_saia_failures", {})

    class Completions:
        calls = 0

        def create(self, **kw):
            Completions.calls += 1
            raise _saia_error(openai.InternalServerError, 504, "Inference registry error")

    client = type("C", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    waits: list[float] = []
    for _ in range(provider.SAIA_UNAVAILABLE_AFTER):
        with pytest.raises(openai.InternalServerError):
            provider.saia_chat(client, sleep=waits.append, model="glm-5.3-flash")
    # Each call: one try plus a short retry per gateway wait, not the long busy waits
    assert Completions.calls == provider.SAIA_UNAVAILABLE_AFTER * (len(provider.SAIA_GATEWAY_WAITS) + 1)
    assert max(waits) <= max(provider.SAIA_GATEWAY_WAITS)
    with pytest.raises(provider.SaiaModelUnavailable, match="glm-5.3-flash"):
        provider.saia_chat(client, sleep=waits.append, model="glm-5.3-flash")
    assert Completions.calls == provider.SAIA_UNAVAILABLE_AFTER * (len(provider.SAIA_GATEWAY_WAITS) + 1)


def test_bridge_ensemble_set_by_hand(data_copy: Path) -> None:
    sys.path.insert(0, str(REPO / "figures"))
    import rater_lib as rl
    work = data_copy / "work" / "bridge"
    (work / "consensus").mkdir(parents=True)
    trio = ["qwen", "deepseek4", "gemma4"]
    for s in rl.PAPER_STEMS:
        res = json.loads((REPO / "data/results_v2_full_consensus" / f"{s}.json").read_text())
        res["judge_input_models"] = trio
        (work / "consensus" / f"{s}.json").write_text(json.dumps(res))
        for t in trio:
            (work / "candidates" / t).mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / "data/results_v2_full_consensus" / f"{s}.json", work / "candidates" / t)
    run("bridge_test.py", data_copy, "--compare-only", "--candidates", ",".join(trio),
        "--ensemble", ",".join(trio))
    payload = json.loads(next((data_copy / "data/calibration").glob("bridge_*.json")).read_text())
    assert payload["complete"] and payload["ensemble"] == trio
    assert all(p["judged"] for p in payload["papers"].values())
    md = next((data_copy / "data/calibration").glob("bridge_*.md")).read_text()
    assert "Ensemble set by hand" in md and "Choice of the third candidate" not in md


# ── Provenance: which models scored each paper ──────────────────────────────

def test_provenance_of_published_scores_is_reconstructed() -> None:
    import provenance
    d = json.loads((REPO / "data/results_v2_full_consensus/alper2018.json").read_text())
    row = provenance.describe("alper2018", d)
    assert row["setup"] == "v2 (published)" and row["judge"] == "claude-opus-4-7"
    assert row["ensemble"] == "qwen3.5-397b-a17b; glm-4.7; openai-gpt-oss-120b"
    short = provenance.describe("x", {**d, "judge_input_models": ["qwen", "glm"]})
    assert short["missing_candidates"] == "openai-gpt-oss-120b"
    assert short["setup_id"] == row["setup_id"]  # same setup, one model failed


def test_provenance_of_new_scores(monkeypatch) -> None:
    import provenance
    monkeypatch.setenv("GITHUB_SHA", "abcdef1234567890")
    cand = {"qwen": {"scoring": provenance.candidate_stamp("qwen", "qwen3.5-397b-a17b")},
            "gemma4": {"scoring": provenance.candidate_stamp("gemma4", "gemma-4-31b-it")}}
    assert cand["qwen"]["scoring"]["code"] == "abcdef1234"
    s = provenance.judge_stamp(["qwen", "deepseek4", "gemma4"], cand, judge="claude-opus-5-5",
                               judged_by="claude-opus-5", provider="foundry", effort="high",
                               declined={"model": "claude-opus-5-5", "category": None},
                               judge_instructions="judge prompt")
    assert s["missing"] == ["deepseek4"]
    assert s["ensemble"]["deepseek4"] == "deepseek-v4-flash-0731"
    assert s["judged_by"] == "claude-opus-5" and s["declined_by"] == "claude-opus-5-5"
    row = provenance.describe("p", {"scoring": s})
    assert row["missing_candidates"] == "deepseek-v4-flash-0731"
    assert row["candidates"] == "qwen3.5-397b-a17b; gemma-4-31b-it"
    assert "judge claude-opus-5-5 (high)" in row["setup"]
    # Same models, same judge, same rubric: same setup id regardless of what failed
    s2 = provenance.judge_stamp(["qwen", "deepseek4", "gemma4"], {**cand, "deepseek4": {}},
                                judge="claude-opus-5-5", judged_by="claude-opus-5-5",
                                provider="foundry", effort="high", declined=None,
                                judge_instructions="judge prompt")
    assert s2["setup_id"] == s["setup_id"] and s2["missing"] == []


def test_provenance_table_covers_every_scored_paper(data_copy: Path) -> None:
    env = {**os.environ, "DATA_DIR": str(data_copy / "data"), "WORK_DIR": str(data_copy / "work")}
    subprocess.run([sys.executable, str(PIPELINE / "provenance.py")], env=env, check=True,
                   capture_output=True)
    rows = list(csv.DictReader((data_copy / "data/scoring_provenance.csv").open()))
    n = len(list((data_copy / "data/results_v2_full_consensus").glob("*.json")))
    assert len(rows) == n and {r["setup"] for r in rows} == {"v2 (published)"}


def test_rescore_comparison(data_copy: Path) -> None:
    """Rescored = published copies: perfect agreement; published data untouched."""
    rows = [r for r in csv.DictReader(open(REPO / "data/scoring_provenance.csv"))
            if r["missing_candidates"]]
    stems = [r["stem"] for r in rows[:3]]
    trio = ["qwen", "deepseek4", "gemma4"]
    new_dir = data_copy / "data/rescored/test/consensus"
    new_dir.mkdir(parents=True)
    for s in stems:
        d = json.loads((REPO / "data/results_v2_full_consensus" / f"{s}.json").read_text())
        d["judge_input_models"] = trio
        (new_dir / f"{s}.json").write_text(json.dumps(d))
    before = {p.name: p.read_bytes() for p in (data_copy / "data/results_v2_full_consensus").glob("*.json")}
    run("rescore.py", data_copy, "--compare-only", "--stems", ",".join(stems),
        "--ensemble", ",".join(trio), "--name", "test")
    out = json.loads((data_copy / "data/rescored/test/comparison.json").read_text())
    assert out["complete"] and out["papers_judged"] == stems
    assert all(out["assay_agreement"][d]["pct"] == 100 for d in "BED" if out["assay_agreement"].get(d))
    assert all(v["mean_abs_diff"] == 0 for v in out["study_level"].values())
    assert set(out["published_missing"]) >= set(stems)
    prov = list(csv.DictReader((data_copy / "data/rescored/test/scoring_provenance.csv").open()))
    assert [r["stem"] for r in prov] == stems
    assert before == {p.name: p.read_bytes() for p in (data_copy / "data/results_v2_full_consensus").glob("*.json")}


# ── New preprints are set aside for now ─────────────────────────────────────

def _add_search_row(root: Path, pmid: str, title: str, doi: str,
                    journal: str = "Some journal") -> None:
    with open(root / "data/pubmed_expansion.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow(
            [pmid, title, "Doe J et al.", "2026", journal, doi, "update:2026-12-03", "no",
             "Psilocybin/Psilocin"])


def _pending_pmids(root: Path, **env_extra: str) -> set[str]:
    env = {**os.environ, "DATA_DIR": str(root / "data"), "WORK_DIR": str(root / "work"),
           **env_extra}
    script = f"""
import sys, json; sys.path.insert(0, {str(PIPELINE)!r})
import fetch_pdfs as fp
from paths import REGISTRY_JSON, MANUAL_DECISIONS_JSON
p = fp.pending(fp._load_rows(), json.loads(REGISTRY_JSON.read_text()),
               json.loads(MANUAL_DECISIONS_JSON.read_text()))
print(json.dumps([r["pmid"] for r in p]))
"""
    return set(json.loads(subprocess.run([sys.executable, "-c", script], env=env, check=True,
                                         capture_output=True, text=True).stdout))


def test_preprints_are_set_aside(data_copy: Path) -> None:
    import preprints
    assert preprints.is_preprint("10.64898/2026.07.05.736652")
    assert preprints.is_preprint("", "bioRxiv : the preprint server for biology")
    assert not preprints.is_preprint("10.1016/j.pnpbp.2026.111940", "Prog Neuropsychopharmacol")
    _add_search_row(data_copy, "99999990", "Psilocybin changes behaviour in mice.",
                    "10.64898/2026.01.01.000001", "bioRxiv")
    _add_search_row(data_copy, "99999991", "Psilocybin changes another behaviour in rats.",
                    "10.9999/journal.2026")
    run("build_prisma_accounting.py", data_copy)
    rows = {r["pmid"]: r for r in csv.DictReader(
        open(data_copy / "data/prisma_accounting.csv", encoding="utf-8"))}
    assert rows["99999990"]["disposition"] == "deferred_preprint"
    assert rows["99999991"]["disposition"] == "pdf_unavailable_relevant"
    # Published preprints are untouched
    published = list(csv.DictReader(open(REPO / "data/prisma_accounting.csv", encoding="utf-8")))
    assert all(rows[r["pmid"]] == r for r in published if r["pmid"])
    # Not fetched unless switched on, or included by hand
    assert {"99999990", "99999991"} & _pending_pmids(data_copy) == {"99999991"}
    assert {"99999990", "99999991"} <= _pending_pmids(data_copy, INCLUDE_PREPRINTS="true")
    dec_path = data_copy / "data/manual_decisions.json"
    dec = json.loads(dec_path.read_text())
    dec["10.64898/2026.01.01.000001"] = {"disposition": "included_in_review"}
    dec_path.write_text(json.dumps(dec))
    assert "99999990" in _pending_pmids(data_copy)


# ── Inbox files under any name are matched to their paper ──────────────────

def test_inbox_files_are_matched_by_doi_or_title(tmp_path: Path, monkeypatch) -> None:
    import fitz
    import fetch_pdfs as fp
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(fp, "INBOX_DIR", inbox)

    def pdf(name: str, text: str) -> None:
        doc = fitz.open()
        doc.new_page().insert_text((50, 72), text, fontsize=10)
        doc.save(inbox / name)

    rows = [{"pmid": "111", "doi": "10.1016/j.pnpbp.2026.111940",
             "title": "Serotonergic psychedelics and amphetamine shift male rat ultrasonic vocalizations."},
            {"pmid": "222", "doi": "10.1177/02698811261478600",
             "title": "Beyond head-twitch response: Acute psilocybin affects spontaneous "
                      "behaviors in rats in a dose-dependent manner."},
            {"pmid": "333", "doi": "", "title": "Psilocybin and something else in mice."}]
    pdf("1-s2.0-S0278584626001234-main.pdf",
        "Progress in Neuro-Psychopharmacology\nhttps://doi.org/10.1016/j.pnpbp.2026.111940.")
    pdf("download (3).pdf", "Original Paper\nBeyond head-twitch\nresponse: Acute psilo-\n"
        "cybin affects spontaneous behaviors in rats\nin a dose-dependent manner\nA. Author")
    pdf("111_supp.pdf", "named by hand already")
    pdf("mmc1.pdf", "Supplementary Table S1")
    out = fp.match_inbox(rows)
    assert sorted(out["matched"]) == [("1-s2.0-S0278584626001234-main.pdf", "111.pdf"),
                                      ("download (3).pdf", "222.pdf")]
    assert out["unmatched"] == ["mmc1.pdf"]
    assert {p.name for p in inbox.iterdir()} == {"111.pdf", "222.pdf", "111_supp.pdf", "mmc1.pdf"}


# ── Model output that strays from the schema is repaired, not fatal ─────────

def test_off_schema_model_output_is_repaired() -> None:
    from score_studies import (coerce_types, compute_study_scores, normalize_keys,
                               recompute_raw_totals)
    raw = {
        "housing_conditions": {"handling": "not reported"},
        "assays": [
            {"assay_name": "Open field",
             "behavioural_complexity": {"B1_num_measures": {"score": "1", "confidence": "high"},
                                        "B2_temporal_dynamics": {"score": 1}},
             "environmental_complexity": {"E1_environment_type": "yes"},
             "recording_duration": {"D5_follow_up": {"score": "2 (two follow-ups)"}},
             "experimental_conditions": {"application_type": "i.p.", "setup_restrain": None}},
            "not an assay",
        ],
    }
    result = coerce_types(normalize_keys(coerce_types(raw)))
    recompute_raw_totals(result)
    compute_study_scores(result)
    a = result["assays"][0]
    assert len(result["assays"]) == 1
    assert a["behavioural_complexity"]["raw_total"] == 2
    assert a["behavioural_complexity"]["B1_num_measures"] == {"score": 1, "confidence": "low"}
    assert a["environmental_complexity"]["E1_environment_type"] == {"score": 1, "confidence": "low"}
    assert a["recording_duration"]["D5_followup"]["score"] == 2
    assert a["experimental_conditions"]["application_type"]["value"] == "i.p."
    assert result["housing_conditions"]["handling"]["value"] == "not reported"
    assert len(result["format_fixes"]) >= 6
    # Well-formed output is left alone
    clean = {"assays": [{"behavioural_complexity": {"B1_num_measures": {"score": 1}}}]}
    assert "format_fixes" not in coerce_types(clean)


# ── A reply cut off at max_tokens gets one retry with a little sampling ─────

def test_saia_retries_a_truncated_reply(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace as NS
    import provider
    monkeypatch.setenv("SAIA_API_KEY", "dummy")
    monkeypatch.setattr(provider, "docling_convert", lambda pdf, key: "paper text")
    monkeypatch.setattr(provider, "_saia_throttle", lambda: None)
    replies = [("length", '{"assays": [{"x": 1'), ("stop", '{"assays": []}')]
    temps = []

    class Completions:
        def create(self, **kw):
            temps.append(kw["temperature"])
            finish, text = replies.pop(0)
            return NS(choices=[NS(finish_reason=finish, message=NS(content=text))])

    p = provider.SaiaProvider(model="deepseek-v4-flash-0731")
    p.client = NS(chat=NS(completions=Completions()))
    assert p.score_pdf(tmp_path / "x.pdf", "prompt") == {"assays": []}
    assert temps == [0.0, 0.3] and p.last_temperature == 0.3


# ── Papers missing a candidate model wait for it; partial verdicts are redone ─

def test_judging_waits_for_a_missing_model(tmp_path: Path, monkeypatch) -> None:
    import monthly_update as mu
    cand, cons = tmp_path / "candidates", tmp_path / "consensus"
    cons.mkdir()
    monkeypatch.setattr(mu, "CANDIDATES_DIR", cand)
    monkeypatch.setattr(mu, "CONSENSUS_DIR", cons)
    models = ["qwen", "deepseek4", "gemma4"]

    def scored_by(stem: str, *tags: str) -> None:
        for t in tags:
            (cand / t).mkdir(parents=True, exist_ok=True)
            (cand / t / f"{stem}.json").write_text("{}")

    reg = {"a": {}, "b": {}}
    # New paper, DeepSeek failed: wait one run, then judge with the other two
    scored_by("a", "qwen", "gemma4")
    assert mu.plan_judging("a", models, reg) == "hold"
    assert mu.plan_judging("a", models, reg) == "judge"
    assert reg["a"]["candidate_attempts"] == 2
    # Earlier verdict without DeepSeek: kept while DeepSeek still fails...
    scored_by("b", "qwen", "gemma4")
    (cons / "b.json").write_text(json.dumps({"judge_input_models": ["qwen", "gemma4"]}))
    assert mu.plan_judging("b", models, reg) == "hold" and (cons / "b.json").exists()
    # ...and set aside for a new verdict once DeepSeek has scored it
    scored_by("b", "deepseek4")
    assert mu.plan_judging("b", models, reg) == "judge"
    assert not (cons / "b.json").exists() and (cons / "b.json.partial").exists()
    assert mu.plan_judging("c", models, reg) == "skip"
