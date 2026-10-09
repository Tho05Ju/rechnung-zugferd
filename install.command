#!/bin/bash
# Installiert die Rechnungs-App auf diesem Mac (Python-Umgebung + Pakete).
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.rechnung-app/venv"
SILENT=0; [ "$1" = "/silent" ] && SILENT=1

fail() {
  echo; echo "FEHLER: $1"
  [ $SILENT -eq 0 ] && read -n 1 -s -r -p "Taste druecken zum Beenden ..."
  exit 1
}

if [ ! -x "$VENV/bin/python" ]; then
  echo "[1/3] Suche Python ..."
  PY=""
  for c in python3.13 python3.12 python3.14 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
    P=$(command -v "$c" 2>/dev/null) || continue
    "$P" -c 'import sys,venv; sys.exit(0 if sys.version_info>=(3,12) else 1)' 2>/dev/null && { PY="$P"; break; }
  done
  if [ -z "$PY" ]; then
    open "https://www.python.org/downloads/macos/" 2>/dev/null
    fail "Python 3.12 oder neuer nicht gefunden. Bitte von python.org installieren (Seite wurde geoeffnet) und install.command erneut starten."
  fi
  echo "      Verwende $PY"
  echo "[2/3] Lege Programmumgebung an ..."
  mkdir -p "$HOME/.rechnung-app"
  "$PY" -m venv "$VENV" || fail "Programmumgebung konnte nicht angelegt werden."
fi

echo "[3/3] Installiere Pakete (kann einige Minuten dauern) ..."
"$VENV/bin/python" -m pip install -q --disable-pip-version-check -r requirements.txt || fail "Paketinstallation fehlgeschlagen. Bitte Internetverbindung pruefen."
"$VENV/bin/python" -W ignore -c "import flask,pymupdf,reportlab,pikepdf,facturx" || fail "Pakete konnten nicht geladen werden."

echo; echo "Fertig. Starte die App per Doppelklick auf start.command."
[ $SILENT -eq 0 ] && read -n 1 -s -r -p "Taste druecken zum Beenden ..."
exit 0
