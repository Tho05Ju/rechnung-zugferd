#!/bin/bash
# Doppelklick zum Starten (Mac). Oeffnet das Tool im Browser: http://127.0.0.1:5001
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.rechnung-app/venv"
[ -x "$VENV/bin/python" ] || ./install.command /silent
[ -x "$VENV/bin/python" ] || { read -n 1 -s -r -p "Installation fehlgeschlagen. Taste druecken ..."; exit 1; }
(sleep 3; open "http://127.0.0.1:5001") &
"$VENV/bin/python" app.py
