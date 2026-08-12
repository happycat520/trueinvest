# Dashboard data pipeline

The dashboard reads three static JSON files. There is no live API call from
the browser — `js/dashboard.js` just fetches whatever is currently sitting
in this folder. This is the same pipeline output used by the original
[samuelstocks](https://github.com/tehochess/samuelstocks) dashboard.

- `insider.json` — SEC EDGAR Form 4 filings (open-market insider buys/sells)
- `key_dates.json` — dividend ex-dates + upcoming earnings with short-interest
- `price_movement.json` — 3-day price streaks, RSI, 200-day MA, volume, signal

## How it's generated

A GitHub Actions workflow (`.github/workflows/nightly.yml` in the
samuelstocks repo) runs on weekday mornings and:

1. Runs `scripts/fetch_insider.py`, `scripts/fetch_key_dates.py`, and
   `scripts/fetch_price_movement.py` (Python + `yfinance`) over the ticker
   universe defined in `scripts/tickers.py` (currently the S&P 500 for
   insider/key-dates, with a DJIA subset also defined).
2. Writes the three JSON files above.
3. Commits them back to the repo.

To keep this site's dashboard current, copy the latest `insider.json`,
`key_dates.json`, and `price_movement.json` from that pipeline's output into
this folder (`data/dashboard/`), or point your own deploy step at the same
repo/workflow. No changes to `dashboard.html`, `dashboard.js`, or
`dashboard.css` are needed — they're built to match this schema exactly.

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
