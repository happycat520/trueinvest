# CrystalWell Daily Digest — Design Spec (v2)
### Now matched to the real samuelstocks data schema

This supersedes the v1 spec, which was built against a guessed schema. Everything
below reflects the actual `insider.json` / `key_dates.json` / `price_movement.json`
produced by github.com/tehochess/samuelstocks — the same files your live dashboards
already read.

## 1. Principle: conjunctions, not conclusions (unchanged)

The digest states facts, never judgments. "3 insiders bought after a 14% decline,"
never "this looks like an opportunity." See v1 rationale — nothing here changes that.

## 2. What the real data actually looks like

**`insider.json`** — `{"updated", "updated_iso", "buys": [...], "sells": [...]}`.
Buys and sells are separate lists (not one list with a `transaction_type` field). Buys
carry `shares`/`value`; sells carry `shares_sold`/`shares_remaining`/`value`. Both carry
`ticker`, `company`, `insider`, `role`, `date`, `filing_url`. **There is only one date
field** — sourced from Yahoo Finance's "Start Date" — not a separate transaction vs.
filing date. The digest describes this as "insider activity dated X," not "filed X,"
since the pipeline doesn't actually distinguish the two.

**`key_dates.json`** — `{"updated", "updated_iso", "hasUpcoming", "dividends": [...],
"earnings": [...]}`. Dividends carry `exDate`/`exStatus` (`upcoming`/`recent`/`suspended`/
`none`) — reliably populated. Earnings entries carry `earningsDate`, plus, unexpectedly,
`shortRatio`, `shortPct`, and `squeezeFlag` — short-interest data already sitting in this
file. **Important data-quality note:** in the snapshot copied for this build, `earningsDate`
was `"N/A"` for all 482 tickers — the underlying `yfinance` calendar lookup in
`fetch_key_dates.py` isn't currently returning real dates (see that script's `stock.calendar`
call). This means the "ahead of a catalyst" rules below are, right now, effectively "ahead
of a dividend ex-date" only — a much more routine/predictable event than an earnings date.
The code path for earnings is real and will activate automatically the moment that upstream
lookup starts working again; no digest-side change will be needed. Worth raising with
whoever maintains `fetch_key_dates.py` if catalyst-timing accuracy matters to you.

**`price_movement.json`** — `{"updated", "updated_iso", "downStreaks": [...],
"upStreaks": [...]}`. Each entry is a stock already flagged by the pipeline for 3
consecutive days of one-directional movement, with a precomputed `signal` object
(`name`, `strength`, `color`, `icon`, `reason`) plus `totalMove`, RSI, and volume context.
This is richer than assumed in v1 — membership in either list is already a filtered,
meaningful event, and the pipeline's own qualitative labels ("Breakdown," "Strong Peak,"
etc.) are reused directly in the digest rather than re-derived.

## 3. The four rules, redefined against real fields

| # | Label | Trigger (v2) | Change from v1 |
|---|---|---|---|
| 1 | **Cluster Buy Into a Decline** | 2+ distinct insiders bought in the trailing 7 days, AND the ticker appears in `downStreaks` | Was a `pct_change_10d` threshold; now keys off the pipeline's own 3-day streak detection and reuses its `signal.name`/`reason` |
| 2 | **Buying Ahead of a Catalyst** | Any insider buy in the trailing 7 days, AND an upcoming dividend ex-date (or, once fixed upstream, earnings date) falls within 10 days | Functionally: dividend-only for now, per the earnings data-quality note above |
| 3 | **Cluster Sell Ahead of a Catalyst** | 2+ distinct insiders sold in the trailing 7 days, AND an upcoming catalyst within 10 days | Same caveat as #2 |
| 4 | **Buying Into Strength** | Any insider buy in the trailing 7 days, AND the ticker appears in `upStreaks` | Same change as #1 |

## 4. What's always shown, even on a quiet day (unchanged principle, richer content)

1. **Cross-signal section** — same as v1.
2. **Latest Insider Activity** — now correctly reports the exact most-recent date present
   in the data (e.g. "dated 2026-08-13"), not the digest send date — insider data lags
   the other two sources by design (Form 4-style disclosure timing), and hiding that lag
   behind "today" would be misleading.
3. **Upcoming Key Dates (7 days)** — pulled from dividends' `exDate`/`exStatus`.
4. **Notable Price Streaks** *(new in v2)* — a short list of `downStreaks`/`upStreaks`
   entries where the pipeline's own `signal.strength >= 2` (the same threshold
   `samuelstocks/scripts/send_email.py` already uses for its "high-conviction" banner,
   reused here for consistency with your existing product). This uses real, already-computed
   pipeline output rather than adding new calculation logic.
5. **Per-source freshness footer** — each of the three sources reports its own
   `updated` timestamp, since they refresh at different times and (as seen above) can
   lag each other by days, not just hours.

## 5. Data the loader captures but doesn't yet use

`load_catalysts()` collects `shortRatio` / `shortPct` / `squeezeFlag` per ticker into
`short_interest_by_ticker`, since it's already present in `key_dates.json`'s earnings
list. It isn't wired into any rule yet — flagged here as a low-effort future addition
(a fifth rule, e.g. "Insider buy + squeeze flag," would need no new data source) rather
than something to build now, to keep this iteration scoped to "update the digest to use
the real data," not "add new rules."

## 6. Repo layout

```
trueinvest/
├── data/
│   ├── dashboard/
│   │   ├── insider.json          ← copied from samuelstocks/data/ (this delivery)
│   │   ├── key_dates.json        ← copied from samuelstocks/data/ (this delivery)
│   │   └── price_movement.json   ← copied from samuelstocks/data/ (this delivery)
│   └── digest/
│       └── digest_2026-08-17.{json,html,txt}   ← generator output, one run's worth
├── scripts/
│   └── digest/
│       ├── generate_digest.py
│       ├── DESIGN.md             (this file)
│       └── tests/
│           └── quiet_day/        ← synthetic empty-data fixtures, for testing the
│                                     zero-signal render path only (not real data)
└── .github/
    └── workflows/
        └── daily-digest.yml      ← scheduled run + digest archive commit;
                                     send step intentionally left as a TODO
```

**Refreshing `data/dashboard/*.json` going forward:** these three files need to be
re-copied from samuelstocks (or however that pipeline's output reaches this repo)
before each digest run — the workflow above assumes something upstream keeps them
current. If `trueinvest` doesn't already have its own job pulling this data, that's
a prerequisite step to add alongside the digest workflow, not something the digest
generator does itself.

## 7. Sending the email — reuse what already exists

`samuelstocks/scripts/send_email.py` already has a working Gmail SMTP send (via
`smtplib.SMTP_SSL`, credentials from `SENDER_GMAIL` / `SENDER_GMAIL_APP_PASS` environment
variables). That's a faster path to an actual send than evaluating a new ESP from
scratch — the workflow's commented-out send step assumes reusing that exact pattern,
with credentials moved into GitHub Actions Secrets rather than local environment
variables. Swap for a proper ESP later if you need unsubscribe management, deliverability
monitoring, or list growth at a scale Gmail SMTP won't comfortably handle.

## 8. Legal-adjacent copy notes (unchanged)

Rule labels stay pattern-named, not implication-named. Footer disclaimer unchanged.
Flag both for review alongside the broader securities-law consult before this reaches
real subscribers.
