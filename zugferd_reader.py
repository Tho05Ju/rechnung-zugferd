"""Liest Lieferantenrechnungen im ZUGFeRD-/Factur-X-Format (PDF mit eingebettetem CII-XML).

Liefert dieselbe Struktur wie invoice_parser.parse_invoice(), damit der Rest der App nichts davon merkt.
Gibt None zurück, wenn die PDF kein (lesbares) ZUGFeRD-XML enthält -> dann greift der Layout-Parser.
"""
import re
from decimal import Decimal, InvalidOperation

import pikepdf
from lxml import etree

from calc import q2

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}

# UN/ECE-Code -> Kürzel der App (Gegenstück zu UNIT_CODES in zugferd.py)
UNIT_LABELS = {
    "C62": "ST", "H87": "ST", "MTR": "M", "KMT": "KM", "KGM": "KG", "GRM": "G", "TNE": "T", "LTR": "L",
    "MTK": "M2", "MTQ": "M3", "SET": "SET", "PK": "PAK", "RO": "RL", "BJ": "EIM", "CT": "KAR",
    "HUR": "STD", "PR": "PAAR", "LS": "PSCH",
    # Verpackungseinheiten (UN/ECE Rec. 21, Präfix X)
    "SCK": "SACK", "XBJ": "EIM","XCT": "KAR", "XPK": "PAK", "XRO": "RL", "XBX": "KAR", "XPP": "ST", "XNE": "ST",
}
ADDR_KEYS = ("name", "name2", "street", "zip", "city")


def _x(el, path):
    return el.xpath(path, namespaces=NS)


def _text(el, path):
    r = _x(el, path)
    return (r[0].text or "").strip() if r else ""


def _dec(s, default="0"):
    try:
        return Decimal(str(s).strip())
    except InvalidOperation:
        return Decimal(default)


def _date(el, path):
    """Format 102 (JJJJMMTT) -> TT.MM.JJJJ (so wie der Layout-Parser es liefert)."""
    s = _text(el, path)
    return f"{s[6:8]}.{s[4:6]}.{s[0:4]}" if re.fullmatch(r"\d{8}", s) else ""


def extract_xml(path):
    """Eingebettetes CII-XML aus der PDF holen (oder None)."""
    try:
        with pikepdf.open(path) as pdf:
            for name, spec in pdf.attachments.items():
                data = spec.get_file().read_bytes()
                if name.lower().endswith(".xml") and b"CrossIndustryInvoice" in data[:4000]:
                    return data
    except Exception:
        return None
    return None


def _address(party):
    """Adresse aus einer (Ship-to-/Buyer-)Partei; Feldnamen wie in invoice_parser._address()."""
    if party is None:
        return None
    name = (_text(party, "ram:Name") or _text(party, "ram:SpecifiedLegalOrganization/ram:TradingBusinessName"))
    base = party if _x(party, "ram:PostalTradeAddress") else (_x(party, "ram:SpecifiedLegalOrganization") or [party])[0]
    street = _text(base, "ram:PostalTradeAddress/ram:LineOne")
    extra = " ".join(filter(None, (_text(base, "ram:PostalTradeAddress/ram:LineTwo"), _text(base, "ram:PostalTradeAddress/ram:LineThree"))))
    addr = {"name": name, "name2": "", "street": street or extra,
            "zip": _text(base, "ram:PostalTradeAddress/ram:PostcodeCode"), "city": _text(base, "ram:PostalTradeAddress/ram:CityName")}
    if street and extra:
        addr["name2"] = extra
    return addr if any(addr.values()) else None


def _charge_item(sign, amount, reason, base_name=""):
    """Zu-/Abschlag als eigene Position (Menge 1, Preis +/-)."""
    price = sign * amount
    label = reason or ("Zuschlag" if sign > 0 else "Abschlag")
    return {"article": "", "description": label + (f" ({base_name})" if base_name else ""), "supplier_codes": "",
            "qty": "1", "unit": "ST", "price": str(price), "price_unit": "1", "markup": "",
            "supplier_value": str(price), "mismatch": False}


def _charges(el, base_name=""):
    out = []
    for ac in _x(el, "ram:SpecifiedTradeAllowanceCharge"):
        amount = _dec(_text(ac, "ram:ActualAmount"))
        if amount == 0:
            continue  # z. B. 'Schnittkosten 0,00' – bringt nichts
        is_charge = _text(ac, "ram:ChargeIndicator/udt:Indicator").lower() == "true"
        out.append(_charge_item(1 if is_charge else -1, amount, _text(ac, "ram:Reason"), base_name))
    return out


def read_zugferd(path):
    xml = extract_xml(path)
    if not xml:
        return None
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    if etree.QName(root).localname != "CrossIndustryInvoice":
        return None

    result = {"supplier": {}, "deliveries": [], "items": [], "warnings": []}
    tx = _x(root, "rsm:SupplyChainTradeTransaction")[0]
    agree = _x(tx, "ram:ApplicableHeaderTradeAgreement")[0]
    sett = _x(tx, "ram:ApplicableHeaderTradeSettlement")[0]
    sup = result["supplier"]
    sup["name"] = _text(agree, "ram:SellerTradeParty/ram:Name")
    sup["invoice_no"] = _text(root, "rsm:ExchangedDocument/ram:ID")
    sup["date"] = _date(root, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    sup["customer_no"] = _text(agree, "ram:BuyerTradeParty/ram:ID")
    summ = _x(sett, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    basis_total = _text(summ[0], "ram:TaxBasisTotalAmount") if summ else ""
    if basis_total:
        sup["goods_value"] = str(_dec(basis_total))
    if summ and _text(summ[0], "ram:GrandTotalAmount"):
        sup["gross"] = str(_dec(_text(summ[0], "ram:GrandTotalAmount")))

    unknown_units = set()
    deliveries = []
    for li in _x(tx, "ram:IncludedSupplyChainTradeLineItem"):
        prod = _x(li, "ram:SpecifiedTradeProduct")[0]
        name = _text(prod, "ram:Name")
        desc = _text(prod, "ram:Description")
        article = _text(prod, "ram:SellerAssignedID") or _text(prod, "ram:BuyerAssignedID") or _text(prod, "ram:GlobalID")
        article = re.sub(r"\s+", " ", article)  # Würth füllt Artikelnummern mit Leerzeichen auf
        qty_el = _x(li, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
        qty = _dec(qty_el[0].text) if qty_el else Decimal(0)
        code = (qty_el[0].get("unitCode") if qty_el else "") or "C62"
        unit = UNIT_LABELS.get(code)
        if unit is None:
            unknown_units.add(code)
            unit = "ST"
        price = _dec(_text(li, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"))
        basis = _dec(_text(li, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:BasisQuantity"), "1")
        if basis <= 0:
            basis = Decimal(1)
        settle = _x(li, "ram:SpecifiedLineTradeSettlement")[0]
        charges = _charges(settle, article or name)
        line_total = _dec(_text(settle, "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount"))
        charge_sum = sum((_dec(c["supplier_value"]) for c in charges), Decimal(0))
        value = line_total - charge_sum  # Wert der Position selbst, ohne ihre Zu-/Abschläge
        result["items"].append({
            "article": article, "description": "\n".join(x for x in (name, desc) if x), "supplier_codes": "",
            "qty": str(qty), "unit": unit, "price": str(price), "price_unit": f"{basis.normalize():f}", "markup": "",
            "supplier_value": str(value), "mismatch": abs(q2(qty * price / basis) - value) > Decimal("0.01"),
        })
        result["items"].extend(charges)

        ship = _x(li, "ram:SpecifiedLineTradeDelivery/ram:ShipToTradeParty")
        addr = _address(ship[0]) if ship else None
        dnote = _x(li, "ram:SpecifiedLineTradeDelivery/ram:DeliveryNoteReferencedDocument")
        if addr:
            d = {"no": _text(dnote[0], "ram:IssuerAssignedID") if dnote else "",
                 "date": _date(dnote[0], "ram:FormattedIssueDateTime/qdt:DateTimeString") if dnote else "", "address": addr}
            if not any(d["address"] == x["address"] and d["no"] == x["no"] for x in deliveries):
                deliveries.append(d)

    result["items"].extend(_charges(sett))  # Zu-/Abschläge auf Rechnungsebene (Fracht, Rabatt …)

    if not deliveries:  # Kopfebene, sonst Rechnungsempfänger
        hs = _x(tx, "ram:ApplicableHeaderTradeDelivery/ram:ShipToTradeParty")
        addr = (_address(hs[0]) if hs else None) or _address((_x(agree, "ram:BuyerTradeParty") or [None])[0])
        if addr:
            deliveries.append({"no": "", "address": addr,
                               "date": _date(tx, "ram:ApplicableHeaderTradeDelivery/ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString")})
    result["deliveries"] = deliveries

    # Hinweise
    guideline = _text(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID").lower()
    if not result["items"]:
        if "minimum" in guideline or "basicwl" in guideline:
            result["warnings"].append("Das ZUGFeRD-Profil dieser Rechnung (MINIMUM/BASIC WL) enthält keine Positionen – bitte Positionen von Hand erfassen.")
        else:
            result["warnings"].append("Die ZUGFeRD-Rechnung enthält keine Positionen.")
    total = sum((_dec(i["supplier_value"]) for i in result["items"]), Decimal(0))
    if result["items"] and basis_total and abs(total - _dec(basis_total)) > Decimal("0.01"):
        result["warnings"].append(
            f"Summe der erkannten Positionen ({total} €) weicht vom Nettobetrag der Rechnung ({_dec(basis_total)} €) ab – bitte prüfen.")
    if any(i["mismatch"] for i in result["items"]):
        result["warnings"].append("Bei markierten Positionen passt Menge × Preis nicht zum Positionswert (Preiseinheit prüfen).")
    if unknown_units:
        result["warnings"].append("Unbekannte Mengeneinheit(en) " + ", ".join(sorted(unknown_units)) + " – als ST übernommen, bitte prüfen.")
    addrs = {tuple(sorted(d["address"].items())) for d in deliveries}
    if len(addrs) > 1:
        result["warnings"].append("Die Rechnung enthält mehrere unterschiedliche Lieferadressen – die erste wurde übernommen.")
    return result
