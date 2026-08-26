#!/bin/bash
# Ishlab chiqish paytida tez sinash uchun (venv orqali).
set -e
cd "$(dirname "$0")"
source venv/bin/activate
python3 app.py
