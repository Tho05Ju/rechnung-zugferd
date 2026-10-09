# Rechnungstool – Lieferantenrechnung → ZUGFeRD-Endkundenrechnung

Lokale Web-App (Flask). Lieferantenrechnung (PDF) hochladen, Aufschlag bzw. Listenpreis − Rabatt festlegen,
Endkundenrechnung als ZUGFeRD/Factur-X (PDF/A-3, Profil EN 16931) erzeugen. Daten bleiben auf dem eigenen Rechner (`data/`, `Rechnungen/`).

## Starten
Voraussetzung: **Python** ([python.org](https://www.python.org/downloads/)); unter Windows „Add to PATH“ anhaken.

| System | Python | Start |
|---|---|---|
| macOS | 3.12 oder neuer (`install.command` prüft das) | Doppelklick auf `start.command` (beim ersten Mal ggf. Rechtsklick → Öffnen), Details in `LIESMICH.txt`; alternativ fertige App `Rechnung.app` |
| Windows | 3.9 oder neuer | Doppelklick auf `start.bat` |

Beim ersten Start wird automatisch eine virtuelle Umgebung angelegt und installiert. Danach öffnet sich http://127.0.0.1:5001.
Zuerst unter **Einstellungen** Absenderdaten, Steuernummer/USt-IdNr., IBAN und optional ein Logo hinterlegen.

## Funktionen
- Einlesen von Lieferantenrechnungen (derzeit Layout EFG Gienger Franken), Preiseinheiten (je 100/1000 …) werden erkannt.
- Kalkulation je Position: **Aufschlag auf EK** oder **Listenpreis − Kundenrabatt**; Positionswert überschreibt den globalen Wert.
- Artikelstamm: Datanorm-4-Import (`.001/.002/…`) und eigene Artikel; Artikelsuche im Editor; Treffer beim Upload werden automatisch auf „Liste“ gestellt.
- Kundendatenbank (Lieferadresse als Standard, editierbar), § 13b-Rechnungen, DATEV-Export, ZUGFeRD-Import von Lieferantenrechnungen.

## Hinweise
- Datanorm: Version 4 (semikolongetrennt). Feldfolge zentral in `datanorm.py` (`COL`) anpassbar, falls ein Hersteller abweicht. Version 5 ist nicht enthalten.
- Windows wurde nicht auf einem Windows-Rechner getestet. Vor dem produktiven Versand eine Testrechnung mit einem externen Validator (z. B. Mustang, veraPDF) prüfen.
- Tests: `.venv/bin/python tests/test_core.py` (Windows: `.venv\Scripts\python tests\test_core.py`).
