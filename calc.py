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


def compute(items, global_markup, vat_rate, small_business=False):
    """Liefert (lines, totals). Positions-Aufschlag überschreibt den globalen Aufschlag."""
    g = D(global_markup)
    lines = []
    for it in items:
        qty = D(it.get("qty"))
        price = D(it.get("price"))
        basis = D(it.get("price_unit"), "1")
        if basis <= 0:
            basis = Decimal(1)
        own = has_value(it.get("markup"))
        m = D(it.get("markup")) if own else g
        unit_price = q2(price * (1 + m / 100))
        lines.append({
            "markup": m,
            "markup_own": own,
            "basis": basis,
            "unit_price": unit_price,
            "total": q2(qty * unit_price / basis),
            "cost": q2(qty * price / basis),
        })
    net = sum((l["total"] for l in lines), Decimal(0))
    cost = sum((l["cost"] for l in lines), Decimal(0))
    rate = Decimal(0) if small_business else D(vat_rate, "19")
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
