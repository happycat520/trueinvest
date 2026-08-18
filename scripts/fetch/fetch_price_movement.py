import json, os, time, math
from datetime import datetime, timedelta, date
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "dashboard" / "price_movement.json"
from zoneinfo import ZoneInfo
import yfinance as yf
import pandas as pd
import numpy as np
from tickers import SP500_TICKERS, COMPANY_NAMES

PST = ZoneInfo("America/Los_Angeles")

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas   = np.diff(closes)
    gains    = np.where(deltas > 0, deltas, 0.0)
    losses   = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)

def rsi_label(rsi):
    if rsi is None: return {"label": "N/A",     "level": "neutral"}
    if rsi < 30:    return {"label": str(rsi),   "level": "oversold"}
    if rsi > 70:    return {"label": str(rsi),   "level": "overbought"}
    if rsi < 45:    return {"label": str(rsi),   "level": "weak"}
    if rsi > 55:    return {"label": str(rsi),   "level": "strong"}
    return              {"label": str(rsi),       "level": "neutral"}

def classify_signal(all_down, all_up, vol_signal, rsi, vs_200d_pct):
    if all_down:
        rsi_oversold = rsi is not None and rsi < 30
        below_200d   = vs_200d_pct is not None and vs_200d_pct < -5
        if vol_signal == "heavy":
            return {"name": "Breakdown",      "strength": 3, "color": "red",   "icon": "🔴", "reason": "Down streak + heavy volume = institutional selling. Floor may be lower."}
        elif vol_signal == "light" and rsi_oversold and below_200d:
            return {"name": "Strong Bottom",  "strength": 3, "color": "green", "icon": "🟢", "reason": "Down streak + light volume + RSI oversold + below 200d MA. High-conviction reversal candidate."}
        elif vol_signal == "light" and rsi_oversold:
            return {"name": "Near Bottom",    "strength": 2, "color": "amber", "icon": "🟡", "reason": "Down streak + light volume + RSI oversold. Watch for reversal."}
        elif vol_signal == "light":
            return {"name": "Possible Bottom","strength": 1, "color": "amber", "icon": "⚠️", "reason": "Down streak + light volume. RSI not yet oversold — confirm before acting."}
        else:
            return {"name": "Downtrend",      "strength": 1, "color": "muted", "icon": "—",  "reason": "Down streak with normal volume. No reversal signal yet."}
    elif all_up:
        rsi_overbought = rsi is not None and rsi > 70
        above_200d     = vs_200d_pct is not None and vs_200d_pct > 10
        if vol_signal == "heavy" and rsi_overbought and above_200d:
            return {"name": "Strong Peak",  "strength": 3, "color": "red",   "icon": "🔴", "reason": "Up streak + heavy volume + RSI overbought + extended above 200d MA. High risk of reversal."}
        elif vol_signal == "heavy" and rsi_overbought:
            return {"name": "Near Peak",    "strength": 2, "color": "amber", "icon": "🟡", "reason": "Up streak + heavy volume + RSI overbought. Consider taking profits."}
        elif vol_signal == "heavy":
            return {"name": "Momentum",     "strength": 1, "color": "green", "icon": "📈", "reason": "Up streak + heavy volume. Strong buying interest — RSI not yet overbought."}
        elif vol_signal == "light":
            return {"name": "Weak Rally",   "strength": 1, "color": "muted", "icon": "—",  "reason": "Up streak on light volume. Low conviction — may stall or reverse."}
        else:
            return {"name": "Uptrend",      "strength": 1, "color": "muted", "icon": "—",  "reason": "Up streak with normal volume. No strong signal yet."}
    return {"name": "—", "strength": 0, "color": "muted", "icon": "—", "reason": ""}


def analyze_ticker(ticker):
    company = COMPANY_NAMES.get(ticker, ticker)
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period="1y")

        if hist is None or len(hist) < 20:
            print("  " + ticker + ": not enough data")
            return None

        closes    = hist["Close"].values
        volumes   = hist["Volume"].values
        dates_idx = hist.index

        rsi = compute_rsi(closes, period=14)

        if len(closes) >= 200:
            ma200 = round(float(np.mean(closes[-200:])), 2)
        else:
            ma200 = round(float(np.mean(closes)), 2)
        current_price = round(float(closes[-1]), 2)

        if math.isnan(current_price) or math.isnan(ma200):
            print("  " + ticker + ": price/ma200 is NaN (bad data from source), skipping")
            return None

        vs_200d_pct   = round(((current_price - ma200) / ma200) * 100, 1)

        avg_volume_20d = float(np.mean(volumes[-20:]))

        pct_changes  = pd.Series(closes).pct_change().values * 100
        last3_pcts   = pct_changes[-3:]
        last3_vols   = volumes[-3:]
        last3_dates  = [str(dates_idx[-3].date()), str(dates_idx[-2].date()), str(dates_idx[-1].date())]

        all_down = all(c < 0 for c in last3_pcts)
        all_up   = all(c > 0 for c in last3_pcts)

        latest_vol     = float(last3_vols[-1])
        vol_vs_avg_pct = round(((latest_vol - avg_volume_20d) / avg_volume_20d) * 100, 1)
        vol_signal     = "light" if vol_vs_avg_pct < -20 else ("heavy" if vol_vs_avg_pct > 20 else "normal")
        total_move_pct = round(float(sum(last3_pcts)), 2)

        signal = classify_signal(all_down, all_up, vol_signal, rsi, vs_200d_pct)

        result = {
            "ticker":       ticker,
            "company":      company,
            "price":        current_price,
            "ma200":        ma200,
            "vs200dPct":    vs_200d_pct,
            "rsi":          rsi,
            "rsiLabel":     rsi_label(rsi),
            "day1":         {"date": last3_dates[0], "pct": round(float(last3_pcts[0]), 2), "vol": int(last3_vols[0])},
            "day2":         {"date": last3_dates[1], "pct": round(float(last3_pcts[1]), 2), "vol": int(last3_vols[1])},
            "day3":         {"date": last3_dates[2], "pct": round(float(last3_pcts[2]), 2), "vol": int(last3_vols[2])},
            "totalMove":    total_move_pct,
            "volVsAvg":     vol_vs_avg_pct,
            "volSignal":    vol_signal,
            "avgVolume20d": int(avg_volume_20d),
            "allDown":      all_down,
            "allUp":        all_up,
            "signal":       signal,
        }

        direction = "DOWN" if all_down else ("UP" if all_up else "MIXED")
        print("  " + ticker + ": " + direction + " " + str(total_move_pct) + "% | RSI=" + str(rsi) + " | vs200d=" + str(vs_200d_pct) + "% | vol=" + vol_signal + " | signal=" + signal["name"])
        return result

    except Exception as e:
        print("  " + ticker + ": ERROR - " + str(e))
        return None


def main():
    all_results = []

    for ticker in SP500_TICKERS:
        r = analyze_ticker(ticker)
        if r:
            all_results.append(r)
        time.sleep(0.5)

    down_streaks = [r for r in all_results if r["allDown"]]
    up_streaks   = [r for r in all_results if r["allUp"]]

    down_streaks.sort(key=lambda x: (-x["signal"]["strength"], x["totalMove"]))
    up_streaks.sort(key=lambda x:   (-x["signal"]["strength"], -x["totalMove"]))

    now = datetime.now(PST)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "updated":     now.strftime("%b %d, %Y %I:%M %p PST"),
            "updated_iso": now.isoformat(),
            "downStreaks": down_streaks,
            "upStreaks":   up_streaks,
        }, f, indent=2, allow_nan=False)

    print("Done: " + str(len(down_streaks)) + " down streaks, " + str(len(up_streaks)) + " up streaks")


if __name__ == "__main__":
    main()
