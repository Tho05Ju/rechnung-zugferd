"""Lieferantenrechnung hochladen -> Endkundenrechnung als ZUGFeRD-PDF erzeugen. Lokal: python app.py"""
import datetime as dt
import json
import re
import sqlite3
import uuid
import warnings
from decimal import Decimal
from pathlib import Path

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_file, url_for

warnings.filterwarnings("ignore")

from calc import D, compute, fmt_num, fmt_qty
from datanorm import parse_datanorm
from collections import Counter
from invoice_parser import parse_invoice
from zugferd import create_zugferd

BASE = Path(__file__).parent
DATA = BASE / "data"
UPLOADS = DATA / "uploads"
OUT = BASE / "Rechnungen"
for p in (DATA, UPLOADS, OUT):
    p.mkdir(exist_ok=True)

app = Flask(__name__)

SETTING_DEFAULTS = {
    "name": "", "street": "", "zip": "", "city": "", "country": "DE", "email": "", "phone": "",
    "tax_number": "", "vat_id": "", "iban": "", "bic": "", "bank_name": "",
    "kleinunternehmer": "0", "vat_rate": "19", "payment_days": "14", "default_markup": "0",
    "number_format": "RE-{year}-{n:04d}", "next_number": "1",
}
CUSTOMER_FIELDS = ["name", "name2", "street", "zip", "city", "country", "email", "vat_id"]


# ------------------------------------------------------------------ DB
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATA / "rechnung.db")
        g.db.row_factory = sqlite3.Row
        g.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, name2 TEXT, street TEXT, zip TEXT, city TEXT,
                country TEXT DEFAULT 'DE', email TEXT, vat_id TEXT, created TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT DEFAULT 'draft', number TEXT, data TEXT,
                source_pdf TEXT, out_pdf TEXT, customer_name TEXT, net TEXT, gross TEXT, created TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL DEFAULT 'own', supplier TEXT NOT NULL DEFAULT '',
                article_no TEXT NOT NULL, short1 TEXT, short2 TEXT, unit TEXT DEFAULT 'ST', list_price TEXT DEFAULT '0',
                price_unit INTEGER DEFAULT 1, wg TEXT, discount_group TEXT, updated TEXT,
                UNIQUE(source, supplier, article_no));
            CREATE INDEX IF NOT EXISTS idx_articles_no ON articles(article_no COLLATE NOCASE);
        """)
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def get_settings():
    s = dict(SETTING_DEFAULTS)
    s.update({r["key"]: r["value"] for r in db().execute("SELECT * FROM settings")})
    return s


LOGO = DATA / "logo.png"


def seller_view(s):
    out = dict(s)
    out["logo_path"] = str(LOGO) if LOGO.exists() else ""
    out["kleinunternehmer"] = s["kleinunternehmer"] == "1"
    return out


def norm(s):
    return re.sub(r"[^a-z0-9äöüß]", "", (s or "").lower())


def customer_key(c):
    return norm(c.get("name")) + "|" + norm(c.get("zip")) + "|" + norm(c.get("street"))


def find_customer(c):
    for r in db().execute("SELECT * FROM customers"):
        if customer_key(dict(r)) == customer_key(c):
            return dict(r)
    return None


def next_number(s):
    return s["number_format"].format(year=dt.date.today().year, n=int(D(s["next_number"], "1")))


# ------------------------------------------------------------------ Seiten
@app.get("/")
def index():
    rows = db().execute("SELECT * FROM invoices ORDER BY id DESC LIMIT 100").fetchall()
    return render_template("index.html", invoices=rows, settings_ok=bool(get_settings()["name"]))


@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".pdf"):
        return redirect(url_for("index"))
    path = UPLOADS / f"{uuid.uuid4().hex}.pdf"
    f.save(path)
    s = get_settings()
    parsed = parse_invoice(str(path))
    items = parsed["items"]
    for it in items:
        it["qty"] = fmt_qty(it["qty"]).replace(".", "")
        it["price"] = fmt_num(it["price"], 2 if D(it["price"]) == D(it["price"]).quantize(Decimal("0.01")) else 4)
        it["price"] = it["price"].replace(".", "")
    matched = match_articles(items, s)
    if matched:
        parsed["warnings"].append(f"{matched} von {len(items)} Positionen im Artikelstamm gefunden – Kalkulation: Listenpreis − Kundenrabatt.")
    addr = parsed["deliveries"][0]["address"] if parsed["deliveries"] else {k: "" for k in CUSTOMER_FIELDS}
    cust = {k: addr.get(k, "") for k in CUSTOMER_FIELDS}
    cust["country"] = "DE"
    cust["id"] = None
    known = find_customer(cust)
    if known:
        cust = {k: known[k] or "" for k in CUSTOMER_FIELDS} | {"id": known["id"]}
    dates = []
    for d in parsed["deliveries"]:
        try:
            dates.append(dt.datetime.strptime(d["date"], "%d.%m.%Y").date())
        except ValueError:
            pass
    data = {
        "supplier": parsed["supplier"], "warnings": parsed["warnings"],
        "delivery_address": cust if not known else {k: addr.get(k, "") for k in CUSTOMER_FIELDS},
        "meta": {"number": next_number(s), "date": dt.date.today().isoformat(),
                 "delivery_date": (max(dates) if dates else dt.date.today()).isoformat(), "note": ""},
        "customer": cust, "global_markup": s["default_markup"], "global_discount": "0", "items": items,
    }
    cur = db().execute(
        "INSERT INTO invoices (status, number, data, source_pdf, customer_name, created, updated) VALUES ('draft',?,?,?,?,?,?)",
        (data["meta"]["number"], json.dumps(data, ensure_ascii=False), path.name, cust["name"], now(), now()))
    db().commit()
    return redirect(url_for("invoice", iid=cur.lastrowid))


def match_articles(items, s):
    """Positionen der Lieferantenrechnung im Artikelstamm suchen (Artikelnr. oder Hersteller-Codes)."""
    n = 0
    for it in items:
        it.setdefault("mode", "markup")
        cands = [it["article"]] + re.split(r"[\s/]+", it.get("supplier_codes", ""))
        art = None
        for c in filter(None, cands):
            art = db().execute("SELECT * FROM articles WHERE article_no=? COLLATE NOCASE ORDER BY source='own' DESC LIMIT 1", (c,)).fetchone()
            if art and D(art["list_price"]) > 0:
                break
            art = None
        if not art:
            continue
        basis = D(art["price_unit"], "1") or Decimal(1)
        old = D(it["price_unit"], "1")
        if old != basis:  # EK auf die Preiseinheit des Stamms umrechnen
            it["price"] = fmt_num(D(it["price"]) * basis / old, 2).replace(".", "")
            it["price_unit"] = str(int(basis))
        it["list_price"] = fmt_num(art["list_price"], 2).replace(".", "")
        it["mode"] = "list"
        n += 1
    return n


def load_invoice(iid):
    row = db().execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if not row:
        abort(404)
    return row, json.loads(row["data"])


@app.get("/invoice/<int:iid>")
def invoice(iid):
    row, data = load_invoice(iid)
    customers = [dict(r) for r in db().execute("SELECT * FROM customers ORDER BY name")]
    s = get_settings()
    return render_template("invoice.html", inv=row, data=data, customers=customers, settings=s,
                           vat_rate=0 if s["kleinunternehmer"] == "1" else float(D(s["vat_rate"], "19")))


@app.get("/invoice/<int:iid>/source")
def source(iid):
    row, _ = load_invoice(iid)
    return send_file(UPLOADS / row["source_pdf"], mimetype="application/pdf")


@app.get("/invoice/<int:iid>/download")
def download(iid):
    row, _ = load_invoice(iid)
    if not row["out_pdf"] or not (OUT / row["out_pdf"]).exists():
        abort(404)
    return send_file(OUT / row["out_pdf"], as_attachment=True, download_name=row["out_pdf"], mimetype="application/pdf")


@app.post("/invoice/<int:iid>/delete")
def delete_invoice(iid):
    row, _ = load_invoice(iid)
    db().execute("DELETE FROM invoices WHERE id=?", (iid,))
    db().commit()
    return redirect(url_for("index"))


# ------------------------------------------------------------------ API
def clean_payload(p):
    c = {k: str(p["customer"].get(k, "") or "").strip() for k in CUSTOMER_FIELDS}
    c["country"] = (c["country"] or "DE").upper()
    c["id"] = p["customer"].get("id")
    items = []
    for it in p["items"]:
        items.append({
            "article": str(it.get("article", "")).strip(), "description": str(it.get("description", "")).strip(),
            "qty": str(it.get("qty", "")).strip(), "unit": str(it.get("unit", "")).strip() or "ST",
            "price": str(it.get("price", "")).strip(), "price_unit": str(it.get("price_unit", "1")) or "1",
            "markup": str(it.get("markup", "")).strip(), "discount": str(it.get("discount", "")).strip(),
            "list_price": str(it.get("list_price", "")).strip(), "mode": "list" if it.get("mode") == "list" else "markup",
            "mismatch": bool(it.get("mismatch")), "supplier_value": it.get("supplier_value", ""),
        })
    m = p["meta"]
    meta = {k: str(m.get(k, "")).strip() for k in ("number", "date", "delivery_date", "note")}
    return c, items, meta, str(p.get("global_markup", "0")).strip(), str(p.get("global_discount", "0")).strip()


def upsert_customer(c, as_new):
    """Kundendatenbank: bestehenden Kunden aktualisieren, per Name/PLZ/Straße wiederfinden oder neu anlegen."""
    if not (c["name"] and c["street"] and c["zip"] and c["city"]):
        return c.get("id")
    cid = None if as_new else c.get("id")
    if not cid:
        known = find_customer(c)
        cid = known["id"] if known else None
    vals = [c[k] for k in CUSTOMER_FIELDS]
    if cid:
        db().execute("UPDATE customers SET " + ",".join(f"{k}=?" for k in CUSTOMER_FIELDS) + ",updated=? WHERE id=?", vals + [now(), cid])
    else:
        cid = db().execute("INSERT INTO customers (" + ",".join(CUSTOMER_FIELDS) + ",created,updated) VALUES (" +
                           ",".join("?" * (len(CUSTOMER_FIELDS) + 2)) + ")", vals + [now(), now()]).lastrowid
    return cid


def persist(iid, payload):
    row, data = load_invoice(iid)
    c, items, meta, gm, gd = clean_payload(payload)
    if payload.get("save_customer", True):
        c["id"] = upsert_customer(c, bool(payload.get("as_new")))
    s = get_settings()
    lines, totals = compute(items, gm, s["vat_rate"], s["kleinunternehmer"] == "1", gd)
    data.update(meta=meta, customer=c, items=items, global_markup=gm, global_discount=gd)
    db().execute("UPDATE invoices SET data=?, number=?, customer_name=?, net=?, gross=?, updated=? WHERE id=?",
                 (json.dumps(data, ensure_ascii=False), meta["number"], c["name"], str(totals["net"]), str(totals["gross"]), now(), iid))
    db().commit()
    return row, data, lines, totals, s


def result_json(lines, totals, extra=None):
    return {"ok": True, "totals": {k: str(v) for k, v in totals.items()},
            "lines": [{"unit_price": str(l["unit_price"]), "total": str(l["total"])} for l in lines], **(extra or {})}


@app.post("/api/invoice/<int:iid>/save")
def api_save(iid):
    _, data, lines, totals, _ = persist(iid, request.get_json())
    return jsonify(result_json(lines, totals, {"customer_id": data["customer"]["id"]}))


def validate(data, s):
    err = []
    for k, label in (("name", "Name"), ("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")):
        if not s[k].strip():
            err.append(f"Einstellungen: {label} des Rechnungsstellers fehlt.")
    if not (s["tax_number"].strip() or s["vat_id"].strip()):
        err.append("Einstellungen: Steuernummer oder USt-IdNr. fehlt (Pflichtangabe auf der Rechnung).")
    if not s["iban"].strip():
        err.append("Einstellungen: IBAN fehlt.")
    c = data["customer"]
    for k, label in (("name", "Name"), ("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")):
        if not c[k]:
            err.append(f"Kunde: {label} fehlt.")
    m = data["meta"]
    for k, label in (("number", "Rechnungsnummer"), ("date", "Rechnungsdatum"), ("delivery_date", "Lieferdatum")):
        if not m[k]:
            err.append(f"{label} fehlt.")
    if not data["items"]:
        err.append("Keine Positionen vorhanden.")
    for i, it in enumerate(data["items"], 1):
        if not it["description"] and not it["article"]:
            err.append(f"Position {i}: Bezeichnung fehlt.")
        if D(it["qty"]) <= 0:
            err.append(f"Position {i}: Menge muss größer 0 sein.")
        if it["mode"] == "list" and D(it["list_price"]) <= 0:
            err.append(f"Position {i}: Listenpreis fehlt (Modus „Liste“).")
    return err


@app.post("/api/invoice/<int:iid>/pdf")
def api_pdf(iid):
    row, data, lines, totals, s = persist(iid, request.get_json())
    err = validate(data, s)
    clash = db().execute("SELECT id FROM invoices WHERE number=? AND status='final' AND id<>?", (data["meta"]["number"], iid)).fetchone()
    if clash:
        err.append(f"Die Rechnungsnummer {data['meta']['number']} ist bereits vergeben.")
    if err:
        return jsonify({"ok": False, "errors": err, "customer_id": data["customer"]["id"]}), 422
    try:
        pdf, _xml = create_zugferd(data, seller_view(s), lines, totals)
    except Exception as e:  # XSD-/PDF-Fehler sichtbar machen
        return jsonify({"ok": False, "errors": [f"Erzeugung fehlgeschlagen: {e}"]}), 500
    name = re.sub(r"[^\w.-]", "_", f"Rechnung_{data['meta']['number']}") + ".pdf"
    (OUT / name).write_bytes(pdf)
    db().execute("UPDATE invoices SET status='final', out_pdf=?, updated=? WHERE id=?", (name, now(), iid))
    if data["meta"]["number"] == next_number(s):
        db().execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('next_number',?)", (str(int(D(s["next_number"], "1")) + 1),))
    db().commit()
    return jsonify(result_json(lines, totals, {"download": url_for("download", iid=iid), "file": name}))


# ------------------------------------------------------------------ Artikelstamm
def _like_filter(q):
    where, args = [], []
    for tok in q.split():
        where.append("(article_no LIKE ? OR short1 LIKE ? OR short2 LIKE ?)")
        args += [f"%{tok}%"] * 3
    return (" WHERE " + " AND ".join(where)) if where else "", args


@app.get("/articles")
def articles():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1) or 1))
    where, args = _like_filter(q)
    total = db().execute("SELECT COUNT(*) FROM articles" + where, args).fetchone()[0]
    rows = db().execute("SELECT * FROM articles" + where + " ORDER BY source='own' DESC, supplier, article_no LIMIT 50 OFFSET ?",
                        args + [(page - 1) * 50]).fetchall()
    sup = db().execute("SELECT supplier, source, COUNT(*) n FROM articles GROUP BY supplier, source").fetchall()
    return render_template("articles.html", rows=rows, q=q, page=page, total=total, pages=(total + 49) // 50, suppliers=sup,
                           report=request.args.get("report", ""))


@app.get("/api/articles/search")
def articles_search():
    where, args = _like_filter(request.args.get("q", "").strip())
    rows = db().execute("SELECT * FROM articles" + where + " ORDER BY source='own' DESC, article_no LIMIT 20", args).fetchall() if where else []
    return jsonify([dict(r) for r in rows])


@app.post("/articles/save")
def article_save():
    f = request.form
    vals = (f.get("article_no", "").strip(), f.get("short1", "").strip(), f.get("short2", "").strip(),
            f.get("unit", "").strip() or "ST", str(D(f.get("list_price"))), int(D(f.get("price_unit"), "1")), now())
    if not vals[0]:
        return redirect(url_for("articles"))
    if f.get("id"):
        db().execute("UPDATE articles SET article_no=?, short1=?, short2=?, unit=?, list_price=?, price_unit=?, updated=? WHERE id=? AND source='own'",
                     vals + (f["id"],))
    else:
        db().execute("INSERT INTO articles (source, supplier, article_no, short1, short2, unit, list_price, price_unit, updated) "
                     "VALUES ('own','',?,?,?,?,?,?,?) ON CONFLICT(source, supplier, article_no) DO UPDATE SET short1=excluded.short1, "
                     "short2=excluded.short2, unit=excluded.unit, list_price=excluded.list_price, price_unit=excluded.price_unit, updated=excluded.updated", vals)
    db().commit()
    return redirect(url_for("articles"))


@app.post("/articles/<int:aid>/delete")
def article_delete(aid):
    db().execute("DELETE FROM articles WHERE id=? AND source='own'", (aid,))
    db().commit()
    return redirect(url_for("articles"))


@app.post("/articles/import")
def articles_import():
    supplier = request.form.get("supplier", "").strip()
    files = [f for f in request.files.getlist("files") if f.filename]
    if not supplier or not files:
        return redirect(url_for("articles", report="Bitte Lieferant angeben und mindestens eine Datei wählen."))
    d = db()
    existing = {r[0].lower() for r in d.execute("SELECT article_no FROM articles WHERE source='datanorm' AND supplier=?", (supplier,))}
    stats, new, upd, deleted, batch = Counter(), 0, 0, 0, []
    sql = ("INSERT INTO articles (source, supplier, article_no, short1, short2, unit, list_price, price_unit, wg, discount_group, updated) "
           "VALUES ('datanorm',?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source, supplier, article_no) DO UPDATE SET short1=excluded.short1, "
           "short2=excluded.short2, unit=excluded.unit, list_price=excluded.list_price, price_unit=excluded.price_unit, "
           "wg=excluded.wg, discount_group=excluded.discount_group, updated=excluded.updated")
    ts = now()
    for rec in parse_datanorm((f.stream for f in files), stats):
        if rec["op"] == "delete":
            d.execute("DELETE FROM articles WHERE source='datanorm' AND supplier=? AND article_no=?", (supplier, rec["article_no"]))
            existing.discard(rec["article_no"].lower())
            deleted += 1
            continue
        key = rec["article_no"].lower()
        new, upd = (new + 1, upd) if key not in existing else (new, upd + 1)
        existing.add(key)
        batch.append((supplier, rec["article_no"], rec["short1"], rec["short2"], rec["unit"], str(rec["list_price"]),
                      rec["price_unit"], rec["wg"], rec["discount_group"], ts))
        if len(batch) >= 5000:
            d.executemany(sql, batch)
            batch = []
    if batch:
        d.executemany(sql, batch)
    d.commit()
    skipped = ", ".join(f"{k.replace('skipped_', 'Satzart ')}: {v}" for k, v in sorted(stats.items()) if k.startswith("skipped_"))
    report = f"Import {supplier}: {new} neu, {upd} aktualisiert, {deleted} gelöscht, {stats['errors']} fehlerhafte Zeilen." + (f" Übersprungen: {skipped}." if skipped else "")
    if new + upd + deleted == 0:
        report += " Es wurden keine Artikel erkannt – Datei ist evtl. nicht Datanorm 4 (semikolongetrennt)."
    return redirect(url_for("articles", report=report))


# ------------------------------------------------------------------ Kunden & Einstellungen
@app.get("/customers")
def customers():
    rows = db().execute("SELECT * FROM customers ORDER BY name").fetchall()
    return render_template("customers.html", customers=rows, fields=CUSTOMER_FIELDS)


@app.post("/customers/save")
def customer_save():
    c = {k: request.form.get(k, "").strip() for k in CUSTOMER_FIELDS}
    c["country"] = (c["country"] or "DE").upper()
    cid = request.form.get("id")
    if cid:
        db().execute("UPDATE customers SET " + ",".join(f"{k}=?" for k in CUSTOMER_FIELDS) + ",updated=? WHERE id=?",
                     [c[k] for k in CUSTOMER_FIELDS] + [now(), cid])
    elif c["name"]:
        upsert_customer(c, True)
    db().commit()
    return redirect(url_for("customers"))


@app.post("/customers/<int:cid>/delete")
def customer_delete(cid):
    db().execute("DELETE FROM customers WHERE id=?", (cid,))
    db().commit()
    return redirect(url_for("customers"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        up = request.files.get("logo")
        if request.form.get("remove_logo"):
            LOGO.unlink(missing_ok=True)
        elif up and up.filename:
            from PIL import Image
            try:
                img = Image.open(up.stream)
                img.thumbnail((1200, 600))
                if img.mode in ("RGBA", "LA", "P"):  # Transparenz auf Weiß flachrechnen (PDF/A)
                    img = img.convert("RGBA")
                    bg = Image.new("RGB", img.size, "white")
                    bg.paste(img, mask=img.split()[3])
                    img = bg
                img.convert("RGB").save(LOGO, "PNG")
            except Exception:
                return render_template("settings.html", s=get_settings(), logo=LOGO.exists(), logo_error="Die Datei konnte nicht als Bild gelesen werden (PNG oder JPG verwenden)."), 400
        for k in SETTING_DEFAULTS:
            v = "1" if k == "kleinunternehmer" and request.form.get(k) else ("0" if k == "kleinunternehmer" else request.form.get(k, "").strip())
            db().execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (k, v))
        db().commit()
        return redirect(url_for("index"))
    return render_template("settings.html", s=get_settings(), logo=LOGO.exists())


@app.get("/logo")
def logo():
    if not LOGO.exists():
        abort(404)
    return send_file(LOGO, mimetype="image/png", max_age=0)


@app.context_processor
def inject_version():
    try:
        return {"version": (BASE / "VERSION").read_text().strip()}
    except OSError:
        return {"version": ""}


@app.template_filter("money")
def money(v):
    return fmt_num(v) if v not in (None, "") else ""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
