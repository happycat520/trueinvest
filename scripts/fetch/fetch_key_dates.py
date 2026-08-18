import json, os, time
from datetime import datetime, timedelta, date
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard" / "key_dates.json"
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
from tickers import SP500_TICKERS, COMPANY_NAMES

PST   = ZoneInfo("America/Los_Angeles")
TODAY = date.today()

def safe_float(v):
    try:
        f = float(v)
        return 0.0 if pd.isna(f) else round(f, 4)
    except:
        return 0.0

def fetch_ticker(ticker):
    company = COMPANY_NAMES.get(ticker, ticker)
    dividend_row = None
    earnings_row = None

    try:
        stock = yf.Ticker(ticker)
        info  = stock.info

        # ── DIVIDEND ──────────────────────────────────────────────
        ex_ts     = info.get("exDividendDate")
        ex_str    = "N/A"
        ex_status = "none"

        if ex_ts:
            ex_date_obj = datetime.fromtimestamp(ex_ts).date()
            ex_str      = ex_date_obj.strftime("%Y-%m-%d")
            days_ago    = (TODAY - ex_date_obj).days

            if ex_date_obj >= TODAY:
                ex_status = "upcoming"
            elif days_ago <= 90:
                ex_status = "recent"
            elif days_ago > 365:
                ex_str    = "Suspended"
                ex_status = "suspended"
            else:
                ex_status = "recent"

        div_rate = safe_float(info.get("dividendRate", 0))
        price    = safe_float(info.get("currentPrice") or info.get("regularMarketPrice", 0))

        if div_rate > 0 and price > 0:
            div_yield_pct = round((div_rate / price) * 100, 2)
        else:
            div_yield_pct = 0.0

        if div_yield_pct > 15:
            div_yield_pct = 0.0

        dividend_row = {
            "ticker":        ticker,
            "company":       company,
            "exDate":        ex_str,
            "exStatus":      ex_status,
            "dividendRate":  round(div_rate, 2),
            "dividendYield": div_yield_pct,
            "price":         round(price, 2),
        }
        print("  " + ticker + ": ex=" + ex_str + " [" + ex_status + "] rate=$" + str(round(div_rate,2)) + " yield=" + str(div_yield_pct) + "%")

        # ── EARNINGS ──────────────────────────────────────────────
        short_ratio = safe_float(info.get("shortRatio", 0))
        short_pct   = safe_float(info.get("shortPercentOfFloat", 0))

        earn_str = "N/A"
        try:
            cal = stock.calendar
            # yfinance's Ticker.calendar now returns a plain dict (confirmed against the
            # installed yfinance source: Quote._fetch_calendar builds `self._calendar = dict()`,
            # with `{}` on failure). It has NOT returned a DataFrame for some time, so the old
            # `not cal.empty` guard below always raised AttributeError on a dict (dicts have no
            # .empty), which silently fell into the broad except clause and produced "N/A" for
            # every ticker regardless of whether Yahoo actually had a date. `if cal:` is the
            # correct truthiness check for both the failure case ({} is falsy) and the
            # populated case.
            if cal:
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                # ed is a list of datetime.date objects per yfinance's internal implementation,
                # not strings - pd.Timestamp() below handles date objects fine either way.
                candidates = ed if isinstance(ed, list) else ([ed] if ed else [])

                future_dates = []
                for c in candidates:
                    try:
                        d = pd.Timestamp(c).date()
                        if d >= TODAY:
                            future_dates.append(d)
                    except (ValueError, TypeError):
                        pass

                if future_dates:
                    future_dates.sort()
                    earn_str = str(future_dates[0])
        except (AttributeError, KeyError, TypeError) as e:
            # Narrowed from a bare `except Exception` so a future yfinance API change (this
            # API has broken/changed shape multiple times upstream) prints a visible per-ticker
            # warning instead of silently reverting every ticker to "N/A" again.
            print("  " + ticker + ": calendar err - " + str(e))

        squeeze_flag      = short_ratio >= 5.0
        short_pct_display = round(short_pct * 100, 1) if short_pct < 1 else round(short_pct, 1)

        earnings_row = {
            "ticker":       ticker,
            "company":      company,
            "earningsDate": earn_str,
            "shortRatio":   round(short_ratio, 1),
            "shortPct":     short_pct_display,
            "squeezeFlag":  squeeze_flag,
        }
        print("  " + ticker + ": earn=" + earn_str + " short_ratio=" + str(round(short_ratio,1)))

    except Exception as e:
        print("  " + ticker + ": ERROR - " + str(e))
        dividend_row = {"ticker": ticker, "company": company, "exDate": "N/A", "exStatus": "none", "dividendRate": 0, "dividendYield": 0, "price": 0}
        earnings_row = {"ticker": ticker, "company": company, "earningsDate": "N/A", "shortRatio": 0, "shortPct": 0, "squeezeFlag": False}

    return dividend_row, earnings_row


def main():
    dividends = []
    earnings  = []

    for ticker in SP500_TICKERS:
        d, e = fetch_ticker(ticker)
        if d: dividends.append(d)
        if e: earnings.append(e)
        time.sleep(0.5)

    def div_sort(x):
        status = x.get("exStatus", "none")
        ex     = x.get("exDate", "")
        if status == "upcoming":  return ("0", ex)
        if status == "recent":    return ("1", ex)
        if status == "suspended": return ("3", ex)
        return ("4", ex)
    dividends.sort(key=div_sort)

    has_upcoming = any(d.get("exStatus") == "upcoming" for d in dividends)
    earnings.sort(key=lambda x: -x["shortRatio"])

    now = datetime.now(PST)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "updated":     now.strftime("%b %d, %Y %I:%M %p PST"),
            "updated_iso": now.isoformat(),
            "hasUpcoming": has_upcoming,
            "dividends":   dividends,
            "earnings":    earnings,
        }, f, indent=2)

    upcoming_count = sum(1 for d in dividends if d.get("exStatus") == "upcoming")
    recent_count   = sum(1 for d in dividends if d.get("exStatus") == "recent")
    print("Done: " + str(upcoming_count) + " upcoming, " + str(recent_count) + " recent, " + str(len(earnings)) + " earnings rows")


if __name__ == "__main__":
    main()
