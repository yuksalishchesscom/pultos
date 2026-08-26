import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(
            "relay/config.json topilmadi. Avval 'python3 setup.py' ni ishga tushiring."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
