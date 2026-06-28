#!/usr/bin/env python3
"""
enrich_bgg_names_es.py
Rellena la columna `traduccion` (nombre en espanol) consultando la API XML de
BoardGameGeek (endpoint `thing`).

COMO OBTIENE EL ESPANOL
-----------------------
La API `thing` NO etiqueta el idioma de los <name type="alternate"> (mezcla
aleman, italiano, frances, espanol, japones... sin marca de idioma). El idioma
SI esta en las versiones:
    thing?id=...&versions=1
devuelve <versions><item type="boardgameversion"> con
    <link type="language" value="Spanish"/>
Estrategia:
  1. Pedimos versions=1 y recogemos las versiones cuyo idioma es Spanish.
  2. Usamos el nombre de esas versiones como candidato a titulo espanol.
  3. Lo cruzamos con los <name type="alternate"> del juego para subir confianza.
  4. Escribimos SIEMPRE un CSV de auditoria, porque los nombres de version en BGG
     son irregulares (a veces "Spanish edition" en vez del titulo real).

Sin dependencias externas (solo stdlib). Cache JSON reanudable + backoff (429/202).
Respeta el fair use de BGG: 1 peticion cada --sleep segundos (por defecto 5).

EJEMPLOS
--------
  # Validacion rapida contra los 31 titulos ya conocidos (no necesita CSV):
  python enrich_bgg_names_es.py --selftest

  # Primera pasada sensata: solo juegos rankeados hasta rank 5000
  python enrich_bgg_names_es.py \
      --input boardgames_ranks_reducido.csv \
      --ranks-csv boardgames_ranks.csv --rank-max 5000

  # Todos los rankeados (lento; ~1-2 h):
  python enrich_bgg_names_es.py --input boardgames_ranks_reducido.csv \
      --ranks-csv boardgames_ranks.csv

  # Todo el catalogo (MUY lento; ~12 h). Solo si sabes lo que haces:
  python enrich_bgg_names_es.py --input boardgames_ranks_reducido.csv --all
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

BGG_URL = "https://boardgamegeek.com/xmlapi2/thing"
UA = "WallabotBGGEnricher/1.0 (offline name enrichment; respects BGG fair use)"

# Nombres de version que NO son un titulo (descriptores genericos a descartar).
# Solo descarta cuando la cadena ENTERA es generica (coincidencia ^...$).
GENERIC_RE = re.compile(
    r"^\s*("
    r"spanish( (edition|version))?|"
    r"edici[oó]n( en)? espa[nñ]ola|versi[oó]n espa[nñ]ola|en espa[nñ]ol|"
    r"(primera|segunda|tercera|first|second|third)?\s*"
    r"(edici[oó]n|edition|reimpresi[oó]n|reprint|tirada|version|versi[oó]n)|"
    r"1\.?[ªa]?\s*edici[oó]n|2\.?[ªa]?\s*edici[oó]n|"
    r"\d{4}|deluxe|big box|promo|kickstarter"
    r")\s*$",
    re.IGNORECASE,
)

# Mapa curado para --selftest (id -> ES esperado). Sirve para validar el script.
CURATED = {
    "325": "Catan: Navegantes", "926": "Catan: Ciudades y Caballeros",
    "27760": "Catan: Mercaderes y Bárbaros", "135378": "Catan: Exploradores y Piratas",
    "2807": "Catan: Ampliación 5-6 jugadores", "4390": "Carcassonne: Cazadores y Recolectores",
    "2591": "Carcassonne: El Río", "2993": "Carcassonne: Posadas y Catedrales",
    "5405": "Carcassonne: Mercaderes y Constructores", "9209": "¡Aventureros al Tren!",
    "14996": "¡Aventureros al Tren! Europa", "266192": "Alas", "2651": "Alta Tensión",
    "34635": "Edad de Piedra", "84876": "Los Castillos de Borgoña",
    "178900": "Código Secreto", "478": "Ciudadelas",
    "284083": "The Crew: La búsqueda del Noveno Planeta",
}


def norm(s):
    """Normaliza para comparar: minusculas, sin acentos, solo alfanumerico."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def is_generic(name):
    name = (name or "").strip()
    return len(name) < 2 or bool(GENERIC_RE.match(name))


def fetch(ids, sleep, max_retries):
    """Descarga un lote de ids. Devuelve bytes XML o None si falla de forma persistente."""
    url = f"{BGG_URL}?id={','.join(ids)}&versions=1"
    delay = max(sleep, 1)
    for _ in range(max_retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                code = r.getcode()
                data = r.read()
            if code == 200:
                return data
            if code == 202:  # encolado: esperar y reintentar
                time.sleep(max(delay, 5)); delay = min(delay * 2, 120); continue
        except urllib.error.HTTPError as e:
            if e.code == 414:  # URI demasiado larga: el lote es excesivo
                raise
            if e.code in (429, 502, 503, 504, 202):
                time.sleep(max(delay, 5)); delay = min(delay * 2, 120); continue
            time.sleep(delay); delay = min(delay * 2, 120); continue
        except (urllib.error.URLError, TimeoutError, ET.ParseError):
            time.sleep(delay); delay = min(delay * 2, 120); continue
    return None


def parse(xml_bytes):
    """XML -> {id: {primary, alternates[], es_versions[], fetched_at}}."""
    out = {}
    root = ET.fromstring(xml_bytes)
    for item in root.findall("item"):
        gid = item.get("id")
        primary, alternates = "", []
        for nm in item.findall("name"):
            t = nm.get("type")
            if t == "primary":
                primary = nm.get("value", "")
            elif t == "alternate":
                alternates.append(nm.get("value", ""))
        es_versions = []
        versions = item.find("versions")
        if versions is not None:
            for v in versions.findall("item"):
                langs = [l.get("value", "") for l in v.findall("link")
                         if l.get("type") == "language"]
                if any(l.lower() == "spanish" for l in langs):
                    for nm in v.findall("name"):
                        if nm.get("type") == "primary":
                            if nm.get("value"):
                                es_versions.append(nm.get("value"))
                            break
        out[gid] = {
            "primary": primary, "alternates": alternates,
            "es_versions": es_versions,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    return out


def choose_es(rec):
    """Decide el titulo espanol. Devuelve (nombre, confianza, motivo). '' si no hay."""
    cands = [c for c in rec.get("es_versions", []) if not is_generic(c)]
    if not cands:
        return "", "", "sin version ES con titulo util"
    alts = {norm(a) for a in rec.get("alternates", [])}
    cross = [c for c in cands if norm(c) in alts]
    if cross:                                   # version ES que ademas es un alternate
        return Counter(cross).most_common(1)[0][0], "alta", "version ES coincide con alternate"
    freq = Counter(cands)
    if freq.most_common(1)[0][1] > 1:           # varias versiones ES con el mismo nombre
        return freq.most_common(1)[0][0], "media", "varias versiones ES coinciden"
    return sorted(cands, key=lambda x: (len(x), x))[0], "media-baja", "una sola version ES (revisar)"


# ----------------------------- cache -----------------------------
def load_cache(path):
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"[aviso] cache ilegible en {path}, empiezo vacia", file=sys.stderr)
    return {}


def save_cache(path, cache):
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, path)


# ----------------------------- scope -----------------------------
def ids_from_input(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [row["id"] for row in csv.DictReader(f) if row.get("id")]


def ids_from_ranks(path, rank_max):
    ids = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rk = (row.get("rank") or "").strip()
            if rk in ("", "0"):
                continue
            try:
                rv = int(rk)
            except ValueError:
                continue
            if rank_max is not None and rv > rank_max:
                continue
            ids.append(row["id"])
    return ids


# ----------------------------- main -----------------------------
def run(args):
    cache = load_cache(args.cache)

    # ---- selftest: ids curados, sin CSV ----
    if args.selftest:
        target = list(CURATED.keys())
    elif args.ids:
        target = [x.strip() for x in args.ids.split(",") if x.strip()]
    elif args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            target = [ln.strip() for ln in f if ln.strip()]
    elif args.ranks_csv:
        target = ids_from_ranks(args.ranks_csv, args.rank_max)
    elif args.all:
        target = ids_from_input(args.input)
    else:
        print("ERROR: elige un alcance: --selftest | --ids | --ids-file | "
              "--ranks-csv [--rank-max N] | --all", file=sys.stderr)
        return 2

    # dedup conservando orden
    seen = set()
    target = [x for x in target if not (x in seen or seen.add(x))]
    if args.limit:
        target = target[:args.limit]

    pending = target if args.refresh else [i for i in target if i not in cache]
    print(f"Objetivo: {len(target)} ids | en cache: {len(target) - len(pending)} | "
          f"a descargar: {len(pending)}")
    if pending:
        eta_min = len(pending) / max(args.batch, 1) * args.sleep / 60
        print(f"Lotes de {args.batch}, sleep {args.sleep}s -> ETA aprox {eta_min:.1f} min")

    # ---- descarga por lotes ----
    failed = []
    for k in range(0, len(pending), args.batch):
        batch = pending[k:k + args.batch]
        data = fetch(batch, args.sleep, args.max_retries)
        if data is None:
            failed.extend(batch)
            print(f"[fallo] lote {k // args.batch + 1}: {batch[:3]}... reintenta en otra pasada",
                  file=sys.stderr)
        else:
            parsed = parse(data)
            for gid in batch:  # marca tambien los ids que no devolvio BGG (invalidos)
                cache[gid] = parsed.get(gid, {
                    "primary": "", "alternates": [], "es_versions": [],
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "missing": True,
                })
            save_cache(args.cache, cache)
        done = min(k + args.batch, len(pending))
        print(f"  {done}/{len(pending)}", end="\r", flush=True)
        if done < len(pending):
            time.sleep(args.sleep)
    print()
    if failed:
        print(f"[aviso] {len(failed)} ids no descargados; relanza el script para reintentarlos",
              file=sys.stderr)

    # ---- selftest: comparar contra el mapa curado ----
    if args.selftest:
        print("\n=== SELFTEST: BGG vs curado ===")
        ok = 0
        for gid, esp in CURATED.items():
            rec = cache.get(gid, {})
            chosen, conf, _ = choose_es(rec)
            match = "OK " if norm(chosen) == norm(esp) else "DIF"
            if match == "OK ":
                ok += 1
            print(f"{match} {gid:>7} | curado: {esp!r:45} | BGG[{conf or '-'}]: {chosen!r}")
        print(f"\nCoincidencias exactas: {ok}/{len(CURATED)} "
              f"(no pasa nada si difieren: BGG y la edicion real no siempre casan al 100%)")
        return 0

    # ---- auditoria ----
    allowed = {"alta", "media"} if not args.include_low else {"alta", "media", "media-baja"}
    audit_rows = []
    for gid in target:
        rec = cache.get(gid, {})
        chosen, conf, motivo = choose_es(rec)
        audit_rows.append({
            "id": gid, "primary": rec.get("primary", ""),
            "n_versiones_es": len(rec.get("es_versions", [])),
            "elegido": chosen, "confianza": conf, "motivo": motivo,
            "versiones_es": " | ".join(rec.get("es_versions", [])),
            "alternates": " | ".join(rec.get("alternates", [])),
        })
    with open(args.audit, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()) if audit_rows else
                           ["id", "primary", "n_versiones_es", "elegido", "confianza",
                            "motivo", "versiones_es", "alternates"])
        w.writeheader()
        w.writerows(audit_rows)
    print(f"Auditoria -> {args.audit} ({len(audit_rows)} filas)")

    # ---- CSV enriquecido (preserva traduccion existente salvo --overwrite) ----
    chosen_map = {r["id"]: r for r in audit_rows if r["elegido"] and r["confianza"] in allowed}
    n_set = 0
    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if "traduccion" not in fields:
            fields = fields + ["traduccion"]
        rows = list(reader)
    for row in rows:
        gid = row.get("id")
        if gid in chosen_map:
            cur = (row.get("traduccion") or "").strip()
            if not cur or args.overwrite:
                row["traduccion"] = chosen_map[gid]["elegido"]
                n_set += 1
        row.setdefault("traduccion", "")
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"Enriquecido -> {args.output} | traducciones escritas/actualizadas: {n_set}")
    by_conf = Counter(r["confianza"] for r in audit_rows if r["elegido"])
    print(f"Candidatos por confianza: {dict(by_conf)}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Enriquecer columna traduccion (ES) via API thing de BGG")
    p.add_argument("--input", default="boardgames_ranks_reducido.csv",
                   help="CSV a enriquecer (necesita columna id)")
    p.add_argument("--output", default="boardgames_ranks_reducido_es.csv")
    p.add_argument("--audit", default="bgg_es_audit.csv")
    p.add_argument("--cache", default="bgg_names_cache.json")
    # alcance (elige uno)
    p.add_argument("--selftest", action="store_true", help="valida contra 31 titulos conocidos")
    p.add_argument("--ids", help="lista de ids separada por comas")
    p.add_argument("--ids-file", dest="ids_file", help="fichero con un id por linea")
    p.add_argument("--ranks-csv", dest="ranks_csv", help="boardgames_ranks.csv para filtrar por rank")
    p.add_argument("--rank-max", dest="rank_max", type=int, default=None,
                   help="solo rank <= N (con --ranks-csv)")
    p.add_argument("--all", action="store_true", help="todos los ids del --input (MUY lento)")
    p.add_argument("--limit", type=int, default=None, help="corta a N ids tras filtrar")
    # red / robustez
    p.add_argument("--batch", type=int, default=20, help="ids por peticion (max ~20 en BGG)")
    p.add_argument("--sleep", type=float, default=5.0, help="segundos entre peticiones")
    p.add_argument("--max-retries", dest="max_retries", type=int, default=6)
    p.add_argument("--refresh", action="store_true", help="ignora cache para los ids elegidos")
    # escritura
    p.add_argument("--overwrite", action="store_true",
                   help="sobrescribe traduccion existente (por defecto se conserva)")
    p.add_argument("--include-low", dest="include_low", action="store_true",
                   help="tambien escribe candidatos de confianza media-baja")
    return p


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
