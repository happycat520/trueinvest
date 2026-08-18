# CrystalWell Data Fetchers

Gives `trueinvest` its own ability to populate `data/dashboard/*.json` directly,
rather than depending on copying output from the separate `samuelstocks` repo.

## Data provenance (accurate, unlike samuelstocks' README/email footer)

| File | Fetcher | Actual source |
|---|---|---|
| `insider.json` | `fetch_insider_edgar.py` | **SEC EDGAR, direct.** Submissions API + raw Form 4 XML. No third-party vendor hop. |
| `key_dates.json` | `fetch_key_dates.py` | **Yahoo Finance (`yfinance`).** Dividend ex-dates + earnings calendar + short interest, all via `yf.Ticker(...).info` / `.calendar`. |
| `price_movement.json` | `fetch_price_movement.py` | **Yahoo Finance (`yfinance`).** 1-year daily OHLCV via `yf.Ticker(...).history(period="1y")`, with RSI/MA200/streak detection computed locally. |

`samuelstocks`' own README and email footer both label the insider data as
"SEC EDGAR Form 4," which isn't accurate for that repo — it's actually sourced
via `yfinance`, which Yahoo's own documentation attributes to a third-party
vendor (LSEG Data and Analytics / Refinitiv), not a direct EDGAR pull. This
repo's `fetch_insider_edgar.py` is what makes that label actually true here.

## Setup

```
pip install requests yfinance pandas numpy
```

Before running `fetch_insider_edgar.py` for real: **edit `USER_AGENT`** at the
top of the file. SEC requires a descriptive User-Agent identifying a real
contact and will throttle/reject generic ones.

## Running

```bash
cd scripts/fetch
python3 fetch_insider_edgar.py      # -> ../../data/dashboard/insider.json
python3 fetch_key_dates.py          # -> ../../data/dashboard/key_dates.json
python3 fetch_price_movement.py     # -> ../../data/dashboard/price_movement.json
```

Run all three before `scripts/digest/generate_digest.py`.

## Known limitations — read before trusting this in production

**`fetch_insider_edgar.py` has not been run against live SEC EDGAR.** This
build environment's network sandbox doesn't allow outbound requests to
`www.sec.gov` / `data.sec.gov`, so the XML-parsing logic was verified against
a hand-built mock matching the real ownership-document schema
(`scripts/fetch/tests/test_fetch_insider_edgar.py` — all passing), but a live
end-to-end run has not happened. **Before a full S&P 500 run, temporarily set
`SP500_TICKERS` to 2-3 known-active tickers (e.g. `["AAPL", "MSFT", "JPM"]`)
and manually sanity-check the output** — insider names, roles, share counts,
and dollar values against what you can see on EDGAR's own filing pages —
before trusting it at scale.

Other limitations documented inline in `fetch_insider_edgar.py`'s NOTES
section:
- Only open-market buys (code `P`) and sells (code `S`) are captured —
  option exercises, grants, gifts, and tax-withholding transactions are
  intentionally excluded, matching the "conviction trade" framing of the
  original pipeline, but derivative-security transactions (options, RSUs)
  aren't parsed at all yet.
- Joint filings covering multiple reporting owners collapse into one
  insider string and one role — a genuine ambiguity in the source XML, not
  just a shortcut here.
- `fetch_key_dates.py` has a real, separately-diagnosed data-quality issue:
  earnings dates from `yfinance`'s `.calendar` were returning `"N/A"` for
  every ticker due to a dict/DataFrame API mismatch in the original
  samuelstocks code — already fixed in the copy here, but worth confirming
  against a live run since it hasn't been tested live either (same network
  restriction as above).

## Rate limits

- SEC EDGAR: 10 requests/second max, enforced with a 0.15s delay between
  calls in `fetch_insider_edgar.py` (~6.7 req/sec, comfortable margin).
  Mandatory descriptive User-Agent header (see Setup above).
- Yahoo Finance via `yfinance`: no official documented limit, but both
  copied scripts keep the original 0.5s delay between tickers as a
  courtesy/stability measure.
