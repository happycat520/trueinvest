# Dashboard data pipeline

The dashboard reads three static JSON files. There is no live API call from
the browser — `js/dashboard.js` just fetches whatever is currently sitting
in this folder.

This pipeline is self-contained within this repo — it fetches directly from
SEC EDGAR and Yahoo Finance rather than depending on an external repo. See
"How it's generated" below.

- `insider.json` — SEC EDGAR Form 4 filings (open-market insider buys/sells)
- `key_dates.json` — dividend ex-dates + upcoming earnings with short-interest
- `price_movement.json` — 3-day price streaks, RSI, 200-day MA, volume, signal

## How it's generated

`.github/workflows/fetch-and-digest.yml` runs on a schedule (13:00 UTC,
Monday–Friday) and:

1. Runs three fetch scripts in `scripts/fetch/`, over the ticker universe
   defined in `scripts/fetch/tickers.py` (DJIA + S&P 500, ~482 tickers,
   single source of truth — edit only that file to add/remove tickers):
   - `fetch_insider_edgar.py` — **SEC EDGAR submissions API + raw Form 4
     XML, directly** (stdlib only, no third-party data vendor in the loop).
     This replaced an earlier version of this pipeline that sourced insider
     data from yfinance/LSEG while labeling it "SEC EDGAR" — that mislabel
     is fixed; the data now genuinely comes from EDGAR.
   - `fetch_key_dates.py` — Yahoo Finance (`yfinance`), for dividend ex-dates
     and upcoming earnings/short-interest.
   - `fetch_price_movement.py` — Yahoo Finance (`yfinance`), for price
     streaks, RSI, 200-day MA, and volume.
2. Writes the three JSON files above into this folder.
3. Runs `scripts/digest/generate_digest.py` to build the daily digest email
   from the same freshly-fetched data.
4. Commits `data/dashboard/`, `data/digest/`, and `data/cache/` back to the
   repo.

The actual digest **send** step is intentionally commented out in the
workflow pending the securities-law consult — see
`scripts/digest/DESIGN.md` section 7. Fetching, JSON generation, and the
dashboard itself are unaffected by that; only the outbound email is paused.

To run it manually (e.g. to test), use the workflow's `workflow_dispatch`
trigger from the Actions tab, or run the three fetch scripts + digest
generator locally with `pip install requests yfinance pandas numpy`.

No changes to `dashboard.html`, `dashboard.js`, or `dashboard.css` are
needed to keep this current — they're built to match the schema below
exactly, and the workflow keeps that schema stable.

## Shape reference

**`insider.json`**
```
{
  "updated": "Aug 12, 2026 01:26 AM PST",
  "updated_iso": "...",
  "buys":  [{ ticker, company, insider, role, date, filing_url, shares, value }],
  "sells": [{ ticker, company, insider, role, date, filing_url, shares_sold, shares_remaining, expiry, value }]
}
```

**`key_dates.json`**
```
{
  "updated": "...", "updated_iso": "...", "hasUpcoming": true,
  "dividends": [{ ticker, company, exDate, exStatus, dividendRate, dividendYield, price }],
  "earnings":  [{ ticker, company, earningsDate, shortRatio, shortPct, squeezeFlag }]
}
```

**`price_movement.json`**
```
{
  "updated": "...", "updated_iso": "...",
  "downStreaks": [ ...see below... ],
  "upStreaks":   [ ...see below... ],
  "allStocks":   [ ...same shape, not currently rendered on this page... ]
}
```
Each streak row:
```
{
  ticker, company, price, ma200, vs200dPct, rsi,
  rsiLabel: { label, level },              // level: oversold | overbought | weak | strong | neutral
  day1/day2/day3: { date, pct, vol },
  totalMove, volVsAvg, volSignal,          // volSignal: light | heavy | normal
  avgVolume20d, allDown, allUp,
  signal: { name, strength, color, icon, reason }   // color: red | amber | green | muted
}
```
