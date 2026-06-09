#!/usr/bin/env python3
"""
Download PDFs for new, relevant papers from PubMed expansion CSV.
Filters out already-included, false positives, MDMA, and ketamine papers.
Tries Unpaywall, PMC, and Europe PMC for open-access PDFs.
"""

import csv
import os
import re
import time
import json
import urllib.request
import urllib.error
import ssl

# Paths. Override any of these via environment variables; the defaults assume
# you run this from your own working tree with PDFs alongside the scripts.
# (Source PDFs are not redistributed — see the repo README.)
CSV_PATH = os.environ.get("PUBMED_EXPANSION_CSV", "pubmed_expansion.csv")
PDF_DIR = os.environ.get("PDF_DIR", "pdfs_new")
EXISTING_PDF_DIR = os.environ.get("EXISTING_PDF_DIR", "pdfs")
NOT_FOUND_CSV = os.environ.get("PDFS_NOT_FOUND_CSV", "pdfs_not_found.csv")

# Compounds to KEEP
KEEP_COMPOUNDS = {
    "psilocybin", "psilocin", "lsd", "dmt", "5-meo-dmt", "doi",
    "ibogaine", "mescaline", "ayahuasca", "psychedelic", "psychedelics"
}

# Compounds to EXCLUDE
EXCLUDE_COMPOUNDS = {"mdma", "ketamine"}

# Unpaywall / PMC require a contact email. Set your own via UNPAYWALL_EMAIL.
EMAIL = os.environ.get("UNPAYWALL_EMAIL", "your-email@example.com")

# SSL context (some servers need this)
ssl_ctx = ssl.create_default_context()


def extract_first_author_lastname(authors_short):
    """Extract first author's last name from 'Smith AB et al.' format."""
    if not authors_short:
        return "unknown"
    # Take everything before the first space or comma
    # Handle formats like "De Gregorio D et al." or "van der Berg A et al."
    author = authors_short.strip()
    # Remove "et al." suffix
    author = re.sub(r'\s+et\s+al\.?$', '', author)
    # Split by comma to get first author if multiple
    author = author.split(',')[0].strip()
    # Now extract the last name: everything except the last initials
    # e.g., "De Gregorio D" -> "De Gregorio", "Smith AB" -> "Smith"
    parts = author.split()
    if not parts:
        return "unknown"
    # Initials are typically 1-2 uppercase chars (A, AB, etc.)
    # Work backwards to find where initials end and name begins
    name_parts = []
    for i, part in enumerate(parts):
        # Check if this looks like an initial (1-2 uppercase letters, possibly with period)
        if re.match(r'^[A-Z]{1,3}\.?$', part) and i > 0:
            break
        name_parts.append(part)

    if not name_parts:
        name_parts = [parts[0]]

    lastname = "".join(name_parts).lower()
    # Remove special characters
    lastname = re.sub(r'[^a-z]', '', lastname)
    return lastname if lastname else "unknown"


def is_relevant_compound(detected_compounds):
    """Check if the detected compounds indicate a relevant paper."""
    if not detected_compounds:
        return False

    dc_lower = detected_compounds.lower().strip()

    # Exclude false positives
    if "unclassified" in dc_lower or "false positive" in dc_lower:
        return False

    # Exclude MDMA and ketamine (unless combined with a classical psychedelic)
    compounds_list = [c.strip().lower() for c in dc_lower.split(',')]

    # Check if any compound is in keep list
    has_relevant = False
    for compound in compounds_list:
        compound_clean = compound.strip()
        if compound_clean in EXCLUDE_COMPOUNDS:
            continue
        # Check if compound matches any keep keyword
        for keep in KEEP_COMPOUNDS:
            if keep in compound_clean:
                has_relevant = True
                break
        if has_relevant:
            break

    return has_relevant


def get_existing_pdfs():
    """Get set of existing PDF filenames (lowercase, without extension)."""
    existing = set()
    for f in os.listdir(EXISTING_PDF_DIR):
        if f.endswith('.pdf'):
            existing.add(f[:-4].lower())
    # Also check new PDF dir
    if os.path.exists(PDF_DIR):
        for f in os.listdir(PDF_DIR):
            if f.endswith('.pdf'):
                existing.add(f[:-4].lower())
    return existing


def fetch_url(url, timeout=30):
    """Fetch URL and return response bytes, or None on failure."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (research paper downloader; mailto:' + EMAIL + ')'
        })
        resp = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
        return resp.read(), resp.headers.get('Content-Type', '')
    except Exception as e:
        return None, str(e)


def try_unpaywall(doi):
    """Try to get PDF URL from Unpaywall API."""
    url = f"https://api.unpaywall.org/v2/{doi}?email={EMAIL}"
    data, content_type = fetch_url(url, timeout=15)
    if data is None:
        return None

    try:
        j = json.loads(data)
        # Check best_oa_location first
        best = j.get('best_oa_location')
        if best and best.get('url_for_pdf'):
            return best['url_for_pdf']

        # Check all oa_locations
        for loc in j.get('oa_locations', []):
            if loc.get('url_for_pdf'):
                return loc['url_for_pdf']
    except (json.JSONDecodeError, KeyError):
        pass

    return None


def try_pmc(pmid):
    """Try to get PMCID from PubMed and then fetch PDF from PMC."""
    # First, convert PMID to PMCID using NCBI API
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}&format=json&tool=pdf_downloader&email={EMAIL}"
    data, _ = fetch_url(url, timeout=15)
    if data is None:
        return None, None

    try:
        j = json.loads(data)
        records = j.get('records', [])
        if records and records[0].get('pmcid'):
            pmcid = records[0]['pmcid']
            # Try PMC direct PDF
            pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
            return pmc_url, pmcid
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return None, None


def try_europepmc(pmcid):
    """Try to get PDF from Europe PMC."""
    # pmcid should be like "PMC1234567"
    url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"
    return url


def download_pdf(url, filepath, timeout=60):
    """Download a PDF from URL and save to filepath. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (research paper downloader; mailto:' + EMAIL + ')',
            'Accept': 'application/pdf,*/*'
        })
        resp = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
        content = resp.read()
        content_type = resp.headers.get('Content-Type', '')

        # Verify it's actually a PDF (check magic bytes or content-type)
        if content[:4] == b'%PDF' or 'pdf' in content_type.lower():
            with open(filepath, 'wb') as f:
                f.write(content)
            return True
        else:
            # Sometimes HTML error pages are returned
            if len(content) > 1000 and b'<html' not in content[:500].lower():
                # Might be a PDF without proper header, save it anyway
                with open(filepath, 'wb') as f:
                    f.write(content)
                return True
            return False
    except Exception as e:
        return False


def main():
    # Read CSV
    papers = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            papers.append(row)

    print(f"Total papers in CSV: {len(papers)}")

    # Filter: new papers only (not already included)
    new_papers = [p for p in papers if p.get('already_included', '').strip().lower() != 'yes']
    print(f"Papers not already included: {len(new_papers)}")

    # Filter: relevant compounds only
    relevant = [p for p in new_papers if is_relevant_compound(p.get('detected_compounds', ''))]
    print(f"Papers with relevant compounds: {len(relevant)}")

    # Show compound distribution
    compound_counts = {}
    for p in relevant:
        dc = p.get('detected_compounds', '').strip()
        compound_counts[dc] = compound_counts.get(dc, 0) + 1
    print("\nCompound distribution in relevant papers:")
    for comp, count in sorted(compound_counts.items(), key=lambda x: -x[1]):
        print(f"  {comp}: {count}")

    # Limit to 200
    if len(relevant) > 200:
        print(f"\nLimiting to first 200 papers (out of {len(relevant)})")
        relevant = relevant[:200]

    # Get existing PDFs
    existing = get_existing_pdfs()
    print(f"\nExisting PDFs: {len(existing)}")

    # Process papers
    downloaded = 0
    skipped_existing = 0
    not_found = []
    no_doi_count = 0

    for i, paper in enumerate(relevant):
        pmid = paper.get('pmid', '').strip()
        doi = paper.get('doi', '').strip()
        title = paper.get('title', '').strip()
        year = paper.get('year', '').strip()
        authors = paper.get('authors_short', '').strip()
        compounds = paper.get('detected_compounds', '').strip()

        lastname = extract_first_author_lastname(authors)
        filename_base = f"{lastname}{year}"
        filepath = os.path.join(PDF_DIR, f"{filename_base}.pdf")

        print(f"\n[{i+1}/{len(relevant)}] {authors} ({year}) - {compounds}")
        print(f"  Title: {title[:80]}...")
        print(f"  DOI: {doi}")
        print(f"  Target filename: {filename_base}.pdf")

        # Check if already exists
        if filename_base.lower() in existing:
            print(f"  -> SKIP: already exists")
            skipped_existing += 1
            continue

        # No DOI? Record and skip
        if not doi:
            print(f"  -> No DOI, skipping")
            not_found.append({
                'pmid': pmid, 'doi': '', 'title': title,
                'year': year, 'detected_compounds': compounds,
                'reason': 'no DOI'
            })
            no_doi_count += 1
            continue

        # Try Unpaywall
        print(f"  Trying Unpaywall...")
        time.sleep(1)  # Rate limit: 1/sec
        pdf_url = try_unpaywall(doi)

        if pdf_url:
            print(f"  Found OA URL: {pdf_url[:80]}...")
            if download_pdf(pdf_url, filepath):
                print(f"  -> DOWNLOADED via Unpaywall")
                downloaded += 1
                existing.add(filename_base.lower())
                continue
            else:
                print(f"  -> Download failed from Unpaywall URL")
        else:
            print(f"  No Unpaywall OA URL found")

        # Try PMC
        print(f"  Trying PMC (PMID: {pmid})...")
        time.sleep(0.4)  # Rate limit: 3/sec for NCBI
        pmc_url, pmcid = try_pmc(pmid)

        if pmc_url:
            print(f"  Found PMC: {pmcid}")
            time.sleep(0.4)
            if download_pdf(pmc_url, filepath):
                print(f"  -> DOWNLOADED via PMC")
                downloaded += 1
                existing.add(filename_base.lower())
                continue
            else:
                print(f"  -> PMC download failed, trying Europe PMC...")
                # Try Europe PMC
                epmc_url = try_europepmc(pmcid)
                time.sleep(0.4)
                if download_pdf(epmc_url, filepath):
                    print(f"  -> DOWNLOADED via Europe PMC")
                    downloaded += 1
                    existing.add(filename_base.lower())
                    continue
                else:
                    print(f"  -> Europe PMC download also failed")
        else:
            print(f"  No PMCID found")

        # Not found
        print(f"  -> NOT FOUND (no OA version)")
        not_found.append({
            'pmid': pmid, 'doi': doi, 'title': title,
            'year': year, 'detected_compounds': compounds,
            'reason': 'no OA version available'
        })

    # Write not-found CSV
    if not_found:
        with open(NOT_FOUND_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['pmid', 'doi', 'title', 'year', 'detected_compounds', 'reason'])
            writer.writeheader()
            writer.writerows(not_found)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total relevant new papers: {len(relevant)}")
    print(f"Skipped (already existed): {skipped_existing}")
    print(f"PDFs downloaded: {downloaded}")
    print(f"PDFs not available: {len(not_found)}")
    print(f"  - No DOI: {no_doi_count}")
    print(f"  - No OA version: {len(not_found) - no_doi_count}")
    print(f"\nNot-found list saved to: {NOT_FOUND_CSV}")
    print(f"PDFs saved to: {PDF_DIR}")


if __name__ == '__main__':
    main()
