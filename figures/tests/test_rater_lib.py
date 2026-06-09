from pathlib import Path
import pytest
import rater_lib as rl

# Published datasets live in <repo>/data/ (figures/tests/ -> figures/ -> repo -> data/).
DATA = Path(__file__).resolve().parent.parent.parent / "data"

def test_paper_stems_count_and_goulart():
    assert len(rl.PAPER_STEMS) == 20
    # paper 8 (index 7) maps to the spaced consensus stem, not the docx token
    assert rl.PAPER_STEMS[7] == "goulart da silva2022"
    assert rl.PAPER_STEMS[0] == "alper2018"
    assert rl.PAPER_STEMS[19] == "yu2023"

def test_every_stem_has_consensus():
    # Every HITL-scored paper must have a published consensus record.
    for stem in rl.PAPER_STEMS:
        assert (DATA / "results_v2_full_consensus" / f"{stem}.json").exists(), stem

def test_every_stem_has_docling():
    # Docling markdown is derived from publisher PDFs, which are NOT redistributed
    # in the public dataset. Skip this integrity check when pdfs/ is absent;
    # it still runs in a local dev checkout that has the source PDFs.
    pdf_dir = DATA / "pdfs"
    if not pdf_dir.is_dir():
        pytest.skip("pdfs/ not present (PDFs are not redistributed publicly)")
    for stem in rl.PAPER_STEMS:
        assert (pdf_dir / f"{stem}.docling.md").exists(), stem

def test_hitl_roundtrip(tmp_path, monkeypatch):
    f = tmp_path / "hitl.json"
    monkeypatch.setattr(rl, "HITL_JSON", f)
    assert rl.load_hitl() == {}          # missing file -> empty
    rl.save_paper_scores(
        stem="marek2018",
        paper_num=17,
        assays=[{
            "assay_name": "Head Twitch Response (HTR)",
            "B": {k: 0 for k in rl.B_ITEMS} | {"B1": 2},
            "E": {k: 0 for k in rl.E_ITEMS} | {"E1": 1},
            "D": {k: 0 for k in rl.D_ITEMS} | {"D1": 1},
            "_provenance": {"B1": "auto", "B4": "user"},
        }],
    )
    data = rl.load_hitl()
    assert data["marek2018"]["paper_num"] == 17
    a = data["marek2018"]["assays"][0]
    assert a["B"]["B1"] == 2
    assert a["_provenance"]["B4"] == "user"

def test_save_paper_scores_is_idempotent_per_stem(tmp_path, monkeypatch):
    f = tmp_path / "hitl.json"
    monkeypatch.setattr(rl, "HITL_JSON", f)
    rl.save_paper_scores("yu2023", 20, [{"assay_name": "OFT", "B": {}, "E": {}, "D": {}, "_provenance": {}}])
    rl.save_paper_scores("yu2023", 20, [{"assay_name": "PPI", "B": {}, "E": {}, "D": {}, "_provenance": {}}])
    data = rl.load_hitl()
    # second write for same stem replaces, not appends a duplicate stem key
    assert list(data.keys()) == ["yu2023"]
    assert data["yu2023"]["assays"][0]["assay_name"] == "PPI"

def test_load_consensus_items_marek():
    assays = rl.load_consensus_items("marek2018")
    assert len(assays) == 1
    a = assays[0]
    assert "Head Twitch" in a["assay_name"]
    assert set(a["B"]) == set(rl.B_ITEMS)
    assert set(a["E"]) == set(rl.E_ITEMS)
    assert set(a["D"]) == set(rl.D_ITEMS)
    assert all(isinstance(v, int) for v in a["B"].values())
    # known value from consensus: B1 score = 2
    assert a["B"]["B1"] == 2

def test_parse_ana_docx_only_filled_papers():
    ana = rl.parse_ana_docx()
    # version4 docx: Ana filled all 20 papers (papers 6-10 added 2026-06-09).
    assert "marek2018" in ana
    assert "alper2018" in ana               # filled in v3 (was blank in v2)
    assert "gregory2025" in ana             # paper 9, filled in version4
    assert len(ana) == 20
    marek = ana["marek2018"]
    assert len(marek) >= 1
    assert set(rl.B_ITEMS).issubset(marek[0]["B"].keys())

def test_pair_assays_wds_htr_equivalence():
    # wet-dog-shake (human) must match head twitch response (llm)
    human = [{"name": "WDS"}]
    llm = [{"assay_name": "Head Twitch Response (HTR)"}]
    pairs = rl.pair_assays(human, llm)
    assert pairs == [(0, 0)]


def test_build_pairs_three_way_smoke():
    # Integration smoke: requires human_scores_hitl.json to exist.
    import plot_three_way as p3
    pairs = p3.build_pairs()
    assert len(pairs) >= 1
    for pr in pairs:
        assert "human" in pr and "llm" in pr and "ana" in pr
        assert "stem" in pr
    # at least the papers 11-20 produce some ana-present pairs
    assert any(pr["ana"] is not None for pr in pairs)
    # you+me vs LLM should span all scored assays
    assert sum(1 for pr in pairs if pr["llm"] is not None) >= 40
