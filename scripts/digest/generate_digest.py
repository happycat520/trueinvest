#!/usr/bin/env python3
"""
CrystalWell Daily Digest Generator (v2 - matched to real samuelstocks schema)
==============================================================================

Combines the three live dashboards - Insider Trading, Key Dates, Price Movement -
into a single daily email that flags cross-signal conjunctions. See DESIGN.md for
the full rationale (why this stays factual/conjunction-only rather than making
buy/sell judgments).

Reads directly from the JSON files produced by the samuelstocks pipeline
(github.com/tehochess/samuelstocks) - the same files your live dashboards read.
No guessed schema this time: adapters below are built against the actual field
names in insider.json / key_dates.json / price_movement.json.

USAGE
-----
    python generate_digest.py [--date YYYY-MM-DD] [--data-dir PATH] [--out-dir PATH]

Defaults assume this script lives at scripts/digest/generate_digest.py and reads
from ../../data/dashboard relative to itself (see repo layout in DESIGN.md).
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# The fetch scripts (fetch_insider_edgar.py, fetch_key_dates.py,
# fetch_price_movement.py) all timestamp their output in PST, since this
# is fundamentally a US-market pipeline. The digest should use the same
# clock for its default "today" - otherwise, on a GitHub Actions runner
# (which runs in UTC), a late-evening Pacific run could label the digest
# one calendar day ahead of the data it's actually summarizing.
PST = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RULES_CONFIG = {
    "cluster_min_insiders": 2,       # distinct insiders required for a "cluster"
    "lookback_days_insider": 7,      # trailing window for insider activity
    "catalyst_window_days": 10,      # upcoming key-date window considered "ahead of a catalyst"
    "min_streak_signal_strength": 2, # matches the samuelstocks convention (send_email.py) for a "notable" streak
}


# ---------------------------------------------------------------------------
# Common internal shapes (rules only ever see these - not raw JSON)
# ---------------------------------------------------------------------------

@dataclass
class InsiderEvent:
    ticker: str
    company: str
    insider_name: str
    role: str
    transaction_type: str    # "buy" or "sell" (derived from which list the record came from)
    value_usd: float
    event_date: date         # the pipeline's single "date" field - the only date available,
                              # sourced from Yahoo Finance's "Start Date"; not distinguished
                              # from a separate filing date, so digest copy describes it as
                              # "insider activity dated X", not "filed X"


@dataclass
class CatalystEvent:
    ticker: str
    company: str
    catalyst_type: str        # "dividend_ex_date" or "earnings"
    catalyst_date: date


@dataclass
class StreakEvent:
    ticker: str
    company: str
    direction: str             # "down" or "up"
    total_move_pct: float
    signal_name: str
    signal_strength: int
    signal_reason: str
    short_ratio: Optional[float] = None
    short_pct: Optional[float] = None
    squeeze_flag: Optional[bool] = None


@dataclass
class Signal:
    rule_id: str
    label: str
    ticker: str
    company: str
    facts: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Adapters - matched to the real samuelstocks JSON schema
# ---------------------------------------------------------------------------

def _parse_date_safe(value: str) -> Optional[date]:
    if not value or value in ("N/A", "Suspended"):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_insiders(path: Path) -> list:
    """insider.json shape: {"updated", "updated_iso", "buys": [...], "sells": [...]}
    buys carry "shares"/"value"; sells carry "shares_sold"/"shares_remaining"/"value".
    Both carry: ticker, company, insider, role, date, filing_url.
    """
    raw = json.loads(path.read_text())
    events = []
    for b in raw.get("buys", []):
        d = _parse_date_safe(b.get("date", ""))
        if d is None:
            continue
        events.append(InsiderEvent(
            ticker=b["ticker"].upper(),
            company=b.get("company", b["ticker"]),
            insider_name=b.get("insider", "Unknown insider"),
            role=b.get("role", ""),
            transaction_type="buy",
            value_usd=float(b.get("value", 0)),
            event_date=d,
        ))
    for s in raw.get("sells", []):
        d = _parse_date_safe(s.get("date", ""))
        if d is None:
            continue
        events.append(InsiderEvent(
            ticker=s["ticker"].upper(),
            company=s.get("company", s["ticker"]),
            insider_name=s.get("insider", "Unknown insider"),
            role=s.get("role", ""),
            transaction_type="sell",
            value_usd=float(s.get("value", 0)),
            event_date=d,
        ))
    return events, raw.get("updated_iso"), raw.get("updated")


def load_catalysts(path: Path) -> list:
    """key_dates.json shape: {"updated", "updated_iso", "hasUpcoming",
    "dividends": [{ticker, company, exDate, exStatus, dividendRate, dividendYield, price}],
    "earnings": [{ticker, company, earningsDate, shortRatio, shortPct, squeezeFlag}]}

    NOTE: earningsDate is frequently "N/A" in this pipeline (yfinance's earnings-calendar
    lookup is unreliable) - dividends' exDate/exStatus is the more consistently populated
    source of upcoming-catalyst dates. Both are checked; whichever is present is used.
    shortRatio/shortPct/squeezeFlag from the earnings list are carried through as
    supporting context (not currently used to trigger a rule - see DESIGN.md notes on
    a possible future Contrarian/Sentiment rule).
    """
    raw = json.loads(path.read_text())
    catalysts = []
    short_interest_by_ticker = {}

    for div in raw.get("dividends", []):
        if div.get("exStatus") != "upcoming":
            continue
        d = _parse_date_safe(div.get("exDate", ""))
        if d is None:
            continue
        catalysts.append(CatalystEvent(
            ticker=div["ticker"].upper(),
            company=div.get("company", div["ticker"]),
            catalyst_type="dividend_ex_date",
            catalyst_date=d,
        ))

    for earn in raw.get("earnings", []):
        short_interest_by_ticker[earn["ticker"].upper()] = {
            "short_ratio": earn.get("shortRatio"),
            "short_pct": earn.get("shortPct"),
            "squeeze_flag": earn.get("squeezeFlag"),
        }
        d = _parse_date_safe(earn.get("earningsDate", ""))
        if d is None:
            continue
        catalysts.append(CatalystEvent(
            ticker=earn["ticker"].upper(),
            company=earn.get("company", earn["ticker"]),
            catalyst_type="earnings",
            catalyst_date=d,
        ))

    return catalysts, short_interest_by_ticker, raw.get("updated_iso"), raw.get("updated")


def load_streaks(path: Path) -> list:
    """price_movement.json shape: {"updated", "updated_iso",
    "downStreaks": [...], "upStreaks": [...]} - each entry is a 3-consecutive-day
    price streak with a precomputed "signal" object (name/strength/color/icon/reason).
    Membership in either list already means the pipeline flagged 3 straight days of
    one-directional movement; totalMove/signal fields add texture on top of that.
    """
    raw = json.loads(path.read_text())
    events = []
    for s in raw.get("downStreaks", []):
        sig = s.get("signal", {})
        events.append(StreakEvent(
            ticker=s["ticker"].upper(),
            company=s.get("company", s["ticker"]),
            direction="down",
            total_move_pct=float(s.get("totalMove", 0)),
            signal_name=sig.get("name", ""),
            signal_strength=int(sig.get("strength", 0)),
            signal_reason=sig.get("reason", ""),
        ))
    for s in raw.get("upStreaks", []):
        sig = s.get("signal", {})
        events.append(StreakEvent(
            ticker=s["ticker"].upper(),
            company=s.get("company", s["ticker"]),
            direction="up",
            total_move_pct=float(s.get("totalMove", 0)),
            signal_name=sig.get("name", ""),
            signal_strength=int(sig.get("strength", 0)),
            signal_reason=sig.get("reason", ""),
        ))
    return events, raw.get("updated_iso"), raw.get("updated")


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------

def group_by_ticker(events: list) -> dict:
    grouped = {}
    for e in events:
        grouped.setdefault(e.ticker, []).append(e)
    return grouped


def money(value: float) -> str:
    return f"${value:,.0f}"


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def run_rules(digest_date: date, insiders: list, catalysts: list, streaks: list) -> list:
    cfg = RULES_CONFIG
    insiders_by_ticker = group_by_ticker(insiders)
    catalysts_by_ticker = group_by_ticker(catalysts)
    streaks_by_ticker = group_by_ticker(streaks)

    lookback_start = digest_date - timedelta(days=cfg["lookback_days_insider"])
    catalyst_end = digest_date + timedelta(days=cfg["catalyst_window_days"])

    signals = []

    for ticker, events in insiders_by_ticker.items():
        recent = [e for e in events if lookback_start <= e.event_date <= digest_date]
        recent_buys = [e for e in recent if e.transaction_type == "buy"]
        recent_sells = [e for e in recent if e.transaction_type == "sell"]
        distinct_buyers = {e.insider_name for e in recent_buys}
        distinct_sellers = {e.insider_name for e in recent_sells}
        company = events[0].company

        ticker_streaks = streaks_by_ticker.get(ticker, [])
        down_streak = next((s for s in ticker_streaks if s.direction == "down"), None)
        up_streak = next((s for s in ticker_streaks if s.direction == "up"), None)

        upcoming = [
            c for c in catalysts_by_ticker.get(ticker, [])
            if digest_date <= c.catalyst_date <= catalyst_end
        ]

        # Rule 1: Cluster Buy Into a Decline
        if len(distinct_buyers) >= cfg["cluster_min_insiders"] and down_streak is not None:
            total_value = sum(e.value_usd for e in recent_buys)
            signals.append(Signal(
                rule_id="cluster_buy_into_decline",
                label="Cluster Buy Into a Decline",
                ticker=ticker,
                company=company,
                facts=[
                    f"{len(distinct_buyers)} distinct insiders bought in the trailing "
                    f"{cfg['lookback_days_insider']} days ({money(total_value)} combined)",
                    f"3-day price streak: {down_streak.total_move_pct:+.2f}% "
                    f"({down_streak.signal_name}: {down_streak.signal_reason})",
                ],
            ))

        # Rule 2: Buying Ahead of a Catalyst
        if recent_buys and upcoming:
            next_cat = min(upcoming, key=lambda c: c.catalyst_date)
            total_value = sum(e.value_usd for e in recent_buys)
            signals.append(Signal(
                rule_id="buying_ahead_of_catalyst",
                label="Buying Ahead of a Catalyst",
                ticker=ticker,
                company=company,
                facts=[
                    f"{len(recent_buys)} insider buy(s) in the trailing "
                    f"{cfg['lookback_days_insider']} days ({money(total_value)} combined)",
                    f"{next_cat.catalyst_type.replace('_', ' ').title()} scheduled "
                    f"{next_cat.catalyst_date.isoformat()} "
                    f"({(next_cat.catalyst_date - digest_date).days} days out)",
                ],
            ))

        # Rule 3: Cluster Sell Ahead of a Catalyst
        if len(distinct_sellers) >= cfg["cluster_min_insiders"] and upcoming:
            next_cat = min(upcoming, key=lambda c: c.catalyst_date)
            total_value = sum(e.value_usd for e in recent_sells)
            signals.append(Signal(
                rule_id="cluster_sell_ahead_of_catalyst",
                label="Cluster Sell Ahead of a Catalyst",
                ticker=ticker,
                company=company,
                facts=[
                    f"{len(distinct_sellers)} distinct insiders sold in the trailing "
                    f"{cfg['lookback_days_insider']} days ({money(total_value)} combined)",
                    f"{next_cat.catalyst_type.replace('_', ' ').title()} scheduled "
                    f"{next_cat.catalyst_date.isoformat()} "
                    f"({(next_cat.catalyst_date - digest_date).days} days out)",
                ],
            ))

        # Rule 4: Buying Into Strength
        if recent_buys and up_streak is not None:
            total_value = sum(e.value_usd for e in recent_buys)
            signals.append(Signal(
                rule_id="buying_into_strength",
                label="Buying Into Strength",
                ticker=ticker,
                company=company,
                facts=[
                    f"{len(recent_buys)} insider buy(s) in the trailing "
                    f"{cfg['lookback_days_insider']} days ({money(total_value)} combined)",
                    f"3-day price streak: {up_streak.total_move_pct:+.2f}% "
                    f"({up_streak.signal_name}: {up_streak.signal_reason})",
                ],
            ))

    signals.sort(key=lambda s: (s.ticker, s.label))
    return signals


# ---------------------------------------------------------------------------
# "Latest activity" summary - shown even when zero rules fire
# ---------------------------------------------------------------------------

def build_raw_summary(digest_date: date, insiders: list, catalysts: list, streaks: list) -> dict:
    event_dates_available = [e.event_date for e in insiders if e.event_date <= digest_date]
    latest_event_date = max(event_dates_available) if event_dates_available else None
    latest_events = [e for e in insiders if e.event_date == latest_event_date] if latest_event_date else []

    largest = max(latest_events, key=lambda e: e.value_usd, default=None)

    week_end = digest_date + timedelta(days=7)
    upcoming_this_week = sorted(
        [c for c in catalysts if digest_date <= c.catalyst_date <= week_end],
        key=lambda c: c.catalyst_date,
    )

    notable_streaks = sorted(
        [s for s in streaks if s.signal_strength >= RULES_CONFIG["min_streak_signal_strength"]],
        key=lambda s: -s.signal_strength,
    )

    return {
        "latest_event_date": latest_event_date,
        "total_events_on_latest_date": len(latest_events),
        "largest_transaction": largest,
        "upcoming_this_week": upcoming_this_week,
        "notable_streaks": notable_streaks[:8],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "CrystalWell Analytics delivers signals derived from public SEC filings and market "
    "data. This email is informational only and is not investment advice or a "
    "recommendation to buy or sell any security."
)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CrystalWell Daily Digest — {digest_date}</title>
<style>
  :root {{
    --cw-navy: #0b1e3d;
    --cw-navy-deep: #071229;
    --cw-ink: #1c2536;
    --cw-ink-faint: #646c85;
    --cw-accent: #4f8cff;
    --cw-border: #e2e6ee;
    --cw-bg: #f5f7fb;
    --font-display: "Source Serif 4", Georgia, "Times New Roman", serif;
    --font-body: "Inter", -apple-system, Helvetica, Arial, sans-serif;
    --font-mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
  }}
  body {{ margin:0; padding:0; background:var(--cw-bg); font-family:var(--font-body); color:var(--cw-ink); }}
  .wrap {{ max-width:600px; margin:0 auto; background:#ffffff; }}
  .header {{ padding:28px 32px; background:linear-gradient(135deg, var(--cw-navy), var(--cw-navy-deep)); }}
  .header .brand {{ font-family:var(--font-display); font-size:20px; color:#ffffff; letter-spacing:0.02em; }}
  .header .date {{ font-family:var(--font-mono); font-size:12px; color:#b9c6e6; margin-top:4px; }}
  .section {{ padding:24px 32px; border-bottom:1px solid var(--cw-border); }}
  .section-title {{ font-family:var(--font-display); font-size:17px; margin:0 0 4px 0; color:var(--cw-navy); }}
  .section-subtitle {{ font-size:11px; color:var(--cw-ink-faint); margin:0 0 14px 0; font-family:var(--font-mono); }}
  .signal {{ border:1px solid var(--cw-border); border-radius:8px; padding:16px; margin-bottom:12px; }}
  .signal .ticker {{ font-family:var(--font-mono); font-weight:600; font-size:14px; color:var(--cw-navy); }}
  .signal .rule-label {{ display:inline-block; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; color:var(--cw-accent); margin-left:8px; }}
  .signal .company {{ font-size:13px; color:var(--cw-ink-faint); margin:2px 0 8px 0; }}
  .signal ul {{ margin:0; padding-left:18px; font-size:13px; line-height:1.55; }}
  .empty-state {{ font-size:13px; color:var(--cw-ink-faint); font-style:italic; }}
  .summary-line {{ font-size:13px; line-height:1.6; }}
  .summary-line .mono {{ font-family:var(--font-mono); }}
  .streak-row {{ font-size:13px; padding:6px 0; border-bottom:1px solid var(--cw-border); }}
  .streak-row .ticker {{ font-family:var(--font-mono); font-weight:600; color:var(--cw-navy); }}
  .dates-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .dates-table th {{ text-align:left; font-family:var(--font-mono); font-size:10.5px; text-transform:uppercase; letter-spacing:0.04em; color:var(--cw-ink-faint); padding:0 10px 8px 0; border-bottom:1px solid var(--cw-border); }}
  .dates-table td {{ padding:7px 10px 7px 0; border-bottom:1px solid var(--cw-border); }}
  .dates-table tr:last-child td {{ border-bottom:none; }}
  .dates-table .ticker {{ font-family:var(--font-mono); font-weight:600; color:var(--cw-navy); }}
  .dates-table .mono {{ font-family:var(--font-mono); }}
  .footer {{ padding:20px 32px; font-size:11px; color:var(--cw-ink-faint); line-height:1.6; }}
  .footer a {{ color:var(--cw-ink-faint); }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="brand">CrystalWell Analytics</div>
      <div class="date">Daily Digest — {digest_date_pretty}</div>
    </div>

    <div class="section">
      <p class="section-title">Cross-Signal Combinations</p>
      <p class="section-subtitle">Insider Trading × Key Dates × Price Movement</p>
      {signals_html}
    </div>

    <div class="section">
      <p class="section-title">Latest Insider Activity</p>
      <p class="summary-line">{events_line}</p>
      <p class="summary-line">{largest_line}</p>
    </div>

    <div class="section">
      <p class="section-title">Upcoming Key Dates (7 days)</p>
      {upcoming_html}
    </div>

    <div class="section">
      <p class="section-title">Notable Price Streaks</p>
      <p class="section-subtitle">Strength ≥ {min_strength} out of the pipeline's own signal scale</p>
      {streaks_html}
    </div>

    <div class="footer">
      Data as of — Insider: {insider_updated} · Key Dates: {keydates_updated} · Price Movement: {pricemove_updated}<br><br>
      {disclaimer}<br><br>
      <a href="https://crystalwellanalytics.com/dashboard.html">View full dashboards</a>
      &nbsp;·&nbsp;
      <a href="https://crystalwellanalytics.com/unsubscribe">Unsubscribe</a>
    </div>
  </div>
</body>
</html>
"""

SIGNAL_HTML = """<div class="signal">
  <span class="ticker">{ticker}</span><span class="rule-label">{label}</span>
  <div class="company">{company}</div>
  <ul>{fact_items}</ul>
</div>
"""

STREAK_ROW_HTML = """<div class="streak-row">
  <span class="ticker">{ticker}</span> — {company}: {direction_arrow} {total_move:+.2f}% ({signal_name})
</div>
"""


def render_html(digest_date: date, signals: list, summary: dict, freshness: dict) -> str:
    if signals:
        signals_html = "\n".join(
            SIGNAL_HTML.format(
                ticker=s.ticker, label=s.label, company=s.company,
                fact_items="".join(f"<li>{fact}</li>" for fact in s.facts),
            )
            for s in signals
        )
    else:
        signals_html = '<p class="empty-state">No cross-signal combinations today.</p>'

    if summary["latest_event_date"] is not None:
        events_line = (
            f"<span class='mono'>{summary['total_events_on_latest_date']}</span> insider "
            f"transaction(s) dated <span class='mono'>{summary['latest_event_date'].isoformat()}</span> "
            f"(most recent available in the data)."
        )
    else:
        events_line = "No insider activity available in the current data window."

    if summary["largest_transaction"]:
        t = summary["largest_transaction"]
        largest_line = (
            f"Largest: <span class='mono'>{t.ticker}</span> — {t.insider_name} ({t.role}), "
            f"{t.transaction_type} {money(t.value_usd)}."
        )
    else:
        largest_line = ""

    if summary["upcoming_this_week"]:
        rows = "\n".join(
            f'<tr><td class="ticker">{c.ticker}</td><td>{c.company}</td>'
            f'<td>{c.catalyst_type.replace("_", " ").title()}</td>'
            f'<td class="mono">{c.catalyst_date.isoformat()}</td></tr>'
            for c in summary["upcoming_this_week"][:10]
        )
        upcoming_html = (
            '<table class="dates-table" cellpadding="0" cellspacing="0">'
            '<tr><th>Ticker</th><th>Company</th><th>Event</th><th>Date</th></tr>'
            f"{rows}"
            "</table>"
        )
    else:
        upcoming_html = '<p class="empty-state">No key dates scheduled in the next 7 days.</p>'

    if summary["notable_streaks"]:
        streaks_html = "\n".join(
            STREAK_ROW_HTML.format(
                ticker=s.ticker, company=s.company,
                direction_arrow="▲" if s.direction == "up" else "▼",
                total_move=s.total_move_pct, signal_name=s.signal_name,
            )
            for s in summary["notable_streaks"]
        )
    else:
        streaks_html = '<p class="empty-state">No high-conviction price streaks today.</p>'

    return HTML_TEMPLATE.format(
        digest_date=digest_date.isoformat(),
        digest_date_pretty=digest_date.strftime("%A, %B %d, %Y"),
        signals_html=signals_html,
        events_line=events_line,
        largest_line=largest_line,
        upcoming_html=upcoming_html,
        streaks_html=streaks_html,
        min_strength=RULES_CONFIG["min_streak_signal_strength"],
        insider_updated=freshness.get("insider", "—"),
        keydates_updated=freshness.get("key_dates", "—"),
        pricemove_updated=freshness.get("price_movement", "—"),
        disclaimer=DISCLAIMER,
    )


def render_text(digest_date: date, signals: list, summary: dict, freshness: dict) -> str:
    lines = [
        "CRYSTALWELL ANALYTICS — DAILY DIGEST",
        digest_date.strftime("%A, %B %d, %Y"),
        "",
        "CROSS-SIGNAL COMBINATIONS",
        "-" * 40,
    ]
    if signals:
        for s in signals:
            lines.append(f"{s.ticker} — {s.label} ({s.company})")
            for fact in s.facts:
                lines.append(f"  - {fact}")
            lines.append("")
    else:
        lines += ["No cross-signal combinations today.", ""]

    lines += ["LATEST INSIDER ACTIVITY", "-" * 40]
    if summary["latest_event_date"] is not None:
        lines.append(
            f"{summary['total_events_on_latest_date']} insider transaction(s) dated "
            f"{summary['latest_event_date'].isoformat()} (most recent available in the data)."
        )
        if summary["largest_transaction"]:
            t = summary["largest_transaction"]
            lines.append(f"Largest: {t.ticker} — {t.insider_name} ({t.role}), {t.transaction_type} {money(t.value_usd)}.")
    else:
        lines.append("No insider activity available in the current data window.")

    lines += ["", "UPCOMING KEY DATES (7 DAYS)", "-" * 40]
    if summary["upcoming_this_week"]:
        for c in summary["upcoming_this_week"][:10]:
            lines.append(f"{c.ticker} {c.catalyst_type.replace('_', ' ')} on {c.catalyst_date.isoformat()}")
    else:
        lines.append("No key dates scheduled in the next 7 days.")

    lines += ["", "NOTABLE PRICE STREAKS", "-" * 40]
    if summary["notable_streaks"]:
        for s in summary["notable_streaks"]:
            arrow = "UP" if s.direction == "up" else "DOWN"
            lines.append(f"{s.ticker} — {s.company}: {arrow} {s.total_move_pct:+.2f}% ({s.signal_name})")
    else:
        lines.append("No high-conviction price streaks today.")

    lines += [
        "", "-" * 40,
        f"Data as of — Insider: {freshness.get('insider', '—')} · "
        f"Key Dates: {freshness.get('key_dates', '—')} · "
        f"Price Movement: {freshness.get('price_movement', '—')}",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def signal_to_dict(s: Signal) -> dict:
    return {"rule_id": s.rule_id, "label": s.label, "ticker": s.ticker, "company": s.company, "facts": s.facts}


def main():
    parser = argparse.ArgumentParser(description="Generate the CrystalWell daily digest.")
    default_data_dir = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard"
    default_out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "digest"
    parser.add_argument("--date", default=None, help="Digest date, YYYY-MM-DD (default: today, PST)")
    parser.add_argument("--data-dir", default=str(default_data_dir), help="Directory with insider.json / key_dates.json / price_movement.json")
    parser.add_argument("--out-dir", default=str(default_out_dir), help="Directory to write digest_<date>.{json,html,txt}")
    args = parser.parse_args()

    digest_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(PST).date()
    )
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    insiders, insider_updated_iso, insider_updated = load_insiders(data_dir / "insider.json")
    catalysts, short_interest, kd_updated_iso, kd_updated = load_catalysts(data_dir / "key_dates.json")
    streaks, pm_updated_iso, pm_updated = load_streaks(data_dir / "price_movement.json")

    freshness = {"insider": insider_updated, "key_dates": kd_updated, "price_movement": pm_updated}

    signals = run_rules(digest_date, insiders, catalysts, streaks)
    summary = build_raw_summary(digest_date, insiders, catalysts, streaks)

    html = render_html(digest_date, signals, summary, freshness)
    text = render_text(digest_date, signals, summary, freshness)

    summary_json = {
        "latest_event_date": summary["latest_event_date"].isoformat() if summary["latest_event_date"] else None,
        "total_events_on_latest_date": summary["total_events_on_latest_date"],
        "largest_transaction": (
            {
                "ticker": summary["largest_transaction"].ticker,
                "insider_name": summary["largest_transaction"].insider_name,
                "role": summary["largest_transaction"].role,
                "transaction_type": summary["largest_transaction"].transaction_type,
                "value_usd": summary["largest_transaction"].value_usd,
            } if summary["largest_transaction"] else None
        ),
        "upcoming_this_week": [
            {"ticker": c.ticker, "catalyst_type": c.catalyst_type, "catalyst_date": c.catalyst_date.isoformat()}
            for c in summary["upcoming_this_week"]
        ],
        "notable_streaks": [
            {
                "ticker": s.ticker, "direction": s.direction, "total_move_pct": s.total_move_pct,
                "signal_name": s.signal_name, "signal_strength": s.signal_strength,
            }
            for s in summary["notable_streaks"]
        ],
    }

    payload = {
        "digest_date": digest_date.isoformat(),
        "data_freshness": freshness,
        "signal_count": len(signals),
        "signals": [signal_to_dict(s) for s in signals],
        "summary": summary_json,
    }

    (out_dir / f"digest_{digest_date.isoformat()}.json").write_text(json.dumps(payload, indent=2))
    (out_dir / f"digest_{digest_date.isoformat()}.html").write_text(html)
    (out_dir / f"digest_{digest_date.isoformat()}.txt").write_text(text)

    print(f"Wrote digest for {digest_date.isoformat()} to {out_dir}")
    print(f"  Signals flagged: {len(signals)}")
    for s in signals:
        print(f"    - {s.ticker}: {s.label}")


if __name__ == "__main__":
    main()
