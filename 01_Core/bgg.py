"""
bgg.py
------
Consulta ligera a BoardGameGeek (XMLAPI2) como "diccionario que se mantiene solo":
dado el TÍTULO de un anuncio, decir (a) si corresponde a un juego real y (b) si
BGG lo clasifica como juego base (boardgame) o expansión (boardgameexpansion).
Refuerza la relevancia y la distinción base/expansion SIN listas manuales.

PRINCIPIO: REFUERZO, no autoridad. Ante CUALQUIER fallo (red, timeout, HTTP 202/
429, parseo, XML inesperado) NO lanza excepción hacia el llamador: devuelve None
y registra a nivel info. Así el bot sigue funcionando igual que hoy si BGG no
responde (degradación elegante).

CACHÉ persistente en 01_Core/bgg_cache.json (BGG aplica rate-limit y Actions es
stateless entre runs): clave = título normalizado; valor = el dict encontrado o
un centinela de "no encontrado" con fecha. Escritura ATÓMICA (tmp + os.replace).
Los aciertos no caducan (el tipo de un juego no cambia); los "no encontrado"
caducan a los BGG_CACHE_TTL_DAYS días para poder reintentar.

AUTÓNOMO: no importa de classifier ni de main (no acopla la red de BGG al
clasificador). La integración (flag bgg.enabled, override base->expansion) vive
en main.py, desactivada por defecto.
"""

import os
import re
import json
import time
import logging
import datetime
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger("bgg")

_BASE = "https://boardgamegeek.com/xmlapi2"
_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bgg_cache.json")

# Tipo BGG -> categoría interna del proyecto.
_KIND_MAP = {"boardgame": "base", "boardgameexpansion": "expansion"}

# Parámetros (override por variable de entorno; por defecto conservadores).
def _envf(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _envi(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

_TIMEOUT = _envf("BGG_TIMEOUT", 12.0)        # timeout por petición HTTP
_MAX_RETRIES = _envi("BGG_MAX_RETRIES", 3)   # reintentos ante 202/429
_RETRY_WAIT = _envf("BGG_RETRY_WAIT", 2.0)   # base de espera entre reintentos (s)
_CACHE_TTL_DAYS = _envi("BGG_CACHE_TTL_DAYS", 30)  # frescura del "no encontrado"

_HEADERS = {"User-Agent": "wallabot/1.0 (board game alerts)"}


# --- configuración (flag enabled), sigue el patrón de classifier --------------
_BGG_ENABLED = os.getenv("BGG_ENABLED", "0") not in ("0", "false", "False", "")


def bgg_enabled():
    """True si la integración BGG está activa (bgg.enabled / BGG_ENABLED)."""
    return _BGG_ENABLED


def configure_from_settings(settings):
    """Aplica la sección 'bgg' de bot_settings.yaml. Entorno > yaml > default.
    Por defecto DESACTIVADO: no cambia el comportamiento hasta activarlo."""
    global _BGG_ENABLED
    b = (settings or {}).get("bgg") or {}
    if "BGG_ENABLED" not in os.environ and b.get("enabled") is not None:
        _BGG_ENABLED = bool(b.get("enabled"))


# --- normalización de títulos -------------------------------------------------
def _strip_accents(text):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("à", "a"), ("è", "e"), ("ç", "c"), ("ü", "u")):
        text = text.replace(a, b)
    return text


def _cache_key(title):
    """Clave de caché: minúsculas, sin tildes, solo alfanumérico+espacio,
    colapsado. Así 'Catán' y 'catan ' caen en la misma entrada."""
    t = _strip_accents((title or "").lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Ruido típico de títulos de Wallapop que estorba a la búsqueda de BGG.
_PRICE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:€|eur|euros?)", re.IGNORECASE)
_NOISE_RE = re.compile(
    r"\b(hago\s+envios?|envio\s+gratis|envios?|reservad[oa]|negociable|oferta|"
    r"precintad[oa]|nuevo\s+a\s+estrenar|como\s+nuevo|segunda\s+mano|2\s*mano|"
    r"juego\s+de\s+mesa|board\s*game)\b", re.IGNORECASE)


def _clean_title(title):
    """Limpieza razonable para consultar BGG: quita emojis/símbolos, precios y
    ruido de venta, colapsa espacios. Conserva el nombre legible (con tildes).
    Muchos títulos no casarán; es aceptable (degradación elegante)."""
    t = title or ""
    # Orden: primero precios (necesitan el '€' intacto) y ruido de venta; después
    # se quitan emojis/símbolos (todo lo que no sea letra/dígito/espacio o
    # separadores comunes de nombres) y se colapsan espacios.
    t = _PRICE_RE.sub(" ", t)
    t = _NOISE_RE.sub(" ", t)
    t = re.sub(r"[^\w\s:&'\-+/.áéíóúñàèìòùçü]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


# --- caché persistente (carga perezosa, escritura atómica) --------------------
_CACHE = None   # dict | None (cargado al primer uso)


def _today():
    return datetime.date.today().isoformat()


def _fresh(entry):
    """True si un centinela de 'no encontrado' aún está dentro de la TTL."""
    ts = (entry or {}).get("ts")
    if not ts:
        return False
    try:
        d = datetime.date.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.date.today() - d).days < _CACHE_TTL_DAYS


def _load_cache():
    """Lee bgg_cache.json. Ante cualquier error devuelve {} (nunca lanza)."""
    try:
        with open(_CACHE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.info("BGG caché ilegible (%s); se ignora", e)
        return {}


def _save_cache(cache):
    """Escritura ATÓMICA: vuelca a un tmp y reemplaza. Nunca lanza."""
    tmp = _CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, _CACHE_PATH)
    except OSError as e:
        log.info("BGG no pudo guardar la caché (%s)", e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _get_cache():
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_cache()
    return _CACHE


# --- consulta a BGG -----------------------------------------------------------
def _get(path, params):
    """GET con manejo de rate-limit: BGG responde 202 mientras procesa y 429 si
    saturas. Reintenta con espera creciente hasta _MAX_RETRIES; si no, None.
    Devuelve el cuerpo (texto XML) o None ante cualquier fallo."""
    url = _BASE + path
    for attempt in range(_MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=_TIMEOUT,
                             headers=_HEADERS)
        except requests.RequestException as e:
            log.info("BGG red/timeout (%s): %s", path, e)
            return None
        if r.status_code == 200:
            return r.text
        if r.status_code in (202, 429):
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_WAIT * (attempt + 1))
                continue
            log.info("BGG %s: HTTP %s tras %d reintentos", path,
                     r.status_code, attempt)
            return None
        log.info("BGG %s: HTTP %s", path, r.status_code)
        return None
    return None


def _pick_from_search(xml_text):
    """De la respuesta XML de /search saca el mejor candidato como
    {bgg_id, name, kind} o None. Prefiere 'base' sobre 'expansion' cuando el
    mismo nombre casa con ambos (conservador: no degradar a expansión sin más)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.info("BGG XML inválido: %s", e)
        return None
    candidates = []
    for item in root.findall("item"):
        kind = _KIND_MAP.get(item.get("type"))
        if kind is None:
            continue
        name_el = item.find("name")
        candidates.append({
            "bgg_id": item.get("id"),
            "name": name_el.get("value") if name_el is not None else "",
            "kind": kind,
        })
    if not candidates:
        return None
    base = next((c for c in candidates if c["kind"] == "base"), None)
    return base or candidates[0]


def _query_bgg(query):
    """Busca en BGG: primero exacto (exact=1), luego laxo. Devuelve dict o None."""
    if not query:
        return None
    params = {"query": query, "type": "boardgame,boardgameexpansion"}
    xml = _get("/search", dict(params, exact=1))
    item = _pick_from_search(xml) if xml else None
    if item is None:
        xml = _get("/search", params)        # segundo intento, búsqueda laxa
        item = _pick_from_search(xml) if xml else None
    return item


# --- API pública --------------------------------------------------------------
def lookup(title):
    """Dado un título de anuncio, devuelve {bgg_id, name, kind} con
    kind ∈ {'base','expansion'}, o None si BGG no lo reconoce o falla.

    Usa caché persistente; consulta la red solo en miss (o si el 'no encontrado'
    cacheado ha caducado). NUNCA lanza: ante fallo devuelve None.
    """
    key = _cache_key(title)
    if not key:
        return None
    cache = _get_cache()
    hit = cache.get(key)
    if hit is not None:
        if hit.get("not_found"):
            if _fresh(hit):
                return None                  # no encontrado y aún fresco
            # caducado: cae a reconsultar abajo
        else:
            return {k: hit.get(k) for k in ("bgg_id", "name", "kind")}

    result = _query_bgg(_clean_title(title))
    if result is None:
        cache[key] = {"not_found": True, "ts": _today()}
    else:
        cache[key] = dict(result, ts=_today())
    _save_cache(cache)
    return result


# --- categoría con descripción: expansiones del juego base (S4) ---------------
# Frases que indican mera COMPATIBILIDAD (el anuncio menciona una expansión pero
# NO la vende): no deben hacer que un base pase a 'expansion'. Sobre texto
# normalizado (_cache_key: minúsculas, sin tildes).
_COMPAT_RE = re.compile(
    r"compatible|ampliab|se amplia|para ampliar|se puede ampliar|sirve para|"
    r"junto a|ademas de|tambien tengo|tengo tambien|no incluye")


def _fetch_expansions(base_id):
    """Nombres de las expansiones de un juego base vía thing?id=<id>
    (links boardgameexpansion). [] ante cualquier fallo."""
    xml = _get("/thing", {"id": base_id})
    if not xml:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        log.info("BGG thing XML inválido: %s", e)
        return []
    names = []
    for item in root.findall("item"):
        for link in item.findall("link"):
            if link.get("type") == "boardgameexpansion" and link.get("value"):
                names.append(link.get("value"))
    return names


def _expansions_for_base(base_id):
    """Expansiones (nombres) del juego base, cacheadas en bgg_cache.json bajo una
    clave aparte. [] si no hay base_id o BGG falla."""
    if not base_id:
        return []
    cache = _get_cache()
    ckey = "__exp__:" + str(base_id)
    hit = cache.get(ckey)
    if hit is not None:
        return hit.get("names", [])
    names = _fetch_expansions(base_id)
    cache[ckey] = {"names": names, "ts": _today()}
    _save_cache(cache)
    return names


def _distinctive(name):
    """Parte DISTINTIVA del nombre de una expansión (lo que la diferencia del base):
    el trozo tras ':' si lo hay (p.ej. 'Rising Sun: Kami Unbound' -> 'kami unbound'),
    normalizado. Si no hay ':' devuelve el nombre completo normalizado."""
    raw = name.split(":", 1)[1] if ":" in name else name
    return _cache_key(raw)


def _expansion_in_text(exp_names, title, description):
    """True si alguna expansión (su parte distintiva, de >=2 palabras) aparece en
    el TÍTULO (alta confianza) o en la DESCRIPCIÓN sin contexto de mera
    compatibilidad. Conservador: nombres distintivos cortos se ignoran."""
    t = _cache_key(title)
    d = _cache_key(description)
    compat = bool(_COMPAT_RE.search(d))
    for name in exp_names:
        dist = _distinctive(name)
        if len(dist) < 6 or len(dist.split()) < 2:
            continue                      # poco distintivo -> evita falsos positivos
        if dist in t:
            return True                   # en el título: alta confianza
        if dist in d and not compat:
            return True                   # en la descripción y NO es compatibilidad
    return False


def categorize(title, description=""):
    """Refuerzo de categoría con BGG. Devuelve 'expansion' si BGG indica que lo
    que se vende es una expansión —porque el TÍTULO resuelve a expansión, o porque
    el TÍTULO/DESCRIPCIÓN nombra una expansión CONCRETA del juego base—, o None si
    BGG no aporta. Conservador (ante la duda, None: no degrada un base válido).
    NUNCA lanza."""
    info = lookup(title)
    if info is None:
        return None
    if info.get("kind") == "expansion":
        return "expansion"
    names = _expansions_for_base(info.get("bgg_id"))
    if names and _expansion_in_text(names, title, description):
        return "expansion"
    return None


def flush():
    """Persiste la caché en disco (por si se prefiere escribir al final de la
    pasada). lookup() ya guarda en cada miss, así que normalmente es redundante."""
    if _CACHE is not None:
        _save_cache(_CACHE)
