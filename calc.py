"""Preis- und Summenberechnung (maßgeblich für Anzeige-Check, XML und PDF)."""
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")


def D(value, default="0"):
    """Zahl aus str/int/float/Decimal; akzeptiert deutsche Schreibweise (1.234,56)."""
    if isinstance(value, Decimal):
        return value
    s = str(value if value is not None else "").strip().replace(" ", "").replace("€", "").replace("%", "")
    if s == "":
        s = default
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


def q2(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def has_value(v):
    return str(v if v is not None else "").strip() != ""


def compute(items, global_markup, vat_rate, small_business=False, global_discount="0", reverse_charge=False):
    """Liefert (lines, totals).

    mode "markup": VK = EK * (1 + Aufschlag%); mode "list": VK = Listenpreis * (1 - Kundenrabatt%).
    Ein Wert in der Position überschreibt jeweils den globalen Wert (auch 0).
    reverse_charge: §13b UStG – Rechnung netto ohne Umsatzsteuer (Steuerschuldner ist der Leistungsempfänger)."""
    gm, gd = D(global_markup), D(global_discount)
    lines = []
    for it in items:
        qty = D(it.get("qty"))
        price = D(it.get("price"))
        basis = D(it.get("price_unit"), "1")
        if basis <= 0:
            basis = Decimal(1)
        mode = "list" if it.get("mode") == "list" else "markup"
        if mode == "list":
            own = has_value(it.get("discount"))
            pct = D(it.get("discount")) if own else gd
            unit_price = q2(D(it.get("list_price")) * (1 - pct / 100))
        else:
            own = has_value(it.get("markup"))
            pct = D(it.get("markup")) if own else gm
            unit_price = q2(price * (1 + pct / 100))
        total = q2(qty * unit_price / basis)
        cost = q2(qty * price / basis) if price > 0 else total  # ohne EK keine Marge ausweisen
        lines.append({"mode": mode, "markup": pct, "markup_own": own, "basis": basis,
                      "unit_price": unit_price, "total": total, "cost": cost})
    net = sum((l["total"] for l in lines), Decimal(0))
    cost = sum((l["cost"] for l in lines), Decimal(0))
    rate = Decimal(0) if (small_business or reverse_charge) else D(vat_rate, "19")
    tax = q2(net * rate / 100)
    totals = {"net": net, "cost": cost, "markup_amount": net - cost, "rate": rate, "tax": tax, "gross": net + tax}
    return lines, totals


def fmt_num(x, decimals=2):
    """Deutsches Zahlenformat: 1.234,56"""
    x = D(x)
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_qty(x):
    """Menge ohne überflüssige Nullen (max. 3 Nachkommastellen)."""
    x = D(x)
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return fmt_num(Decimal(s), len(s.split(".")[1]) if "." in s else 0)


def fmt_price_unit(basis):
    b = D(basis, "1")
    return fmt_num(b, 0)
