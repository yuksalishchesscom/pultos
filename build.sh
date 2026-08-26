#!/bin/bash
# Linux uchun yakka ishga tayyor fayl (--onefile) yig'adi.
# Windows .exe kerak bo'lsa, bu skriptni haqiqiy Windows kompyuterda
# (yoki GitHub Actions Windows runnerida) alohida ishga tushirish kerak.
set -e
cd "$(dirname "$0")"
source venv/bin/activate

pyinstaller --onefile --name PultOS \
  --add-data "templates:templates" \
  --add-data "static:static" \
  app.py

echo ""
echo "Tayyor: dist/PultOS"
echo "Fleshkaga dist/PultOS bilan birga config.json faylini ham nusxalang."
