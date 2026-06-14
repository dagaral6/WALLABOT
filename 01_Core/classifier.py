"""
classifier.py
-------------
Análisis de anuncios con Ollama, dividido en tareas PEQUEÑAS y enfocadas
(un modelo de 3B acierta mucho más así que con una única pregunta compleja).

La RELEVANCIA (¿es el juego que busco?) NO la decide el LLM: la decide el
TÍTULO. Si alguna palabra buscada aparece en el título, el juego es correcto.
Esto es barato y fiable, y es donde el spam de "tags" no llega.

El LLM se reserva para lo que sí necesita contexto:
  - classify_category(): sobre un anuncio cuyo título YA coincide, decide si es
    base / expansion / components / lote (usando la descripción).
  - check_lote(): para anuncios cuyo título NO coincide, comprueba si es un
    LOTE de varios juegos que incluye el buscado (ignorando listas de tags).

Si el LLM activo no está disponible, se aplican respaldos conservadores.
El LLM puede ser Ollama (local, por defecto) o un proveedor cloud gratuito
(Groq / Gemini) seleccionado con la variable de entorno LLM_PROVIDER — ver
la sección "LLM helper" más abajo.
"""

import os
import re
import json
import time
import logging
import requests

log = logging.getLogger("classifier")

# Configurable por entorno: OLLAMA_HOST=http://host:11434 (cloud / remoto).
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT = OLLAMA_HOST + "/api/chat"
OLLAMA_TAGS = OLLAMA_HOST + "/api/tags"

VALID = ("base", "expansion", "components", "lote")


# ---------------------------------------------------------------------------
#  COINCIDENCIA POR TÍTULO (relevancia, sin LLM)
# ---------------------------------------------------------------------------

# Palabras demasiado genéricas para validar por sí solas un título.
_STOPWORDS = {"de", "la", "el", "los", "las", "y", "juego", "mesa",
              "edicion", "edición", "the", "of", "game"}


def _normalize(text):
    if not text:
        return ""
    text = text.lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"),
                 ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        text = text.replace(a, b)
    return text


# Marcadores que inician una lista de nombres de OTROS juegos que NO forman
# parte de lo que se vende (spam SEO o referencias tipo "Similar a:"). Cortamos
# la descripción ahí. Para 'tags' exigimos ':' (no cortar en "sin tags ni
# nada"); para "similar a"/"parecido a" los dos puntos son opcionales.
_TAG_MARKERS_RE = re.compile(
    r"(?:\b(?:tags?|etiquetas?|palabras\s+clave|keywords?)\b\s*:)"
    r"|(?:\b(?:similar(?:es)?|parecidos?)\s+a\b\s*:?)"
    r"|(?:\bjuegos\s+similares\b\s*:?)"
    r"|(?:\bte\s+puede\s+interesar\b\s*:?)",
    re.IGNORECASE,
)


def strip_tag_spam(description):
    """
    Recorta la descripción en el primer marcador tipo 'Tags:' o 'Similar a:' y
    devuelve solo la parte de delante (la descripción real). Esos marcadores
    suelen preceder a una lista de nombres de otros juegos que el vendedor pone
    para salir en más búsquedas, pero que NO forman parte de lo que vende. Si no
    hay marcador, deja la descripción igual.
    """
    if not description:
        return description
    # Buscamos sobre el texto normalizado (sin tildes ni mayúsculas) y cortamos
    # el original en el mismo índice: _normalize conserva la longitud.
    m = _TAG_MARKERS_RE.search(_normalize(description))
    if m:
        return description[:m.start()].strip()
    return description


# Palabras que AUMENTAN la sospecha de que un anuncio es solo componentes o una
# expansión. No deciden por sí solas (un juego base puede mencionarlas); se
# pasan como pista al LLM, que decide con el contexto completo.
_COMPONENT_HINT_WORDS = ["inserto", "insertos", "separador", "separadores",
                         "organizador", "instrucciones", "manual", "fundas",
                         "sleeves", "solo cartas", "solo el tablero",
                         "recambio", "repuesto"]
_EXPANSION_HINT_WORDS = ["expansion", "expansiones", "ampliacion",
                         "ampliaciones", "promo"]


def _suspicion_hints(title, description):
    """Pistas (no definitivas) que resaltan señales de componentes/expansión."""
    text = _normalize(title) + " " + _normalize(description)
    hints = []
    if any(w in text for w in _COMPONENT_HINT_WORDS):
        hints.append("menciona piezas/accesorios sueltos (inserto, separador, "
                     "instrucciones, fundas...); si NO incluye el juego base "
                     "completo y jugable, es 'components'")
    if any(w in text for w in _EXPANSION_HINT_WORDS):
        hints.append("menciona 'expansión/ampliación', pero eso por sí solo NO "
                     "lo convierte en expansión: es 'expansion' SOLO si se vende "
                     "únicamente la expansión, sin el juego base. Si incluye el "
                     "juego base completo, es 'base'")
    return hints


# ---------------------------------------------------------------------------
#  SEÑAL FUERTE DE JUEGO BASE (determinista, sin LLM)
# ---------------------------------------------------------------------------
# Un modelo de 3B confunde a menudo un juego base con su línea de expansiones
# (p. ej. "Los Colonos de Catán - El Juego" salía como 'expansion'). Si el
# título deja claro que es el juego base y NO hay señal de "solo expansión /
# solo componentes", lo tratamos como base SIN preguntar al LLM. Esto además
# funciona aunque Ollama esté caído.
_STRONG_BASE_PHRASES = (
    "juego base", "caja base", "caja basica", "edicion base", "version base",
    "juego completo", "core set", "core box", "base game",
    "los colonos de catan",   # nombre canónico del Catán base en español
)
_BASE_SUFFIX_RE = re.compile(r"\bel juego(?:\s+base)?\s*$")

# Señales de que es SOLO una expansión o SOLO componentes: bloquean el atajo a
# base (en esos casos preferimos que decida el LLM o el respaldo).
_EXP_OR_COMP_ONLY = (
    "solo la expansion", "solo expansion", "solo la ampliacion",
    "solo ampliacion", "unicamente la expansion", "sin el juego base",
    "no incluye el juego", "no incluye la base", "necesitas el juego base",
    "requiere el juego base", "solo los insertos", "solo insertos",
    "solo las fundas", "solo fundas", "solo cartas", "solo el tablero",
    "solo manual", "solo instrucciones", "es un recambio", "es un repuesto",
)


def _expansion_or_component_only(title, description):
    t = _normalize(title)
    full = t + " " + _normalize(description)
    if t.startswith(("expansion ", "ampliacion ", "promo ")):
        return True
    return any(p in full for p in _EXP_OR_COMP_ONLY)


def strong_base_signal(title, description=""):
    """True si el TÍTULO deja claro que es el juego base completo (y no hay
    indicios de que sea solo expansión o solo componentes)."""
    if _expansion_or_component_only(title, description):
        return False
    t = _normalize(title)
    if any(p in t for p in _STRONG_BASE_PHRASES):
        return True
    return bool(_BASE_SUFFIX_RE.search(t))


def title_matches(target, title):
    """
    True si ALGUNA palabra significativa del término buscado aparece como
    palabra en el título. Tokeniza por palabras (ignorando puntuación pegada
    como ':' o ',') y compara por palabra completa: así 'catan' no encaja
    dentro de otra palabra, pero 'Wingspan:' sí cuenta como 'wingspan'.
    """
    t_words = set(re.findall(r"\w+", _normalize(title)))
    target_words = [w for w in re.findall(r"\w+", _normalize(target))
                    if w not in _STOPWORDS]
    if not target_words:
        target_words = re.findall(r"\w+", _normalize(target))
    return any(w in t_words for w in target_words)


# ---------------------------------------------------------------------------
#  LLM helper — cascada con circuit breaker por proveedor
# ---------------------------------------------------------------------------
# Variables de entorno:
#   GEMINI_API_KEY   = clave de aistudio.google.com   (1er proveedor)
#   GROQ_API_KEY     = clave de console.groq.com      (2o proveedor)
#   LLM_API_KEY +
#   LLM_BASE_URL     = API compatible OpenAI adicional (opcional)
#   LLM_OLLAMA_HOST  = host de Ollama (por defecto localhost)
#
# Orden de cascada (configurable con LLM_CASCADE):
#   Por defecto: gemini,groq,rules
#   Ollama local: LLM_CASCADE=ollama,gemini,groq,rules
#   Solo reglas:  LLM_CASCADE=rules
#
# LLM_COOLDOWN = segundos de pausa por proveedor tras 429 sostenido (def. 600)

_GROQ_BASE   = "https://api.groq.com/openai/v1"
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

_DEFAULT_MODELS = {
    "groq":   "llama-3.1-8b-instant",
    "gemini": "gemini-2.5-flash-lite",
    "openai": "",
    "ollama": "",               # se usa el model del config yaml
}

# Throttle: segundos mínimos entre llamadas a cada proveedor
_DEFAULT_INTERVALS = {
    "ollama": 0.0, "groq": 2.1, "openai": 2.1, "gemini": 4.1,
}

# --- cascade ---
_raw_cascade = os.getenv("LLM_CASCADE", "gemini,groq,rules")
LLM_CASCADE   = [p.strip().lower() for p in _raw_cascade.split(",") if p.strip()]
# Para compatibilidad: si se define LLM_PROVIDER a un valor concreto y
# LLM_CASCADE no está en el entorno, lo respetamos.
if "LLM_PROVIDER" in os.environ and "LLM_CASCADE" not in os.environ:
    _lp = os.environ["LLM_PROVIDER"].strip().lower()
    if _lp != "rules":
        LLM_CASCADE = [_lp, "rules"]
    else:
        LLM_CASCADE = ["rules"]

# Para que main.py pueda hacer "LLM activo: gemini / …"
LLM_PROVIDER = LLM_CASCADE[0] if LLM_CASCADE else "rules"

# --- circuit breakers (un reloj por proveedor, en memoria) ---
try:
    _LLM_COOLDOWN = float(os.getenv("LLM_COOLDOWN", "600"))
except ValueError:
    _LLM_COOLDOWN = 600.0

_breaker_until: dict[str, float] = {}   # proveedor -> monotonic timestamp

def _breaker_open(provider: str) -> bool:
    return time.monotonic() < _breaker_until.get(provider, 0.0)

def _trip_breaker(provider: str) -> None:
    _breaker_until[provider] = time.monotonic() + _LLM_COOLDOWN
    remaining = [p for p in LLM_CASCADE if p != "rules" and not _breaker_open(p)]
    next_p = remaining[0] if remaining else "rules"
    log.warning(
        "LLM cascade: %s en cooldown (%.0f min). Siguiente: %s.",
        provider, _LLM_COOLDOWN / 60.0, next_p,
    )

# --- throttle por proveedor ---
_last_call: dict[str, float] = {}

def _throttle(provider: str) -> None:
    raw = os.getenv("LLM_MIN_INTERVAL")
    try:
        interval = float(raw) if raw is not None else _DEFAULT_INTERVALS.get(provider, 2.1)
    except ValueError:
        interval = _DEFAULT_INTERVALS.get(provider, 2.1)
    since = time.monotonic() - _last_call.get(provider, 0.0)
    wait = interval - since
    if wait > 0:
        time.sleep(wait)
    _last_call[provider] = time.monotonic()


def _cloud_model(provider: str) -> str:
    return os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(provider, "")


def _api_key(provider: str) -> str:
    if provider == "groq":
        return os.getenv("GROQ_API_KEY", "")
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY", "")
    if provider == "openai":
        return os.getenv("LLM_API_KEY", "")
    return ""


def _json_from_text(text):
    """json.loads tolerante: quita vallas ``` y recorta al {...} exterior."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            text = text[i:j + 1]
    return json.loads(text)


def _post_with_retry(provider, url, headers, payload, timeout, tries=2):
    """POST con 2 reintentos cortos. Si agota los intentos con 429, abre el
    circuit breaker del proveedor para que la cascada salte al siguiente."""
    r = None
    for attempt in range(tries):
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == tries - 1:
                if r.status_code == 429:
                    _trip_breaker(provider)
                break
            try:
                wait = float(r.headers.get("retry-after"))
            except (TypeError, ValueError):
                wait = 5.0 * (attempt + 1)
            log.info("LLM %s: HTTP %s, reintento en %.0fs...",
                     provider, r.status_code, min(wait, 20))
            time.sleep(min(wait, 20))
            continue
        break
    r.raise_for_status()
    return r


def _ask_provider(provider, model, schema, messages, timeout=120):
    """Llama a un proveedor concreto. Lanza RequestException si falla."""
    if _breaker_open(provider):
        raise requests.RequestException(
            "%s en cooldown (circuit breaker abierto)" % provider)
    if provider == "ollama":
        return _ask_ollama(model, schema, messages, timeout)
    key = _api_key(provider)
    if not key:
        raise requests.RequestException(
            "falta la API key del proveedor '%s'" % provider)
    _throttle(provider)
    if provider == "gemini":
        return _ask_gemini(provider, key, schema, messages, timeout)
    if provider in ("groq", "openai"):
        return _ask_openai_compat(provider, key, schema, messages, timeout)
    raise requests.RequestException("proveedor desconocido: '%s'" % provider)


def _ask(model, schema, messages, timeout=120):
    """Intenta los proveedores de LLM_CASCADE en orden hasta que uno responde.
    Si todos fallan, lanza RequestException para que el llamador use reglas."""
    for provider in LLM_CASCADE:
        if provider == "rules":
            raise requests.RequestException("cascade agotada — usando reglas")
        try:
            return _ask_provider(provider, model, schema, messages, timeout)
        except requests.RequestException as exc:
            log.warning("LLM cascade: %s falló (%s), probando siguiente...",
                        provider, exc)
    raise requests.RequestException(
        "todos los proveedores de la cascada fallaron")


def _ask_ollama(model, schema, messages, timeout):
    payload = {
        "model": model,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0},
        "messages": messages,
    }
    r = requests.post(OLLAMA_CHAT, json=payload, timeout=timeout)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def _ask_openai_compat(provider, key, schema, messages, timeout):
    """Groq y cualquier API compatible con OpenAI (LLM_BASE_URL)."""
    base = (_GROQ_BASE if provider == "groq"
            else os.getenv("LLM_BASE_URL", "").rstrip("/"))
    if not base:
        raise requests.RequestException("falta LLM_BASE_URL para 'openai'")
    props = ", ".join((schema.get("properties") or {}).keys())
    msgs = list(messages) + [{
        "role": "system",
        "content": "Responde UNICAMENTE con un objeto JSON valido con las "
                   "claves: " + props + ". Sin texto adicional."}]
    payload = {
        "model": _cloud_model(provider),
        "temperature": 0,
        "messages": msgs,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": "Bearer " + key}
    r = _post_with_retry(provider, base + "/chat/completions",
                         headers, payload, timeout)
    return _json_from_text(r.json()["choices"][0]["message"]["content"])


def _ask_gemini(provider, key, schema, messages, timeout):
    """Gemini: system -> systemInstruction; assistant -> role 'model'."""
    system_parts, contents = [], []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            contents.append({
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            })
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    if system_parts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]}
    url = "%s/models/%s:generateContent" % (_GEMINI_BASE, _cloud_model(provider))
    r = _post_with_retry(provider, url, {"x-goog-api-key": key}, payload, timeout)
    parts = r.json()["candidates"][0]["content"]["parts"]
    return _json_from_text("".join(p.get("text", "") for p in parts))


def llm_available():
    """(ok, descripcion) del LLM activo, para el banner de arranque."""
    parts = []
    for p in LLM_CASCADE:
        if p == "rules":
            parts.append("rules")
            continue
        model = _cloud_model(p) or "?"
        if _breaker_open(p):
            parts.append("%s[cooldown]" % p)
        else:
            parts.append("%s/%s" % (p, model))
    cascade_str = " → ".join(parts)
    # Comprobación rápida del primer proveedor activo (no rules)
    first = next((p for p in LLM_CASCADE if p != "rules" and not _breaker_open(p)), None)
    if first is None:
        return len([p for p in LLM_CASCADE if p == "rules"]) > 0, cascade_str
    if first == "ollama":
        return ollama_available(), cascade_str
    key = _api_key(first)
    if not key:
        return False, cascade_str + " (falta API key)"
    try:
        if first == "groq":
            r = requests.get(_GROQ_BASE + "/models", timeout=8,
                             headers={"Authorization": "Bearer " + key})
        elif first == "gemini":
            r = requests.get(_GEMINI_BASE + "/models", timeout=8,
                             headers={"x-goog-api-key": key})
        else:
            base = os.getenv("LLM_BASE_URL", "").rstrip("/")
            if not base:
                return False, cascade_str + " (falta LLM_BASE_URL)"
            r = requests.get(base + "/models", timeout=8,
                             headers={"Authorization": "Bearer " + key})
        return r.status_code == 200, cascade_str
    except requests.RequestException as e:
        return False, "%s (%s)" % (cascade_str, e)


# ---------------------------------------------------------------------------
#  TAREA 1: categoría (título YA coincide)
# ---------------------------------------------------------------------------

_CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_board_game": {"type": "boolean"},
        "category": {"type": "string", "enum": list(VALID)},
        "includes_base_game": {"type": "boolean"},
    },
    "required": ["is_board_game", "category", "includes_base_game"],
}

_CATEGORY_PROMPT = """Clasificas anuncios de juegos de mesa de segunda mano.
El título contiene el nombre buscado, pero ese nombre puede coincidir con otros
productos (ropa, electrónica, medallas, música, libros, herramientas...).

Primero decide is_board_game: ¿el anuncio vende un JUEGO DE MESA, o una
expansión, componentes o un lote de juegos de mesa? Pon false si es cualquier
otra cosa aunque el nombre coincida (p.ej. guantes, interruptores, CDs,
medallas, vinilos, libros). Si is_board_game es false, la categoría da igual
(pon "base").

Si is_board_game es true, di qué tipo de producto es:
- "base": incluye el JUEGO BASE completo y jugable. Si además trae extras
  (insertos, fundas, una expansión añadida), SIGUE siendo "base".
- "expansion": es SOLO una expansión/ampliación, SIN el juego base.
- "components": son SOLO piezas o accesorios sueltos, sin un juego jugable
  (solo insertos, solo fundas, cartas sueltas, un recambio, solo el tablero).
- "lote": son VARIOS juegos distintos vendidos juntos.

MUY IMPORTANTE: clasifica el PRODUCTO PRINCIPAL que se vende. Que la descripción
mencione expansiones (porque el vendedor tenga más, por compatibilidad, o porque
diga "sin expansiones") NO convierte un juego base en "expansion". Marca
"expansion" SOLO si lo que se vende es ÚNICAMENTE la expansión, sin el juego
base. Títulos como "X - El Juego", "Los Colonos de Catán" o "X edición base" son
el JUEGO BASE.

Pista: "incluye insertos" / "con fundas" = extra de un juego base -> "base".
"solo los insertos" / "insertos para X" sin el juego -> "components".
Si dudas entre base y expansión y parece estar el juego completo, elige "base".

Marca includes_base_game=true si incluye el juego base completo.
Responde SOLO en JSON."""

_CATEGORY_FEWSHOT = [
    ("TÍTULO: Los Colonos de Catán - El Juego\n"
     "DESCRIPCIÓN: El juego base de Catán, completo. También tengo a la venta "
     "las expansiones Navegantes y Ciudades y Caballeros por separado.",
     {"is_board_game": True, "category": "base", "includes_base_game": True}),
    ("TÍTULO: Catan edición base\n"
     "DESCRIPCIÓN: Caja base completa y jugable. Compatible con todas las "
     "expansiones.",
     {"is_board_game": True, "category": "base", "includes_base_game": True}),
    ("TÍTULO: Wingspan con inserto de madera\n"
     "DESCRIPCIÓN: Juego base completo, le añadí un inserto organizador.",
     {"is_board_game": True, "category": "base", "includes_base_game": True}),
    ("TÍTULO: Insertos para Wingspan\n"
     "DESCRIPCIÓN: Solo los insertos impresos en 3D, no incluye el juego.",
     {"is_board_game": True, "category": "components",
      "includes_base_game": False}),
    ("TÍTULO: Catan Navegantes\n"
     "DESCRIPCIÓN: Solo la expansión; necesitas el Catan básico para jugar.",
     {"is_board_game": True, "category": "expansion",
      "includes_base_game": False}),
    ("TÍTULO: Lote Catan, Azul y Carcassonne\n"
     "DESCRIPCIÓN: Tres juegos completos, se venden juntos.",
     {"is_board_game": True, "category": "lote", "includes_base_game": True}),
    ("TÍTULO: Guantes Inis Trangoworld Talla L\n"
     "DESCRIPCIÓN: Guantes de montaña, poco uso.",
     {"is_board_game": False, "category": "base", "includes_base_game": False}),
    ("TÍTULO: Interruptor Somfy Inis Uno 1800191\n"
     "DESCRIPCIÓN: Interruptor para persianas, a estrenar.",
     {"is_board_game": False, "category": "base", "includes_base_game": False}),
]


def classify_category(title, description, use_llm=True, model="qwen2.5:3b"):
    """Devuelve 'base'|'expansion'|'components'|'lote'|'unknown'."""
    description = strip_tag_spam(description)
    # Atajo determinista: si el título es claramente el juego base (y no es un
    # lote), lo damos por 'base' sin preguntar al LLM. Evita el error de que un
    # modelo pequeño marque un juego base como 'expansion', y funciona aunque
    # Ollama esté caído.
    if (not any(w in _normalize(title) for w in _LOTE_WORDS)
            and strong_base_signal(title, description)):
        return "base"
    if not use_llm:
        return _fallback_category(title, description)
    msgs = [{"role": "system", "content": _CATEGORY_PROMPT}]
    for u, a in _CATEGORY_FEWSHOT:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant",
                     "content": json.dumps(a, ensure_ascii=False)})
    user_msg = (f"TÍTULO: {title}\n"
                f"DESCRIPCIÓN: {description or '(sin descripción)'}")
    hints = _suspicion_hints(title, description)
    if hints:
        user_msg += ("\n\nPISTAS (no definitivas, decide por el contexto):\n- "
                     + "\n- ".join(hints))
    msgs.append({"role": "user", "content": user_msg})
    try:
        data = _ask(model, _CATEGORY_SCHEMA, msgs)
        if not data.get("is_board_game", True):
            return "not_game"
        cat = data.get("category", "unknown")
        if data.get("includes_base_game") and cat in ("base", "expansion"):
            cat = "base"
        return cat if cat in VALID else "unknown"
    except requests.RequestException as e:
        log.warning("LLM no disponible [%s]: %s", LLM_PROVIDER, e)
        return "unknown"
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Respuesta no parseable (%s).", e)
        return "unknown"


# ---------------------------------------------------------------------------
#  TAREA 2: ¿lote que incluye el juego buscado? (título NO coincide)
# ---------------------------------------------------------------------------

_LOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_lote": {"type": "boolean"},
        "includes_target": {"type": "boolean"},
        "games": {"type": "string"},
    },
    "required": ["is_lote", "includes_target"],
}

_LOTE_PROMPT = """Analizas un anuncio de juegos de mesa de segunda mano.
El TÍTULO no menciona el JUEGO BUSCADO, así que solo nos interesa un caso:
que el anuncio sea un LOTE (varios juegos distintos vendidos juntos) que
INCLUYA el juego buscado.

CUIDADO CON EL SPAM: muchos vendedores añaden al final de la descripción una
lista larga de nombres de juegos (a veces tras "Tags:", "Etiquetas:",
"palabras clave", o como una ristra de títulos) SOLO para salir en más
búsquedas. Esos nombres NO forman parte de lo que se vende. Para que cuente
como lote, los juegos deben describirse como parte real del lote (cantidades,
estado, "se venden juntos", precio del conjunto...), NO en una lista de tags.

- is_lote: true solo si realmente se venden varios juegos juntos.
- includes_target: true solo si el JUEGO BUSCADO es uno de los del lote real
  (no si solo aparece en una lista de tags).
- games: nombra los juegos que de verdad componen el lote.
Responde SOLO en JSON."""

_LOTE_FEWSHOT = [
    ("JUEGO BUSCADO: catan\n"
     "TÍTULO: Lote de 3 juegos de mesa\n"
     "DESCRIPCIÓN: Vendo juntos Catan, Carcassonne y Azul, los tres completos "
     "y en buen estado. Precio por el lote entero.",
     {"is_lote": True, "includes_target": True,
      "games": "Catan, Carcassonne, Azul"}),
    ("JUEGO BUSCADO: wingspan\n"
     "TÍTULO: El Favor del Faraón\n"
     "DESCRIPCIÓN: Juego El Favor del Faraón, edición 2015, perfecto estado. "
     "Tags: catan carcassonne root wingspan dune brass nemesis eurogame",
     {"is_lote": False, "includes_target": False,
      "games": "El Favor del Faraón"}),
    ("JUEGO BUSCADO: root\n"
     "TÍTULO: Pack juegos de estrategia\n"
     "DESCRIPCIÓN: Lote con Root, Scythe y Terraforming Mars. Todo original, "
     "se vende el conjunto.",
     {"is_lote": True, "includes_target": True,
      "games": "Root, Scythe, Terraforming Mars"}),
]


def check_lote(target, title, description, use_llm=True, model="qwen2.5:3b"):
    """
    Devuelve dict {is_lote, includes_target, games}. Si Ollama falla, devuelve
    is_lote=False (no podemos confirmar sin LLM).
    """
    description = strip_tag_spam(description)
    if not use_llm:
        return {"is_lote": False, "includes_target": False, "games": ""}
    msgs = [{"role": "system", "content": _LOTE_PROMPT}]
    for u, a in _LOTE_FEWSHOT:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant",
                     "content": json.dumps(a, ensure_ascii=False)})
    msgs.append({"role": "user",
                 "content": f"JUEGO BUSCADO: {target}\n"
                            f"TÍTULO: {title}\n"
                            f"DESCRIPCIÓN: {description or '(sin descripción)'}"})
    try:
        data = _ask(model, _LOTE_SCHEMA, msgs)
        return {
            "is_lote": bool(data.get("is_lote", False)),
            "includes_target": bool(data.get("includes_target", False)),
            "games": data.get("games", ""),
        }
    except requests.RequestException as e:
        log.warning("LLM no disponible [%s]: %s", LLM_PROVIDER, e)
        return {"is_lote": False, "includes_target": False, "games": ""}
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Respuesta no parseable (%s).", e)
        return {"is_lote": False, "includes_target": False, "games": ""}


# ---------------------------------------------------------------------------
#  RESPALDO de categoría sin LLM (conservador)
# ---------------------------------------------------------------------------

_LOTE_WORDS = ["lote", "pack", "coleccion", "conjunto", "varios juegos", "bundle"]

# Pistas baratas (sin LLM) de que un anuncio PODRÍA ser un lote. Solo si alguna
# aparece consultamos al LLM en la rama de lotes; así evitamos una llamada por
# cada anuncio cuyo título no coincide.
_LOTE_HINTS = ["lote", "pack", "coleccion", "conjunto", "varios", "bundle",
               "juegos de mesa"]


def looks_like_lote(title, description):
    """Heurística barata: ¿el texto sugiere un lote de varios juegos?"""
    text = _normalize(title) + " " + _normalize(strip_tag_spam(description))
    return any(h in text for h in _LOTE_HINTS)


def _fallback_category(title, description):
    t, d = _normalize(title), _normalize(description)
    full = f"{t} {d}"
    if any(w in t for w in _LOTE_WORDS):   # 'lote' en el TÍTULO
        return "lote"
    if strong_base_signal(title, description):
        return "base"
    if "solo la expansion" in d or "solo expansion" in d:
        return "expansion"
    if ("no incluye el juego" in d or "sin el juego base" in d
            or "solo los insertos" in d or "solo las fundas" in d):
        return "components"
    return "unknown"


def ollama_available():
    try:
        return requests.get(OLLAMA_TAGS, timeout=5).status_code == 200
    except requests.RequestException:
        return False
