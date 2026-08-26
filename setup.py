"""Bir martalik sozlash skripti.

Ishga tushirish: python3 setup.py

Parolni, Gemini API kalitni va (agar xohlasangiz) uy kompyuteriga ulanish
uchun kerak bo'lgan relay maʼlumotlarini so'raydi, keyin config.json faylini
yaratadi. Faylda hech qanday ochiq sir yo'q -- parolning o'zi emas (faqat
xeshi), Gemini kalit, RELAY_TOKEN va AGENT_SECRET ham parol orqali
shifrlangan holda saqlanadi.

Agar relay/uy agenti maʼlumotlari kiritilsa, uy agenti tomonida ham xuddi
shu tokenlar kerak bo'ladi -- shuning uchun bu skript alohida
'home_agent_config.json' faylini ham yozadi (ochiq holda, chunki u faqat
ishonchli uy kompyuterida turadi). Shu faylni home_agent/config.json
sifatida uy kompyuteringizga ko'chiring.
"""

import base64
import getpass
import json
import os
import secrets

from backend.security import encrypt_str, generate_salt, hash_password

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HOME_AGENT_CONFIG_PATH = os.path.join(BASE_DIR, "home_agent_config.json")


def _ask_yes_no(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("ha", "h", "y", "yes")


def main() -> None:
    print("=== PultOS sozlash ===")

    if os.path.exists(CONFIG_PATH):
        if not _ask_yes_no("config.json allaqachon mavjud. Qayta yozilsinmi? (ha/yo'q): "):
            print("Bekor qilindi.")
            return

    password = getpass.getpass("Ilova uchun parolni kiriting: ")
    password2 = getpass.getpass("Parolni takrorlang: ")
    if not password:
        print("Parol bo'sh bo'lishi mumkin emas.")
        return
    if password != password2:
        print("Parollar mos kelmadi.")
        return

    api_key = getpass.getpass("Gemini API kalitini kiriting: ").strip()
    if not api_key:
        print("API kalit bo'sh bo'lishi mumkin emas.")
        return

    salt = generate_salt()
    config = {
        "password_hash": hash_password(password),
        "salt": base64.urlsafe_b64encode(salt).decode("utf-8"),
        "encrypted_api_key": encrypt_str(api_key, password, salt),
    }

    print()
    setup_relay = _ask_yes_no(
        "Uy kompyuteriga ulanish va xabarlar bo'limini hozir sozlaysizmi? "
        "(VPS relay-server manzili kerak bo'ladi) (ha/yo'q): "
    )
    if setup_relay:
        relay_url = input("Relay-server manzili (masalan ws://IP:8765 yoki wss://domen): ").strip()
        if relay_url:
            relay_token = secrets.token_urlsafe(32)
            agent_secret = secrets.token_urlsafe(32)

            config["relay_url"] = relay_url
            config["encrypted_relay_token"] = encrypt_str(relay_token, password, salt)
            config["encrypted_agent_secret"] = encrypt_str(agent_secret, password, salt)

            home_agent_config = {
                "relay_url": relay_url,
                "relay_token": relay_token,
                "agent_secret": agent_secret,
                "watch_paths": [],
            }
            with open(HOME_AGENT_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(home_agent_config, f, indent=2)

            print(f"Uy agenti uchun sozlama yozildi: {HOME_AGENT_CONFIG_PATH}")
            print(
                "Bu faylni 'home_agent/config.json' nomi bilan uy kompyuteringizga ko'chiring "
                "va 'watch_paths' ichiga kuzatiladigan loyiha papkangizni yozing."
            )
        else:
            print("Relay manzili kiritilmadi -- bu qism keyinroq sozlanadi.")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"\nTayyor! Sozlamalar '{CONFIG_PATH}' fayliga saqlandi.")
    print("Endi 'python3 app.py' bilan sinab ko'rishingiz mumkin.")


if __name__ == "__main__":
    main()
