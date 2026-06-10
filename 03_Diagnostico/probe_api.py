"""
probe_api.py
------------
Sonda de depuración de la API de Wallapop. Hace UNA búsqueda y analiza en
profundidad la respuesta cruda para ver:
  - cuántos resultados devuelve realmente la API
  - en qué parte de la estructura JSON viven (por si el parser actual solo
    está leyendo una sección)
  - una muestra de títulos y precios
También guarda la respuesta completa en 'raw_wallapop_response.json'.

NO modifica nada. Úsalo desde la carpeta del proyecto:

    python3 probe_api.py            # busca 'wingspan'
    python3 probe_api.py "catan"    # busca otra cosa
"""

import sys
import json
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))

import requests
import main
from scraper import SEARCH_URL, HEADERS


def sample_item(d):
    """Extrae (título, precio) de un elemento que puede venir envuelto."""
    if not isinstance(d, dict):
        return (str(d)[:40], "")
    inner = d.get("content") or d.get("item") or d
    if not isinstance(inner, dict):
        inner = d
    title = inner.get("title") or inner.get("name") or "(sin título)"
    price = inner.get("price")
    if isinstance(price, dict):
        price = price.get("amount")
    return (str(title)[:55], price)


def looks_like_listings(lst):
    """¿Es una lista de anuncios?"""
    dicts = [x for x in lst if isinstance(x, dict)]
    if not dicts:
        return False
    for d in dicts[:5]:
        inner = d.get("content") or d.get("item") or d
        if isinstance(inner, dict) and (
                "title" in inner or "name" in inner
                or "price" in inner or "web_slug" in inner):
            return True
    return False


def walk(obj, path, found):
    if isinstance(obj, list):
        if looks_like_listings(obj):
            found.append((path, obj))
            return  # no recurseamos dentro de una lista de anuncios
        for i, x in enumerate(obj):
            walk(x, f"{path}[{i}]", found)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, f"{path}.{k}", found)


def main_probe():
    config = main.load_config()
    target = sys.argv[1] if len(sys.argv) > 1 else "wingspan"
    params = {
        "source": "search_box",
        "keywords": target,
        "latitude": config["location"]["latitude"],
        "longitude": config["location"]["longitude"],
        "order_by": "newest",
    }

    print("=" * 64)
    print(f"SONDA API Wallapop  | keywords='{target}'")
    print(f"URL: {SEARCH_URL}")
    print(f"params: {params}")
    print("=" * 64)

    r = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
    print(f"HTTP status: {r.status_code}")
    print(f"Tamaño respuesta: {len(r.text)} caracteres")
    print(f"URL final: {r.url}\n")

    try:
        data = r.json()
    except ValueError:
        print("La respuesta NO es JSON. Primeros 800 caracteres:")
        print(r.text[:800])
        return

    # Guardar respuesta completa para inspección (en 04_Logs)
    _raw_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "04_Logs", "raw_wallapop_response.json")
    with open(_raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Respuesta completa guardada en '{_raw_path}'.\n")

    if isinstance(data, dict):
        print("Claves de primer nivel:", list(data.keys()))
        # Buscar campos de conteo/paginación
        for k, v in data.items():
            if any(s in k.lower() for s in ("count", "total", "next", "page")):
                print(f"  · {k} = {v}")
        print()

    found = []
    walk(data, "root", found)
    if not found:
        print("No encontré ninguna lista de anuncios en la respuesta.")
        print("Esto sugiere que el endpoint o los parámetros han cambiado.")
        return

    print(f"Encontradas {len(found)} lista(s) de anuncios:\n")
    for path, lst in found:
        print(f"  Ruta: {path}")
        print(f"  Nº de anuncios: {len(lst)}")
        for d in lst[:5]:
            t, p = sample_item(d)
            print(f"     - {t}  | {p} EUR")
        if len(lst) > 5:
            print(f"     ... y {len(lst) - 5} más")
        print()

    biggest = max(found, key=lambda x: len(x[1]))
    print("-" * 64)
    print(f"La lista más grande está en '{biggest[0]}' con {len(biggest[1])} "
          f"anuncios.")
    print("Pásame esta salida y, si quieres, el archivo "
          "raw_wallapop_response.json, y ajusto el lector de resultados.")


if __name__ == "__main__":
    main_probe()
