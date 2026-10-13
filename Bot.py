import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHANNEL_ID"]

def get_gold_price():
    url = "https://api.gold-api.com/price/XAU"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()
    return data["price"]

def send_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )
    response.raise_for_status()

if __name__ == "__main__":
    try:
        price = get_gold_price()
        now = datetime.now(timezone.utc).strftime("%H:%M UTC")
        message = (
            "🥇 GOLD TRADERS KOSOVA\n\n"
            f"XAU/USD: ${price:,.2f}\n"
            f"Koha: {now}\n\n"
            "ℹ️ Përditësim i çmimit, jo sinjal i garantuar BUY/SELL."
        )
        send_message(message)
    except Exception as e:
        print(f"Gabim: {e}")
        raise
