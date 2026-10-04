const INIT = JSON.parse(document.getElementById('init').textContent);
const S = INIT.data, CUSTS = INIT.customers, RATE = INIT.vat_rate;
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const PRICE_UNITS = [1, 10, 100, 1000, 10000];

// ---- Zahlen (deutsches Format)
const num = v => { let s = String(v ?? '').trim().replace(/\s|€|%/g, ''); if (!s) return 0;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.'); const n = parseFloat(s); return isNaN(n) ? 0 : n; };
const r2 = x => Math.round(x * 100 + (x >= 0 ? 1e-7 : -1e-7)) / 100;
const eur = x => r2(x).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const own = it => String(it.markup ?? '').trim() !== '';

// ---- Kunde
const cust = S.customer;
const sel = $('#cust-select');
CUSTS.forEach(c => { const o = new Option(`${c.name}${c.name2 ? ' – ' + c.name2 : ''}, ${c.zip} ${c.city}  (Nr. ${c.id})`, c.id); sel.add(o); });
let pristine = { ...cust };
function fillCustomer() {
  $$('[data-c]').forEach(i => i.value = cust[i.dataset.c] ?? '');
  sel.value = cust.id ?? '';
  hint();
}
function hint() {
  const dirty = cust.id && ['name', 'name2', 'street', 'zip', 'city', 'country', 'email', 'vat_id'].some(k => (cust[k] || '') !== (pristine[k] || ''));
  $('#as-new-wrap').style.display = dirty ? 'flex' : 'none';
  if (!dirty) $('#as-new').checked = false;
  $('#cust-hint').textContent = !cust.id ? 'Neuer Kunde – wird beim Speichern in der Kundendatenbank angelegt.'
    : dirty ? 'Adresse geändert – wird beim Speichern beim Kunden Nr. ' + cust.id + ' aktualisiert.' : 'Bestehender Kunde Nr. ' + cust.id + '.';
}
sel.onchange = () => {
  const c = CUSTS.find(x => String(x.id) === sel.value);
  const src = c || S.delivery_address;
  ['name', 'name2', 'street', 'zip', 'city', 'country', 'email', 'vat_id'].forEach(k => cust[k] = src[k] || (k === 'country' ? 'DE' : ''));
  cust.id = c ? c.id : null; pristine = { ...cust }; fillCustomer();
};
$$('[data-c]').forEach(i => i.oninput = () => { cust[i.dataset.c] = i.value; hint(); });
$$('[data-m]').forEach(i => { i.value = S.meta[i.dataset.m] ?? ''; i.oninput = () => S.meta[i.dataset.m] = i.value; });
fillCustomer();

// ---- Positionen
const gm = $('#global-markup'); gm.value = S.global_markup; gm.oninput = () => { S.global_markup = gm.value; recalc(); };
function rowHtml(i) {
  return `<tr data-i="${i}"><td class="mute" style="padding-top:12px">${i + 1}</td>
  <td><input data-f="article" placeholder="Art.-Nr." style="margin-bottom:4px;font-size:12px"><textarea data-f="description" rows="2" placeholder="Bezeichnung"></textarea></td>
  <td><input data-f="qty" class="num" inputmode="decimal"></td><td><input data-f="unit"></td>
  <td><input data-f="price" class="num" inputmode="decimal"></td>
  <td><select data-f="price_unit">${PRICE_UNITS.map(u => `<option value="${u}">je ${u.toLocaleString('de-DE')}</option>`).join('')}</select></td>
  <td><input data-f="markup" class="num" inputmode="decimal"></td>
  <td class="c" data-o="unit"></td><td class="c" data-o="total"></td>
  <td><button type="button" class="link err" title="Position entfernen" data-del>✕</button></td></tr>`;
}
function renderRows() {
  $('#rows').innerHTML = S.items.map((_, i) => rowHtml(i)).join('');
  $$('#rows tr').forEach(tr => {
    const it = S.items[+tr.dataset.i];
    $$('[data-f]', tr).forEach(el => {
      el.value = it[el.dataset.f] ?? '';
      el.oninput = () => { it[el.dataset.f] = el.value; recalc(); };
    });
    $('[data-del]', tr).onclick = () => { S.items.splice(+tr.dataset.i, 1); renderRows(); };
  });
  recalc();
}
function calc() {
  let net = 0, cost = 0;
  const lines = S.items.map(it => {
    const m = own(it) ? num(it.markup) : num(S.global_markup);
    const basis = num(it.price_unit) || 1;
    const unit = r2(num(it.price) * (1 + m / 100));
    const total = r2(num(it.qty) * unit / basis);
    net += total; cost += r2(num(it.qty) * num(it.price) / basis);
    return { unit, total, basis };
  });
  net = r2(net); const tax = r2(net * RATE / 100);
  return { lines, net, cost: r2(cost), tax, gross: net + tax };
}
function recalc() {
  const c = calc();
  $$('#rows tr').forEach(tr => {
    const i = +tr.dataset.i, it = S.items[i], l = c.lines[i];
    $('[data-o=unit]', tr).innerHTML = `${eur(l.unit)} €<div class="mute" style="font-size:11px">je ${l.basis.toLocaleString('de-DE')} ${it.unit || ''}</div>`;
    $('[data-o=total]', tr).textContent = eur(l.total) + ' €';
    const mk = $('[data-f=markup]', tr); mk.classList.toggle('own', own(it)); mk.placeholder = S.global_markup === '' ? '0' : String(S.global_markup);
    tr.classList.toggle('mm', !!it.mismatch);
    tr.title = it.mismatch ? 'Menge × Preis passt nicht zum Positionswert der Lieferantenrechnung – Preiseinheit prüfen' : '';
  });
  $('#totals').innerHTML = `<div class="mute"><span>Einkauf netto</span><span>${eur(c.cost)} €</span></div>
   <div class="mute"><span>Aufschlag gesamt</span><span>${eur(c.net - c.cost)} €</span></div>
   <div><span>Summe netto</span><span>${eur(c.net)} €</span></div>
   <div><span>${RATE ? 'zzgl. USt ' + RATE.toLocaleString('de-DE') + ' %' : 'USt (Kleinunternehmer)'}</span><span>${eur(c.tax)} €</span></div>
   <div class="grand"><span>Gesamtbetrag</span><span>${eur(c.gross)} €</span></div>`;
}
$('#add').onclick = () => { S.items.push({ article: '', description: '', qty: '1', unit: 'ST', price: '0', price_unit: '1', markup: '' }); renderRows(); };
renderRows();

// ---- Speichern / Erzeugen
function payload() {
  return { meta: S.meta, customer: cust, items: S.items, global_markup: S.global_markup,
    save_customer: $('#save-customer').checked, as_new: $('#as-new').checked };
}
async function post(path, btn) {
  btn.disabled = true; $('#errors').innerHTML = '';
  try {
    const r = await fetch(`/api/invoice/${INIT.iid}/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) });
    const j = await r.json();
    if (j.customer_id !== undefined && j.customer_id !== null) { cust.id = j.customer_id; pristine = { ...cust }; if (!CUSTS.find(c => c.id === cust.id)) { CUSTS.push({ ...cust }); sel.add(new Option(`${cust.name}, ${cust.zip} ${cust.city} (Nr. ${cust.id})`, cust.id)); } $('#as-new').checked = false; fillCustomer(); }
    if (!j.ok) { $('#errors').innerHTML = `<div class="banner err"><b>Noch nicht möglich:</b><ul>${j.errors.map(e => `<li>${e.replace(/</g, '&lt;')}</li>`).join('')}</ul></div>`; scrollTo(0, 0); return null; }
    return j;
  } finally { btn.disabled = false; }
}
$('#save').onclick = async e => { const j = await post('save', e.target); if (j) $('#status').textContent = 'Gespeichert ' + new Date().toLocaleTimeString('de-DE'); };
$('#make').onclick = async e => {
  const j = await post('pdf', e.target); if (!j) return;
  $('#status').innerHTML = `Erzeugt: <a href="${j.download}">${j.file}</a>`; location.href = j.download;
};
