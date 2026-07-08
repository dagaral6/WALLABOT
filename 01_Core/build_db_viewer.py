"""
build_db_viewer.py
------------------
Genera el VISOR de la base de datos (HTML autónomo) para consultar en GitHub
Pages qué anuncios tiene el bot vistos ahora mismo. Datos embebidos en el HTML
(mismo patrón que 03_Diagnostico/build_review_html.py), SOLO LECTURA de la BD.

Como los anuncios retirados/vendidos se BORRAN de la BD, todo lo que aparece
aquí son anuncios VIVOS/disponibles: los 'keep' (te encajan, con su enlace) y
los 'reject' (descartados, con el motivo en la columna 'category').

Filtros: persona, alerta, decisión, categoría, idioma, rango de precio y texto.

Uso:
    py 01_Core/build_db_viewer.py                 # lee alerts.db, escribe docs/db.html
    py 01_Core/build_db_viewer.py <db> <salida.html>
"""

import os
import sys
import json
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
# Misma resolución que database.DB_PATH (respeta DATA_DIR en cloud).
DEFAULT_DB = os.path.join(os.getenv("DATA_DIR") or BASE, "alerts.db")
DEFAULT_OUT = os.path.normpath(os.path.join(BASE, "..", "docs", "db.html"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_rows(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(seen_items)")}
    desc_sql = "description" if "description" in cols else "'' AS description"
    lang_sql = "language" if "language" in cols else "NULL AS language"
    catid_sql = "category_id" if "category_id" in cols else "NULL AS category_id"
    rows = con.execute(
        f"""SELECT alert_name, item_id, title, price, url, category, decision,
                   {desc_sql}, {lang_sql}, {catid_sql}, first_seen
            FROM seen_items
            ORDER BY first_seen DESC, alert_name, title""").fetchall()
    con.close()
    data = []
    for r in rows:
        alert_name = r["alert_name"] or ""
        persona, _, alerta = alert_name.partition("/")
        if not alerta:            # sin '/': todo es la alerta, sin persona
            persona, alerta = "", alert_name
        data.append({
            "persona": persona,
            "alerta": alerta,
            "alert_name": alert_name,
            "item_id": r["item_id"],
            "title": r["title"] or "",
            "price": r["price"],
            "url": r["url"] or "",
            "category": r["category"] or "",
            "decision": r["decision"] or "",
            "description": r["description"] or "",
            "language": r["language"] or "",
            "category_id": (str(r["category_id"]) if r["category_id"] not in (None, "") else ""),
            "first_seen": r["first_seen"] or "",
        })
    return data


def build_html(data):
    data_js = json.dumps(data, ensure_ascii=False)
    # Escapa </ y los separadores de linea/parrafo (U+2028/U+2029): validos
    # en JSON pero invalidos dentro de un literal JS.
    data_js = (data_js.replace("</", "<\\/")
                      .replace(chr(0x2028), "\\u2028")
                      .replace(chr(0x2029), "\\u2029"))
    return _HTML.replace("__DATA__", data_js)


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    out_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not os.path.exists(db_path):
        print(f"AVISO: no encuentro la BD ({db_path}); genero un visor vacío.")
        data = []
    else:
        data = load_rows(db_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_html(data))
    n_keep = sum(1 for d in data if d["decision"] == "keep")
    n_reject = sum(1 for d in data if d["decision"] == "reject")
    personas = len({d["persona"] for d in data if d["persona"]})
    print(f"BD:     {db_path}")
    print(f"Salida: {out_path}")
    print(f"Anuncios: {len(data)}  (keep={n_keep}, reject={n_reject}, personas={personas})")
    return 0


# ===========================================================================
#  Plantilla HTML (datos embebidos en __DATA__)
# ===========================================================================
_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Base de datos · Wallapop Alerts</title>
<style>
  :root{
    --bg:#eef2f3; --surface:#ffffff; --ink:#15242b; --muted:#637780;
    --line:#dde5e8; --line-strong:#cdd8dc;
    --accent:#0e8f78; --accent-soft:#e3f4f0;
    --base:#2b5f8a; --base-soft:#e6eff7;
    --lote:#6d4aa6; --lote-soft:#efe9f8;
    --expansion:#0c7c6b; --expansion-soft:#e2f3f0;
    --warn:#b4690e; --warn-soft:#fff4e2; --warn-line:#f0d6a8;
    --mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{font-family:var(--sans);color:var(--ink);background:var(--bg);font-size:14px;line-height:1.45}
  a{color:var(--accent);text-decoration:none}
  a:hover{text-decoration:underline}

  header{position:sticky;top:0;z-index:30;background:var(--surface);border-bottom:1px solid var(--line-strong)}
  .head-inner{max-width:1320px;margin:0 auto;padding:14px 18px 12px}
  .eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:600}
  h1{margin:2px 0 0;font-size:19px;font-weight:680;letter-spacing:-.01em}
  h1 .count{color:var(--accent)}
  .sub{color:var(--muted);font-size:12.5px;margin-top:3px}
  .sub a{font-weight:600}

  .stats{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
  .stat{flex:1 1 110px;min-width:92px;border:1px solid var(--line);border-radius:9px;padding:7px 10px;background:#fbfcfc}
  .stat .n{font-family:var(--mono);font-size:18px;font-weight:600;letter-spacing:-.02em}
  .stat .l{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin-top:1px}
  .stat.keep .n{color:#1f6b4e}
  .stat.reject .n{color:var(--warn)}

  .toolbar{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}
  .tb-inner{max-width:1320px;margin:0 auto;padding:10px 18px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .search{flex:1 1 220px;min-width:170px;position:relative}
  .search input{width:100%;padding:8px 10px 8px 30px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);font:inherit}
  .search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);opacity:.5}
  select,.btn,.num{font:inherit;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);padding:8px 10px;color:var(--ink)}
  select,.btn{cursor:pointer}
  select{padding-right:26px}
  .num{width:96px}
  .btn:hover{border-color:var(--accent);color:var(--accent)}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  .btn.primary:hover{filter:brightness(1.06);color:#fff}
  .btn.ghost{background:transparent}
  .spacer{flex:1 1 auto}
  .price-range{display:inline-flex;gap:6px;align-items:center;color:var(--muted);font-size:12px}

  .wrap{max-width:1320px;margin:0 auto;padding:14px 18px 80px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line-strong);border-radius:12px;overflow:hidden}
  thead th{position:sticky;top:0;background:#f3f6f7;text-align:left;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600;padding:9px 12px;border-bottom:1px solid var(--line-strong);z-index:5;white-space:nowrap}
  tbody td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
  tbody tr:last-child td{border-bottom:0}
  tbody tr{border-left:3px solid transparent}
  tbody tr.keep{border-left-color:var(--accent)}
  tbody tr.reject{border-left-color:var(--warn-line)}
  tbody tr:hover{background:#f7fafa}

  .c-idx{width:36px;color:var(--muted);font-family:var(--mono);font-size:12px;text-align:right}
  .c-price{width:96px}
  .c-who{width:150px}
  .c-cat{width:150px}
  .c-date{width:120px}

  .title{font-weight:560;letter-spacing:-.005em}
  .desc{margin-top:5px;font-size:12px;color:#4a5b62;max-width:640px;
        display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}
  .desc.expanded{-webkit-line-clamp:unset;display:block}
  .id{display:block;margin-top:4px;font-family:var(--mono);font-size:10.5px;color:var(--muted);opacity:.8}
  .price{font-family:var(--mono);font-weight:600}
  .who .p{font-weight:600}
  .who .a{display:block;font-size:12px;color:var(--muted)}
  .date{font-family:var(--mono);font-size:12px;color:var(--muted)}

  .badge{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.02em;padding:3px 9px;border-radius:99px;border:1px solid transparent}
  .badge.base{color:var(--base);background:var(--base-soft);border-color:#cfe0ee}
  .badge.lote{color:var(--lote);background:var(--lote-soft);border-color:#ddd2ee}
  .badge.expansion{color:var(--expansion);background:var(--expansion-soft);border-color:#c9e8e2}
  .badge.other{color:var(--muted);background:#eef1f2;border-color:var(--line-strong)}
  .badge.keep{color:#1f6b4e;background:#e4f3ec;border-color:#c5e6d6}
  .badge.reject{color:var(--warn);background:var(--warn-soft);border-color:var(--warn-line)}
  .lang{display:inline-block;margin-top:5px;font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:5px;border:1px solid transparent}
  .lang.es{color:#1f6b4e;background:#e4f3ec;border-color:#c5e6d6}
  .lang.ca{color:#7a3ea0;background:#f1e8f8;border-color:#e0cef0}
  .lang.en{color:#235b8c;background:#e6eff7;border-color:#cfe0ee}
  .lang.otro{color:#9a5a12;background:#fbeedd;border-color:#f0d6a8}
  .lang.none{color:var(--muted);background:#eef1f2;border-color:var(--line-strong)}

  .empty-row td{padding:40px;text-align:center;color:var(--muted)}

  @media (max-width:640px){
    .head-inner,.tb-inner,.wrap{padding-left:12px;padding-right:12px}
    .c-who,.c-cat,.c-date{width:auto}.stat{flex-basis:30%}
  }
</style>
</head>
<body>
<header>
  <div class="head-inner">
    <div class="eyebrow">Wallapop Alerts · base de datos</div>
    <h1>Anuncios en seguimiento <span class="count" id="hCount">0</span></h1>
    <div class="sub">Todo lo que aparece aquí está <b>disponible ahora</b> (los retirados se borran).
      <b>keep</b> = te encaja, con su enlace · <b>reject</b> = descartado, con el motivo en «categoría».
      · <a href="./index.html">← Volver al configurador</a></div>

    <div class="stats">
      <div class="stat"><div class="n" id="sTotal">0</div><div class="l">Total</div></div>
      <div class="stat keep"><div class="n" id="sKeep">0</div><div class="l">Notificados (keep)</div></div>
      <div class="stat reject"><div class="n" id="sReject">0</div><div class="l">Descartados (reject)</div></div>
      <div class="stat"><div class="n" id="sPersonas">0</div><div class="l">Personas</div></div>
      <div class="stat"><div class="n" id="sAlertas">0</div><div class="l">Alertas</div></div>
      <div class="stat"><div class="n" id="sShown">0</div><div class="l">Mostrados</div></div>
    </div>
  </div>
</header>

<div class="toolbar">
  <div class="tb-inner">
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="Buscar en título o descripción…" autocomplete="off">
    </div>
    <select id="fPersona"><option value="">Todas las personas</option></select>
    <select id="fAlerta"><option value="">Todas las alertas</option></select>
    <select id="fDecision">
      <option value="">keep + reject</option>
      <option value="keep">solo keep</option>
      <option value="reject">solo reject</option>
    </select>
    <select id="fCat"><option value="">Categorías / motivos</option></select>
    <select id="fLang">
      <option value="">Todos los idiomas</option>
      <option value="es">es</option><option value="ca">ca</option>
      <option value="en">en</option><option value="otro">otro</option>
    </select>
    <span class="price-range">€ <input class="num" id="fMin" type="number" placeholder="mín" min="0"> – <input class="num" id="fMax" type="number" placeholder="máx" min="0"></span>
    <select id="fSort">
      <option value="recent">Más recientes</option>
      <option value="price_asc">Precio ↑</option>
      <option value="price_desc">Precio ↓</option>
      <option value="title">Título A→Z</option>
    </select>
    <span class="spacer"></span>
    <button class="btn ghost" id="bReset">Limpiar filtros</button>
    <button class="btn primary" id="bCsv">Exportar CSV</button>
  </div>
</div>

<div class="wrap">
  <table>
    <thead>
      <tr>
        <th class="c-idx">#</th>
        <th>Anuncio</th>
        <th class="c-price">Precio</th>
        <th class="c-who">Persona · alerta</th>
        <th class="c-cat">Decisión · categoría</th>
        <th class="c-date">Visto</th>
      </tr>
    </thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<script>
const DATA = __DATA__;
const $ = id => document.getElementById(id);
const tb = $("tb");

function fmtPrice(p){
  if(p === null || p === undefined || p === "") return "—";
  const n = Number(p);
  if(Number.isNaN(n)) return "—";
  return (Number.isInteger(n) ? n.toString() : n.toFixed(2)) + " €";
}
function fmtDate(s){ return s ? String(s).slice(0, 10) : "—"; }
function catClass(c){ return ["base","lote","expansion"].includes(c) ? c : "other"; }
function langClass(l){ return ["es","ca","en","otro"].includes(l) ? l : "none"; }

function currentList(){
  const q = $("q").value.trim().toLowerCase();
  const persona = $("fPersona").value;
  const alerta = $("fAlerta").value;
  const dec = $("fDecision").value;
  const cat = $("fCat").value;
  const lang = $("fLang").value;
  const min = $("fMin").value === "" ? null : Number($("fMin").value);
  const max = $("fMax").value === "" ? null : Number($("fMax").value);
  let list = DATA.filter(d => {
    if(persona && d.persona !== persona) return false;
    if(alerta && d.alerta !== alerta) return false;
    if(dec && d.decision !== dec) return false;
    if(cat && d.category !== cat) return false;
    if(lang && (d.language || "") !== lang) return false;
    if(min !== null && (d.price === null || Number(d.price) < min)) return false;
    if(max !== null && (d.price === null || Number(d.price) > max)) return false;
    if(q && !(d.title.toLowerCase().includes(q) || (d.description||"").toLowerCase().includes(q))) return false;
    return true;
  });
  const sort = $("fSort").value;
  const num = p => (p === null || p === undefined || p === "") ? Infinity : Number(p);
  if(sort === "price_asc") list = list.slice().sort((a,b) => num(a.price) - num(b.price));
  else if(sort === "price_desc") list = list.slice().sort((a,b) => num(b.price) - num(a.price));
  else if(sort === "title") list = list.slice().sort((a,b) => a.title.localeCompare(b.title, "es"));
  else list = list.slice().sort((a,b) => String(b.first_seen).localeCompare(String(a.first_seen)));
  return list;
}

function buildRow(d, n){
  const tr = document.createElement("tr");
  tr.className = d.decision === "keep" ? "keep" : (d.decision === "reject" ? "reject" : "");

  const tdIdx = document.createElement("td"); tdIdx.className = "c-idx"; tdIdx.textContent = n;

  const tdAd = document.createElement("td");
  const a = document.createElement("a"); a.className = "title"; a.textContent = d.title || "(sin título)";
  if(d.url){ a.href = d.url; a.target = "_blank"; a.rel = "noopener"; }
  tdAd.appendChild(a);
  const dtext = (d.description || "").trim();
  if(dtext){
    const desc = document.createElement("div"); desc.className = "desc";
    desc.textContent = dtext; desc.title = "Clic para expandir/contraer";
    desc.addEventListener("click", () => desc.classList.toggle("expanded"));
    tdAd.appendChild(desc);
  }
  const idEl = document.createElement("span"); idEl.className = "id"; idEl.textContent = "#" + d.item_id;
  tdAd.appendChild(idEl);

  const tdPrice = document.createElement("td"); tdPrice.className = "c-price";
  const pr = document.createElement("span"); pr.className = "price"; pr.textContent = fmtPrice(d.price);
  tdPrice.appendChild(pr);

  const tdWho = document.createElement("td"); tdWho.className = "c-who who";
  const pp = document.createElement("span"); pp.className = "p"; pp.textContent = d.persona || "—";
  const aa = document.createElement("span"); aa.className = "a"; aa.textContent = d.alerta || d.alert_name;
  tdWho.append(pp, aa);

  const tdCat = document.createElement("td"); tdCat.className = "c-cat";
  const dec = document.createElement("span"); dec.className = "badge " + (d.decision === "keep" ? "keep" : "reject");
  dec.textContent = d.decision || "—";
  const bd = document.createElement("span"); bd.className = "badge " + catClass(d.category);
  bd.textContent = d.category || "—";
  if(d.decision === "reject") bd.title = "Motivo de rechazo del bot";
  const lg = document.createElement("span"); lg.className = "lang " + langClass(d.language);
  lg.textContent = d.language || "?";
  tdCat.append(dec, document.createTextNode(" "), bd, document.createElement("br"), lg);

  const tdDate = document.createElement("td"); tdDate.className = "c-date";
  const dt = document.createElement("span"); dt.className = "date"; dt.textContent = fmtDate(d.first_seen);
  tdDate.appendChild(dt);

  tr.append(tdIdx, tdAd, tdPrice, tdWho, tdCat, tdDate);
  return tr;
}

function render(){
  const list = currentList();
  tb.textContent = "";
  $("sShown").textContent = list.length;
  if(list.length === 0){
    const tr = document.createElement("tr"); tr.className = "empty-row";
    const td = document.createElement("td"); td.colSpan = 6;
    td.textContent = "Ningún anuncio coincide con el filtro.";
    tr.appendChild(td); tb.appendChild(tr); return;
  }
  const frag = document.createDocumentFragment();
  list.forEach((d, i) => frag.appendChild(buildRow(d, i + 1)));
  tb.appendChild(frag);
}

function fillSelect(sel, values){
  for(const v of values){ const o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); }
}
function uniq(key){ return [...new Set(DATA.map(d => d[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),"es")); }

function initStats(){
  $("hCount").textContent = DATA.length;
  $("sTotal").textContent = DATA.length;
  $("sKeep").textContent = DATA.filter(d => d.decision === "keep").length;
  $("sReject").textContent = DATA.filter(d => d.decision === "reject").length;
  $("sPersonas").textContent = new Set(DATA.map(d => d.persona).filter(Boolean)).size;
  $("sAlertas").textContent = new Set(DATA.map(d => d.alert_name).filter(Boolean)).size;
}

function csvCell(v){
  if(v === null || v === undefined) v = "";
  v = String(v);
  return /[",\n]/.test(v) ? '"' + v.replace(/"/g,'""') + '"' : v;
}
function exportCsv(){
  const cols = ["persona","alerta","title","price","decision","category","language","category_id","url","first_seen","item_id"];
  const lines = [cols.join(",")];
  for(const d of currentList()) lines.push(cols.map(c => csvCell(d[c])).join(","));
  const blob = new Blob(["﻿" + lines.join("\n")], {type:"text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "wallabot_db.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let qT = null;
$("q").addEventListener("input", () => { clearTimeout(qT); qT = setTimeout(render, 150); });
["fPersona","fAlerta","fDecision","fCat","fLang","fSort"].forEach(id => $(id).addEventListener("change", render));
["fMin","fMax"].forEach(id => $(id).addEventListener("input", () => { clearTimeout(qT); qT = setTimeout(render, 200); }));
$("bReset").addEventListener("click", () => {
  ["q","fMin","fMax"].forEach(id => $(id).value = "");
  ["fPersona","fAlerta","fDecision","fCat","fLang"].forEach(id => $(id).value = "");
  $("fSort").value = "recent"; render();
});
$("bCsv").addEventListener("click", exportCsv);

fillSelect($("fPersona"), uniq("persona"));
fillSelect($("fAlerta"), uniq("alerta"));
fillSelect($("fCat"), uniq("category"));
initStats();
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
