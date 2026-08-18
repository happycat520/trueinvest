#!/usr/bin/env python3
"""
CrystalWell Insider Fetcher — direct from SEC EDGAR
=====================================================

Replaces samuelstocks/scripts/fetch_insider.py's yfinance-based approach.
That script pulled `yf.Ticker(ticker).insider_transactions`, which Yahoo
Finance's own documentation attributes to a third-party vendor (LSEG Data
and Analytics / Refinitiv) rather than a direct SEC feed - despite the
samuelstocks README and email footer both (incorrectly) labeling it
"SEC EDGAR Form 4." This script is a direct EDGAR pull: no vendor hop,
no LSEG lag - just SEC's own submissions API and the raw Form 4 XML.

DATA FLOW
---------
1. Ticker -> CIK lookup via SEC's bulk mapping file (cached locally,
   refreshed on a configurable interval - CIKs essentially never change).
2. Per-CIK recent filings list via the submissions API, filtered to
   form "4" within the lookback window.
3. Per-filing: fetch the primary XML ownership document and parse
   non-derivative transactions (the open-market buys/sells this pipeline
   cares about - derivative transactions, i.e. options/RSUs, are not
   currently parsed; see NOTES at the bottom).
4. Aggregate into the exact same {"buys": [...], "sells": [...]} shape
   as the existing insider.json, so nothing downstream (digest generator,
   dashboard.js) needs to change.

*** IMPORTANT - COULD NOT BE TESTED AGAINST LIVE SEC.GOV FROM THIS BUILD
ENVIRONMENT (network sandbox does not allow www.sec.gov / data.sec.gov).
The XML-parsing logic below is unit-tested against a hand-built mock that
matches the real SEC ownership-document XML schema exactly (see
scripts/fetch/tests/test_fetch_insider_edgar.py), but a live end-to-end
run has not been performed. Run it against a small ticker list first and
sanity-check the output before trusting it across the full S&P 500. ***

SEC FAIR-ACCESS REQUIREMENTS (both enforced below)
----------------------------------------------------
- Max 10 requests/second per IP (REQUEST_DELAY_SECONDS keeps this well under)
- A descriptive User-Agent header identifying the requester - EDIT
  USER_AGENT below before running this for real; SEC does reject/throttle
  generic or missing User-Agent strings.
"""

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from pathlib import Path

import requests

from tickers import SP500_TICKERS, COMPANY_NAMES
from roles import is_ceo, is_cfo

PST = ZoneInfo("America/Los_Angeles")

# --- EDIT THIS before running for real. SEC will throttle/reject requests
# without a descriptive User-Agent identifying a real contact.
USER_AGENT = "CrystalWellAnalytics/1.0 (contact: info@crystalwellanalytics.com)"

HEADERS = {"User-Agent": USER_AGENT}

# Stay comfortably under SEC's 10 req/sec fair-access limit.
REQUEST_DELAY_SECONDS = 0.15  # ~6.7 req/sec

LOOKBACK_DAYS = 30  # matches samuelstocks' fetch_insider.py convention

# Open-market transaction codes we treat as genuine buy/sell conviction signals.
# Excludes grants (A), option exercises (M), tax withholding (F), gifts (G),
# conversions (C), etc. - same "open-market only" spirit as the old script's
# PURCHASE/ACQUI/BUY and SALE/SELL/DISPO text matching, but using the actual
# authoritative SEC transaction code instead of fuzzy text matching.
BUY_CODES = {"P"}   # Open market or private purchase
SELL_CODES = {"S"}  # Open market or private sale

CIK_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "cik_map.json"
CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CIK_MAP_MAX_AGE_DAYS = 7  # CIKs essentially never change; weekly refresh is plenty

XML_NAMESPACE_STRIP = True  # SEC ownership XML sometimes uses a default namespace; strip it for simpler xpath


def _get(url: str, **kwargs) -> requests.Response:
    """Single point for all SEC requests - enforces headers + rate limiting."""
    resp = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp


# ---------------------------------------------------------------------------
# Step 1: Ticker -> CIK mapping (cached)
# ---------------------------------------------------------------------------

def load_or_refresh_cik_map() -> dict:
    """Returns {ticker: cik_str_zero_padded_10}. Cached to data/cache/cik_map.json."""
    if CIK_MAP_PATH.exists():
        age_days = (time.time() - CIK_MAP_PATH.stat().st_mtime) / 86400
        if age_days < CIK_MAP_MAX_AGE_DAYS:
            return json.loads(CIK_MAP_PATH.read_text())

    print("Refreshing ticker -> CIK map from SEC...")
    resp = _get(CIK_MAP_URL)
    raw = resp.json()  # {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}

    mapping = {}
    for entry in raw.values():
        ticker = entry["ticker"].upper()
        cik = str(entry["cik_str"]).zfill(10)
        mapping[ticker] = cik

    CIK_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    CIK_MAP_PATH.write_text(json.dumps(mapping))
    print(f"  Cached {len(mapping)} ticker -> CIK mappings")
    return mapping


# ---------------------------------------------------------------------------
# Step 2: Per-CIK recent Form 4 filings
# ---------------------------------------------------------------------------

def get_recent_form4_filings(cik: str, cutoff: date) -> list:
    """Returns [{"accessionNumber", "filingDate", "primaryDocument"}] for
    Form 4 filings on/after cutoff. Reads only the submissions API's
    "recent" array (covers roughly the last year / 1000 filings) - a
    30-day lookback is always well within that, so pagination into the
    older `filings.files` pages is not implemented here. If you extend
    LOOKBACK_DAYS well beyond ~90 days for a low-activity ticker, revisit
    this assumption.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = _get(url)
    except requests.HTTPError as e:
        print(f"  CIK {cik}: submissions fetch failed - {e}")
        return []

    data = resp.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])

    results = []
    for form, accession, filing_date_str, primary_doc in zip(forms, accessions, filing_dates, primary_docs):
        if form != "4":
            continue
        try:
            filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if filing_date < cutoff:
            continue
        results.append({
            "accessionNumber": accession,
            "filingDate": filing_date_str,
            "primaryDocument": primary_doc,
        })
    return results


# ---------------------------------------------------------------------------
# Step 3: Fetch + parse the Form 4 XML itself
# ---------------------------------------------------------------------------

def build_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    cik_int = str(int(cik))  # strip leading zeros for the Archives path
    accession_no_dashes = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primary_document}"


def build_filing_index_url(cik: str, accession_number: str) -> str:
    cik_int = str(int(cik))
    accession_no_dashes = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{accession_number}-index.htm"


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find(el, path):
    """Namespace-agnostic find - SEC ownership XML doesn't consistently use
    a default namespace across filers/years, so match on local tag name."""
    if el is None:
        return None
    parts = path.split("/")
    current = el
    for part in parts:
        found = None
        for child in current:
            if _strip_ns(child.tag) == part:
                found = child
                break
        if found is None:
            return None
        current = found
    return current


def _text(el, path, default=None):
    node = _find(el, path)
    if node is None or node.text is None:
        return default
    return node.text.strip()


def parse_role(reporting_owner_el) -> str:
    rel = _find(reporting_owner_el, "reportingOwnerRelationship")
    if rel is None:
        return "Insider"
    is_officer = _text(rel, "isOfficer", "0") == "1"
    is_director = _text(rel, "isDirector", "0") == "1"
    is_ten_pct = _text(rel, "isTenPercentOwner", "0") == "1"
    officer_title = _text(rel, "officerTitle", "")

    if is_officer and officer_title:
        return officer_title
    if is_officer:
        return "Officer"
    if is_director:
        return "Director"
    if is_ten_pct:
        return "10% Owner"
    return "Insider"


def parse_form4_xml(xml_bytes: bytes, ticker: str, company: str, cik: str, accession_number: str) -> list:
    """Returns a list of raw transaction dicts (not yet split into buys/sells).
    Each dict: {ticker, company, insider, role, date, filing_url, shares,
    price, value, code, acquired_disposed, shares_owned_after}
    """
    root = ET.fromstring(xml_bytes)

    reporting_owners = [c for c in root if _strip_ns(c.tag) == "reportingOwner"]
    if not reporting_owners:
        return []

    # Most filings have one reporting owner; joint filings can have more.
    # Build a role lookup, defaulting to the first owner's name for all
    # transactions in the filing (SEC ownership XML doesn't tie individual
    # transactions to a specific owner when there are multiple - this is a
    # known simplification, flagged in NOTES at the bottom of this file).
    owner_names = []
    role = "Insider"
    for owner in reporting_owners:
        name = _text(owner, "reportingOwnerId/rptOwnerName", "Unknown insider")
        owner_names.append(name)
        role = parse_role(owner)  # last owner's role wins if multiple - simplification

    insider_name = " / ".join(owner_names)
    filing_url = build_filing_index_url(cik, accession_number)

    non_derivative_table = _find(root, "nonDerivativeTable")
    if non_derivative_table is None:
        return []

    transactions = []
    for txn in non_derivative_table:
        if _strip_ns(txn.tag) != "nonDerivativeTransaction":
            continue

        txn_date = _text(txn, "transactionDate/value")
        code = _text(txn, "transactionCoding/transactionCode")
        shares_str = _text(txn, "transactionAmounts/transactionShares/value")
        price_str = _text(txn, "transactionAmounts/transactionPricePerShare/value")
        acquired_disposed = _text(txn, "transactionAmounts/transactionAcquiredDisposedCode/value")
        shares_after_str = _text(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")

        if not txn_date or not code or not shares_str:
            continue

        try:
            shares = float(shares_str)
            price = float(price_str) if price_str else 0.0
            shares_after = float(shares_after_str) if shares_after_str else 0.0
        except ValueError:
            continue

        transactions.append({
            "ticker": ticker,
            "company": company,
            "insider": insider_name,
            "role": role,
            "date": txn_date,
            "filing_url": filing_url,
            "shares": shares,
            "price": price,
            "value": round(shares * price, 2),
            "code": code,
            "acquired_disposed": acquired_disposed,
            "shares_owned_after": shares_after,
        })

    return transactions


# How many parse failures to dump full diagnostics for. Printing this for
# every single failure would flood the log (we saw 1,555 of them in one run);
# a handful is enough to see the actual response content and diagnose it.
MAX_DIAGNOSTIC_DUMPS = 3
_diagnostic_dumps_done = 0


def fetch_ticker_insider_activity(ticker: str, cik: str, cutoff: date) -> tuple:
    """Returns (buys, sells, parse_attempts, parse_failures) for one ticker,
    in the same record shape as the original insider.json plus counters used
    by main() to detect a systemic failure (see NOTES at the bottom)."""
    global _diagnostic_dumps_done
    company = COMPANY_NAMES.get(ticker, ticker)
    buys, sells = [], []
    parse_attempts = 0
    parse_failures = 0

    filings = get_recent_form4_filings(cik, cutoff)
    if not filings:
        return buys, sells, parse_attempts, parse_failures

    for f in filings:
        doc_url = build_document_url(cik, f["accessionNumber"], f["primaryDocument"])
        try:
            resp = _get(doc_url)
        except requests.HTTPError as e:
            print(f"  {ticker}: failed to fetch {doc_url} - {e}")
            continue

        parse_attempts += 1
        try:
            transactions = parse_form4_xml(resp.content, ticker, company, cik, f["accessionNumber"])
        except ET.ParseError as e:
            parse_failures += 1
            print(f"  {ticker}: XML parse error on {doc_url} - {e}")

            # Dump real diagnostics for the first few failures - this is what
            # actually tells us whether SEC is serving a block/rate-limit page
            # instead of the real document, rather than guessing from the
            # error message alone.
            if _diagnostic_dumps_done < MAX_DIAGNOSTIC_DUMPS:
                _diagnostic_dumps_done += 1
                content_type = resp.headers.get("Content-Type", "unknown")
                body_preview = resp.text[:400].replace("\n", " ")
                print(f"    DIAGNOSTIC #{_diagnostic_dumps_done}: status={resp.status_code}, "
                      f"content-type={content_type}")
                print(f"    DIAGNOSTIC #{_diagnostic_dumps_done} body preview: {body_preview!r}")
            continue

        for t in transactions:
            if t["code"] in BUY_CODES:
                buys.append({
                    "ticker": t["ticker"],
                    "company": t["company"],
                    "insider": t["insider"],
                    "role": t["role"],
                    "date": t["date"],
                    "filing_url": t["filing_url"],
                    "shares": int(t["shares"]),
                    "value": int(t["value"]),
                })
            elif t["code"] in SELL_CODES:
                sells.append({
                    "ticker": t["ticker"],
                    "company": t["company"],
                    "insider": t["insider"],
                    "role": t["role"],
                    "date": t["date"],
                    "filing_url": t["filing_url"],
                    "shares_sold": int(t["shares"]),
                    "shares_remaining": int(t["shares_owned_after"]),
                    "expiry": None,  # kept for schema compatibility with the old insider.json; not applicable to Form 4 opens
                    "value": int(t["value"]),
                })

    return buys, sells, parse_attempts, parse_failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cik_map = load_or_refresh_cik_map()
    cutoff = datetime.now(PST).date() - timedelta(days=LOOKBACK_DAYS)

    all_buys, all_sells = [], []
    missing_cik = []
    total_parse_attempts = 0
    total_parse_failures = 0

    for ticker in SP500_TICKERS:
        cik = cik_map.get(ticker.replace("-", "."))  # SEC's map uses e.g. "BRK.B"; tickers.py uses "BRK-B"
        if cik is None:
            cik = cik_map.get(ticker)
        if cik is None:
            missing_cik.append(ticker)
            continue

        buys, sells, parse_attempts, parse_failures = fetch_ticker_insider_activity(ticker, cik, cutoff)
        total_parse_attempts += parse_attempts
        total_parse_failures += parse_failures
        if buys or sells:
            print(f"  {ticker}: {len(buys)} buys, {len(sells)} sells")
        all_buys.extend(buys)
        all_sells.extend(sells)

    if missing_cik:
        print(f"WARNING: no CIK found for {len(missing_cik)} tickers: {missing_cik}")

    # --- Hard failure detection ---
    # Without this, "genuinely no insider activity today" and "every single
    # fetch failed" produce the exact same output shape (0 buys, 0 sells) and
    # the same exit code 0 - so a systemic failure silently overwrites good
    # data with an empty file and GitHub Actions still shows green. This
    # block distinguishes the two cases and refuses to write/commit on a
    # systemic failure, so the last known-good insider.json stays in place
    # instead of being clobbered by a broken run.
    CIK_FAILURE_THRESHOLD = 0.5   # >50% of tickers missing a CIK -> the map itself is likely broken
    PARSE_FAILURE_THRESHOLD = 0.5  # >50% of fetched documents failing to parse -> systemic (e.g. blocked/rate-limited), not per-file noise

    cik_failure_rate = len(missing_cik) / len(SP500_TICKERS) if SP500_TICKERS else 0
    parse_failure_rate = (total_parse_failures / total_parse_attempts) if total_parse_attempts else 0

    if cik_failure_rate > CIK_FAILURE_THRESHOLD:
        print(f"FATAL: {len(missing_cik)}/{len(SP500_TICKERS)} tickers had no CIK "
              f"({cik_failure_rate:.0%}) - the ticker->CIK map itself is likely broken "
              f"(bad download, changed SEC file format, etc). Not writing insider.json - "
              f"leaving the last known-good file in place.")
        raise SystemExit(1)

    if total_parse_attempts > 0 and parse_failure_rate > PARSE_FAILURE_THRESHOLD:
        print(f"FATAL: {total_parse_failures}/{total_parse_attempts} document fetches "
              f"failed to parse ({parse_failure_rate:.0%}). This many failures across "
              f"genuinely different filings almost always means SEC is serving a "
              f"block/rate-limit page instead of real documents (check the DIAGNOSTIC "
              f"dumps above for the actual response content/status/content-type), not "
              f"that {total_parse_failures} individual documents are independently "
              f"malformed. Not writing insider.json - leaving the last known-good file "
              f"in place.")
        raise SystemExit(1)

    def sort_key(x):
        r = x.get("role")
        if is_ceo(r):
            return (0, -x.get("value", 0))
        if is_cfo(r):
            return (1, -x.get("value", 0))
        return (2, -x.get("value", 0))

    all_buys.sort(key=sort_key)
    all_sells.sort(key=sort_key)

    now = datetime.now(PST)
    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard" / "insider.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "updated": now.strftime("%b %d, %Y %I:%M %p PST"),
        "updated_iso": now.isoformat(),
        "source": "SEC EDGAR (direct)",
        "buys": all_buys,
        "sells": all_sells,
    }, indent=2))

    print(f"Done: {len(all_buys)} buys, {len(all_sells)} sells -> {out_path}")
    print(f"  (parse attempts: {total_parse_attempts}, failures: {total_parse_failures}, "
          f"failure rate: {parse_failure_rate:.0%})")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# NOTES / known limitations (read before relying on this in production)
# ---------------------------------------------------------------------------
# 1. Derivative transactions (options, RSUs, warrants) are not parsed - only
#    nonDerivativeTable. This matches the "open-market conviction buy/sell"
#    framing of the original pipeline, but means option-related insider
#    activity (which can also be informative) isn't captured. Adding
#    derivativeTable parsing would be a contained follow-up if useful.
#
# 2. Multi-owner filings (joint Form 4s covering more than one reporting
#    person) currently collapse into one "insider" string (names joined
#    with " / ") and take the LAST owner's role - SEC's XML doesn't map
#    individual transaction rows to a specific owner when a filing covers
#    multiple people, so this is a real ambiguity in the source data, not
#    just a shortcut in this script. Worth revisiting if joint filings turn
#    out to be common enough to matter.
#
# 3. NOT TESTED AGAINST LIVE SEC.GOV - see the top-of-file notice. Run
#    against a handful of tickers first (e.g. temporarily set
#    SP500_TICKERS = ["AAPL", "MSFT", "JPM"] for a smoke test) before a
#    full-universe run.
#
# 4. Request volume: ~503 submissions calls + one XML fetch per qualifying
#    Form 4 filing. At REQUEST_DELAY_SECONDS=0.15 that's a multi-minute
#    job, not a multi-second one - fine for a nightly batch, not something
#    to run interactively without expecting to wait.
#
# 5. CIK ticker-matching: SEC's bulk mapping file uses dot notation for
#    share classes (e.g. "BRK.B") while samuelstocks' tickers.py uses dash
#    notation ("BRK-B") - handled with a fallback lookup above, but worth
#    spot-checking dual-class tickers (BRK-B, BF-B, etc.) specifically in
#    the smoke test.
