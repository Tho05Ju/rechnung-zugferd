#!/bin/bash
# Doppelklick zum Starten (macOS). Öffnet das Tool im Browser: http://127.0.0.1:5001
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; fi
(sleep 2 && open http://127.0.0.1:5001) &
exec .venv/bin/python app.py
