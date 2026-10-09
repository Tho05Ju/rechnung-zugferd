"""Einfache Tests ohne pytest:  .venv/bin/python tests/test_core.py"""
import io
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from calc import compute
from datanorm import parse_datanorm

DN = ("V;060;Test\r\n"
      "A;N;QNYM3025R5;1;NYM-J 3x2,5 qmm R50;Mantelleitung für Außen;1;3;M;59000;R1;100;0\r\n"
      "A;N;QKS25G;1;Klemmschelle M25;;1;2;ST;1316;R1;200;0\r\n"
      "A;N;;1;ohne Nummer;;1;0;ST;100;;;\r\n"
      "B;N;QKS25G;1;Klemmschelle M25 grau;;1;2;ST;1400;R1;200;0\r\n"
      "A;L;ALT;1;;;;;;;;;\r\n"
      "W;N;100;Kabel\r\n").encode("cp850")


def test_datanorm():
    st = Counter()
    recs = list(parse_datanorm([io.BytesIO(DN)], st))
    ups = {r["article_no"]: r for r in recs if r["op"] == "upsert"}
    assert ups["QNYM3025R5"]["list_price"] == Decimal("590.00") and ups["QNYM3025R5"]["price_unit"] == 1000
    assert "Außen" in ups["QNYM3025R5"]["short2"]
    assert ups["QKS25G"]["list_price"] == Decimal("14.00") and ups["QKS25G"]["price_unit"] == 100  # B überschreibt A
    assert [r["article_no"] for r in recs if r["op"] == "delete"] == ["ALT"]
    assert st["errors"] == 1 and st["skipped_V"] == 1 and st["skipped_W"] == 1


def test_calc():
    items = [
        {"qty": "2", "price": "10", "price_unit": "1", "list_price": "20", "mode": "list", "discount": ""},      # global 30 %
        {"qty": "2", "price": "10", "price_unit": "1", "list_price": "20", "mode": "list", "discount": "0"},     # Override 0
        {"qty": "2", "price": "10", "price_unit": "1", "markup": ""},                                              # global 20 %
        {"qty": "50", "price": "306,22", "price_unit": "1000", "markup": "20"},
    ]
    lines, t = compute(items, "20", 19, False, "30")
    assert [str(l["total"]) for l in lines] == ["28.00", "40.00", "24.00", "18.37"]
    assert str(t["net"]) == "110.37" and str(t["tax"]) == "20.97"


if __name__ == "__main__":
    test_datanorm(); test_calc(); print("alle Tests ok")
