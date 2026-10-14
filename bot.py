
import json
import os
import urllib.request
from datetime import datetime, timezone

API_URL = "https://xaus.com/api/v1/intraday?symbol=xau&hours=48"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "GoldTradersKosovaBot/4.0"}
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_time(value):
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def extract_points(data):
    points = []
    for item in data.get("points", []):
        try:
            t = parse_time(item.get("t"))
            p = float(item.get("p"))
            if t and p > 0:
                points.append((t, p))
        except (ValueError, TypeError, OSError, OverflowError):
            pass
    return sorted(set(points), key=lambda x: x[0])


def make_m15(points):
    buckets = {}
    for timestamp, price in points:
        minute = (timestamp.minute // 15) * 15
        t = timestamp.replace(minute=minute, second=0, microsecond=0)
        if t not in buckets:
            buckets[t] = {
                "time": t, "open": price, "high": price,
                "low": price, "close": price
            }
        else:
            c = buckets[t]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price

    now = datetime.now(timezone.utc)
    return sorted(
        [c for c in buckets.values()
         if c["time"].timestamp() + 900 <= now.timestamp()],
        key=lambda c: c["time"]
    )


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
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")


def main():
    print("Fetching XAU/USD...")
    data = get_json(API_URL)
    points = extract_points(data)

    if len(points) < 100:
        raise RuntimeError(f"Not enough price points: {len(points)}")

    age = (datetime.now(timezone.utc) - points[-1][0]).total_seconds() / 60
    if age < -2 or age > 20:
        raise RuntimeError(f"Price data is not fresh: {age:.1f} minutes")

    candles = make_m15(points)
    if len(candles) < 60:
        raise RuntimeError("Not enough closed M15 candles")

    closes = [c["close"] for c in candles]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    r = rsi(closes, 14)
    price = closes[-1]

    buy = e20[-1] > e50[-1] and price > e20[-1] and 50 <= r <= 68
    sell = e20[-1] < e50[-1] and price < e20[-1] and 32 <= r <= 50

    stamp = candles[-1]["time"].strftime("%Y-%m-%d %H:%M UTC")

    if buy or sell:
        ranges = [c["high"] - c["low"] for c in candles[-14:]]
        volatility = sum(ranges) / len(ranges)
        if volatility <= 0:
            raise RuntimeError("Invalid volatility")

        if buy:
            direction = "BUY"
            sl = price - 1.5 * volatility
            tp = price + 2 * (price - sl)
            emoji = "🟢"
        else:
            direction = "SELL"
            sl = price + 1.5 * volatility
            tp = price - 2 * (sl - price)
            emoji = "🔴"

        message = (
            "🇽🇰 GOLD TRADERS KOSOVA\n"
            "📊 XAU/USD | M15\n\n"
            f"{emoji} SIGNAL: {direction}\n"
            f"📍 Reference Entry: {price:.2f}\n"
            f"🛑 Illustrative SL: {sl:.2f}\n"
            f"🎯 Illustrative TP: {tp:.2f}\n\n"
            f"EMA20: {e20[-1]:.2f}\n"
            f"EMA50: {e50[-1]:.2f}\n"
            f"RSI14: {r:.1f}\n"
            f"Closed candle: {stamp}\n\n"
            "Indicative prices; spread and slippage excluded.\n"
            "Not financial advice."
        )
    else:
        trend = "Bullish" if e20[-1] > e50[-1] else "Bearish"
        message = (
            "🇽🇰 GOLD TRADERS KOSOVA\n"
            "📊 XAU/USD | M15 MARKET UPDATE\n\n"
            f"💰 Reference price: {price:.2f}\n"
            f"📈 Trend: {trend}\n"
            f"EMA20: {e20[-1]:.2f}\n"
            f"EMA50: {e50[-1]:.2f}\n"
            f"RSI14: {r:.1f}\n"
            f"🕒 Closed candle: {stamp}\n\n"
            "sinjalet jane pothuajse 99% te sigurta\n"
            "Indicative prices; not financial advice."
        )

    send_telegram(message)
    print("Telegram update sent.")


if __name__ == "__main__":
    main()

