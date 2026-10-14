
import json
import os
import urllib.request
from datetime import datetime, timezone

API_URL = "https://xaus.com/api/v1/intraday?symbol=xau&hours=48"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "GoldTradersKosovaBot/1.0"}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_time(value):
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)

    if isinstance(value, str):
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

    return None


def extract_points(data):
    points = []

    def walk(obj):
        if isinstance(obj, dict):
            time_value = next(
                (obj[k] for k in
                 ("timestamp", "time", "datetime", "date", "ts")
                 if k in obj), None
            )
            price_value = next(
                (obj[k] for k in
                 ("price", "close", "value", "spot_usd_oz")
                 if k in obj), None
            )

            if time_value is not None and price_value is not None:
                try:
                    t = parse_time(time_value)
                    p = float(price_value)
                    if t and p > 0:
                        points.append((t, p))
                except (ValueError, TypeError, OSError):
                    pass

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)

    # Remove duplicate timestamps.
    return sorted(set(points), key=lambda x: x[0])


def make_m15(points):
    buckets = {}

    for t, price in points:
        minute = (t.minute // 15) * 15
        start = t.replace(minute=minute, second=0, microsecond=0)
        candle = buckets.setdefault(
            start,
            {"open": price, "high": price,
             "low": price, "close": price, "time": start}
        )
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price

    now = datetime.now(timezone.utc)
    candles = sorted(buckets.values(), key=lambda c: c["time"])

    # Use only fully closed M15 candles.
    return [c for c in candles
            if (c["time"].timestamp() + 900) <= now.timestamp()]


def ema(values, period):
    result = []
    alpha = 2 / (period + 1)
    current = values[0]

    for value in values:
        current = alpha * value + (1 - alpha) * current
        result.append(current)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [values[i] - values[i - 1]
               for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    return 100 - (100 / (1 + avg_gain / avg_loss))


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError("Telegram did not accept the message")


def main():
    data = get_json(API_URL)
    points = extract_points(data)

    if len(points) < 100:
        raise RuntimeError(
            "Not enough price data. Check the XAUS API response."
        )

    age_minutes = (
        datetime.now(timezone.utc) - points[-1][0]
    ).total_seconds() / 60

    if age_minutes > 20:
        raise RuntimeError(
            f"Price data is too old ({age_minutes:.0f} minutes)."
        )

    candles = make_m15(points)

    if len(candles) < 60:
        raise RuntimeError(
            "Not enough closed M15 candles for EMA 50."
        )

    closes = [c["close"] for c in candles]
    fast = ema(closes, 20)
    slow = ema(closes, 50)

    # Require a crossover on the latest fully closed candle.
    buy_cross = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
    sell_cross = fast[-2] >= slow[-2] and fast[-1] < slow[-1]

    current_rsi = rsi(closes)

    if current_rsi is None:
        raise RuntimeError("Could not calculate RSI.")

    # Approximate volatility using recent M15 candle ranges.
    recent_ranges = [
        c["high"] - c["low"] for c in candles[-14:]
    ]
    atr_proxy = sum(recent_ranges) / len(recent_ranges)

    last = candles[-1]
    entry = last["close"]

    if buy_cross and 50 <= current_rsi <= 70:
        direction = "BUY"
        stop = entry - 1.5 * atr_proxy
        target = entry + 2.0 * (entry - stop)

    elif sell_cross and 30 <= current_rsi <= 50:
        direction = "SELL"
        stop = entry + 1.5 * atr_proxy
        target = entry - 2.0 * (stop - entry)

    else:
        print(
            f"No signal. RSI={current_rsi:.1f}; "
            f"closed candles={len(candles)}"
        )
        return

    message = (
        "🧪 GOLD TRADERS KOSOVA 🇽🇰\n"
        "DEMO SIGNAL — NOT VERIFIED FOR LIVE TRADING\n\n"
        f"Symbol: XAU/USD\n"
        f"Timeframe: M15\n"
        f"Direction: {direction}\n"
        f"Reference entry: {entry:.2f}\n"
        f"Illustrative SL: {stop:.2f}\n"
        f"Illustrative TP: {target:.2f}\n"
        f"EMA 20: {fast[-1]:.2f}\n"
        f"EMA 50: {slow[-1]:.2f}\n"
        f"RSI 14: {current_rsi:.1f}\n"
        f"Closed candle: {last['time'].isoformat()}\n\n"
        "Data: XAUS indicative prices. "
        "Levels exclude spread and slippage. "
        "Strategy not yet backtested."
    )

    send_telegram(message)
    print(f"Demo {direction} signal sent.")


if __name__ == "__main__":
    main()
