"""Erzeugt die Endkundenrechnung als ZUGFeRD-/Factur-X-PDF (Profil EN 16931)."""
import io
import os
import re
import datetime as dt
from decimal import Decimal
from xml.sax.saxutils import escape

import pikepdf
from facturx import generate_from_binary
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from calc import D, fmt_num, fmt_qty, fmt_price_unit, q2

UNIT_CODES = {
    "ST": "C62", "STK": "C62", "STÜCK": "C62", "PCE": "C62", "M": "MTR", "LFM": "MTR", "MTR": "MTR",
    "KM": "KMT", "KG": "KGM", "G": "GRM", "T": "TNE", "L": "LTR", "M2": "MTK", "QM": "MTK", "M3": "MTQ",
    "SET": "SET", "SAT": "SET", "PAK": "PK", "PK": "PK", "RL": "RO", "ROL": "RO", "EIM": "BJ",
    "KAR": "CT", "STD": "HUR", "H": "HUR", "PAA": "PR", "PAAR": "PR", "PSCH": "LS", "PAU": "LS",
}


def unit_code(unit):
    return UNIT_CODES.get(unit.strip().upper(), "C62")


def _d(date_iso):
    return dt.date.fromisoformat(date_iso)


def _d102(date_iso):
    return _d(date_iso).strftime("%Y%m%d")


def _de_date(date_iso):
    return _d(date_iso).strftime("%d.%m.%Y")


def _amt(x):
    return f"{q2(D(x)):.2f}"


# ---------------------------------------------------------------- XML
def build_xml(inv, seller, lines, totals):
    meta, cust, items = inv["meta"], inv["customer"], inv["items"]
    small = seller["kleinunternehmer"]
    rate = totals["rate"]
    cat = "E" if small else "S"
    due = _d(meta["date"]) + dt.timedelta(days=int(D(seller["payment_days"])))
    e = escape

    out = []
    for n, (it, ln) in enumerate(zip(items, lines), 1):
        lines_desc = [x.strip() for x in it["description"].splitlines() if x.strip()]
        name = lines_desc[0] if lines_desc else it["article"]
        desc = " ".join(lines_desc[1:])
        out.append(f"""
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>{n}</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct>
        {f'<ram:SellerAssignedID>{e(it["article"])}</ram:SellerAssignedID>' if it["article"].strip() else ''}
        <ram:Name>{e(name)}</ram:Name>
        {f'<ram:Description>{e(desc)}</ram:Description>' if desc else ''}
      </ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement>
        <ram:NetPriceProductTradePrice>
          <ram:ChargeAmount>{_amt(ln["unit_price"])}</ram:ChargeAmount>
          <ram:BasisQuantity unitCode="{unit_code(it["unit"])}">{ln["basis"].normalize():f}</ram:BasisQuantity>
        </ram:NetPriceProductTradePrice>
      </ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="{unit_code(it["unit"])}">{D(it["qty"]).normalize():f}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>{cat}</ram:CategoryCode><ram:RateApplicablePercent>{rate:.2f}</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{_amt(ln["total"])}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>""")

    def party(name, street, zip_, city, country, extra=""):
        return (f"<ram:Name>{e(name)}</ram:Name>"
                f"<ram:PostalTradeAddress><ram:PostcodeCode>{e(zip_)}</ram:PostcodeCode><ram:LineOne>{e(street)}</ram:LineOne>"
                f"<ram:CityName>{e(city)}</ram:CityName><ram:CountryID>{e(country or 'DE')}</ram:CountryID></ram:PostalTradeAddress>{extra}")

    seller_extra = ""
    if seller["email"]:
        seller_extra += f'<ram:URIUniversalCommunication><ram:URIID schemeID="EM">{e(seller["email"])}</ram:URIID></ram:URIUniversalCommunication>'
    if seller["tax_number"]:
        seller_extra += f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">{e(seller["tax_number"])}</ram:ID></ram:SpecifiedTaxRegistration>'
    if seller["vat_id"]:
        seller_extra += f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(seller["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>'
    buyer_extra = ""
    if cust.get("email"):
        buyer_extra += f'<ram:URIUniversalCommunication><ram:URIID schemeID="EM">{e(cust["email"])}</ram:URIID></ram:URIUniversalCommunication>'
    if cust.get("vat_id"):
        buyer_extra += f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{e(cust["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>'

    buyer_name = cust["name"] if not cust.get("name2") else f'{cust["name"]}, {cust["name2"]}'
    notes = []
    if small:
        notes.append("Kein Umsatzsteuerausweis aufgrund Kleinunternehmerregelung gemäß § 19 UStG.")
    if meta.get("note"):
        notes.append(meta["note"])
    note_xml = "".join(f"<ram:IncludedNote><ram:Content>{e(n)}</ram:Content></ram:IncludedNote>" for n in notes)
    exemption = ('<ram:ExemptionReason>Kleinunternehmer gemäß § 19 UStG</ram:ExemptionReason>' if small else "")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100" xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{e(meta["number"])}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">{_d102(meta["date"])}</udt:DateTimeString></ram:IssueDateTime>
    {note_xml}
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>{"".join(out)}
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>{party(seller["name"], seller["street"], seller["zip"], seller["city"], seller["country"], seller_extra)}</ram:SellerTradeParty>
      <ram:BuyerTradeParty>{party(buyer_name, cust["street"], cust["zip"], cust["city"], cust.get("country"), buyer_extra)}</ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime><udt:DateTimeString format="102">{_d102(meta["delivery_date"])}</udt:DateTimeString></ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:PaymentReference>{e(meta["number"])}</ram:PaymentReference>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:TypeCode>58</ram:TypeCode>
        <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{e(seller["iban"].replace(" ", ""))}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>
        {f'<ram:PayeeSpecifiedCreditorFinancialInstitution><ram:BICID>{e(seller["bic"].replace(" ", ""))}</ram:BICID></ram:PayeeSpecifiedCreditorFinancialInstitution>' if seller["bic"].strip() else ''}
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax>
        <ram:CalculatedAmount>{_amt(totals["tax"])}</ram:CalculatedAmount>
        <ram:TypeCode>VAT</ram:TypeCode>
        {exemption}
        <ram:BasisAmount>{_amt(totals["net"])}</ram:BasisAmount>
        <ram:CategoryCode>{cat}</ram:CategoryCode>
        <ram:RateApplicablePercent>{rate:.2f}</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>Zahlbar bis {due.strftime("%d.%m.%Y")} ohne Abzug.</ram:Description>
        <ram:DueDateDateTime><udt:DateTimeString format="102">{due.strftime("%Y%m%d")}</udt:DateTimeString></ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{_amt(totals["net"])}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{_amt(totals["net"])}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">{_amt(totals["tax"])}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{_amt(totals["gross"])}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{_amt(totals["gross"])}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
""".encode("utf-8")


# ---------------------------------------------------------------- PDF
_FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def _register_fonts():
    import reportlab
    vera = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    cands = _FONT_CANDIDATES + [(os.path.join(vera, "Vera.ttf"), os.path.join(vera, "VeraBd.ttf"))]
    for reg, bold in cands:
        if os.path.exists(reg) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("Body", reg))
            pdfmetrics.registerFont(TTFont("Body-Bold", bold))
            pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
            return
    raise RuntimeError("Keine TrueType-Schrift gefunden (für PDF/A muss die Schrift eingebettet werden).")


class _Numbered(rl_canvas.Canvas):
    footer_fn = None

    def __init__(self, *a, **kw):
        kw["initialFontName"] = "Body"
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self.setFont("Body", 8)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Seite {self._pageNumber} von {total}")
            super().showPage()
        super().save()


def build_pdf(inv, seller, lines, totals):
    _register_fonts()
    meta, cust, items = inv["meta"], inv["customer"], inv["items"]
    small = seller["kleinunternehmer"]
    W, H = A4
    L, R = 25 * mm, 20 * mm
    buf = io.BytesIO()
    grey = colors.HexColor("#555555")

    def footer(c):
        c.setFont("Body", 7.5)
        c.setFillColor(grey)
        c.setStrokeColor(colors.HexColor("#bbbbbb"))
        c.line(L, 22 * mm, W - R, 22 * mm)
        col1 = [seller["name"], seller["street"], f'{seller["zip"]} {seller["city"]}']
        col2 = [f'IBAN: {seller["iban"]}'] + ([f'BIC: {seller["bic"]}'] if seller["bic"] else []) + ([seller["bank_name"]] if seller["bank_name"] else [])
        col3 = ([f'Steuernr.: {seller["tax_number"]}'] if seller["tax_number"] else []) + ([f'USt-IdNr.: {seller["vat_id"]}'] if seller["vat_id"] else [])
        col4 = ([seller["email"]] if seller["email"] else []) + ([seller["phone"]] if seller["phone"] else [])
        for x, col in zip((0, 36, 92, 138), (col1, col2, col3, col4)):
            for j, t in enumerate(col[:3]):
                c.drawString(L + x * mm, 18 * mm - j * 3.4 * mm, t)

    def first_page(c, doc):
        c.saveState()
        c.setFillColor(colors.black)
        if seller.get("logo_path"):
            from reportlab.lib.utils import ImageReader
            img = ImageReader(seller["logo_path"])
            iw, ih = img.getSize()
            sc = min(70 * mm / iw, 28 * mm / ih)
            c.drawImage(img, L, H - 15 * mm - ih * sc, iw * sc, ih * sc, mask=None)
        c.setFont("Body-Bold", 15)
        c.drawRightString(W - R, H - 22 * mm, seller["name"])
        c.setFont("Body", 9)
        c.setFillColor(grey)
        y = H - 28 * mm
        for t in (seller["street"], f'{seller["zip"]} {seller["city"]}', seller["email"], seller["phone"]):
            if t:
                c.drawRightString(W - R, y, t)
                y -= 4 * mm
        # Absenderzeile + Anschriftenfeld (DIN 5008)
        c.setFont("Body", 7)
        c.drawString(L, H - 48 * mm, f'{seller["name"]} · {seller["street"]} · {seller["zip"]} {seller["city"]}')
        c.setLineWidth(0.3)
        c.line(L, H - 49 * mm, L + 80 * mm, H - 49 * mm)
        c.setFillColor(colors.black)
        c.setFont("Body", 10)
        y = H - 54 * mm
        for t in [cust["name"], cust.get("name2", ""), cust["street"], f'{cust["zip"]} {cust["city"]}'] + (
                [] if (cust.get("country") or "DE") == "DE" else [cust["country"]]):
            if t:
                c.drawString(L, y, t)
                y -= 4.6 * mm
        # Infoblock
        info = [("Rechnungs-Nr.:", meta["number"]), ("Rechnungsdatum:", _de_date(meta["date"])),
                ("Lieferdatum:", _de_date(meta["delivery_date"]))]
        if cust.get("id"):
            info.append(("Kunden-Nr.:", str(cust["id"])))
        y = H - 58 * mm
        for k, v in info:
            c.setFont("Body", 9)
            c.setFillColor(grey)
            c.drawString(W - R - 62 * mm, y, k)
            c.setFillColor(colors.black)
            c.setFont("Body-Bold", 9)
            c.drawRightString(W - R, y, v)
            y -= 4.6 * mm
        footer(c)
        c.restoreState()

    def later_page(c, doc):
        c.saveState()
        c.setFont("Body", 8.5)
        c.setFillColor(grey)
        c.drawString(L, H - 18 * mm, f'{seller["name"]} – Rechnung Nr. {meta["number"]} vom {_de_date(meta["date"])}')
        footer(c)
        c.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=L, rightMargin=R, topMargin=25 * mm, bottomMargin=28 * mm,
                          title=f'Rechnung {meta["number"]}', author=seller["name"], subject=f'Rechnung {meta["number"]}')
    f1 = Frame(L, 28 * mm, W - L - R, H - 28 * mm - 100 * mm, id="f1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f2 = Frame(L, 28 * mm, W - L - R, H - 28 * mm - 28 * mm, id="f2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="first", frames=[f1], onPage=first_page, autoNextPageTemplate="later"),
                          PageTemplate(id="later", frames=[f2], onPage=later_page)])

    base = ParagraphStyle("b", fontName="Body", fontSize=8.5, leading=10.5)
    small_s = ParagraphStyle("s", parent=base, fontSize=7.5, leading=9, textColor=grey)
    right = ParagraphStyle("r", parent=base, alignment=TA_RIGHT)
    right_small = ParagraphStyle("rs", parent=small_s, alignment=TA_RIGHT)
    head = ParagraphStyle("h", parent=base, fontName="Body-Bold")
    head_r = ParagraphStyle("hr", parent=head, alignment=TA_RIGHT)
    esc = lambda s: escape(s)

    story = [Paragraph(f'Rechnung Nr. {esc(meta["number"])}', ParagraphStyle("t", fontName="Body-Bold", fontSize=13, leading=16)), Spacer(1, 5 * mm)]
    rows = [[Paragraph("Pos.", head), Paragraph("Bezeichnung", head), Paragraph("Menge", head_r),
             Paragraph("Einzelpreis", head_r), Paragraph("Betrag (netto)", head_r)]]
    for n, (it, ln) in enumerate(zip(items, lines), 1):
        d = [x.strip() for x in it["description"].splitlines() if x.strip()]
        txt = f"<b>{esc(d[0])}</b>" if d else ""
        if len(d) > 1:
            txt += "<br/>" + "<br/>".join(esc(x) for x in d[1:])
        if it["article"].strip():
            txt += f'<br/><font color="#555555" size="7.5">Art.-Nr. {esc(it["article"])}</font>'
        per = f"je {fmt_price_unit(ln['basis'])} {esc(it['unit'])}" if ln["basis"] != 1 else f"je {esc(it['unit'])}"
        rows.append([Paragraph(str(n), base), Paragraph(txt, base),
                     Paragraph(f'{fmt_qty(it["qty"])} {esc(it["unit"])}', right),
                     [Paragraph(f'{fmt_num(ln["unit_price"])} €', right), Paragraph(per, right_small)],
                     Paragraph(f'{fmt_num(ln["total"])} €', right)])
    cw = [10 * mm, 71 * mm, 25 * mm, 30 * mm, 29 * mm]
    tbl = Table(rows, colWidths=cw, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [tbl, Spacer(1, 4 * mm)]

    tot = [[Paragraph("Summe netto", base), Paragraph(f'{fmt_num(totals["net"])} €', right)],
           [Paragraph(f'zzgl. Umsatzsteuer {fmt_num(totals["rate"], 0 if totals["rate"] == totals["rate"].to_integral() else 2)} %', base),
            Paragraph(f'{fmt_num(totals["tax"])} €', right)],
           [Paragraph("Gesamtbetrag", head), Paragraph(f'{fmt_num(totals["gross"])} €', head_r)]]
    tt = Table(tot, colWidths=[45 * mm, 30 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black), ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    due = _d(meta["date"]) + dt.timedelta(days=int(D(seller["payment_days"])))
    foot = [f'Bitte überweisen Sie den Gesamtbetrag bis zum <b>{due.strftime("%d.%m.%Y")}</b> ohne Abzug unter Angabe der '
            f'Rechnungsnummer {esc(meta["number"])} auf das unten genannte Konto.']
    if small:
        foot.append("Kein Umsatzsteuerausweis aufgrund Kleinunternehmerregelung gemäß § 19 UStG.")
    if meta.get("note"):
        foot.append(esc(meta["note"]).replace("\n", "<br/>"))
    story.append(KeepTogether([tt, Spacer(1, 6 * mm)] + [Paragraph(t, base) for t in foot[:1]] +
                              [Spacer(1, 2 * mm)] + [Paragraph(t, base) for t in foot[1:]]))
    doc.build(story, canvasmaker=_Numbered)
    return buf.getvalue()


def _pdfa_prepare(pdf_bytes):
    """sRGB-OutputIntent ergänzen (Voraussetzung für PDF/A-3)."""
    icc_path = next((p for p in ("/System/Library/ColorSync/Profiles/sRGB Profile.icc",
                                 "C:/Windows/System32/spool/drivers/color/sRGB Color Space Profile.icm",
                                 "/usr/share/color/icc/colord/sRGB.icc") if os.path.exists(p)), None)
    if not icc_path:
        return pdf_bytes
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    for page in pdf.pages:  # reportlab legt Helvetica (nicht eingebettet) an und setzt sie in einem leeren Textblock
        fonts = page.Resources.get("/Font")
        if fonts is None:
            continue
        bad = [k for k in fonts.keys() if str(fonts[k].get("/BaseFont")) == "/Helvetica"]
        if not bad:
            continue
        page.contents_coalesce()
        content = page.Contents.read_bytes()
        for k in bad:
            content = re.sub(rb"BT\s+" + re.escape(k.encode()) + rb"\s+[\d.]+\s+Tf\s+[\d.]+\s+TL\s+ET\s*", b"", content)
            if (k + " ").encode() in content:
                raise RuntimeError("Helvetica wird im PDF tatsächlich verwendet – nicht PDF/A-konform")
            del fonts[k]
        page.Contents.write(content)
    icc = pdf.make_stream(open(icc_path, "rb").read())
    icc["/N"] = 3
    oi = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.OutputIntent, S=pikepdf.Name.GTS_PDFA1,
        OutputConditionIdentifier=pikepdf.String("sRGB IEC61966-2.1"),
        Info=pikepdf.String("sRGB IEC61966-2.1"), DestOutputProfile=icc))
    pdf.Root.OutputIntents = pikepdf.Array([oi])
    out = io.BytesIO()
    pdf.save(out, min_version="1.7")
    return out.getvalue()


def create_zugferd(inv, seller, lines, totals):
    xml = build_xml(inv, seller, lines, totals)
    pdf = _pdfa_prepare(build_pdf(inv, seller, lines, totals))
    meta = inv["meta"]
    final = generate_from_binary(
        pdf, xml, flavor="factur-x", level="en16931", check_xsd=True,
        pdf_metadata={"author": seller["name"], "title": f'Rechnung {meta["number"]}',
                      "subject": f'Rechnung {meta["number"]} vom {_de_date(meta["date"])}'},
        lang="de-DE")
    return final, xml
