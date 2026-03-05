import os
import time
import json
import requests
from dotenv import load_dotenv
from uniswap import get_position_status

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

URL = f"https://api.telegram.org/bot{TOKEN}"
offset = 0


def send(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    requests.post(URL + "/sendMessage", json=payload, timeout=20)


def updates():
    global offset
    r = requests.get(URL + "/getUpdates", params={
        "timeout": 30,
        "offset": offset
    }, timeout=35)
    return r.json()


def load_positions():
    # чтобы можно было добавлять позиции в positions.json без перезапуска бота
    with open("positions.json", "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    global offset
    print("Bot started...")

    status_keyboard = {
        "keyboard": [[{"text": "Статус всех позиций"}]],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

    while True:
        try:
            data = updates()

            for u in data.get("result", []):
                offset = u["update_id"] + 1

                msg = u.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = (msg.get("text") or "").strip()

                if text == "/start":
                    send(
                        chat_id,
                        "Бот работает 🚀\nНажми кнопку \"Статус всех позиций\", чтобы показать все позиции.",
                        reply_markup=status_keyboard
                    )

                elif text == "Статус всех позиций":
                    send(chat_id, "⏳ Считаю все позиции...")

                    positions = load_positions()

                    for i, p in enumerate(positions, start=1):
                        try:
                            result = get_position_status(p["network"], p["token_id"])

                            header = (
                                f"🔹 {i}) {p.get('name', 'Position')} | "
                                f"{p['network']} | tokenId={p['token_id']}\n\n"
                            )
                            send(chat_id, header + result)

                        except Exception as e:
                            send(chat_id, f"❌ ERROR {p.get('name','Position')} ({p['network']} #{p['token_id']}): {e}")

                        time.sleep(0.3)

        except Exception as e:
            print("ERROR:", e)

        time.sleep(1)


if __name__ == "__main__":
    main()