import aiohttp
import asyncio
import re
import logging
from datetime import datetime, timedelta

# Mapping currency names to ISO codes
CURRENCY_MAP = {
    "rupiah": "IDR",
    "idr": "IDR",
    "dollar": "USD",
    "dolar": "USD",
    "usd": "USD",
    "euro": "EUR",
    "eur": "EUR",
    "yen": "JPY",
    "jpy": "JPY",
    "pound": "GBP",
    "sterling": "GBP",
    "gbp": "GBP",
    "ringgit": "MYR",
    "myr": "MYR",
    "sgd": "SGD",
    "aud": "AUD",
    "cad": "CAD",
    "chf": "CHF",
    "cny": "CNY",
    "hkd": "HKD",
    "inr": "INR",
    "krw": "KRW",
    "nzd": "NZD",
    "php": "PHP",
    "thb": "THB",
    "vnd": "VND",
    "sar": "SAR",
}

def parse_amount(amount_str: str) -> float:
    """Parse amount string like '100rb', '1.5jt', '2m' to float."""
    amount_str = amount_str.lower().strip()
    
    # 1. Handle suffixes for multiplier
    suffix_map = {
        "rb": 1000,
        "ribu": 1000,
        "jt": 1000000,
        "juta": 1000000,
        "m": 1000000000,
        "miliar": 1000000000,
    }
    
    multiplier = 1
    for s, m in suffix_map.items():
        if amount_str.endswith(s):
            multiplier = m
            amount_str = amount_str[:-len(s)].strip()
            break

    # 2. Extract ONLY the numeric part (digits, commas, dots)
    # This removes 'rp', '$', or any other prefix/suffix
    numeric_match = re.search(r'[\d.,]+', amount_str)
    if not numeric_match:
        return 0.0
    
    amount_str = numeric_match.group(0)
    
    # Clean up thousand separators and decimal points
    if "," in amount_str and "." in amount_str:
        if amount_str.find(".") < amount_str.find(","):
            # "." is thousands, "," is decimal (Indo: 1.500,50)
            amount_str = amount_str.replace(".", "").replace(",", ".")
        else:
            # "," is thousands, "." is decimal (US: 1,500.50)
            amount_str = amount_str.replace(",", "")
    elif "," in amount_str:
        # If it's something like "500,000", it's thousands.
        # If it's "1,5", it's decimal.
        # General rule: if there are 3 digits after the LAST comma, it's likely thousands.
        parts = amount_str.split(",")
        if len(parts[-1]) == 3 and len(parts) > 1:
            amount_str = amount_str.replace(",", "")
        else:
            amount_str = amount_str.replace(",", ".")
    elif "." in amount_str:
        # Same logic for dot
        parts = amount_str.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1:
            amount_str = amount_str.replace(".", "")
        # else it's already a valid float string with decimal dot
    
    try:
        val = float(amount_str)
        return val * multiplier
    except ValueError:
        return 0.0

def get_iso_code(name: str) -> str:
    """Get ISO code from currency name."""
    name = name.lower().strip()
    return CURRENCY_MAP.get(name)

async def fetch_currency_data(amount: float, from_curr: str, to_curr: str):
    """Fetch conversion and trend data from Frankfurter API."""
    from_curr = from_curr.upper()
    to_curr = to_curr.upper()
    
    base_url = "https://api.frankfurter.app"
    
    async with aiohttp.ClientSession() as session:
        # 1. Fetch latest conversion
        latest_url = f"{base_url}/latest?amount={amount}&from={from_curr}&to={to_curr}"
        async with session.get(latest_url) as resp:
            if resp.status != 200:
                return None, f"Gagal mengambil data terbaru ({resp.status})"
            latest_data = await resp.json()
        
        # 2. Fetch conversion for 1 unit to get current rate
        rate_url = f"{base_url}/latest?amount=1&from={from_curr}&to={to_curr}"
        async with session.get(rate_url) as resp:
            if resp.status == 200:
                rate_data = await resp.json()
                current_rate = rate_data["rates"][to_curr]
            else:
                current_rate = latest_data["rates"][to_curr] / amount if amount != 0 else 0
        
        # 3. Fetch trend (yesterday or latest available before today)
        # We use a range of 2 days to ensure we get at least two points for trend
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7) # Get last week to be safe with weekends
        trend_url = f"{base_url}/{start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}?from={from_curr}&to={to_curr}"
        
        trend_info = ""
        async with session.get(trend_url) as resp:
            if resp.status == 200:
                trend_data = await resp.json()
                rates = trend_data.get("rates", {})
                dates = sorted(rates.keys())
                if len(dates) >= 2:
                    d_today = dates[-1]
                    d_prev = dates[-2]
                    r_today = rates[d_today][to_curr]
                    r_prev = rates[d_prev][to_curr]
                    
                    diff = r_today - r_prev
                    perc = (diff / r_prev) * 100 if r_prev != 0 else 0
                    
                    if diff > 0:
                        trend_info = f"🔼 Naik {abs(perc):.2f}% (sejak {d_prev})"
                    elif diff < 0:
                        trend_info = f"🔽 Turun {abs(perc):.2f}% (sejak {d_prev})"
                    else:
                        trend_info = "➖ Stabil"
        
        return {
            "amount": amount,
            "from": from_curr,
            "to": to_curr,
            "result": latest_data["rates"][to_curr],
            "rate": current_rate,
            "trend": trend_info,
            "date": latest_data["date"]
        }, None

def format_currency(val: float, curr: str) -> str:
    """Format currency with thousand separators."""
    if curr == "IDR":
        return f"Rp {int(val):,}".replace(",", ".")
    return f"{val:,.2f} {curr}".replace(",", "temp").replace(".", ",").replace("temp", ".")
