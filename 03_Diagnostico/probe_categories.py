"""
probe_categories.py
-------------------
Descubre el category_id NATIVO de Wallapop para juegos de mesa, a partir de TUS
propios resultados (la API filtra por ID numérico, no por nombre). Scrapea una
keyword y muestra la DISTRIBUCIÓN de category_id en los resultados, con títulos
de ejemplo por categoría. El category_id que comparten los juegos de mesa de
verdad es el que hay que poner en bot_settings.yaml (search.category_ids).

    py probe_categories.py            # keyword 'catan'
    py probe_categories.py "cities"   # una keyword ruidosa (mejor para verlo)

Solo lectura de la API pública (sin credenciales). No toca la BD ni el código.
Esta máquina tiene un fallo SSL local; en GitHub Actions el scraping va con
verificación normal. Aquí (solo diagnóstico, datos públicos) saltamos el SSL.
"""

import os
import sys
import requests
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import scraper  # noqa: E402  (reutilizamos su parsing)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass

# Valencia (de configs/dario.yaml).
LAT, LON = 39.4699, -0.3763

# Posibles nombres de categoría dentro del item crudo (varían según versión de
# la API). Solo para mostrar una pista legible junto al ID.
_NAME_KEYS = ("category_name", "category", "taxonomy", "subcategory_name")


def _raw_name(raw):
    for k in _NAME_KEYS:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            for kk in ("name", "title", "label"):
                if isinstance(v.get(kk), str) and v[kk].strip():
                    return v[kk].strip()
    return ""


def _search_no_ssl(kw, pages=3):
    rows, seen, token, page = [], set(), None, 0
    while page < pages:
        page += 1
        params = ({"next_page": token} if token else
                  {"source": "search_box", "keywords": kw,
                   "latitude": LAT, "longitude": LON})
        try:
            resp = requests.get(scraper.SEARCH_URL, params=params,
                                headers=scraper.HEADERS, timeout=25, verify=False)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            print(f"  error scrape '{kw}': {e}")
            break
        raw = scraper._extract_items(payload)
        for r in raw:
            it = scraper._normalize_item(r)
            if it["id"] and it["id"] not in seen:
                seen.add(it["id"])
                rows.append((it, _raw_name(r) if isinstance(r, dict) else "", r))
        token = scraper._extract_next_page(payload)
        if not raw or not token:
            break
    return rows


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "catan"
    print(f"Scrapeando '{kw}' (max ~3 páginas, SSL OFF)...\n")
    rows = _search_no_ssl(kw)
    if not rows:
        print("Sin resultados.")
        return 1

    # Volcado de las claves CRUDAS de los 2 primeros anuncios (para confirmar
    # cómo se llama el campo de categoría en el payload).
    print("Claves crudas del primer anuncio (para diagnóstico):")
    for it, _, r in rows[:1]:
        if isinstance(r, dict):
            print("  keys:", sorted(r.keys()))
            for k in list(r.keys()):
                if "categ" in k.lower() or "vertical" in k.lower() or "taxonom" in k.lower():
                    print(f"    {k} = {r.get(k)!r}")
    print()

    by_cat = defaultdict(list)          # category_id -> [(title, name)]
    sin_id = 0
    for it, name, _ in rows:
        cid = it.get("category_id")
        if cid is None:
            sin_id += 1
            continue
        by_cat[str(cid)].append((it.get("title", ""), name))

    print(f"Total anuncios: {len(rows)}")
    print(f"Sin category_id en el payload: {sin_id}/{len(rows)}"
          + ("  <-- el payload NO trae category_id (avísame: haría falta otra vía)"
             if sin_id == len(rows) else ""))
    print()
    print("Distribución por category_id (de más a menos frecuente):")
    print("-" * 64)
    for cid, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        name = next((n for _, n in items if n), "")
        etiqueta = f"  ({name})" if name else ""
        print(f"category_id = {cid}{etiqueta}  ->  {len(items)} anuncios")
        for title, _ in items[:4]:
            print(f"      · {title[:64]}")
    print("-" * 64)
    top = max(by_cat.items(), key=lambda x: len(x[1]), default=(None, []))[0]
    print(f"\nSUGERENCIA: el category_id dominante para '{kw}' es {top!r}.")
    print("Verifica que los títulos de arriba SON juegos de mesa y, si encaja,")
    print("ponlo en bot_settings.yaml -> search.category_ids: [%s]" %
          (top if top else "..."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
