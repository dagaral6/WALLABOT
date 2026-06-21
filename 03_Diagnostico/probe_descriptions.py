"""
probe_descriptions.py
---------------------
Paso 0 de "revalidar con descripcion": comprueba si la API de BUSQUEDA de
Wallapop devuelve la DESCRIPCION de cada anuncio (o solo el titulo). De esto
depende todo el enfoque: si la busqueda no trae descripcion, produccion tampoco
la tiene barata (habria que pedir el detalle de cada anuncio, 1 peticion extra
por anuncio).

Scrapea una sola keyword (por defecto la problematica "mare nostrum") y reporta
cuantos anuncios traen descripcion no vacia, con ejemplos.

    py probe_descriptions.py
    py probe_descriptions.py "catan"

Solo lectura de la API publica de Wallapop (sin credenciales). No toca la BD.
"""

import os
import sys
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import scraper  # noqa: E402  (reutilizamos su parsing)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Valencia (de configs/dario.yaml).
LAT, LON = 39.4699, -0.3763

# Esta maquina tiene un fallo SSL local (certificados); en GitHub Actions el
# scraping va bien con verificacion normal. Solo para este SONDEO de diagnostico
# (datos publicos, sin credenciales) saltamos la verificacion SSL.
try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass


def _search_no_ssl(kw, pages=2):
    """Replica minima de scraper.search con verify=False (solo diagnostico)."""
    items, seen, token, page = [], set(), None, 0
    while page < pages:
        page += 1
        params = ({"next_page": token} if token else
                  {"source": "search_box", "keywords": kw,
                   "latitude": LAT, "longitude": LON})
        resp = requests.get(scraper.SEARCH_URL, params=params,
                            headers=scraper.HEADERS, timeout=25, verify=False)
        resp.raise_for_status()
        payload = resp.json()
        raw = scraper._extract_items(payload)
        for r in raw:
            it = scraper._normalize_item(r)
            if it["id"] and it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
        token = scraper._extract_next_page(payload)
        if not raw or not token:
            break
    return items


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "mare nostrum"
    print(f"Scrapeando '{kw}' (max ~2 paginas, verify SSL OFF)...")
    items = _search_no_ssl(kw, pages=2)
    print(f"Recibidos: {len(items)}\n")

    con_desc = [it for it in items if (it.get("description") or "").strip()]
    sin_desc = len(items) - len(con_desc)
    print(f"Con descripcion no vacia: {len(con_desc)}/{len(items)}")
    print(f"Sin descripcion:          {sin_desc}/{len(items)}\n")

    if con_desc:
        avg = sum(len(it["description"]) for it in con_desc) / len(con_desc)
        print(f"Longitud media de descripcion: {avg:.0f} caracteres\n")
        print("Ejemplos (titulo -> primeros 120 car. de descripcion):")
        for it in con_desc[:8]:
            d = it["description"].replace("\n", " ")[:120]
            print(f"  - {it['title'][:50]}")
            print(f"      desc: {d}")
    else:
        print("NINGUN anuncio trae descripcion en la busqueda.")
        print("=> Produccion solo dispone del TITULO sin pedir el detalle de "
              "cada anuncio (1 peticion extra por anuncio).")

    print("\nRESULTADO:", "DESCRIPCION DISPONIBLE" if len(con_desc) > len(items) / 2
          else "DESCRIPCION NO DISPONIBLE (o muy escasa) en la busqueda")
    return 0


if __name__ == "__main__":
    sys.exit(main())
