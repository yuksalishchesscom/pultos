"""Relay-server uchun bir martalik sozlash.

Ishga tushirish: python3 setup.py

RELAY_TOKENni PultOS klientdan (fleshkadan) oling -- u pultos/setup.py
ishga tushirilganda generatsiya qilinadi va sizga ko'rsatiladi/yoziladi.
Telegram bot tokenini @BotFather orqali oling.
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def main() -> None:
    print("=== PultOS relay sozlash ===")

    relay_token = input("RELAY_TOKEN (fleshkadagi PultOS setup.py chiqargan token): ").strip()
    if not relay_token:
        print("RELAY_TOKEN bo'sh bo'lishi mumkin emas.")
        return

    bot_token = input("Telegram bot tokeni (@BotFather'dan, bo'sh qoldirish mumkin): ").strip()
    chat_id = input("Onangizning Telegram chat_id (agar hali bilmasangiz bo'sh qoldiring): ").strip()

    host = input("Server manzili (default 0.0.0.0): ").strip() or "0.0.0.0"
    port = input("Port (default 8765): ").strip() or "8765"

    config = {
        "relay_token": relay_token,
        "telegram_bot_token": bot_token or None,
        "telegram_allowed_chat_id": chat_id or None,
        "host": host,
        "port": int(port),
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"\nTayyor! Sozlamalar '{CONFIG_PATH}' fayliga saqlandi.")
    print("Endi 'python3 server.py' bilan ishga tushiring.")
    if not chat_id:
        print(
            "Eslatma: onangiz botga birinchi xabarni yozgach, chat_id avtomatik "
            "aniqlanadi va config.json'ga yoziladi."
        )


if __name__ == "__main__":
    main()
