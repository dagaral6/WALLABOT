"""
scraper.py
----------
Cliente para la API no oficial de Wallapop. Hace peticiones directas al
endpoint de búsqueda y devuelve anuncios normalizados, SIGUIENDO LA PAGINACIÓN
(meta.next_page) para no quedarse solo con la primera página.
"""

import time
import logging
import requests

log = logging.getLogger("wallapop")

SEARCH_URL = "https://api.wallapop.com/api/v3/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "X-DeviceOS": "0",
}


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return _to_float(value.get("amount"))
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _extract_category_id(raw):
    """category_id NATIVO de Wallapop, tolerante a variaciones del payload de
    búsqueda (el campo no siempre se llama igual ni vive al mismo nivel).
    Devuelve el valor tal cual (str|int) o None. Orden de búsqueda:
    claves planas -> objeto 'category' anidado -> 'taxonomy'."""
    if not isinstance(raw, dict):
        return None
    for k in ("category_id", "categoryId", "category_id_v2", "vertical_id"):
        v = raw.get(k)
        if v not in (None, ""):
            return v
    cat = raw.get("category")
    if isinstance(cat, dict):
        for k in ("id", "category_id", "categoryId"):
            v = cat.get(k)
            if v not in (None, ""):
                return v
    elif isinstance(cat, (int, str)) and str(cat).strip():
        return cat
    tax = raw.get("taxonomy")
    if isinstance(tax, list) and tax and isinstance(tax[0], dict):
        v = tax[0].get("id") or tax[0].get("category_id")
        if v not in (None, ""):
            return v
    return None


def _normalize_item(raw):
    item_id = raw.get("id") or raw.get("item_id")
    title = raw.get("title") or raw.get("name") or ""
    description = (
        raw.get("description")
        or raw.get("storytelling")
        or raw.get("body")
        or ""
    )
    price = (
        _to_float(raw.get("price"))
        or _to_float(raw.get("sale_price"))
        or _to_float(raw.get("price_amount"))
    )
    web_slug = raw.get("web_slug") or raw.get("slug")
    if web_slug:
        url = f"https://es.wallapop.com/item/{web_slug}"
    elif item_id:
        url = f"https://es.wallapop.com/item/{item_id}"
    else:
        url = None

    image = None
    images = raw.get("images") or []
    if images and isinstance(images, list):
        first = images[0]
        if isinstance(first, dict):
            image = (
                first.get("urls", {}).get("medium")
                if isinstance(first.get("urls"), dict)
                else first.get("medium") or first.get("url")
            )
        elif isinstance(first, str):
            image = first

    shipping = raw.get("shipping") or {}
    loc = raw.get("location") or {}

    return {
        "id": str(item_id) if item_id else None,
        "title": title,
        "description": description,
        "price": price,
        "url": url,
        "image": image,
        # Categoría NATIVA de Wallapop (la elige el vendedor al publicar). Sirve
        # para filtrar lo que no es juego de mesa (p. ej. 'cities'/'mare nostrum'
        # traen libros, CDs, videojuegos). Puede venir como int o str.
        "category_id": _extract_category_id(raw),
        # Datos para el filtro de entrega (radio / envío):
        "is_shippable": bool(shipping.get("item_is_shippable"))
        and bool(shipping.get("user_allows_shipping")),
        "lat": loc.get("latitude"),
        "lon": loc.get("longitude"),
    }


def _extract_items(payload):
    if isinstance(payload.get("search_objects"), list):
        return [obj.get("content", obj) for obj in payload["search_objects"]]
    try:
        items = payload["data"]["section"]["payload"]["items"]
        if isinstance(items, list):
            return items
    except (KeyError, TypeError):
        pass
    if isinstance(payload.get("items"), list):
        return payload["items"]
    return []


def _extract_next_page(payload):
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            return meta.get("next_page")
    return None


def search(keywords, latitude, longitude, min_price=None, max_price=None,
           category_ids=None,
           max_items=200, max_pages=40, page_pause=0.4, retries=2):
    """
    Sigue la paginación (meta.next_page) hasta agotar resultados o límites.
    La 1ª página usa los criterios de búsqueda; las siguientes, solo el token
    next_page (que ya lleva dentro todos los criterios). Si una página no
    aporta anuncios nuevos o no hay más token, paramos. Así, si el mecanismo de
    paginación fallara, en el peor caso devolvemos la primera página (sin
    bucles infinitos).

    category_ids: lista/iterable de IDs de categoría NATIVA de Wallapop para
    restringir la búsqueda en el servidor (p. ej. juegos de mesa). Si se indica,
    la paginación devuelve solo esa categoría, así los juegos de mesa reales no
    quedan sepultados bajo ruido (videojuegos, libros...) en keywords genéricas.
    Vacío/None = sin filtro (comportamiento de siempre).

    Parámetros que puedes ajustar si hiciera falta:
      max_items  -> tope de anuncios a recopilar por búsqueda
      max_pages  -> tope de páginas a pedir
      page_pause -> pausa (segundos) entre páginas, para no saturar la API
    """
    base_params = {
        "source": "search_box",
        "keywords": keywords,
        "latitude": latitude,
        "longitude": longitude,
    }
    if min_price is not None:
        base_params["min_sale_price"] = min_price
    if max_price is not None:
        base_params["max_sale_price"] = max_price
    if category_ids:
        # La API acepta varias categorías separadas por coma.
        base_params["category_ids"] = ",".join(
            str(c).strip() for c in category_ids if str(c).strip())

    all_items = []
    seen_ids = set()
    next_token = None
    page = 0

    while page < max_pages and len(all_items) < max_items:
        page += 1
        params = {"next_page": next_token} if next_token else base_params

        payload = None
        for attempt in range(retries + 1):
            try:
                resp = requests.get(SEARCH_URL, params=params,
                                    headers=HEADERS, timeout=25)
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    log.warning("Rate limit (429). Esperando %ss...", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                break
            except requests.RequestException as e:
                log.warning("Error en búsqueda (pág %d, intento %d): %s",
                            page, attempt + 1, e)
                time.sleep(2 * (attempt + 1))

        if payload is None:
            break

        raw_items = _extract_items(payload)
        nuevos = 0
        for r in raw_items:
            it = _normalize_item(r)
            if it["id"] and it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                all_items.append(it)
                nuevos += 1

        next_token = _extract_next_page(payload)
        if not raw_items or nuevos == 0 or not next_token:
            break
        time.sleep(page_pause)

    log.info("  '%s': %d anuncios recopilados en %d página(s).",
             keywords, len(all_items), page)
    return all_items
