# Hand-off: pushing to GitHub & archiving to Zenodo

Everything in this directory has already been built and verified locally:

- The dashboard builds cleanly (`OBSERVABLE_BASE=/psychedelic-behavioral-review npm run build`)
  and generates all 287 per-study pages.
- The figures regenerate from `data/` via `uv run python figures/plot_*.py`.
- `uv run python -m pytest figures/tests/` → 8 passed, 1 skipped (the skipped
  test needs the source PDFs, which are not redistributed).
- No secrets, PDFs, caches, or build artifacts are tracked (12 MB committed total).

The steps below are **account-level actions only you can perform.**

## 0. Rotate the API keys (precaution)

The keys in `../scoring/.env` were never committed, but rotate them before going
public anyway: regenerate your SAIA / Anthropic / Gemini / OpenRouter / Azure keys.

## 1. Authenticate the GitHub CLI

The real GitHub CLI is `/usr/bin/gh` (v2.4.0). An unrelated `~/.local/bin/gh`
(v0.0.4) shadows it on your PATH, and the stored token is currently expired — so
use the full path and re-authenticate:

```bash
/usr/bin/gh auth login -h github.com
```

(This opens an interactive browser/device flow.)

## 2. Create the repo and push

From **this** directory (it is already a git repo on branch `main`):

```bash
cd "$(git rev-parse --show-toplevel)"   # = .../publication
/usr/bin/gh repo create hummuscience/psychedelic-behavioral-review \
  --public --source=. --remote=origin --push
```

Web-UI fallback (if you prefer not to use `gh`): create an empty **public** repo
named `psychedelic-behavioral-review` under `hummuscience`, then:

```bash
git remote add origin git@github.com:hummuscience/psychedelic-behavioral-review.git
git push -u origin main
```

> If you choose a **different repo name**, update all three of:
> `.github/workflows/deploy.yml` (the `OBSERVABLE_BASE` value),
> `README.md` (the dashboard URL), and `CITATION.cff` (`repository-code` + `url`).

## 3. Enable GitHub Pages

Repo → **Settings → Pages → Source = "GitHub Actions"**. The push already
triggered the build workflow; if it ran before you flipped this, re-run it from
the **Actions** tab.

## 4. Verify the live site

Open https://hummuscience.github.io/psychedelic-behavioral-review/ and click
through **Studies → a per-study page → Dosages → Pipeline/PRISMA**. Confirm the
3D cube renders and the studies table loads.

## 5. Archive to Zenodo for a citable DOI

1. Log in to https://zenodo.org with your GitHub account and authorize the Zenodo
   GitHub app.
2. In Zenodo's GitHub settings, flip the toggle **ON** for
   `hummuscience/psychedelic-behavioral-review`.
3. Back on GitHub, cut a **Release** (tag `v1.0.0`). Zenodo automatically archives
   that release and mints a DOI.

## 6. Backfill the DOI

Edit `CITATION.cff` — uncomment and set the `doi:` line. Optionally also fill in
your `orcid:`. Update the citation section of `README.md` if you want the DOI
inline. Then:

```bash
git add CITATION.cff README.md
git commit -m "docs: add Zenodo DOI"
git push
```

## Known content note

`data/dosages_llm_summary.csv` is header-only (the per-compound dose rollup is
derived live from the consensus JSONs at dashboard build time, so this standalone
CSV was never populated). The `/data` downloads page will show it as "0 rows".
This is cosmetic and does not affect any visualization. Remove the file and its
download link, or populate it, if you'd rather it not appear.
