
import json
import os
import urllib.request
from datetime import datetime, timezone

API_URL = "https://xaus.com/api/v1/intraday?symbol=xau&hours=48"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GoldTradersKosovaBot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_time(value):
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(value, timezone.utc)

    if isinstance(value, str):
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    return None


def extract_points(data):
    if not isinstance(data, dict):
        raise RuntimeError("API returned an unexpected JSON format.")

    raw_points = data.get("points", [])
    if not isinstance(raw_points, list):
        raise RuntimeError("API response does not contain a points list.")

    points = []

    for item in raw_points:
        if not isinstance(item, dict):
            continue

        try:
            timestamp = item.get("t")
            price = item.get("p")

            if timestamp is None or price is None:
                continue

            time_value = parse_time(timestamp)
            price_value = float(price)

            if time_value is not None and price_value > 0:
                points.append((time_value, price_value))

        except (ValueError, TypeError, OSError, OverflowError):
            continue

    return sorted(set(points), key=lambda point: point[0])


def make_m15(points):
    buckets = {}

    for timestamp, price in points:
        minute = (timestamp.minute // 15) * 15
        candle_time = timestamp.replace(
            minute=minute,
            second=0,
            microsecond=0
        )

        if candle_time not in buckets:
            buckets[candle_time] = {
                "time": candle_time,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }
        else:
            candle = buckets[candle_time]
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price

    now = datetime.now(timezone.utc)

    # Use only candles whose 15-minute period has ended.
    candles = [
        candle
        for candle in buckets.values()
        if (candle["time"].timestamp() + 900) <= now.timestamp()
    ]

    return sorted(candles, key=lambda candle: candle["time"])


def ema(values, period):
    alpha = 2 / (period + 1)
    result = []
    current = values[0]

    for value in values:
        current = alpha * value + (1 - alpha) * current
        result.append(current)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[index] - values[index - 1]
        for index in range(1, len(values))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for index in range(period, len(changes)):
        average_gain = (
            average_gain * (period - 1) + gains[index]
        ) / period

        average_loss = (
            average_loss * (period - 1) + losses[index]
        ) / period

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Telegram did not accept the message.")


def main():
    print("Fetching XAUUSD price history...")

    data = get_json(API_URL)
    points = extract_points(data)

    print(f"Price points received: {len(points)}")

    if len(points) < 100:
        sample_keys = (
            list(data.keys())
            if isinstance(data, dict)
            else [type(data).__name__]
        )
        raise RuntimeError(
            f"Not enough price data: {len(points)} points. "
            f"API response keys: {sample_keys}"
        )

    latest_time = points[-1][0]
    age_minutes = (
        datetime.now(timezone.utc) - latest_time
    ).total_seconds() / 60

    if age_minutes < -2:
        raise RuntimeError("API returned a future timestamp.")

    if age_minutes > 20:
        raise RuntimeError(
            f"Price data is too old: {age_minutes:.0f} minutes."
        )

    candles = make_m15(points)
    print(f"Closed M15 candles: {len(candles)}")

    if len(candles) < 60:
        raise RuntimeError(
            "Not enough closed M15 candles for EMA 50. "
            "The API may not have enough recent history yet."
        )

    closes = [candle["close"] for candle in candles]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes, 14)

    if current_rsi is None:
        raise RuntimeError("Could not calculate RSI.")

    buy_cross = (
        ema20[-2] <= ema50[-2]
        and ema20[-1] > ema50[-1]
    )

    sell_cross = (
        ema20[-2] >= ema50[-2]
        and ema20[-1] < ema50[-1]
    )

    # Average recent candle ranges as a simple volatility estimate.
    recent_ranges = [
        candle["high"] - candle["low"]
        for candle in candles[-14:]
    ]
    volatility = sum(recent_ranges) / len(recent_ranges)

    last_candle = candles[-1]
    entry = last_candle["close"]

    if buy_cross and 50 <= current_rsi <= 70:
        direction = "BUY"
        stop_loss = entry - 1.5 * volatility
        take_profit = entry + 2 * (entry - stop_loss)

    elif sell_cross and 30 <= current_rsi <= 50:
        direction = "SELL"
        stop_loss = entry + 1.5 * volatility
        take_profit = entry - 2 * (stop_loss - entry)

    else:
        print(
            "No signal this run. "
            f"RSI={current_rsi:.1f}, "
            f"EMA20={ema20[-1]:.2f}, "
            f"EMA50={ema50[-1]:.2f}"
        )
        return

    message = (
        "🧪 GOLD TRADERS KOSOVA 🇽🇰\n"
        "DEMO SIGNAL — NOT BACKTESTED\n\n"
        "Symbol: XAU/USD\n"
        "Timeframe: M15\n"
        f"Direction: {direction}\n"
        f"Reference entry: {entry:.2f}\n"
        f"Illustrative SL: {stop_loss:.2f}\n"
        f"Illustrative TP: {take_profit:.2f}\n\n"
        f"EMA 20: {ema20[-1]:.2f}\n"
        f"EMA 50: {ema50[-1]:.2f}\n"
        f"RSI 14: {current_rsi:.1f}\n"
        f"Candle closed at: "
        f"{last_candle['time'].isoformat()}\n\n"
        "Data: XAUS indicative gold prices.\n"
        "Levels exclude broker spread and slippage.\n"
        "This strategy has not been validated for live trading."
    )

    send_telegram(message)
    print(f"Demo {direction} signal sent to Telegram.")


if __name__ == "__main__":
    main()
