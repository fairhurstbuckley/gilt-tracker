"""
UK 30-Year Gilt Yield Tracker
Fetches data from the Bank of England Statistical Interactive Database
and generates an interactive HTML dashboard with a Last Twelve Months view.
"""

import requests
import csv
import io
import os
import sys
import webbrowser
import json
import base64
from datetime import datetime, timedelta
from pathlib import Path


SERIES_CODE = "IUDMNZC"
BOE_API_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
OUTPUT_DIR = Path(__file__).parent
DASHBOARD_FILE = OUTPUT_DIR / "index.html"
DATA_FILE = OUTPUT_DIR / "gilt_data.json"
LOGO_FILE = OUTPUT_DIR.parent / "Branding" / "Fairhurst-Buckley-logo-COLOUR.jpg"

# CNBC quote API for live benchmark 30-year gilt bond yield (matches FT figure)
CNBC_API_URL = (
    "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
    "?symbols=GB30Y-GB&requestMethod=itv&no498=1&partnerId=2"
    "&fund=1&exthrs=1&output=json&events=1"
)

# Typical lending margin over gilts for UK commercial property (bps)
PROPERTY_LENDING_SPREAD_BPS = 175


def fetch_gilt_data():
    """Fetch 30-year gilt yield data from Bank of England API for the last 12 months."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=366)

    date_from = start_date.strftime("%d/%b/%Y")
    date_to = end_date.strftime("%d/%b/%Y")

    params = {
        "csv.x": "yes",
        "Datefrom": date_from,
        "Dateto": date_to,
        "SeriesCodes": SERIES_CODE,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    print(f"Fetching gilt data from {date_from} to {date_to}...")
    response = requests.get(BOE_API_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    return parse_boe_csv(response.text)


def parse_boe_csv(csv_text):
    """Parse the Bank of England CSV response into a list of {date, yield} dicts."""
    data_points = []
    reader = csv.reader(io.StringIO(csv_text))

    header_found = False
    date_col = None
    yield_col = None

    for row in reader:
        if not row or all(cell.strip() == "" for cell in row):
            continue

        # Find the header row containing "DATE" and the series code
        if not header_found:
            upper_row = [cell.strip().upper() for cell in row]
            if "DATE" in upper_row:
                date_col = upper_row.index("DATE")
                for i, cell in enumerate(upper_row):
                    if SERIES_CODE in cell:
                        yield_col = i
                        break
                if yield_col is not None:
                    header_found = True
                continue

        if not header_found:
            continue

        # Parse data rows
        try:
            date_str = row[date_col].strip()
            yield_str = row[yield_col].strip()
            if not date_str or not yield_str:
                continue

            date_obj = parse_boe_date(date_str)
            yield_val = float(yield_str)
            data_points.append({
                "date": date_obj.strftime("%Y-%m-%d"),
                "yield": round(yield_val, 4),
            })
        except (ValueError, IndexError):
            continue

    data_points.sort(key=lambda x: x["date"])
    print(f"Parsed {len(data_points)} data points.")
    return data_points


def parse_boe_date(date_str):
    """Parse a BoE date string, trying multiple formats."""
    formats = ["%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


def compute_stats(data_points):
    """Compute summary statistics from the data."""
    if not data_points:
        return {}

    yields = [d["yield"] for d in data_points]
    current = data_points[-1]
    previous = data_points[-2] if len(data_points) >= 2 else data_points[-1]

    # Find 1-week-ago and 1-month-ago values
    current_date = datetime.strptime(current["date"], "%Y-%m-%d")
    week_ago_target = current_date - timedelta(days=7)
    month_ago_target = current_date - timedelta(days=30)
    year_start = datetime(current_date.year, 1, 1)

    week_ago_val = find_nearest_value(data_points, week_ago_target)
    month_ago_val = find_nearest_value(data_points, month_ago_target)
    ytd_start_val = find_nearest_value(data_points, year_start)

    return {
        "current_yield": current["yield"],
        "current_date": current["date"],
        "previous_yield": previous["yield"],
        "daily_change": round(current["yield"] - previous["yield"], 4),
        "high_12m": round(max(yields), 4),
        "low_12m": round(min(yields), 4),
        "high_date": data_points[yields.index(max(yields))]["date"],
        "low_date": data_points[yields.index(min(yields))]["date"],
        "week_change": round(current["yield"] - week_ago_val, 4) if week_ago_val else None,
        "month_change": round(current["yield"] - month_ago_val, 4) if month_ago_val else None,
        "ytd_change": round(current["yield"] - ytd_start_val, 4) if ytd_start_val else None,
        "data_points_count": len(data_points),
    }


def find_nearest_value(data_points, target_date):
    """Find the yield value nearest to a target date."""
    target_str = target_date.strftime("%Y-%m-%d")
    best = None
    best_diff = None
    for d in data_points:
        diff = abs((datetime.strptime(d["date"], "%Y-%m-%d") - target_date).days)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = d["yield"]
    return best


def save_data(data_points, stats):
    """Save data and stats to JSON for reference."""
    output = {
        "last_updated": datetime.now().isoformat(),
        "series": SERIES_CODE,
        "stats": stats,
        "data": data_points,
    }
    with open(DATA_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Data saved to {DATA_FILE}")


def load_logo_base64():
    """Load the Fairhurst Buckley logo and return as a base64 data URI."""
    try:
        with open(LOGO_FILE, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except FileNotFoundError:
        print(f"Warning: Logo not found at {LOGO_FILE}")
        return ""


def fetch_live_gilt_yield():
    """Fetch live 30-year gilt benchmark bond yield from CNBC (matches FT figure)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        response = requests.get(CNBC_API_URL, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Navigate to the quote data
        quote = data.get("FormattedQuoteResult", {}).get("FormattedQuote", [{}])[0]
        if not quote or not quote.get("last"):
            print("Warning: CNBC API returned no quote data.")
            return None

        def parse_pct(val):
            """Parse a percentage string like '5.129%' to float."""
            if not val:
                return None
            return float(val.replace("%", "").strip())

        live = {
            "yield": parse_pct(quote.get("last")),
            "previous_close": parse_pct(quote.get("previous_day_closing")),
            "open": parse_pct(quote.get("open")),
            "high": parse_pct(quote.get("high")),
            "low": parse_pct(quote.get("low")),
            "change": float(quote.get("change", "0")),
            "name": quote.get("name", "British 30 Year Gilt"),
            "last_time": quote.get("last_time", ""),
            "yr_high": parse_pct(quote.get("yrhiprice")),
            "yr_low": parse_pct(quote.get("yrloprice")),
            "yr_high_date": quote.get("yrhidate", ""),
            "yr_low_date": quote.get("yrlodate", ""),
            "maturity": quote.get("maturity_date", ""),
            "coupon": quote.get("coupon", ""),
        }

        if live["yield"] is None:
            print("Warning: Could not parse live yield from CNBC.")
            return None

        print(f"  Live yield: {live['yield']:.3f}% (CNBC, {live['name']})")
        return live

    except Exception as e:
        print(f"Warning: Could not fetch live yield from CNBC: {e}")
        return None


def generate_dashboard(data_points, stats, live_data=None):
    """Generate the HTML dashboard file."""
    dates_json = json.dumps([d["date"] for d in data_points])
    updated_time = datetime.now().strftime("%d %b %Y at %H:%M")
    logo_data_uri = load_logo_base64()

    # Determine whether we have live market data
    has_live = live_data is not None and live_data.get("yield") is not None

    # Adjust historical BoE chart data up to benchmark level if we have live data.
    # We match the CNBC date to the nearest BoE data point for an accurate spread,
    # then sanity-check it falls within the expected 0.40–1.00% range.
    if has_live:
        # Find the BoE data point closest to the CNBC quote date
        try:
            cnbc_ts = live_data["last_time"].split("T")[0]
            cnbc_date = datetime.strptime(cnbc_ts, "%Y-%m-%d")
        except (ValueError, KeyError, IndexError):
            cnbc_date = datetime.strptime(stats["current_date"], "%Y-%m-%d")
        matched_boe = find_nearest_value(data_points, cnbc_date)
        if matched_boe is None:
            matched_boe = stats["current_yield"]

        spread = round(live_data["yield"] - matched_boe, 4)

        # Sanity check: benchmark-vs-zero-coupon spread is typically 0.40–1.00%.
        # If it's outside this range, something is wrong — fall back to no adjustment.
        SPREAD_MIN, SPREAD_MAX = 0.40, 1.00
        if SPREAD_MIN <= spread <= SPREAD_MAX:
            yields_json = json.dumps([round(d["yield"] + spread, 4) for d in data_points])
            spread_ok = True
        else:
            print(f"  Warning: Benchmark spread {spread:.2f}% outside expected range "
                  f"({SPREAD_MIN}–{SPREAD_MAX}%). Using unadjusted BoE data.")
            yields_json = json.dumps([d["yield"] for d in data_points])
            spread_ok = False
            spread = 0
    else:
        spread = 0
        spread_ok = False
        yields_json = json.dumps([d["yield"] for d in data_points])

    stats_json = json.dumps(stats)

    def fmt_change(val):
        if val is None:
            return "N/A", ""
        sign = "+" if val >= 0 else ""
        css = "positive" if val > 0 else "negative" if val < 0 else ""
        return f"{sign}{val:.2f}%", css

    # Use live CNBC daily change if available, BoE for period changes
    if has_live:
        daily_str, daily_css = fmt_change(live_data.get("change"))
    else:
        daily_str, daily_css = fmt_change(stats.get("daily_change"))
    week_str, week_css = fmt_change(stats.get("week_change"))
    month_str, month_css = fmt_change(stats.get("month_change"))
    ytd_str, ytd_css = fmt_change(stats.get("ytd_change"))

    # Use live yield as headline if available, else fall back to BoE
    if has_live:
        current_yield = live_data["yield"]
        headline_source = "Live"
    else:
        current_yield = stats["current_yield"]
        headline_source = "BoE"

    implied_borrowing = current_yield + PROPERTY_LENDING_SPREAD_BPS / 100
    yield_3m_ago = find_nearest_value(
        data_points,
        datetime.strptime(stats["current_date"], "%Y-%m-%d") - timedelta(days=90),
    )
    yield_direction = "fallen" if stats.get("month_change", 0) < 0 else "risen"
    direction_impact = "reducing" if yield_direction == "fallen" else "increasing"
    valuation_impact = "upward" if yield_direction == "fallen" else "downward"

    # 12-month high/low: prefer CNBC 52-week data if available
    if has_live and live_data.get("yr_high") is not None:
        high_12m = live_data["yr_high"]
        low_12m = live_data["yr_low"]
        high_12m_date = live_data.get("yr_high_date", "")
        low_12m_date = live_data.get("yr_low_date", "")
        # CNBC dates are MM/DD/YY format — convert for display
        def cnbc_date_display(d):
            if not d:
                return ""
            try:
                dt = datetime.strptime(d, "%m/%d/%y")
                return dt.strftime("%d %b %Y")
            except ValueError:
                return d
        high_12m_display = cnbc_date_display(high_12m_date)
        low_12m_display = cnbc_date_display(low_12m_date)
    else:
        high_12m = stats["high_12m"]
        low_12m = stats["low_12m"]
        high_12m_display = format_date_display(stats["high_date"])
        low_12m_display = format_date_display(stats["low_date"])

    # Month-ago borrowing cost for summary callout
    month_change = stats.get("month_change", 0)
    month_bps = abs(month_change) * 100
    month_ago_yield = current_yield - month_change
    borrowing_verb = "reducing" if month_change < 0 else "increasing"

    # Data freshness info
    live_time_short = ""  # compact time for yield hero (e.g. "09:26 GMT")
    if has_live and live_data.get("last_time"):
        # Parse CNBC timestamp like "2026-02-26T09:22:08.000+0000"
        try:
            live_ts = live_data["last_time"].replace("+0000", "+00:00").split(".")[0]
            live_dt = datetime.strptime(live_ts, "%Y-%m-%dT%H:%M:%S")
            data_freshness = f"Live: {live_dt.strftime('%d %b %Y at %H:%M')} GMT"
            live_time_short = f"as at {live_dt.strftime('%d %b %Y')}, {live_dt.strftime('%H:%M')} GMT"
        except (ValueError, IndexError):
            data_freshness = "Live market data"
            live_time_short = "live"
    else:
        latest_data_date = datetime.strptime(stats["current_date"], "%Y-%m-%d")
        data_lag_days = (datetime.now() - latest_data_date).days
        latest_data_display = format_date_display(stats["current_date"])
        data_freshness = f"Latest data: {latest_data_display} ({data_lag_days}d lag)"

    # Bond details for display
    bond_coupon = live_data.get("coupon", "") if has_live else ""
    raw_maturity = live_data.get("maturity", "") if has_live else ""
    # Format maturity date nicely (e.g. "2054-07-31" -> "July 2054")
    try:
        mat_dt = datetime.strptime(raw_maturity, "%Y-%m-%d")
        bond_maturity = mat_dt.strftime("%B %Y")
    except (ValueError, TypeError):
        bond_maturity = raw_maturity

    # Header subtitle
    if has_live:
        header_subtitle = "Benchmark Bond Yield &middot; Live Market Data"
    else:
        header_subtitle = f"Nominal Zero Coupon &middot; Series {SERIES_CODE} &middot; Bank of England"


    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UK 30-Year Gilt Yield &mdash; Fairhurst Buckley</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Century Gothic', CenturyGothic, Nunito, sans-serif;
            background: #ffffff;
            color: #32373c;
            min-height: 100vh;
        }}

        /* ── Header ── */
        .header {{
            background: #ffffff;
            border-bottom: 3px solid #7ebc3b;
            padding: 20px 40px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 16px;
        }}

        .header-left {{
            display: flex;
            align-items: center;
            gap: 20px;
        }}

        .header-title h1 {{
            font-size: 22px;
            font-weight: 700;
            color: #32373c;
        }}

        .header-title p {{
            font-size: 13px;
            color: #6b7280;
            margin-top: 2px;
        }}

        .header-right {{
            display: flex;
            align-items: center;
            gap: 24px;
        }}

        .header-meta {{
            text-align: right;
            font-size: 12px;
            color: #6b7280;
        }}

        .header-logo img {{
            height: 48px;
            width: auto;
        }}

        /* ── Yield Hero ── */
        .yield-hero {{
            background: #f9fafb;
            border-bottom: 1px solid #e5e7eb;
            padding: 32px 40px;
            display: flex;
            align-items: flex-end;
            gap: 32px;
            flex-wrap: wrap;
        }}

        .yield-current {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            flex-wrap: wrap;
        }}

        .yield-value {{
            font-size: 56px;
            font-weight: 700;
            color: #32373c;
            letter-spacing: -2px;
            line-height: 1;
        }}

        .yield-unit {{
            font-size: 24px;
            color: #6b7280;
            font-weight: 400;
        }}

        .yield-time {{
            width: 100%;
            font-size: 12px;
            color: #9ca3af;
            font-weight: 400;
            letter-spacing: 0;
            margin-top: 2px;
        }}

        .yield-change {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding-bottom: 6px;
        }}

        .change-badge {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 700;
        }}

        .change-badge.positive {{
            background: rgba(126, 188, 59, 0.12);
            color: #5a9a1f;
        }}

        .change-badge.negative {{
            background: rgba(220, 38, 38, 0.08);
            color: #dc2626;
        }}

        .change-label {{
            font-size: 11px;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        /* ── Summary Callout ── */
        .summary-callout {{
            background: #f0f9eb;
            border-bottom: 1px solid #c8e6a5;
            padding: 16px 40px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 14px;
            color: #32373c;
            line-height: 1.5;
        }}

        .summary-callout .sc-icon {{
            font-size: 20px;
            flex-shrink: 0;
        }}

        .summary-callout strong {{
            color: #32373c;
        }}

        .summary-callout .sc-highlight {{
            font-weight: 700;
            color: #7ebc3b;
        }}

        /* ── Container ── */
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 28px 40px;
        }}

        /* ── Stat Cards ── */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}

        .stat-card {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 20px;
            transition: box-shadow 0.2s;
        }}

        .stat-card:hover {{
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}

        .stat-label {{
            font-size: 11px;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}

        .stat-value {{
            font-size: 24px;
            font-weight: 700;
            color: #32373c;
        }}

        .stat-sub {{
            font-size: 12px;
            color: #9ca3af;
            margin-top: 4px;
        }}

        .stat-value.positive {{ color: #5a9a1f; }}
        .stat-value.negative {{ color: #dc2626; }}

        /* ── Chart ── */
        .chart-container {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 24px;
            margin-bottom: 28px;
        }}

        .chart-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 12px;
        }}

        .timeframe-btns {{
            display: flex;
            gap: 6px;
        }}

        .tf-btn {{
            padding: 5px 14px;
            border-radius: 6px;
            border: 1px solid #e5e7eb;
            background: #fff;
            color: #6b7280;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            font-family: inherit;
            transition: all 0.15s;
        }}

        .tf-btn:hover {{
            border-color: #7ebc3b;
            color: #7ebc3b;
        }}

        .tf-btn.active {{
            background: #7ebc3b;
            color: #fff;
            border-color: #7ebc3b;
        }}

        .chart-title {{
            font-size: 16px;
            font-weight: 700;
            color: #32373c;
        }}

        .chart-subtitle {{
            font-size: 13px;
            color: #6b7280;
        }}

        .chart-wrapper {{
            position: relative;
            height: 450px;
        }}

        /* ── Trend Summary ── */
        .trend-summary {{
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 16px 22px;
            margin-bottom: 28px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 14px;
            color: #32373c;
            line-height: 1.5;
        }}

        .trend-summary .trend-icon {{
            font-size: 22px;
            flex-shrink: 0;
        }}

        .trend-summary .trend-direction {{
            font-weight: 700;
        }}

        .trend-summary .trend-favourable {{
            color: #5a9a1f;
        }}

        .trend-summary .trend-adverse {{
            color: #dc2626;
        }}

        .trend-summary .trend-bps {{
            font-weight: 700;
            color: #6b7280;
        }}

        /* ── Implied Value Chart ── */
        .value-chart-container {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            max-height: 0;
            overflow: hidden;
            opacity: 0;
            transition: max-height 0.5s ease, opacity 0.4s ease, padding 0.5s ease, margin 0.5s ease;
            padding: 0 24px;
            margin-bottom: 0;
        }}

        .value-chart-container.visible {{
            max-height: 600px;
            opacity: 1;
            padding: 24px;
            margin-bottom: 28px;
        }}

        .value-chart-wrapper {{
            position: relative;
            height: 400px;
        }}

        /* ── Property Context ── */
        .context-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 28px;
        }}

        .context-card {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 24px;
        }}

        .context-card h3 {{
            font-size: 15px;
            font-weight: 700;
            color: #32373c;
            margin-bottom: 14px;
            padding-bottom: 12px;
            border-bottom: 2px solid #7ebc3b;
        }}

        .context-body {{
            font-size: 14px;
            color: #4b5563;
            line-height: 1.7;
        }}

        .context-body strong {{
            color: #32373c;
        }}

        .context-highlight {{
            background: #f0f9eb;
            border-left: 4px solid #7ebc3b;
            border-radius: 0 8px 8px 0;
            padding: 14px 18px;
            margin-top: 14px;
            font-size: 13px;
            color: #32373c;
            line-height: 1.6;
        }}


        /* ── Property Calculator ── */
        .calculator {{
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 28px;
            margin-bottom: 28px;
        }}

        .calculator h3 {{
            font-size: 17px;
            font-weight: 700;
            color: #32373c;
            margin-bottom: 6px;
        }}

        .calculator .calc-subtitle {{
            font-size: 13px;
            color: #6b7280;
            margin-bottom: 24px;
        }}

        .calc-layout {{
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 32px;
            align-items: start;
        }}

        .calc-inputs {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}

        .calc-field label {{
            display: block;
            font-size: 11px;
            font-weight: 700;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }}

        .calc-field .input-wrap {{
            position: relative;
        }}

        .calc-field .input-wrap .prefix,
        .calc-field .input-wrap .suffix {{
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            font-size: 14px;
            color: #9ca3af;
            pointer-events: none;
        }}

        .calc-field .input-wrap .prefix {{
            left: 14px;
        }}

        .calc-field .input-wrap .suffix {{
            right: 14px;
        }}

        .calc-field input {{
            width: 100%;
            padding: 10px 14px;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            font-family: 'Century Gothic', CenturyGothic, Nunito, sans-serif;
            font-size: 15px;
            font-weight: 700;
            color: #32373c;
            background: #f9fafb;
            transition: border-color 0.2s;
        }}

        .calc-field input:focus {{
            outline: none;
            border-color: #7ebc3b;
            box-shadow: 0 0 0 3px rgba(126, 188, 59, 0.15);
        }}

        .calc-field input.has-prefix {{
            padding-left: 28px;
        }}

        .calc-field input.has-suffix {{
            padding-right: 32px;
        }}

        .calc-toggle-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}

        .calc-toggle-row label {{
            margin-bottom: 0;
        }}

        .calc-toggle {{
            display: flex;
            gap: 2px;
            background: #f3f4f6;
            border-radius: 6px;
            padding: 2px;
        }}

        .ct-btn {{
            padding: 3px 10px;
            border: none;
            border-radius: 5px;
            background: transparent;
            color: #6b7280;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            font-family: inherit;
            transition: all 0.15s;
        }}

        .ct-btn.active {{
            background: #7ebc3b;
            color: #fff;
        }}

        .calc-derived {{
            font-size: 12px;
            color: #7ebc3b;
            font-weight: 600;
            margin-top: 6px;
        }}

        .calc-slider {{
            margin-top: 4px;
        }}

        .calc-slider label {{
            display: block;
            font-size: 11px;
            font-weight: 700;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}

        .calc-slider input[type="range"] {{
            -webkit-appearance: none;
            appearance: none;
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: #e5e7eb;
            outline: none;
            cursor: pointer;
        }}

        .calc-slider input[type="range"]::-webkit-slider-thumb {{
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #7ebc3b;
            border: 2px solid #ffffff;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15);
            cursor: pointer;
        }}

        .calc-slider input[type="range"]::-moz-range-thumb {{
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #7ebc3b;
            border: 2px solid #ffffff;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15);
            cursor: pointer;
        }}

        .calc-slider .slider-value {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-top: 8px;
        }}

        .calc-slider .slider-pct {{
            font-size: 22px;
            font-weight: 700;
            color: #7ebc3b;
        }}

        .calc-slider .slider-desc {{
            font-size: 12px;
            color: #9ca3af;
            text-align: right;
        }}

        .calc-results {{
            min-height: 100%;
        }}

        .calc-results-placeholder {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 200px;
            color: #9ca3af;
            font-size: 14px;
            text-align: center;
            border: 2px dashed #e5e7eb;
            border-radius: 10px;
            padding: 24px;
        }}

        .calc-results-content {{
            display: none;
        }}

        .calc-results-content.visible {{
            display: block;
        }}

        .calc-base-val {{
            display: flex;
            align-items: center;
            gap: 16px;
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 18px 22px;
            margin-bottom: 18px;
        }}

        .calc-base-val .cbv-value {{
            font-size: 28px;
            font-weight: 700;
            color: #32373c;
            white-space: nowrap;
        }}

        .calc-base-val .cbv-label {{
            font-size: 13px;
            color: #6b7280;
            line-height: 1.4;
        }}

        .calc-scenario-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}

        .calc-scenario-table th {{
            text-align: left;
            color: #6b7280;
            font-weight: 700;
            padding: 8px 12px;
            border-bottom: 2px solid #e5e7eb;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .calc-scenario-table td {{
            padding: 9px 12px;
            color: #4b5563;
            border-bottom: 1px solid #f3f4f6;
        }}

        .calc-scenario-table tr.scenario-current td {{
            color: #32373c;
            font-weight: 700;
            background: #f0f9eb;
        }}

        .calc-scenario-table td.val-positive {{
            color: #5a9a1f;
            font-weight: 700;
        }}

        .calc-scenario-table td.val-negative {{
            color: #dc2626;
            font-weight: 700;
        }}

        @media (max-width: 900px) {{
            .calc-layout {{
                grid-template-columns: 1fr;
            }}
        }}

        /* ── Footer ── */
        .footer {{
            text-align: center;
            padding: 24px 40px;
            font-size: 12px;
            color: #9ca3af;
            border-top: 1px solid #e5e7eb;
        }}

        .footer a {{
            color: #7ebc3b;
            text-decoration: none;
        }}

        /* ── Data Note ── */
        .data-note {{
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 22px 28px;
            margin-bottom: 28px;
            font-size: 13px;
            color: #6b7280;
            line-height: 1.7;
        }}

        .data-note h4 {{
            font-size: 13px;
            font-weight: 700;
            color: #32373c;
            margin-bottom: 8px;
        }}

        .data-note p {{
            margin-bottom: 8px;
        }}

        .data-note p:last-child {{
            margin-bottom: 0;
        }}

        /* ── Responsive ── */
        @media (max-width: 900px) {{
            .context-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        @media (max-width: 768px) {{
            .header {{
                padding: 16px 16px;
                gap: 12px;
            }}

            .header-left {{
                gap: 12px;
            }}

            .header-title h1 {{
                font-size: 17px;
            }}

            .header-title p {{
                font-size: 11px;
            }}

            .header-right {{
                gap: 12px;
            }}

            .header-meta {{
                font-size: 11px;
            }}

            .header-logo img {{
                height: 32px;
            }}

            .yield-hero {{
                padding: 20px 16px;
                gap: 16px;
            }}

            .yield-value {{
                font-size: 40px;
            }}

            .yield-change {{
                padding-bottom: 0;
            }}

            .change-badge {{
                font-size: 12px;
                padding: 3px 10px;
            }}

            .summary-callout {{
                padding: 12px 16px;
                font-size: 13px;
            }}

            .container {{
                padding: 20px 16px;
            }}

            .stats-grid {{
                grid-template-columns: 1fr 1fr;
                gap: 10px;
            }}

            .stat-card {{
                padding: 14px;
            }}

            .stat-value {{
                font-size: 20px;
            }}

            .chart-container {{
                padding: 16px;
            }}

            .chart-header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
                margin-bottom: 14px;
            }}

            .chart-title {{
                font-size: 14px;
            }}

            .chart-wrapper, .value-chart-wrapper {{
                height: 260px;
            }}

            .timeframe-btns {{
                gap: 4px;
            }}

            .tf-btn {{
                padding: 5px 11px;
                font-size: 11px;
            }}

            .trend-summary {{
                padding: 12px 16px;
                font-size: 13px;
                margin: 0 0 20px 0;
            }}

            .calculator {{
                padding: 18px;
            }}

            .calculator h3 {{
                font-size: 15px;
            }}

            .calc-subtitle {{
                font-size: 12px;
            }}

            .calc-results-content {{
                padding: 16px;
            }}

            .calc-base-val {{
                padding: 14px;
            }}

            .cbv-value {{
                font-size: 24px;
            }}

            .calc-scenario-table {{
                font-size: 12px;
            }}

            .calc-scenario-table th,
            .calc-scenario-table td {{
                padding: 6px 8px;
            }}

            .data-note {{
                padding: 16px;
                font-size: 12px;
            }}

            .footer {{
                padding: 18px 16px;
                font-size: 11px;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="header-left">
            <div class="header-title">
                <h1>UK 30-Year Gilt Yield</h1>
                <p>{header_subtitle}</p>
            </div>
        </div>
        <div class="header-right">
            <div class="header-meta">
                Last updated: {updated_time}<br>
                {data_freshness}
            </div>
            {'<div class="header-logo"><img src="' + logo_data_uri + '" alt="Fairhurst Buckley"></div>' if logo_data_uri else ''}
        </div>
    </div>

    <div class="yield-hero">
        <div class="yield-current">
            <span class="yield-value">{current_yield:.2f}</span>
            <span class="yield-unit">%</span>
            {'<span class="yield-time">' + live_time_short + '</span>' if live_time_short else ''}
        </div>
        <div class="yield-change">
            <span class="change-label">Daily Change</span>
            <span class="change-badge {daily_css}">{daily_str}</span>
        </div>
        <div class="yield-change">
            <span class="change-label">Weekly</span>
            <span class="change-badge {week_css}">{week_str}</span>
        </div>
        <div class="yield-change">
            <span class="change-label">Monthly</span>
            <span class="change-badge {month_css}">{month_str}</span>
        </div>
        <div class="yield-change">
            <span class="change-label">YTD</span>
            <span class="change-badge {ytd_css}">{ytd_str}</span>
        </div>
    </div>

    <div class="summary-callout">
        <span class="sc-icon">&#9432;</span>
        Over the past month, gilt yields have <strong>{yield_direction} by {abs(month_change):.2f}%</strong> ({month_bps:.0f}bps),
        {borrowing_verb} the implied cost of long-term property debt.
    </div>

    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">52-Week High</div>
                <div class="stat-value">{high_12m:.2f}%</div>
                <div class="stat-sub">{high_12m_display}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">52-Week Low</div>
                <div class="stat-value">{low_12m:.2f}%</div>
                <div class="stat-sub">{low_12m_display}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">52-Week Range</div>
                <div class="stat-value">{high_12m - low_12m:.2f}%</div>
                <div class="stat-sub">High to Low spread</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Implied Borrowing Cost</div>
                <div class="stat-value">{implied_borrowing:.2f}%</div>
                <div class="stat-sub">Gilt + {PROPERTY_LENDING_SPREAD_BPS}bps lending margin</div>
            </div>
        </div>

        <div class="chart-container">
            <div class="chart-header">
                <div>
                    <div class="chart-title" id="yieldChartTitle">Yield History &mdash; Last Twelve Months</div>
                    <div class="chart-subtitle">{'Adjusted to benchmark level (+' + f'{spread:.2f}' + '% spread applied to BoE yield curve)' if spread_ok else 'Daily nominal zero coupon 30-year gilt yield (%)'}</div>
                </div>
                <div class="timeframe-btns">
                    <button class="tf-btn" data-months="1">1M</button>
                    <button class="tf-btn" data-months="3">3M</button>
                    <button class="tf-btn" data-months="6">6M</button>
                    <button class="tf-btn active" data-months="12">1Y</button>
                </div>
            </div>
            <div class="chart-wrapper">
                <canvas id="yieldChart"></canvas>
            </div>
        </div>

        <div class="trend-summary" id="trendSummary"></div>

        <div class="value-chart-container" id="valueChartContainer">
            <div class="chart-header">
                <div>
                    <div class="chart-title">Implied Disposal Value &mdash; Last 12 Months</div>
                    <div class="chart-subtitle" id="valueChartSubtitle">Enter property details below to see historical implied values</div>
                </div>
            </div>
            <div class="value-chart-wrapper">
                <canvas id="valueChart"></canvas>
            </div>
        </div>

        <div class="calculator">
            <h3>Property Valuation Scenario Tool</h3>
            <p class="calc-subtitle">Enter your property details to see how gilt yield movements could affect the achievable disposal price.</p>
            <div class="calc-layout">
                <div class="calc-inputs">
                    <div class="calc-field">
                        <label>Annual Net Rent</label>
                        <div class="input-wrap">
                            <span class="prefix">&pound;</span>
                            <input type="text" id="calcRent" class="has-prefix" placeholder="e.g. 250,000" inputmode="numeric">
                        </div>
                    </div>
                    <div class="calc-field">
                        <div class="calc-toggle-row">
                            <label id="yieldFieldLabel">Property Yield</label>
                            <div class="calc-toggle">
                                <button class="ct-btn active" id="modeYield" data-mode="yield">Yield</button>
                                <button class="ct-btn" id="modePrice" data-mode="price">Guide Price</button>
                            </div>
                        </div>
                        <div class="input-wrap" id="yieldWrap">
                            <input type="text" id="calcYield" class="has-suffix" placeholder="e.g. 5.50" inputmode="decimal">
                            <span class="suffix">%</span>
                        </div>
                        <div class="input-wrap" id="priceWrap" style="display:none;">
                            <span class="prefix">&pound;</span>
                            <input type="text" id="calcPrice" class="has-prefix" placeholder="e.g. 4,500,000" inputmode="numeric">
                        </div>
                        <div class="calc-derived" id="calcDerived" style="display:none;"></div>
                    </div>
                    <div class="calc-slider">
                        <label>Gilt Pass-Through Rate</label>
                        <input type="range" id="calcPassThrough" min="0" max="100" value="50" step="5">
                        <div class="slider-value">
                            <span class="slider-pct" id="calcPassPct">50%</span>
                            <span class="slider-desc" id="calcPassDesc">50bps gilt move = 25bps yield shift</span>
                        </div>
                        <p style="font-size: 12px; color: #9ca3af; margin-top: 12px; line-height: 1.5;">
                            Property yields don't always move by the same amount as gilts.
                            At 50%, only half of the gilt movement affects the property yield.
                            For example, if gilts rise by 0.50%, the property yield rises by just 0.25%.
                        </p>
                    </div>
                </div>
                <div class="calc-results">
                    <div class="calc-results-placeholder" id="calcPlaceholder">
                        Enter the annual rent and property yield<br>to see valuation scenarios
                    </div>
                    <div class="calc-results-content" id="calcContent">
                        <div class="calc-base-val">
                            <div class="cbv-value" id="calcBaseVal">&mdash;</div>
                            <div class="cbv-label">Current implied<br>disposal value</div>
                        </div>
                        <table class="calc-scenario-table">
                            <thead>
                                <tr>
                                    <th>Gilt Move</th>
                                    <th>Property Yield</th>
                                    <th>Implied Value</th>
                                    <th>Change</th>
                                </tr>
                            </thead>
                            <tbody id="calcTableBody">
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>


        <div class="data-note">
            <h4>About this data</h4>
            <p>
                The headline yield is the <strong>benchmark 30-year gilt bond yield</strong>
                {'(' + bond_coupon + ' coupon, maturing ' + bond_maturity + ')' if bond_coupon and bond_maturity else ''}
                &mdash; the same figure quoted by the Financial Times and Bloomberg.
                It is sourced live during UK market hours and updates each time this page is refreshed.
            </p>
            <p>
                The historical chart uses data from the <strong>Bank of England</strong>,
                adjusted to the benchmark yield level so the chart aligns with the headline figure.
                Bank of England data is published with a 2&ndash;3 business day delay;
                the most recent 2&ndash;3 days of the chart therefore reflect the last available BoE reading.
            </p>
        </div>
    </div>

    <div class="footer">
        Live yield: CNBC / Reuters &middot; Historical chart: <a href="https://www.bankofengland.co.uk/statistics/yield-curves" target="_blank">Bank of England</a>
        &middot; Prepared for Fairhurst Buckley
    </div>

    <script>
        const dates = {dates_json};
        const yields = {yields_json};

        // Compute 30-day Simple Moving Average
        function computeSMA(data, window) {{
            const sma = [];
            for (let i = 0; i < data.length; i++) {{
                if (i < window - 1) {{
                    sma.push(null);
                }} else {{
                    let sum = 0;
                    for (let j = i - window + 1; j <= i; j++) {{
                        sum += data[j];
                    }}
                    sma.push(sum / window);
                }}
            }}
            return sma;
        }}
        const yieldSMA30 = computeSMA(yields, 30);

        const ctx = document.getElementById('yieldChart').getContext('2d');

        // Gradient fill using Fairhurst Buckley green
        const gradient = ctx.createLinearGradient(0, 0, 0, 450);
        gradient.addColorStop(0, 'rgba(126, 188, 59, 0.18)');
        gradient.addColorStop(1, 'rgba(126, 188, 59, 0.0)');

        const yieldChart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: dates,
                datasets: [{{
                    label: '30-Year Gilt Yield (%)',
                    data: yields,
                    borderColor: '#7ebc3b',
                    backgroundColor: gradient,
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.15,
                    pointRadius: 0,
                    pointHoverRadius: 6,
                    pointHoverBackgroundColor: '#7ebc3b',
                    pointHoverBorderColor: '#ffffff',
                    pointHoverBorderWidth: 2,
                }}, {{
                    label: '30-Day Moving Average (%)',
                    data: yieldSMA30,
                    borderColor: 'rgba(126, 188, 59, 0.5)',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [6, 4],
                    fill: false,
                    tension: 0.15,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: 'rgba(126, 188, 59, 0.5)',
                    pointHoverBorderColor: '#ffffff',
                    pointHoverBorderWidth: 2,
                    spanGaps: false,
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    intersect: false,
                    mode: 'index',
                }},
                plugins: {{
                    legend: {{
                        display: false,
                    }},
                    tooltip: {{
                        backgroundColor: '#32373c',
                        titleColor: '#ffffff',
                        bodyColor: '#e5e7eb',
                        borderColor: '#7ebc3b',
                        borderWidth: 1,
                        padding: 12,
                        cornerRadius: 8,
                        displayColors: true,
                        titleFont: {{ family: "'Century Gothic', CenturyGothic, Nunito, sans-serif", weight: '700' }},
                        bodyFont: {{ family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                        callbacks: {{
                            title: function(items) {{
                                const dateStr = dates[items[0].dataIndex];
                                const parts = dateStr.split('-');
                                const d = new Date(parts[0], parts[1] - 1, parts[2]);
                                return d.toLocaleDateString('en-GB', {{ day: 'numeric', month: 'long', year: 'numeric' }});
                            }},
                            label: function(item) {{
                                if (item.parsed.y === null || item.parsed.y === undefined) return null;
                                if (item.datasetIndex === 0) {{
                                    return 'Yield: ' + item.parsed.y.toFixed(4) + '%';
                                }} else {{
                                    return '30d MA: ' + item.parsed.y.toFixed(4) + '%';
                                }}
                            }},
                            filter: function(item) {{
                                return item.parsed.y !== null && item.parsed.y !== undefined;
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        type: 'time',
                        time: {{
                            unit: 'month',
                            displayFormats: {{
                                month: 'MMM yyyy'
                            }}
                        }},
                        grid: {{
                            color: '#f3f4f6',
                        }},
                        ticks: {{
                            color: '#6b7280',
                            font: {{ size: 11, family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                            maxRotation: 0,
                        }},
                        border: {{
                            color: '#e5e7eb',
                        }}
                    }},
                    y: {{
                        grid: {{
                            color: '#f3f4f6',
                        }},
                        ticks: {{
                            color: '#6b7280',
                            font: {{ size: 11, family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                            callback: function(value) {{
                                return value.toFixed(2) + '%';
                            }}
                        }},
                        border: {{
                            color: '#e5e7eb',
                        }}
                    }}
                }}
            }}
        }});

        // Populate trend summary
        (function() {{
            const lastYield = yields[yields.length - 1];
            const lastSMA = yieldSMA30[yieldSMA30.length - 1];
            const el = document.getElementById('trendSummary');

            if (lastSMA === null || lastSMA === undefined) {{
                el.style.display = 'none';
                return;
            }}

            const diff = lastYield - lastSMA;
            const diffBps = Math.abs(diff * 100).toFixed(0);
            const falling = diff < 0;

            const icon = falling ? '&#9660;' : '&#9650;';
            const dirClass = falling ? 'trend-favourable' : 'trend-adverse';
            const dirWord = falling ? 'falling' : 'rising';
            const commentary = falling
                ? 'favourable conditions for property values'
                : 'headwind for property values';

            el.innerHTML =
                '<span class="trend-icon ' + dirClass + '">' + icon + '</span>' +
                '<span>30-day trend: Yields <span class="trend-direction ' + dirClass + '">' + dirWord + '</span> ' +
                '&mdash; current yield is <span class="trend-bps">' + diffBps + 'bps</span> ' +
                (falling ? 'below' : 'above') + ' the 30-day moving average. ' +
                '<em>' + commentary + '.</em></span>';
        }})();

        // Time frame selector
        document.querySelectorAll('.tf-btn').forEach(function(btn) {{
            btn.addEventListener('click', function() {{
                document.querySelectorAll('.tf-btn').forEach(function(b) {{ b.classList.remove('active'); }});
                this.classList.add('active');
                const months = parseInt(this.dataset.months);
                const cutoff = new Date();
                cutoff.setMonth(cutoff.getMonth() - months);
                const minDate = cutoff.toISOString().split('T')[0];

                yieldChart.options.scales.x.min = minDate;
                yieldChart.update();

                if (typeof valueChartInstance !== 'undefined' && valueChartInstance) {{
                    valueChartInstance.options.scales.x.min = minDate;
                    valueChartInstance.update();
                }}

                const titles = {{1:'Last Month', 3:'Last 3 Months', 6:'Last 6 Months', 12:'Last Twelve Months'}};
                document.getElementById('yieldChartTitle').textContent = 'Yield History \u2014 ' + titles[months];
            }});
        }});
    </script>

    <script>
        // ── Property Valuation Calculator ──
        const CURRENT_GILT = {current_yield};
        const rentInput = document.getElementById('calcRent');
        const yieldInput = document.getElementById('calcYield');
        const priceInput = document.getElementById('calcPrice');
        const passThroughInput = document.getElementById('calcPassThrough');
        const passPctEl = document.getElementById('calcPassPct');
        const passDescEl = document.getElementById('calcPassDesc');
        const placeholder = document.getElementById('calcPlaceholder');
        const content = document.getElementById('calcContent');
        const baseValEl = document.getElementById('calcBaseVal');
        const tableBody = document.getElementById('calcTableBody');
        const yieldWrap = document.getElementById('yieldWrap');
        const priceWrap = document.getElementById('priceWrap');
        const calcDerived = document.getElementById('calcDerived');
        const modeYieldBtn = document.getElementById('modeYield');
        const modePriceBtn = document.getElementById('modePrice');
        const yieldFieldLabel = document.getElementById('yieldFieldLabel');
        let inputMode = 'yield';

        function parseNumber(str) {{
            return parseFloat(str.replace(/[^0-9.]/g, ''));
        }}

        function formatGBP(val) {{
            if (val >= 1e6) {{
                return '\\u00A3' + (val / 1e6).toFixed(2) + 'm';
            }}
            return '\\u00A3' + val.toLocaleString('en-GB', {{ maximumFractionDigits: 0 }});
        }}

        function formatGBPFull(val) {{
            return '\\u00A3' + val.toLocaleString('en-GB', {{ maximumFractionDigits: 0 }});
        }}

        // ── Implied Value Chart ──
        let valueChartInstance = null;
        const valueChartContainer = document.getElementById('valueChartContainer');
        const valueChartSubtitle = document.getElementById('valueChartSubtitle');

        function updateValueChart(rent, propYield, passThrough) {{
            if (!rent || !propYield || rent <= 0 || propYield <= 0) {{
                valueChartContainer.classList.remove('visible');
                return;
            }}

            // Compute implied values for each historical data point
            const impliedValues = [];
            for (let i = 0; i < yields.length; i++) {{
                const giltDelta = yields[i] - CURRENT_GILT;
                const adjustedYield = propYield + (giltDelta * passThrough);
                if (adjustedYield <= 0) {{
                    impliedValues.push(null);
                }} else {{
                    impliedValues.push(rent / (adjustedYield / 100));
                }}
            }}

            // Compute 30-day SMA of implied values
            const valueSMA30 = [];
            for (let i = 0; i < impliedValues.length; i++) {{
                if (i < 29) {{
                    valueSMA30.push(null);
                }} else {{
                    let sum = 0;
                    let count = 0;
                    for (let j = i - 29; j <= i; j++) {{
                        if (impliedValues[j] !== null) {{
                            sum += impliedValues[j];
                            count++;
                        }}
                    }}
                    valueSMA30.push(count > 0 ? sum / count : null);
                }}
            }}

            // Update subtitle
            const rentDisplay = '\\u00A3' + rent.toLocaleString('en-GB', {{ maximumFractionDigits: 0 }});
            const ptPct = Math.round(passThrough * 100);
            valueChartSubtitle.textContent =
                'Based on ' + rentDisplay + ' rent at ' + propYield.toFixed(2) + '% yield with ' + ptPct + '% gilt pass-through';

            valueChartContainer.classList.add('visible');

            if (valueChartInstance) {{
                valueChartInstance.data.datasets[0].data = impliedValues;
                valueChartInstance.data.datasets[1].data = valueSMA30;
                const todayVal = impliedValues[impliedValues.length - 1];
                valueChartInstance.data.datasets[2].data =
                    new Array(impliedValues.length - 1).fill(null).concat([todayVal]);
                valueChartInstance.update('none');
            }} else {{
                const vCtx = document.getElementById('valueChart').getContext('2d');
                const vGradient = vCtx.createLinearGradient(0, 0, 0, 400);
                vGradient.addColorStop(0, 'rgba(212, 160, 57, 0.18)');
                vGradient.addColorStop(1, 'rgba(212, 160, 57, 0.0)');

                const todayVal = impliedValues[impliedValues.length - 1];
                const todayData = new Array(impliedValues.length - 1).fill(null).concat([todayVal]);

                valueChartInstance = new Chart(vCtx, {{
                    type: 'line',
                    data: {{
                        labels: dates,
                        datasets: [
                            {{
                                label: 'Implied Disposal Value',
                                data: impliedValues,
                                borderColor: '#d4a039',
                                backgroundColor: vGradient,
                                borderWidth: 2.5,
                                fill: true,
                                tension: 0.15,
                                pointRadius: 0,
                                pointHoverRadius: 6,
                                pointHoverBackgroundColor: '#d4a039',
                                pointHoverBorderColor: '#ffffff',
                                pointHoverBorderWidth: 2,
                                spanGaps: true,
                            }},
                            {{
                                label: '30-Day Moving Average',
                                data: valueSMA30,
                                borderColor: 'rgba(212, 160, 57, 0.5)',
                                backgroundColor: 'transparent',
                                borderWidth: 2,
                                borderDash: [6, 4],
                                fill: false,
                                tension: 0.15,
                                pointRadius: 0,
                                pointHoverRadius: 4,
                                pointHoverBackgroundColor: 'rgba(212, 160, 57, 0.5)',
                                pointHoverBorderColor: '#ffffff',
                                pointHoverBorderWidth: 2,
                                spanGaps: false,
                            }},
                            {{
                                label: "Today's Value",
                                data: todayData,
                                borderColor: '#d4a039',
                                backgroundColor: '#d4a039',
                                pointRadius: 8,
                                pointHoverRadius: 10,
                                pointStyle: 'circle',
                                pointBorderColor: '#ffffff',
                                pointBorderWidth: 3,
                                showLine: false,
                                fill: false,
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {{
                            intersect: false,
                            mode: 'index',
                        }},
                        plugins: {{
                            legend: {{
                                display: false,
                            }},
                            tooltip: {{
                                backgroundColor: '#32373c',
                                titleColor: '#ffffff',
                                bodyColor: '#e5e7eb',
                                borderColor: '#d4a039',
                                borderWidth: 1,
                                padding: 12,
                                cornerRadius: 8,
                                displayColors: true,
                                titleFont: {{ family: "'Century Gothic', CenturyGothic, Nunito, sans-serif", weight: '700' }},
                                bodyFont: {{ family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                                callbacks: {{
                                    title: function(items) {{
                                        const dateStr = dates[items[0].dataIndex];
                                        const parts = dateStr.split('-');
                                        const d = new Date(parts[0], parts[1] - 1, parts[2]);
                                        return d.toLocaleDateString('en-GB', {{ day: 'numeric', month: 'long', year: 'numeric' }});
                                    }},
                                    label: function(item) {{
                                        if (item.parsed.y === null || item.parsed.y === undefined) return null;
                                        const val = item.parsed.y;
                                        let lbl = item.dataset.label + ': ';
                                        if (val >= 1e6) {{
                                            lbl += '\\u00A3' + (val / 1e6).toFixed(2) + 'm';
                                        }} else {{
                                            lbl += '\\u00A3' + val.toLocaleString('en-GB', {{ maximumFractionDigits: 0 }});
                                        }}
                                        return lbl;
                                    }},
                                    filter: function(item) {{
                                        return item.parsed.y !== null && item.parsed.y !== undefined;
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                type: 'time',
                                time: {{
                                    unit: 'month',
                                    displayFormats: {{
                                        month: 'MMM yyyy'
                                    }}
                                }},
                                grid: {{ color: '#f3f4f6' }},
                                ticks: {{
                                    color: '#6b7280',
                                    font: {{ size: 11, family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                                    maxRotation: 0,
                                }},
                                border: {{ color: '#e5e7eb' }}
                            }},
                            y: {{
                                grid: {{ color: '#f3f4f6' }},
                                ticks: {{
                                    color: '#6b7280',
                                    font: {{ size: 11, family: "'Century Gothic', CenturyGothic, Nunito, sans-serif" }},
                                    callback: function(value) {{
                                        if (value >= 1e6) {{
                                            return '\\u00A3' + (value / 1e6).toFixed(1) + 'm';
                                        }}
                                        return '\\u00A3' + (value / 1e3).toFixed(0) + 'k';
                                    }}
                                }},
                                border: {{ color: '#e5e7eb' }}
                            }}
                        }}
                    }}
                }});
            }}
        }}

        function updateSliderLabel() {{
            const pt = parseInt(passThroughInput.value);
            passPctEl.textContent = pt + '%';
            const exampleShift = Math.round(50 * pt / 100);
            passDescEl.textContent = '50bps gilt move = ' + exampleShift + 'bps yield shift';
        }}

        function recalculate() {{
            updateSliderLabel();

            const rent = parseNumber(rentInput.value);
            const passThrough = parseInt(passThroughInput.value) / 100;

            let propYield;
            if (inputMode === 'price') {{
                const price = parseNumber(priceInput.value);
                if (!rent || !price || rent <= 0 || price <= 0) {{
                    placeholder.style.display = 'flex';
                    content.classList.remove('visible');
                    calcDerived.style.display = 'none';
                    updateValueChart(0, 0, 0);
                    return;
                }}
                propYield = (rent / price) * 100;
                calcDerived.textContent = 'Implied yield: ' + propYield.toFixed(2) + '%';
                calcDerived.style.display = 'block';
            }} else {{
                propYield = parseNumber(yieldInput.value);
                calcDerived.style.display = 'none';
            }}

            if (!rent || !propYield || rent <= 0 || propYield <= 0) {{
                placeholder.style.display = 'flex';
                content.classList.remove('visible');
                updateValueChart(0, 0, 0);
                return;
            }}

            placeholder.style.display = 'none';
            content.classList.add('visible');

            const baseValue = rent / (propYield / 100);
            baseValEl.textContent = formatGBP(baseValue);

            // Scenarios: gilt moves from -75bps to +75bps in 25bp steps
            // Property yield shift = gilt move * pass-through rate
            const scenarios = [-75, -50, -25, 0, 25, 50, 75];
            let html = '';

            scenarios.forEach(function(deltaBps) {{
                const effectiveShift = deltaBps * passThrough;
                const newPropYield = propYield + (effectiveShift / 100);
                if (newPropYield <= 0) return;

                const newValue = rent / (newPropYield / 100);
                const change = newValue - baseValue;
                const changePct = (change / baseValue) * 100;
                const isCurrent = deltaBps === 0;

                const rowClass = isCurrent ? ' class="scenario-current"' : '';
                const label = isCurrent ? 'Current' : (deltaBps > 0 ? '+' : '') + deltaBps + 'bps';

                let changeCell;
                if (isCurrent) {{
                    changeCell = '<td>&mdash;</td>';
                }} else if (change > 0) {{
                    changeCell = '<td class="val-positive">+' + formatGBPFull(Math.round(change)) + ' (+' + changePct.toFixed(1) + '%)</td>';
                }} else {{
                    changeCell = '<td class="val-negative">' + formatGBPFull(Math.round(change)) + ' (' + changePct.toFixed(1) + '%)</td>';
                }}

                html += '<tr' + rowClass + '>' +
                    '<td>' + label + '</td>' +
                    '<td>' + newPropYield.toFixed(2) + '%</td>' +
                    '<td>' + formatGBP(newValue) + '</td>' +
                    changeCell +
                    '</tr>';
            }});

            tableBody.innerHTML = html;

            // Update implied value chart
            updateValueChart(rent, propYield, passThrough);
        }}

        // Format rent input with commas as user types
        rentInput.addEventListener('input', function() {{
            const raw = this.value.replace(/[^0-9]/g, '');
            if (raw) {{
                this.value = parseInt(raw).toLocaleString('en-GB');
            }}
            recalculate();
        }});

        yieldInput.addEventListener('input', recalculate);
        passThroughInput.addEventListener('input', recalculate);

        priceInput.addEventListener('input', function() {{
            const raw = this.value.replace(/[^0-9]/g, '');
            if (raw) {{
                this.value = parseInt(raw).toLocaleString('en-GB');
            }}
            recalculate();
        }});

        modeYieldBtn.addEventListener('click', function() {{
            inputMode = 'yield';
            modeYieldBtn.classList.add('active');
            modePriceBtn.classList.remove('active');
            yieldWrap.style.display = '';
            priceWrap.style.display = 'none';
            yieldFieldLabel.textContent = 'Property Yield';
            recalculate();
        }});

        modePriceBtn.addEventListener('click', function() {{
            inputMode = 'price';
            modePriceBtn.classList.add('active');
            modeYieldBtn.classList.remove('active');
            yieldWrap.style.display = 'none';
            priceWrap.style.display = '';
            yieldFieldLabel.textContent = 'Guide Price';
            recalculate();
        }});
    </script>
</body>
</html>"""

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard saved to {DASHBOARD_FILE}")
    return DASHBOARD_FILE


def format_date_display(date_str):
    """Format a YYYY-MM-DD date for display."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return date_str


def fetch_and_generate():
    """Fetch fresh data and generate the dashboard. Returns (data_points, stats, live_data)."""
    data_points = fetch_gilt_data()
    if not data_points:
        raise RuntimeError("No data points received from Bank of England API.")

    stats = compute_stats(data_points)
    save_data(data_points, stats)

    # Fetch live benchmark yield from CNBC
    live_data = fetch_live_gilt_yield()

    headline = live_data["yield"] if live_data else stats["current_yield"]
    print(f"  Headline Yield: {headline:.2f}% ({'live' if live_data else 'BoE'})")
    print(f"  BoE Yield:      {stats['current_yield']:.2f}%")
    if live_data:
        spread = live_data["yield"] - stats["current_yield"]
        print(f"  Spread:         {spread:+.2f}% (benchmark vs zero coupon)")
    print(f"  Daily Change:   {stats['daily_change']:+.4f}%")
    print(f"  12M High:       {stats['high_12m']:.2f}%  ({format_date_display(stats['high_date'])})")
    print(f"  12M Low:        {stats['low_12m']:.2f}%  ({format_date_display(stats['low_date'])})")

    generate_dashboard(data_points, stats, live_data=live_data)
    return data_points, stats, live_data


def serve_dashboard(port=8080):
    """Run a local server that fetches fresh BoE data on each page refresh."""
    import http.server
    import time
    import socket

    # Cache so rapid refreshes don't hammer the BoE API
    cache = {"html": None, "time": 0}
    CACHE_TTL = 300  # 5 minutes (BoE data only updates once daily)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_response(204)
                self.end_headers()
                return

            now = time.time()
            if cache["html"] is None or (now - cache["time"]) > CACHE_TTL:
                try:
                    print(f"\n  Fetching fresh data from Bank of England...")
                    fetch_and_generate()
                    with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
                        cache["html"] = f.read()
                    cache["time"] = now
                    print(f"  Data refreshed successfully.\n")
                except Exception as e:
                    print(f"  Error refreshing data: {e}")
                    if cache["html"] is None:
                        self.send_error(500, f"Failed to fetch data: {e}")
                        return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(cache["html"].encode("utf-8"))

        def log_message(self, format, *args):
            pass  # Suppress default request logging

    # Try the requested port, then fall back to alternatives
    for try_port in [port, 8081, 8082, 5500, 0]:
        try:
            server = http.server.HTTPServer(("127.0.0.1", try_port), Handler)
            actual_port = server.server_address[1]
            break
        except OSError:
            if try_port == 0:
                raise
            print(f"  Port {try_port} in use, trying next...")
            continue

    url = f"http://127.0.0.1:{actual_port}"
    print(f"\n  Dashboard server running at {url}")
    print(f"  Refresh the page to see updated data (cached for {CACHE_TTL // 60} min).")
    print(f"  Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


def main():
    print("=" * 50)
    print("  UK 30-Year Gilt Yield Tracker")
    print("=" * 50)
    print()

    if "--serve" in sys.argv:
        serve_dashboard()
        return

    try:
        fetch_and_generate()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)

    print()
    webbrowser.open(str(DASHBOARD_FILE))
    print("Dashboard opened in browser.")


if __name__ == "__main__":
    main()
