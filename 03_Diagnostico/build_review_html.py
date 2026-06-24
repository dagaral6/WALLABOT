"""
build_review_html.py
--------------------
Genera la tabla de revisión interactiva (HTML autónomo) a partir de la BD,
para etiquetar el dataset de reentrenamiento del clasificador/NLI.

Saca TODOS los anuncios vistos: los NOTIFICADOS (decision = 'keep', con
descripción) y los DESCARTADOS (decision = 'reject'; sin descripción guardada,
pero con su motivo de rechazo en la columna 'category': no_title_match,
foreign_language, excluded, components...). Por cada fila: título, idioma
detectado, categoría/motivo, precio, enlace, alerta y decisión. Cada fila lleva
una casilla "¿Bien clasificado?" y un campo "motivo / categoría correcta".
Filtros por alerta y por decisión (keep/reject) para revisar sin ruido.
El HTML exporta a JSONL (listo para afinar el NLI) y CSV, e importa de vuelta
para retomar el trabajo.

Uso:
    py build_review_html.py
    py build_review_html.py <ruta_alerts.db> <salida.html>

Por defecto lee ../01_Core/alerts.db y escribe wallapop_revision_keep.html junto
a este script. SOLO LECTURA de la BD (si faltan columnas description/language
las trata como vacías, no modifica la BD).
"""

import os
import sys
import json
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(BASE, "..", "01_Core", "alerts.db"))
DEFAULT_OUT = os.path.join(BASE, "wallapop_revision_keep.html")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_rows(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cols = {r["name"] for r in con.execute("PRAGMA table_info(seen_items)")}
    has_desc = "description" in cols
    has_lang = "language" in cols
    has_catid = "category_id" in cols
    desc_sql = "description" if has_desc else "'' AS description"
    lang_sql = "language" if has_lang else "NULL AS language"
    catid_sql = "category_id" if has_catid else "NULL AS category_id"
    # keep + reject. keep primero; los reject no tienen descripcion guardada pero
    # si su motivo de rechazo en 'category'.
    rows = con.execute(
        f"""SELECT alert_name, item_id, title, price, url, category, decision,
                   {desc_sql}, {lang_sql}, {catid_sql}, first_seen
            FROM seen_items
            ORDER BY decision DESC, alert_name, category, title""").fetchall()
    con.close()
    data = []
    for r in rows:
        data.append({
            "alert_name": r["alert_name"],
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
    return data, has_desc, has_lang


def build_html(data):
    data_js = json.dumps(data, ensure_ascii=False)
    data_js = (data_js.replace("</", "<\\/")
                      .replace("\u2028", "\\u2028")
                      .replace("\u2029", "\\u2029"))
    return _HTML.replace("__DATA__", data_js)


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    out_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not os.path.exists(db_path):
        print(f"ERROR: no encuentro la BD: {db_path}")
        return 1
    data, has_desc, has_lang = load_rows(db_path)
    html = build_html(data)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    n_keep = sum(1 for d in data if d["decision"] == "keep")
    n_reject = sum(1 for d in data if d["decision"] == "reject")
    con_desc = sum(1 for d in data if d["description"].strip())
    print(f"BD:     {db_path}")
    print(f"Salida: {out_path}")
    print(f"Anuncios: {len(data)}  (keep={n_keep}, reject={n_reject})")
    print(f"  con descripción guardada: {con_desc}"
          + ("" if has_desc else "  (columna 'description' AUSENTE en la BD)"))
    if not has_lang:
        print("  AVISO: columna 'language' ausente en la BD.")
    return 0


# ===========================================================================
#  Plantilla HTML (datos embebidos en __DATA__)
# ===========================================================================
_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de clasificación · Wallapop Alerts</title>
<style>
  :root{
    --bg:#eef2f3; --surface:#ffffff; --ink:#15242b; --muted:#637780;
    --line:#dde5e8; --line-strong:#cdd8dc;
    --accent:#0e8f78; --accent-soft:#e3f4f0;
    --warn:#b4690e; --warn-soft:#fff4e2; --warn-line:#f0d6a8;
    --base:#2b5f8a; --base-soft:#e6eff7;
    --lote:#6d4aa6; --lote-soft:#efe9f8;
    --expansion:#0c7c6b; --expansion-soft:#e2f3f0;
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

  .stats{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
  .stat{flex:1 1 110px;min-width:96px;border:1px solid var(--line);border-radius:9px;padding:7px 10px;background:#fbfcfc}
  .stat .n{font-family:var(--mono);font-size:18px;font-weight:600;letter-spacing:-.02em}
  .stat .l{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin-top:1px}
  .stat.mal .n{color:var(--warn)}
  .stat.rev .n{color:var(--accent)}

  .progress{margin-top:11px}
  .bar{height:7px;border-radius:99px;background:var(--line);overflow:hidden}
  .bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .25s ease}
  .progress .cap{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:5px}
  .save-flag{font-size:11px;color:var(--accent);opacity:0;transition:opacity .3s}
  .save-flag.on{opacity:1}

  .toolbar{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line)}
  .tb-inner{max-width:1320px;margin:0 auto;padding:10px 18px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .search{flex:1 1 220px;min-width:170px;position:relative}
  .search input{width:100%;padding:8px 10px 8px 30px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);font:inherit}
  .search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);opacity:.5}
  select,.btn{font:inherit;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);padding:8px 10px;cursor:pointer;color:var(--ink)}
  select{padding-right:26px}
  .btn:hover{border-color:var(--accent);color:var(--accent)}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  .btn.primary:hover{filter:brightness(1.06);color:#fff}
  .btn.ghost{background:transparent}
  .spacer{flex:1 1 auto}
  .seg{display:inline-flex;border:1px solid var(--line-strong);border-radius:8px;overflow:hidden}
  .seg button{font:inherit;border:0;background:var(--surface);padding:8px 11px;cursor:pointer;color:var(--muted);border-left:1px solid var(--line)}
  .seg button:first-child{border-left:0}
  .seg button.active{background:var(--ink);color:#fff}

  .wrap{max-width:1320px;margin:0 auto;padding:14px 18px 80px;overflow-x:auto}
  table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line-strong);border-radius:12px;overflow:hidden}
  thead th{position:sticky;top:0;background:#f3f6f7;text-align:left;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600;padding:9px 12px;border-bottom:1px solid var(--line-strong);z-index:5;white-space:nowrap}
  tbody td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
  tbody tr:last-child td{border-bottom:0}
  tbody tr{border-left:3px solid transparent}
  tbody tr.reviewed{border-left-color:var(--accent)}
  tbody tr.flagged{background:var(--warn-soft);border-left-color:var(--warn)}
  tbody tr:hover{background:#f7fafa}
  tbody tr.flagged:hover{background:#fdeed6}

  .c-idx{width:36px;color:var(--muted);font-family:var(--mono);font-size:12px;text-align:right}
  .c-rev{width:70px;text-align:center}
  .c-cat{width:128px}
  .c-ok{width:116px;text-align:center}
  .c-mot{min-width:220px}

  .title{font-weight:560;letter-spacing:-.005em}
  .meta{margin-top:3px;font-size:11.5px;color:var(--muted);display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .meta .price{font-family:var(--mono);color:var(--ink);font-weight:600}
  .meta .alert{padding:1px 6px;border:1px solid var(--line-strong);border-radius:99px;background:#fafbfb}
  .meta .id{font-family:var(--mono);font-size:10.5px;opacity:.7}

  .desc{margin-top:6px;font-size:12.5px;color:#36474e;background:#f6f9f9;border:1px solid var(--line);border-radius:7px;padding:7px 9px;white-space:pre-wrap;
        display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer;max-width:680px}
  .desc.expanded{-webkit-line-clamp:unset;display:block}
  .desc.empty{color:var(--muted);font-style:italic;background:transparent;border-style:dashed;cursor:default}
  .desc .more{display:block;margin-top:4px;font-size:11px;color:var(--accent);font-weight:600}

  .badge{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.02em;padding:3px 9px;border-radius:99px;border:1px solid transparent}
  .badge.base{color:var(--base);background:var(--base-soft);border-color:#cfe0ee}
  .badge.lote{color:var(--lote);background:var(--lote-soft);border-color:#ddd2ee}
  .badge.expansion{color:var(--expansion);background:var(--expansion-soft);border-color:#c9e8e2}
  .badge.other{color:var(--muted);background:#eef1f2;border-color:var(--line-strong)}
  .badge.keep{color:#1f6b4e;background:#e4f3ec;border-color:#c5e6d6}
  .badge.reject{color:var(--warn);background:var(--warn-soft);border-color:var(--warn-line)}
  .lang{display:inline-block;margin-top:6px;font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;padding:2px 7px;border-radius:5px;border:1px solid transparent}
  .lang.es{color:#1f6b4e;background:#e4f3ec;border-color:#c5e6d6}
  .lang.ca{color:#7a3ea0;background:#f1e8f8;border-color:#e0cef0}
  .lang.en{color:#235b8c;background:#e6eff7;border-color:#cfe0ee}
  .lang.otro{color:#9a5a12;background:#fbeedd;border-color:#f0d6a8}
  .lang.none{color:var(--muted);background:#eef1f2;border-color:var(--line-strong)}
  .deco{display:block;margin-top:4px;font-size:10.5px;color:var(--muted);font-family:var(--mono)}

  label.chk{display:inline-flex;gap:7px;align-items:center;cursor:pointer;font-size:12px;color:var(--muted);user-select:none}
  label.chk input{width:17px;height:17px;accent-color:var(--accent);cursor:pointer;margin:0}
  tr.flagged .c-ok label.chk{color:var(--warn);font-weight:600}

  .mot-in{width:100%;padding:7px 9px;border:1px dashed var(--line-strong);border-radius:7px;background:#fbfcfc;font:inherit;resize:vertical;min-height:34px;color:var(--ink)}
  .mot-in:focus{outline:none;border-style:solid;border-color:var(--accent);background:#fff}
  tr.flagged .mot-in{border-style:solid;border-color:var(--warn-line);background:#fffaf0}
  .mot-in::placeholder{color:#9fb0b7}

  .empty-row td{padding:40px;text-align:center;color:var(--muted)}
  .note{max-width:1320px;margin:0 auto;padding:0 18px 30px;color:var(--muted);font-size:12px}
  .note code{font-family:var(--mono);background:#e7edee;padding:1px 5px;border-radius:4px}
  .nostore{display:none;max-width:1320px;margin:8px auto 0;padding:8px 12px;border:1px solid var(--warn-line);background:var(--warn-soft);color:var(--warn);border-radius:8px;font-size:12px}
  .nostore.show{display:block}
  input[type=file]{display:none}

  @media (max-width:640px){
    .head-inner,.tb-inner,.wrap,.note{padding-left:12px;padding-right:12px}
    .c-cat{width:auto}.stat{flex-basis:30%}
  }
</style>
</head>
<body>
<header>
  <div class="head-inner">
    <div class="eyebrow">Wallapop Alerts · entrenamiento del clasificador</div>
    <h1>Revisión de anuncios <span class="count" id="hCount">0</span></h1>
    <div class="sub">Anuncios <b>keep</b> (notificados, con descripción) y <b>reject</b> (descartados; sin descripción, con el motivo de rechazo en «categoría»). Marca si la clasificación es correcta; si no, escribe el motivo. Filtra por alerta y decisión. Exporta a JSONL para afinar el NLI.</div>

    <div class="stats">
      <div class="stat"><div class="n" id="sTotal">0</div><div class="l">Total</div></div>
      <div class="stat rev"><div class="n" id="sRev">0</div><div class="l">Revisados</div></div>
      <div class="stat"><div class="n" id="sOk">0</div><div class="l">Bien clasif.</div></div>
      <div class="stat mal"><div class="n" id="sMal">0</div><div class="l">Mal clasif.</div></div>
      <div class="stat"><div class="n" id="sMot">0</div><div class="l">Con motivo</div></div>
    </div>

    <div class="progress">
      <div class="bar"><i id="bar"></i></div>
      <div class="cap"><span id="capTxt">0 revisados</span><span class="save-flag" id="saveFlag">guardado ✓</span></div>
    </div>
  </div>
</header>

<div class="toolbar">
  <div class="tb-inner">
    <div class="search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="Buscar en título o descripción…" autocomplete="off">
    </div>
    <select id="fAlert">
      <option value="">Todas las alertas</option>
    </select>
    <select id="fDecision">
      <option value="">keep + reject</option>
      <option value="keep">solo keep</option>
      <option value="reject">solo reject</option>
    </select>
    <select id="fCat">
      <option value="">Categorías / motivos</option>
    </select>
    <select id="fLang">
      <option value="">Todos los idiomas</option>
      <option value="es">es</option>
      <option value="ca">ca</option>
      <option value="en">en</option>
      <option value="otro">otro</option>
    </select>
    <div class="seg" id="fStatus">
      <button data-v="all" class="active">Todos</button>
      <button data-v="pending">Pendientes</button>
      <button data-v="done">Revisados</button>
      <button data-v="bad">Mal clasif.</button>
    </div>
    <span class="spacer"></span>
    <button class="btn ghost" id="bMarkVisible" title="Marca como revisados los anuncios filtrados ahora mismo">Marcar visibles ✓</button>
    <button class="btn ghost" id="bImport">Importar…</button>
    <button class="btn" id="bCsv">CSV</button>
    <button class="btn primary" id="bJsonl">Exportar JSONL</button>
    <input type="file" id="file" accept=".json,.jsonl,.txt">
  </div>
</div>

<div class="nostore" id="nostore">El autoguardado no está disponible en este entorno. Tus marcas se mantienen mientras no recargues; usa <b>Exportar JSONL</b> para conservarlas.</div>

<div class="wrap">
  <table>
    <thead>
      <tr>
        <th class="c-idx">#</th>
        <th class="c-rev">Revisado</th>
        <th>Anuncio · descripción</th>
        <th class="c-cat">Decisión · categoría · idioma</th>
        <th class="c-ok">¿Bien clasificado?</th>
        <th class="c-mot">Motivo / categoría correcta</th>
      </tr>
    </thead>
    <tbody id="tb"></tbody>
  </table>
</div>

<div class="note">
  El JSONL incluye por anuncio: <code>item_id</code>, <code>title</code>, <code>description</code>, <code>language</code>, <code>category_id</code> (categoría nativa Wallapop), <code>category</code> (la del bot), <code>decision</code>, <code>price</code>, <code>url</code>, <code>alert_name</code>, <code>bien_clasificado</code>, <code>motivo</code> y <code>revisado</code>. Cargando ese mismo archivo con <b>Importar</b> recuperas el estado.
</div>

<script>
const DATA = __DATA__;
const STORAGE_KEY = "wallapop_review_keep_v2";
const TOTAL = DATA.length;

const useStore = (typeof window !== "undefined" && window.storage && typeof window.storage.get === "function");
if(!useStore){ document.getElementById("nostore").classList.add("show"); }

const edits = {};
DATA.forEach(d => { edits[d.item_id] = {r:false, ok:true, m:""}; });

const $ = id => document.getElementById(id);
const tb = $("tb");
$("hCount").textContent = TOTAL;

function fmtPrice(p){
  if(p === null || p === undefined) return "—";
  const n = Number(p);
  return (Number.isInteger(n) ? n.toString() : n.toFixed(2)) + " €";
}
function catClass(c){ return ["base","lote","expansion"].includes(c) ? c : "other"; }
function langClass(l){ return ["es","ca","en","otro"].includes(l) ? l : "none"; }

let fStatus = "all";
function currentList(){
  const q = $("q").value.trim().toLowerCase();
  const cat = $("fCat").value;
  const lang = $("fLang").value;
  const alert = $("fAlert").value;
  const dec = $("fDecision").value;
  return DATA.filter(d => {
    if(alert && d.alert_name !== alert) return false;
    if(dec && d.decision !== dec) return false;
    if(cat && d.category !== cat) return false;
    if(lang && (d.language || "") !== lang) return false;
    if(q && !(d.title.toLowerCase().includes(q) || (d.description||"").toLowerCase().includes(q))) return false;
    const e = edits[d.item_id];
    if(fStatus === "pending" && e.r) return false;
    if(fStatus === "done" && !e.r) return false;
    if(fStatus === "bad" && e.ok) return false;
    return true;
  });
}

function render(){
  const list = currentList();
  tb.textContent = "";
  if(list.length === 0){
    const tr = document.createElement("tr"); tr.className = "empty-row";
    const td = document.createElement("td"); td.colSpan = 6;
    td.textContent = "Ningún anuncio coincide con el filtro.";
    tr.appendChild(td); tb.appendChild(tr); return;
  }
  const frag = document.createDocumentFragment();
  list.forEach((d, i) => frag.appendChild(buildRow(d, i+1)));
  tb.appendChild(frag);
}

function buildRow(d, n){
  const e = edits[d.item_id];
  const tr = document.createElement("tr");
  tr.dataset.id = d.item_id;

  const tdIdx = document.createElement("td"); tdIdx.className = "c-idx"; tdIdx.textContent = n;

  const tdRev = document.createElement("td"); tdRev.className = "c-rev";
  const labR = document.createElement("label"); labR.className = "chk";
  const cbR = document.createElement("input"); cbR.type = "checkbox"; cbR.checked = e.r;
  labR.appendChild(cbR); tdRev.appendChild(labR);

  const tdAd = document.createElement("td");
  const a = document.createElement("a"); a.className = "title"; a.textContent = d.title || "(sin título)";
  if(d.url){ a.href = d.url; a.target = "_blank"; a.rel = "noopener"; }
  const meta = document.createElement("div"); meta.className = "meta";
  const sp = document.createElement("span"); sp.className = "price"; sp.textContent = fmtPrice(d.price);
  const al = document.createElement("span"); al.className = "alert"; al.textContent = d.alert_name;
  const id = document.createElement("span"); id.className = "id"; id.textContent = d.item_id;
  meta.append(sp, al, id);
  const desc = document.createElement("div"); desc.className = "desc";
  const dtext = (d.description || "").trim();
  if(dtext){
    desc.textContent = dtext;
    desc.title = "Clic para expandir/contraer";
    desc.addEventListener("click", () => desc.classList.toggle("expanded"));
  }else{
    desc.classList.add("empty");
    desc.textContent = "(sin descripción guardada)";
  }
  tdAd.append(a, meta, desc);

  const tdCat = document.createElement("td"); tdCat.className = "c-cat";
  const dec = document.createElement("span"); dec.className = "badge " + (d.decision === "keep" ? "keep" : "reject");
  dec.textContent = d.decision || "—";
  const bd = document.createElement("span"); bd.className = "badge " + catClass(d.category);
  bd.textContent = (d.category || "—") + (d.decision === "reject" ? " · motivo" : "");
  if(d.decision === "reject") bd.title = "Motivo de rechazo del bot";
  const lg = document.createElement("span"); lg.className = "lang " + langClass(d.language);
  lg.textContent = d.language || "?";
  const cat = document.createElement("span"); cat.className = "deco";
  cat.textContent = d.category_id ? ("cat. Wallapop #" + d.category_id) : "cat. Wallapop: ?";
  tdCat.append(dec, document.createTextNode(" "), bd, document.createElement("br"), lg, cat);

  const tdOk = document.createElement("td"); tdOk.className = "c-ok";
  const labO = document.createElement("label"); labO.className = "chk";
  const cbO = document.createElement("input"); cbO.type = "checkbox"; cbO.checked = e.ok;
  const txtO = document.createElement("span"); txtO.textContent = e.ok ? "Correcto" : "Incorrecto";
  labO.append(cbO, txtO); tdOk.appendChild(labO);

  const tdMot = document.createElement("td"); tdMot.className = "c-mot";
  const ta = document.createElement("textarea"); ta.className = "mot-in"; ta.rows = 1;
  ta.placeholder = "p. ej. no es este juego (Lost Cities) · rechazo incorrecto, sí es válido · es expansión, no base · idioma mal detectado";
  ta.value = e.m; tdMot.appendChild(ta);

  tr.append(tdIdx, tdRev, tdAd, tdCat, tdOk, tdMot);
  paintRow(tr, e);

  cbR.addEventListener("change", () => { e.r = cbR.checked; paintRow(tr, e); refresh(); scheduleSave(); });
  cbO.addEventListener("change", () => {
    e.ok = cbO.checked; txtO.textContent = e.ok ? "Correcto" : "Incorrecto";
    e.r = true; cbR.checked = true;
    paintRow(tr, e); refresh(); scheduleSave();
  });
  ta.addEventListener("input", () => {
    e.m = ta.value;
    if(ta.value.trim() !== ""){ e.r = true; cbR.checked = true; }
    paintRow(tr, e); updateStats(); scheduleSaveDebounced();
  });
  return tr;
}

function paintRow(tr, e){
  tr.classList.toggle("reviewed", !!e.r);
  tr.classList.toggle("flagged", !e.ok);
}

function updateStats(){
  let rev=0, ok=0, mot=0;
  for(const d of DATA){
    const e = edits[d.item_id];
    if(e.r) rev++; if(e.ok) ok++; if(e.m.trim() !== "") mot++;
  }
  $("sTotal").textContent = TOTAL;
  $("sRev").textContent = rev;
  $("sOk").textContent = ok;
  $("sMal").textContent = TOTAL - ok;
  $("sMot").textContent = mot;
  const pct = TOTAL ? Math.round(rev/TOTAL*100) : 0;
  $("bar").style.width = pct + "%";
  $("capTxt").textContent = rev + " de " + TOTAL + " revisados (" + pct + "%)";
}
function refresh(){ updateStats(); if(fStatus !== "all") render(); }

let saveT = null;
function scheduleSaveDebounced(){ clearTimeout(saveT); saveT = setTimeout(saveNow, 600); }
function scheduleSave(){ clearTimeout(saveT); saveT = setTimeout(saveNow, 150); }
async function saveNow(){
  if(!useStore) return;
  try{
    await window.storage.set(STORAGE_KEY, JSON.stringify(edits));
    const f = $("saveFlag"); f.classList.add("on");
    clearTimeout(saveNow._t); saveNow._t = setTimeout(()=>f.classList.remove("on"), 1200);
  }catch(err){}
}
async function loadSaved(){
  if(!useStore) return;
  try{
    const res = await window.storage.get(STORAGE_KEY);
    if(res && res.value){
      const saved = JSON.parse(res.value);
      for(const k in saved){ if(edits[k]) edits[k] = Object.assign(edits[k], saved[k]); }
    }
  }catch(err){}
}

function download(filename, text, mime){
  const blob = new Blob([text], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
}
function records(){
  return DATA.map(d => {
    const e = edits[d.item_id];
    return {
      item_id: d.item_id, title: d.title, description: d.description,
      language: d.language, category_id: d.category_id,
      category: d.category, decision: d.decision,
      price: d.price, url: d.url, alert_name: d.alert_name,
      bien_clasificado: e.ok, motivo: e.m.trim(), revisado: e.r
    };
  });
}
function exportJsonl(){
  const txt = records().map(r => JSON.stringify(r)).join("\n");
  download("wallapop_revision_keep.jsonl", txt, "application/x-ndjson");
}
function csvCell(v){
  if(v === null || v === undefined) v = "";
  v = String(v);
  return /[",\n]/.test(v) ? '"' + v.replace(/"/g,'""') + '"' : v;
}
function exportCsv(){
  const cols = ["item_id","title","description","language","category_id","category","decision","price","url","alert_name","bien_clasificado","motivo","revisado"];
  const lines = [cols.join(",")];
  for(const r of records()) lines.push(cols.map(c => csvCell(r[c])).join(","));
  download("wallapop_revision_keep.csv", "\ufeff" + lines.join("\n"), "text/csv;charset=utf-8");
}

function applyImported(arr){
  let n = 0;
  for(const r of arr){
    if(r && r.item_id && edits[r.item_id]){
      const e = edits[r.item_id];
      if(typeof r.bien_clasificado === "boolean") e.ok = r.bien_clasificado;
      if(typeof r.motivo === "string") e.m = r.motivo;
      if(typeof r.revisado === "boolean") e.r = r.revisado;
      n++;
    }
  }
  render(); updateStats(); scheduleSave();
  return n;
}
function importText(text){
  text = text.trim();
  let arr = null;
  try{ const j = JSON.parse(text); arr = Array.isArray(j) ? j : Object.values(j); }
  catch(_){
    arr = text.split("\n").map(l => l.trim()).filter(Boolean).map(l => { try{return JSON.parse(l);}catch(__){return null;} }).filter(Boolean);
  }
  if(!arr || !arr.length){ alert("No se pudo leer el archivo. Esperaba JSON o JSONL exportado por esta herramienta."); return; }
  alert("Importadas " + applyImported(arr) + " filas.");
}

function populateFilters(){
  const alerts = [...new Set(DATA.map(d => d.alert_name).filter(Boolean))].sort();
  const cats = [...new Set(DATA.map(d => d.category).filter(Boolean))].sort();
  const fa = $("fAlert"), fc = $("fCat");
  for(const a of alerts){ const o = document.createElement("option"); o.value = a; o.textContent = a; fa.appendChild(o); }
  for(const c of cats){ const o = document.createElement("option"); o.value = c; o.textContent = c; fc.appendChild(o); }
}

let qT = null;
$("q").addEventListener("input", () => { clearTimeout(qT); qT = setTimeout(render, 150); });
$("fAlert").addEventListener("change", render);
$("fDecision").addEventListener("change", render);
$("fCat").addEventListener("change", render);
$("fLang").addEventListener("change", render);
$("fStatus").addEventListener("click", ev => {
  const b = ev.target.closest("button"); if(!b) return;
  fStatus = b.dataset.v;
  [...$("fStatus").children].forEach(x => x.classList.toggle("active", x === b));
  render();
});
$("bJsonl").addEventListener("click", exportJsonl);
$("bCsv").addEventListener("click", exportCsv);
$("bImport").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", ev => {
  const f = ev.target.files[0]; if(!f) return;
  const rd = new FileReader();
  rd.onload = () => { importText(String(rd.result)); ev.target.value = ""; };
  rd.readAsText(f);
});
$("bMarkVisible").addEventListener("click", () => {
  const list = currentList();
  if(!list.length) return;
  if(!confirm("Marcar como revisados los " + list.length + " anuncios visibles?")) return;
  list.forEach(d => edits[d.item_id].r = true);
  render(); updateStats(); scheduleSave();
});

populateFilters();
(async () => { await loadSaved(); render(); updateStats(); })();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
