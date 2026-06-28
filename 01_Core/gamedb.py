"""
gamedb.py
---------
Base de datos OFFLINE de juegos de mesa. Sustituto directo (drop-in) de bgg.py:
expone la misma interfaz pública (`categorize`, `bgg_enabled`,
`configure_from_settings`) pero NO consulta la red: lee 01_Core/gamedb.json,
compilado desde un dump de juegos (ver 03_Diagnostico/build_gamedb.py).

Motivación: la XMLAPI2 de BoardGameGeek quedó cerrada (401 en todo acceso
anónimo, 2025). La versión offline es determinista, sin token, sin rate-limit y
funciona en GitHub Actions sin red.

PRINCIPIO (igual que bgg): REFUERZO, no autoridad. Ante CUALQUIER problema
(JSON ausente o ilegible) NO lanza: degrada a "sin dato" (None) y el bot sigue
clasificando por reglas. categorize() nunca degrada un base válido a otra cosa;
como mucho corrige base -> "expansion".

Lógica de categorize(title, description):
  1. Identifica el juego del título probando n-gramas (de más largo a más corto)
     contra el índice de nombres (inglés + traducción).
  2. Si el juego identificado es una EXPANSIÓN -> "expansion".
  3. Si es un juego BASE, busca si alguna expansión CONCRETA de ese base (su
     parte distintiva) aparece en el título, o en la descripción sin contexto de
     mera compatibilidad -> "expansion".
  4. En cualquier otro caso -> None (no toca el resultado de las reglas).
"""

import os
import re
import json
import logging

log = logging.getLogger("gamedb")

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamedb.json")

# n-grama de título más largo que probamos contra el índice de nombres.
_MAX_NGRAM = 10


# --- flag enabled (compatibilidad con la sección 'bgg' de bot_settings.yaml) ---
# Reusa BGG_ENABLED / sección 'bgg' para no tocar config ni docs; admite también
# GAMEDB_ENABLED / sección 'gamedb' si en el futuro se quiere separar.
def _env_enabled():
    for var in ("GAMEDB_ENABLED", "BGG_ENABLED"):
        if var in os.environ:
            return os.getenv(var) not in ("0", "false", "False", "")
    return None

_ENV_OVERRIDE = _env_enabled()
_ENABLED = _ENV_OVERRIDE if _ENV_OVERRIDE is not None else False


def bgg_enabled():
    """True si la integración está activa (gamedb/bgg enabled o GAMEDB/BGG_ENABLED)."""
    return _ENABLED

# Alias por claridad si en el futuro se renombra en los llamadores.
enabled = bgg_enabled


def configure_from_settings(settings):
    """Aplica la sección 'gamedb' (o 'bgg' por compatibilidad) de
    bot_settings.yaml. Entorno > yaml > default. Por defecto DESACTIVADO."""
    global _ENABLED
    if _ENV_OVERRIDE is not None:
        return                                  # el entorno manda
    s = settings or {}
    cfg = s.get("gamedb") or s.get("bgg") or {}
    if cfg.get("enabled") is not None:
        _ENABLED = bool(cfg.get("enabled"))


# --- normalización (idéntica a bgg.py) ----------------------------------------
def _strip_accents(text):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("à", "a"), ("è", "e"), ("ç", "c"), ("ü", "u")):
        text = text.replace(a, b)
    return text


def _norm(title):
    """minúsculas, sin tildes, solo alfanumérico+espacio, colapsado."""
    t = _strip_accents((title or "").lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Texto que indica mera COMPATIBILIDAD (no que se venda la expansión), igual que bgg.
_COMPAT_RE = re.compile(
    r"compatible|ampliab|se amplia|para ampliar|se puede ampliar|sirve para|"
    r"junto a|ademas de|tambien tengo|tengo tambien|no incluye")


# --- carga perezosa del JSON --------------------------------------------------
_DB = None          # {"names": {...}, "exp_by_base": {...}} | {} si falla


def _get_db():
    global _DB
    if _DB is None:
        try:
            with open(_DB_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or "names" not in data:
                raise ValueError("estructura inesperada")
            data.setdefault("exp_by_base", {})
            _DB = data
        except (OSError, ValueError) as e:
            log.warning("gamedb.json no disponible (%s); refuerzo offline omitido", e)
            _DB = {"names": {}, "exp_by_base": {}}
    return _DB


# --- núcleo: identificar el juego del título ----------------------------------
def _find_game(title_words, names):
    """Devuelve (kind, base_norm) donde kind es 1 (expansion) | 0 (base) | None.
    Prueba n-gramas contiguos del título de MÁS LARGO a más corto; una expansión
    exacta gana de inmediato; si no, el base más específico encontrado."""
    n = len(title_words)
    max_len = min(n, _MAX_NGRAM)
    for L in range(max_len, 0, -1):
        base_hit = None
        for i in range(n - L + 1):
            ng = " ".join(title_words[i:i + L])
            ty = names.get(ng)
            if ty == 1:
                return 1, ng                    # expansión exacta: alta confianza
            if ty == 0 and base_hit is None:
                base_hit = ng
        if base_hit is not None:
            return 0, base_hit                  # base más específico de esta longitud
    return None, None


def categorize(title, description=""):
    """'expansion' si la base de datos offline indica que lo vendido es una
    expansión; None si no aporta. Conservador: ante la duda, None (no degrada un
    base válido). NUNCA lanza."""
    if not bgg_enabled():
        return None
    db = _get_db()
    names = db.get("names") or {}
    if not names:
        return None

    t = _norm(title)
    if not t:
        return None
    words = t.split()

    kind, base = _find_game(words, names)
    if kind == 1:
        return "expansion"
    if kind != 0:
        return None

    # El título es un juego BASE: ¿se nombra una expansión concreta suya?
    exp_names = (db.get("exp_by_base") or {}).get(base) or []
    if not exp_names:
        return None
    d = _norm(description)
    compat = bool(_COMPAT_RE.search(d))
    for dist in exp_names:
        if dist in t:
            return "expansion"                  # en el título: alta confianza
        if dist in d and not compat:
            return "expansion"                  # en la descripción y NO compatibilidad
    return None


def flush():
    """Compatibilidad con la interfaz de bgg.py. La versión offline no escribe
    caché, así que es un no-op."""
    return None
