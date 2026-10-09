"""Datanorm-Import (Version 4, semikolon-getrennt: DATANORM.001/.002 …, .WRG).

Satzarten: A = Artikel neu/ändern, B = Änderungssatz (gleiche Feldfolge wie A), W = Warengruppe (ignoriert),
V/T/P/Z/… werden gezählt und übersprungen. Verarbeitungskennzeichen "L" löscht den Artikel.

Feldfolge A/B (je Hersteller leicht verschieden, deshalb hier zentral anpassbar):
  0 Satzart | 1 Verarb.-Kz | 2 Artikelnr | 3 Textschlüssel | 4 Kurztext 1 | 5 Kurztext 2 | 6 Preis-Kz |
  7 Preiseinheit-Code | 8 Mengeneinheit | 9 Preis | 10 Rabattgruppe | 11 Hauptwarengruppe | …
"""
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

COL = dict(flag=1, no=2, short1=4, short2=5, unit_code=7, unit=8, price=9, discount_group=10, wg=11)
PRICE_UNIT_CODE = {"0": 1, "1": 10, "2": 100, "3": 1000}


def _text(raw):
    for enc in ("utf-8", "cp850"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _price(s):
    """Preis: ganzzahlig = Cent (Datanorm-Standard), mit Komma/Punkt = Dezimalzahl."""
    s = s.strip()
    if not s:
        return None
    try:
        if "," in s or "." in s:
            return Decimal(s.replace(",", "."))
        return Decimal(s) / 100
    except InvalidOperation:
        return None


def parse_datanorm(streams, stats=None):
    """streams: Iterable[bytes-Zeilen-Iterables]. Liefert Dicts mit op='upsert'|'delete'."""
    stats = stats if stats is not None else Counter()
    for stream in streams:
        for raw in stream:
            line = _text(raw).strip("\r\n")
            if not line.strip():
                continue
            f = line.split(";")
            kind = f[0].strip().upper()
            if kind not in ("A", "B"):
                stats["skipped_" + (kind or "?")] += 1
                continue

            def get(name):
                i = COL[name]
                return f[i].strip().strip('"') if i < len(f) else ""

            no = get("no")
            if not no:
                stats["errors"] += 1
                continue
            if get("flag").upper() == "L":
                yield {"op": "delete", "article_no": no}
                continue
            price = _price(get("price"))
            if price is None and kind == "B":
                stats["skipped_B"] += 1
                continue
            yield {
                "op": "upsert", "article_no": no, "short1": get("short1"), "short2": get("short2"),
                "unit": get("unit") or "ST", "list_price": price if price is not None else Decimal(0),
                "price_unit": PRICE_UNIT_CODE.get(get("unit_code"), 1),
                "discount_group": get("discount_group"), "wg": get("wg"),
            }
