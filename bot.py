
import json
import os
import urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

message = (
    "🥇 GOLD TRADERS KOSOVA 🇽🇰\n\n"
    "✅ Telegram bot connected successfully!\n"
    "📊 XAUUSD automation setup is in progress.\n\n"
    "⚠️ Ky është mesazh testues, jo sinjal tregtimi."
)

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
    raise RuntimeError("Telegram rejected the message")

print("Telegram test message sent successfully.")

