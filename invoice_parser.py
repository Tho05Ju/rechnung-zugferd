"""Liest Lieferantenrechnungen (PDF mit Textebene) ein.

Aktuell ausgelegt auf das Layout der EFG Gienger Franken KG (Spalten Artikel / Menge / ME /
Preis / Pos/Wert). Alles, was erkannt wird, ist im Editor änderbar.
"""
import math
import re
from decimal import Decimal

import fitz

from calc import D, q2

NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d+$|^\d+,\d+$")
QTY = re.compile(r"^\d+,\d{3}$")
CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-/._]*$")
DATE = r"(\d{2}\.\d{2}\.\d{4})"
PRICE_UNITS = [1, 10, 100, 1000, 10000]
RIGHT_COL_NOISE = {"Netto", "Nto", "o.Skt", "Kostenlos", "Brutto"}


def _rows(page):
    words = sorted(page.get_text("words"), key=lambda w: (w[1], w[0]))
    rows = []
    for w in words:
        if rows and abs(w[1] - rows[-1]["y"]) <= 3:
            rows[-1]["w"].append(w)
        else:
            rows.append({"y": w[1], "w": [w]})
    for r in rows:
        r["w"].sort(key=lambda w: w[0])
        r["text"] = " ".join(w[4] for w in r["w"])
    return rows


def _item_start(row):
    w = row["w"]
    if w[0][0] >= 130:
        return False
    return any(280 <= x[0] < 330 and QTY.match(x[4]) for x in w)


def _infer_price_unit(qty, price, value):
    if price <= 0 or value <= 0 or qty <= 0:
        return 1
    ratio = float(qty * price / value)
    if ratio <= 0:
        return 1
    return min(PRICE_UNITS, key=lambda u: abs(math.log(ratio / u)))


def _parse_item(row):
    w = row["w"]
    article = w[0][4]
    qty_w = next(x for x in w if 280 <= x[0] < 330 and QTY.match(x[4]))
    qty = D(qty_w[4])
    unit = next((x[4] for x in w if 324 <= x[0] < 360 and x[0] > qty_w[0] and x[4].isalpha()), "")
    price = next((D(x[4]) for x in w if 360 <= x[2] <= 420 and NUM.match(x[4])), None)
    value = next((D(x[4]) for x in w if x[2] >= 440 and NUM.match(x[4])), None)
    return {"article": article, "qty": qty, "unit": unit, "price": price, "value": value}


def _finish_item(it):
    rows = it.pop("desc_rows")
    kept, codes = [], []
    for i, r in enumerate(rows):
        toks = r.split()
        if i > 0 and 1 <= len(toks) <= 3 and all(CODE.match(t) for t in toks) and any(c.isdigit() for c in r):
            codes.append(r)
        else:
            kept.append(r)
    price = it["price"] if it["price"] is not None else Decimal(0)
    value = it["value"] if it["value"] is not None else Decimal(0)
    unit = it["unit"]
    if not unit:
        unit = "kg" if "kupfer" in (it["article"] + " " + " ".join(kept)).lower() else "ST"
    basis = _infer_price_unit(it["qty"], price, value)
    calc = q2(it["qty"] * price / basis)
    return {
        "article": it["article"],
        "description": "\n".join(kept),
        "supplier_codes": " / ".join(codes),
        "qty": str(it["qty"]),
        "unit": unit,
        "price": str(price),
        "price_unit": str(basis),
        "markup": "",
        "supplier_value": str(value),
        "mismatch": abs(calc - value) > Decimal("0.01"),
    }


def parse_invoice(path):
    doc = fitz.open(path)
    full = "\n".join(p.get_text() for p in doc)
    result = {"supplier": {}, "deliveries": [], "items": [], "warnings": []}

    m = re.search(r"(\d{1,6})\s+(\w+)\s+(\d{4,})\s+" + DATE + r"\s+1\b", full)
    if m:
        result["supplier"].update(customer_no=m.group(1), invoice_no=m.group(3), date=m.group(4))
    for key, rx in (("goods_value", r"Warenwert\s*:\s*([\d.]+,\d{2})"), ("gross", r"Gesamt:\s*([\d.]+,\d{2})")):
        mm = re.search(rx, full)
        if mm:
            result["supplier"][key] = str(D(mm.group(1)))

    cur, delivery, mode = None, None, None
    for page in doc:
        rows = _rows(page)
        start = next((i for i, r in enumerate(rows) if r["text"].startswith("Artikel") and "Menge" in r["text"]), -1)
        if start < 0:
            continue
        if not result["supplier"].get("name"):
            for i, r in enumerate(rows):
                if "Bankverbindung" in r["text"]:
                    for r2 in rows[i + 1:i + 6]:
                        name = r2["text"].replace("*", "").strip(" :")
                        if name:
                            result["supplier"]["name"] = name
                            break
        for row in rows[start + 1:]:
            t = row["text"]
            if t.startswith("Zahlbar"):
                break
            if t.startswith("Blatt:"):
                continue
            if t.startswith("Zwischensumme"):
                if cur:
                    result["items"].append(_finish_item(cur))
                    cur = None
                mode = None
                continue
            if row["w"][0][4] == "Lieferung" and row["w"][0][0] < 130:
                if cur:
                    result["items"].append(_finish_item(cur))
                    cur = None
                dm = re.search(r"(\d+)\s+(\S+)\s+vom\s+" + DATE, t)
                delivery = {"no": dm.group(2) if dm else "", "date": dm.group(3) if dm else "", "rows": []}
                result["deliveries"].append(delivery)
                mode = "addr"
                continue
            if _item_start(row):
                if cur:
                    result["items"].append(_finish_item(cur))
                cur = _parse_item(row)
                cur["desc_rows"] = []
                mode = "item"
                continue
            if mode == "addr" and delivery is not None:
                delivery["rows"].append(t)
            elif mode == "item" and cur is not None:
                text = " ".join(w[4] for w in row["w"] if not (w[0] >= 300 and w[4] in RIGHT_COL_NOISE))
                if text.strip():
                    cur["desc_rows"].append(text.strip())
    if cur:
        result["items"].append(_finish_item(cur))

    for d in result["deliveries"]:
        d["address"] = _address(d.pop("rows"))

    # Plausibilität
    goods = result["supplier"].get("goods_value")
    total = sum((D(i["supplier_value"]) for i in result["items"]), Decimal(0))
    if goods and abs(total - D(goods)) > Decimal("0.01"):
        result["warnings"].append(
            f"Summe der erkannten Positionen ({total} €) weicht vom Warenwert der Rechnung ({goods} €) ab – bitte prüfen.")
    if not result["items"]:
        result["warnings"].append("Es wurden keine Positionen erkannt – Layout wird (noch) nicht unterstützt.")
    if any(i["mismatch"] for i in result["items"]):
        result["warnings"].append("Bei markierten Positionen passt Menge × Preis nicht zum Positionswert (Preiseinheit prüfen).")
    addrs = {tuple(sorted(d["address"].items())) for d in result["deliveries"]}
    if len(addrs) > 1:
        result["warnings"].append("Die Rechnung enthält mehrere unterschiedliche Lieferadressen – die erste wurde übernommen.")
    return result


def _address(rows):
    addr = {"name": "", "name2": "", "street": "", "zip": "", "city": ""}
    lines = []
    for r in rows:
        m = re.match(r"^\s*(\d{5})\s+(.+)$", r)
        if m:
            addr["zip"], addr["city"] = m.group(1), m.group(2).strip()
            break
        lines.append(r.strip())
    if lines:
        addr["name"] = lines[0]
        if len(lines) >= 2:
            addr["street"] = lines[-1]
        if len(lines) >= 3:
            addr["name2"] = " ".join(lines[1:-1])
    return addr
