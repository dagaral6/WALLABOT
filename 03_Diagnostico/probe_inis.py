"""
probe_inis.py
-------------
Sonda para entender cuántos resultados ofrece de verdad la API para un término,
y si el orden de búsqueda o el freno de paginación están limitando.

Pagina el término de DOS formas y compara:
  1) order_by = newest  (lo que usa ahora el programa)
  2) orden por defecto   (sin order_by, suele ser relevancia/distancia)

A diferencia del programa, esta sonda NO se detiene cuando una página no aporta
anuncios nuevos: sigue mientras haya token (con tope de páginas), para medir el
total real disponible. Así vemos si el freno del programa nos corta antes.

NO modifica nada. Uso:
    python3 probe_inis.py            # término 'inis'
    python3 probe_inis.py "wingspan" # otro término
"""

import sys
import time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))

import requests
import main
from scraper import (SEARCH_URL, HEADERS, _extract_items,
                     _extract_next_page, _normalize_item)


def paginar(target, lat, lng, order_by, max_pages=40):
    base = {"source": "search_box", "keywords": target,
            "latitude": lat, "longitude": lng}
    if order_by:
        base["order_by"] = order_by

    token = None
    last_token = None
    page = 0
    seen = set()
    titles = []

    while page < max_pages:
        page += 1
        params = {"next_page": token} if token else base
        try:
            r = requests.get(SEARCH_URL, params=params,
                             headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"  pág {page}: error de red ({e})")
            break
        if r.status_code != 200:
            print(f"  pág {page}: HTTP {r.status_code}")
            break

        data = r.json()
        items = _extract_items(data)
        nuevos = 0
        for x in items:
            it = _normalize_item(x)
            if it["id"] and it["id"] not in seen:
                seen.add(it["id"])
                titles.append((it["title"], it["price"]))
                nuevos += 1

        token = _extract_next_page(data)
        print(f"  pág {page}: {len(items)} items, {nuevos} nuevos, "
              f"token siguiente: {'sí' if token else 'NO'}")

        if not items or not token:
            break
        if token == last_token:
            print("  (el token no cambia: posible bucle, paro)")
            break
        last_token = token
        time.sleep(0.4)

    return seen, titles, page


def main_probe():
    config = main.load_config()
    target = sys.argv[1] if len(sys.argv) > 1 else "inis"
    lat = config["location"]["latitude"]
    lng = config["location"]["longitude"]

    print("=" * 64)
    print(f"Comparativa de paginación para '{target}'")
    print("=" * 64)

    print("\n--- ORDEN actual del programa: newest ---")
    s1, _t1, p1 = paginar(target, lat, lng, "newest")
    print(f"  TOTAL con newest: {len(s1)} anuncios únicos en {p1} páginas")

    print("\n--- ORDEN por defecto (sin order_by) ---")
    s2, t2, p2 = paginar(target, lat, lng, None)
    print(f"  TOTAL por defecto: {len(s2)} anuncios únicos en {p2} páginas")

    print("\n" + "-" * 64)
    print(f"Resumen: newest={len(s1)}  |  por_defecto={len(s2)}")
    if len(s2) > len(s1):
        print("=> El orden 'newest' está limitando. Conviene quitarlo.")
    elif len(s1) == len(s2):
        print("=> El orden no cambia el total. La API ofrece esos resultados; "
              "la web puede mostrar más por secciones extra o matching distinto.")

    print("\nTítulos encontrados (orden por defecto):")
    for tit, pr in t2[:40]:
        print(f"   - {tit[:55]}  | {pr} EUR")


if __name__ == "__main__":
    main_probe()
