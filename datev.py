"""DATEV-Export: Ausgangsrechnungen als Buchungsstapel im EXTF-Format (Datenkategorie 21, Versionsnummer 700).

Pro Rechnung eine Buchung  Debitor (Soll)  an  Erlöskonto (Haben):
  - Rechnung mit USt:  Betrag brutto, Erlöskonto ist ein Automatikkonto (Steuer ergibt sich aus dem Konto, BU-Schlüssel leer)
  - §13b-Rechnung:      Betrag netto (= brutto), eigenes Erlöskonto + BU-Schlüssel aus den Einstellungen

Konten und Schlüssel sind bewusst frei einstellbar und NICHT geraten – sie müssen vom Steuerberater bestätigt werden.
Es werden nur die ersten 14 Spalten des Buchungsstapels geschrieben (Umsatz … Buchungstext); die Spaltenüberschriften
in Zeile 2 benennen genau diese Spalten.
"""
import datetime as dt
import re
from decimal import Decimal

from calc import D, q2

FORMAT_VERSION = 13  # Formatversion des Buchungsstapels (zur Versionsnummer 700)
COLUMNS = ["Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Kurs", "Basis-Umsatz", "WKZ Basis-Umsatz",
           "Konto", "Gegenkonto (ohne BU-Schlüssel)", "BU-Schlüssel", "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Skonto", "Buchungstext"]


def _q(text, maxlen=None):
    """Textfeld in Anführungszeichen (DATEV: Texte quoted, Zahlen/Datum nicht)."""
    t = str(text or "").replace('"', "'").replace("\r", " ").replace("\n", " ").replace(";", ",")
    return '"' + (t[:maxlen] if maxlen else t) + '"'


def _amount(x):
    return f"{q2(D(x)):.2f}".replace(".", ",")


def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def first_debitor(sachkontenlaenge):
    return 10 ** int(sachkontenlaenge)  # Debitoren haben eine Stelle mehr als Sachkonten (4 -> 10000)


def check_settings(s):
    """Fehlende Einstellungen für den Export (als Liste von Meldungen)."""
    err = []
    if not _digits(s.get("datev_berater")):
        err.append("Einstellungen: Beraternummer (DATEV) fehlt.")
    if not _digits(s.get("datev_mandant")):
        err.append("Einstellungen: Mandantennummer (DATEV) fehlt.")
    if not _digits(s.get("datev_erloes_konto")):
        err.append("Einstellungen: Erlöskonto für Rechnungen mit Umsatzsteuer fehlt.")
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", (s.get("datev_wj_beginn") or "").strip()):
        err.append("Einstellungen: Beginn des Wirtschaftsjahrs im Format TT.MM. angeben (z. B. 01.01.).")
    return err


def build_export(invoices, s, customers, date_from, date_to, now=None):
    """invoices: Zeilen mit number, net, gross, data(dict). customers: {id: debitor}.
    Liefert (bytes in Windows-1252, errors, count). Bei errors ist bytes None."""
    now = now or dt.datetime.now()
    errors = check_settings(s)
    if not invoices:
        errors.append("Im gewählten Zeitraum gibt es keine fertigen Rechnungen.")
    sk =int(_digits(s.get("datev_sachkontenlaenge")) or 4)
    rows = []
    for inv in invoices:
        d = inv["data"]
        meta, cu = d["meta"], d["customer"]
        label = inv["number"]
        reverse = meta.get("tax_mode") == "13b"
        konto_erl = _digits(s.get("datev_erloes_konto_13b" if reverse else "datev_erloes_konto"))
        if not konto_erl:
            errors.append(f"Rechnung {label}: Kein Erlöskonto für § 13b in den Einstellungen hinterlegt.")
            continue
        debitor = _digits(customers.get(cu.get("id")))
        if not debitor:
            errors.append(f"Rechnung {label}: Kunde „{cu.get('name', '?')}“ hat keine Debitorennummer (Kunde nicht mehr in der Kundendatenbank?).")
            continue
        try:
            beleg = dt.date.fromisoformat(meta["date"])
        except (KeyError, ValueError):
            errors.append(f"Rechnung {label}: Rechnungsdatum fehlt oder ist ungültig.")
            continue
        amount = D(inv["net"] if reverse else inv["gross"])
        bu = _digits(s.get("datev_bu_13b" if reverse else "datev_bu_19"))
        text = f'{cu.get("name", "")} {label}'
        rows.append(";".join([
            _amount(amount), '"S"', '"EUR"', "", "", "", debitor, konto_erl, bu, beleg.strftime("%d%m"),
            _q(label, 36), "", "", _q(text, 60)]))
    if errors:
        return None, errors, 0

    wj = [int(x) for x in re.findall(r"\d+", s["datev_wj_beginn"])]
    wj_start = dt.date(date_from.year if (date_from.month, date_from.day) >= (wj[1], wj[0]) else date_from.year - 1, wj[1], wj[0])
    header = [
        '"EXTF"', "700", "21", '"Buchungsstapel"', str(FORMAT_VERSION), now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}",
        "", '"RE"', _q("Rechnungstool"), '""', _digits(s["datev_berater"]), _digits(s["datev_mandant"]), wj_start.strftime("%Y%m%d"), str(sk),
        date_from.strftime("%Y%m%d"), date_to.strftime("%Y%m%d"), _q(f"Rechnungen {date_from:%d%m%y}-{date_to:%d%m%y}", 30),
        '""', "1", "0", "0", '"EUR"', "", '""', "", "", "", "", "", "", ""]  # 31 Felder
    lines = [";".join(header), ";".join(COLUMNS)] + rows
    return ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace"), [], len(rows)
