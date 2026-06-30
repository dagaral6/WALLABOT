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
El LLM funciona como CASCADA de proveedores (el primero que responde gana; el
resto son red de seguridad): Ollama (local), Groq, Cerebras, Gemini, OpenRouter
y GitHub Models, más el terminal 'rules'. El orden y los modelos se configuran
en bot_settings.yaml (sección 'llm') o por variables de entorno — ver la
sección "LLM helper" más abajo.
"""

import os
import re
import json
import time
import logging
import functools
import unicodedata
import requests

try:
    from wordfreq import zipf_frequency
except ImportError:                      # sin wordfreq: todas las palabras
    zipf_frequency = None                # se tratan como "fuertes" (compat)

try:                                     # detección de idioma (señal secundaria)
    from langdetect import detect_langs as _detect_langs
    from langdetect import DetectorFactory as _DetectorFactory
    _DetectorFactory.seed = 0            # determinista entre ejecuciones
except ImportError:                      # sin langdetect: solo el vocabulario
    _detect_langs = None

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
    # NFC: recompone caracteres descompuestos (p.ej. 'n'+tilde combinante -> 'ñ').
    # Sin esto, una 'ñ'/'ó' en forma NFD se parte y rompe el matching ('borgoña'
    # -> 'borgon'+'a'). Solo unifica representaciones equivalentes; no elimina las
    # marcas de otros idiomas (è, ç, ü...) que esta normalizacion conserva aposta.
    text = unicodedata.normalize("NFC", text).lower()
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


# --- Vocabulario EXPLÍCITO de LOTE (regla dura, rediseño jun 2026) -----------
# Su presencia es CONDICIÓN NECESARIA para clasificar como 'lote': sin él, nunca
# es lote (aunque lo diga el modelo). Deliberadamente ESPECÍFICO (frases de lote
# reales) para no confundir "pack completo de minis" (componentes) ni "Juego
# Base y Expansiones X, Y, Z" (un solo juego) con un lote. En forma normalizada
# (sin tildes, minúsculas), porque se compara contra _normalize(texto).
_LOTE_VOCAB = [
    "lote", "coleccion", "bundle",
    "lote de juegos", "varios juegos", "pack de juegos",
    "conjunto de juegos", "se venden juntos", "se vende junto",
    "se venden todos", "todo junto", "todos juntos",
]
_LOTE_VOCAB_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _LOTE_VOCAB) + r")\b")


def _has_lote_vocab(text):
    """True si el texto contiene vocabulario EXPLÍCITO de lote (_LOTE_VOCAB).
    Por palabra/expresión completa: 'lote' no matchea dentro de 'loteria'."""
    return bool(_LOTE_VOCAB_RE.search(_normalize(text)))


# --- Idioma del anuncio: solo nos interesan español, catalán e inglés -------
# Si el propio anuncio (título/descripción) está en otro idioma, asumimos que
# el juego también lo está y lo descartamos. Dos mecanismos GENERALES (no listas
# de ejemplos concretos):
#   1) Vocabulario funcional de ALTA FRECUENCIA por idioma (artículos,
#      preposiciones, verbos de venta, términos de juego) DELIBERADAMENTE
#      inequívoco: palabras que no existen como tales en es/ca/en, para no
#      rechazar por error un anuncio en los idiomas que sí interesan.
#   2) Declaración explícita del idioma del juego escrita en español
#      ("edición italiana", "en alemán", "idioma X"...): se mapea a idioma y
#      solo marca foreign si ese idioma NO es es/ca/en (el inglés está permitido).
# _normalize() solo quita tildes españolas (á é í ó ú ñ); las marcas propias de
# otros idiomas (è, ç, ü, ã, î, ô...) se conservan intactas para esta detección.
_FOREIGN_LANG_VOCAB = [
    # --- francés ---
    "très", "avec", "français", "française", "jeu", "jeu de société",
    "vendu", "neuf", "état", "boîte", "règles", "pour", "complet avec",
    # --- alemán ---
    "und", "sehr", "gebraucht", "verkaufe", "zustand", "spiel", "spiele",
    "neuwertig", "versand", "der", "das", "mit", "für", "nicht", "neu",
    "ein", "brettspiel", "würfel", "karten", "deutsch", "deutsche", "ovp",
    # --- italiano ---
    "gioco da tavolo", "gioco", "giochi", "giocatori", "edizione",
    "espansione", "espansioni", "scatola", "ottime condizioni", "usato",
    "nuovo di zecca", "nuovo", "perfetto", "della", "dei", "delle", "degli",
    "lingua", "da tavolo", "tedesca", "tedesco", "con scatola",
    # ampliación jun 2026 (fugas reales it que el vocab no cubría):
    "carte", "risorse", "coloni", "raccoglitori", "segnalini", "plancia",
    "pedine", "mazzo", "regolamento", "tessere", "scatole", "giocare",
    # --- portugués ---
    "jogo de tabuleiro", "tabuleiro", "jogo", "jogos", "muito bom estado",
    "perfeito", "não", "edição", "expansão", "versão", "português",
    "portuguesa", "peças", "muito",
    # --- neerlandés ---
    "bordspel", "spel", "spellen", "uitbreiding", "het", "een", "nieuw",
    "gebruikt", "nederlands", "kaarten", "compleet", "basisspel",
    "kolonisten", "zo goed als nieuw",
]
_FOREIGN_LANG_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _FOREIGN_LANG_VOCAB) + r")\b")

# Declaración explícita, en español, de que el JUEGO está en otro idioma.
# Solo idiomas NO permitidos (es/ca/en quedan fuera de la lista a propósito:
# "edición inglesa" / "en castellano" NO deben marcar foreign).
_FOREIGN_DECLARED = (r"italiano|italiana|aleman|alemana|frances|francesa|"
                     r"portugues|portuguesa|neerlandes|neerlandesa|"
                     r"holandes|holandesa")
_FOREIGN_DECL_RE = re.compile(
    r"\b(?:en|edicion|edicio|idioma|version|lengua|texto en|todo en|"
    r"completamente en|solo en|unicamente en)\s+"
    r"(?:" + _FOREIGN_DECLARED + r")\b")


# --- Detección de idioma como señal SECUNDARIA (refuerza el vocabulario) ------
# El vocabulario de listas no cubre todos los anuncios extranjeros (p.ej. un
# título italiano con palabras que no estaban en la lista). langdetect, ya que
# existe, da una segunda señal. CONSERVADORA a propósito: solo marca foreign un
# idioma NO permitido con ALTA confianza y SOLO sobre la DESCRIPCIÓN (prosa). El
# TÍTULO no se usa aquí: lleno de nombres propios y a menudo en inglés, engaña a
# langdetect ("Camel Up Carcassonne" -> it 0.9999; "Rising Sun ... Ed." -> de
# 0.9999), lo que rechazaría anuncios válidos. Por eso se exige una descripción
# con texto suficiente (principio del proyecto: ante la duda, dejar pasar). El
# título extranjero ya lo cubre el vocabulario.
_ALLOWED_LANGS = {"es", "ca", "en"}
_LANGDETECT_ENABLED = os.getenv("LANGDETECT_ENABLED", "1") not in ("0", "false", "False")
try:
    _LANGDETECT_MIN_PROB = float(os.getenv("LANGDETECT_MIN_PROB", "0.95"))
except ValueError:
    _LANGDETECT_MIN_PROB = 0.95
try:
    _LANGDETECT_MIN_DESC = int(os.getenv("LANGDETECT_MIN_DESC", "40"))
except ValueError:
    _LANGDETECT_MIN_DESC = 40


def configure_language_from_settings(settings):
    """Aplica la sección 'language' de bot_settings.yaml (langdetect). Entorno >
    yaml > default. Idempotente."""
    global _LANGDETECT_ENABLED, _LANGDETECT_MIN_PROB
    lang = (settings or {}).get("language") or {}
    if ("LANGDETECT_ENABLED" not in os.environ
            and lang.get("langdetect_enabled") is not None):
        _LANGDETECT_ENABLED = bool(lang.get("langdetect_enabled"))
    if ("LANGDETECT_MIN_PROB" not in os.environ
            and lang.get("langdetect_min_prob") is not None):
        try:
            _LANGDETECT_MIN_PROB = float(lang["langdetect_min_prob"])
        except (TypeError, ValueError):
            log.warning("language.langdetect_min_prob invalido: %s",
                        lang.get("langdetect_min_prob"))


def _langdetect_foreign(title, description):
    """True si langdetect detecta un idioma NO permitido (it/fr/de/pt/nl...) con
    prob >= _LANGDETECT_MIN_PROB en la DESCRIPCIÓN. Usa SOLO la descripción (prosa
    fiable), nunca el título (nombres propios -> falsos positivos). Requiere una
    descripción con texto suficiente (>= _LANGDETECT_MIN_DESC). Degradación
    elegante: sin langdetect, desactivado o descripción corta -> False.

    (El parámetro `title` se mantiene en la firma por claridad del llamador, pero
    NO se usa: el título extranjero lo cubre el vocabulario, no langdetect.)"""
    if not (_LANGDETECT_ENABLED and _detect_langs is not None):
        return False
    desc = (description or "").strip()
    if len(desc) < _LANGDETECT_MIN_DESC:  # poca prosa: detección no fiable
        return False
    try:
        langs = _detect_langs(desc[:600])
    except Exception:                     # langdetect lanza ante texto sin features
        return False
    if not langs:
        return False
    top = langs[0]
    return top.lang not in _ALLOWED_LANGS and top.prob >= _LANGDETECT_MIN_PROB


def looks_foreign_language(title, description):
    """True si el título o la descripción indican que el juego está en un idioma
    distinto de español, catalán o inglés: por vocabulario inequívoco del idioma
    o por una declaración explícita en español ("edición italiana", "en alemán").

    EXCEPCIÓN (override): no se marca foreign si el anuncio indica que el juego
    es JUGABLE en un idioma permitido —"independiente del idioma", o reglas/
    instrucciones/edición en español/castellano/catalán/inglés—. Muchas ediciones
    extranjeras son language-independent o traen reglas en español; ahí el idioma
    de la caja es irrelevante para el comprador. El override usa señales EN
    ESPAÑOL/permitidas, que no aparecen en una descripción genuinamente en otro
    idioma, así que no deja pasar juegos realmente inservibles por idioma.

    Dos señales de "idioma extranjero": (1) el vocabulario/declaración de siempre
    y (2) langdetect (secundaria, conservadora; ver _langdetect_foreign). El
    override _PLAYABLE_OK manda sobre AMBAS: si el anuncio dice que es jugable en
    un idioma permitido, no se descarta aunque la caja esté en otro idioma.
    """
    norm = _normalize(f"{title} {description}")
    foreign = bool(_FOREIGN_LANG_RE.search(norm) or _FOREIGN_DECL_RE.search(norm))
    if not foreign:
        foreign = _langdetect_foreign(title, description)   # señal secundaria
    if not foreign:
        return False
    if _PLAYABLE_OK_RE.search(norm):
        return False
    return True


# Señales de que el juego es usable en un idioma permitido (override del gate).
# Independencia de idioma + mención de español/castellano/catalán/inglés. Son
# términos EN ESPAÑOL/permitidos: no aparecen en prosa genuinamente extranjera.
_PLAYABLE_OK = [
    "independiente del idioma", "independiente de idioma", "idioma independiente",
    "independiente del lenguaje", "no depende del idioma", "idioma irrelevante",
    "language independent", "language-independent", "no necesita idioma",
    "espanol", "castellano", "catalan", "valencià", "valenciano",
    "ingles", "english",
]
_PLAYABLE_OK_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _PLAYABLE_OK) + r")\b")


# ---------------------------------------------------------------------------
#  RELEVANCIA — gate NLI para keywords ambiguas (Cities, Risk, ...)
# ---------------------------------------------------------------------------
# Problema: una keyword de UNA sola palabra y COMÚN ("cities", "risk") cuela
# otros juegos que contienen esa palabra: "Lost Cities", "Underwater Cities",
# "Cities of Sigmar"... title_matches() no puede distinguirlos (para un término
# de una palabra, cualquier coincidencia vale). Aquí, SOLO para esas keywords
# riesgosas, un gate de relevancia NLI decide si el anuncio es EXACTAMENTE el
# juego buscado o uno distinto.
#
# Híbrido y conservador: NLI zero-shot (Hugging Face) cuando hay servicio;
# fallback determinista (lista de confusores) cuando el NLI no responde o duda.
# Ante la duda, deja pasar (no perder anuncios buenos). Reversible: relevance.enabled.
#
# El nombre canónico ('game') y los confusores viven aquí, así NO hay que cambiar
# el esquema de las alertas (alert["keywords"] sigue siendo un string).
_RISKY_KEYWORDS = {
    "cities": {
        "game": "Cities, el juego de mesa de negociación de Devir",
        "confusers": ["lost cities", "underwater cities",
                      "between two cities", "cities of sigmar",
                      "cities sigmar",          # variante sin 'of' (Warhammer)
                      "cities skylines",
                      "7 wonders", "7wonders"],  # 'Cities' es expansion de 7 Wonders
    },
    # Multi-palabra (frase): "rising sun" cuela otros productos que llevan esas
    # dos palabras ("Setting Sun Rising", dardos "Rising Sun"...). A propósito SIN
    # confusores a mano (el usuario rechaza mantener diccionarios): lo resuelven el
    # NLI vivo (semántico, entiende el orden) y la regla de ORDEN del fallback
    # determinista (ver nli_relevance_gate / _phrase_in_order).
    "rising sun": {
        "game": "Rising Sun, el juego de mesa de CMON",
        "confusers": [],
    },
    # "risk" se deja fuera por defecto: tiene variantes legítimas (Risk Legacy,
    # Risk: Star Wars...) y la palabra inglesa "risk" aparece en descripciones.
    # Añadir aquí cuando se afine su lista de confusores.
}

# Configurable por settings (relevance.*) o entorno; por defecto activo.
_RELEVANCE_ENABLED = os.getenv("RELEVANCE_ENABLED", "1") not in ("0", "false", "False")
_NLI_MODEL = os.getenv("NLI_MODEL", "joeddav/xlm-roberta-large-xnli")
try:
    _NLI_MARGIN = float(os.getenv("NLI_MARGIN", "0.15"))
except ValueError:
    _NLI_MARGIN = 0.15
_NLI_HYP_TEMPLATE = "Este anuncio trata de {}."
# Endpoint de inferencia. El antiguo api-inference.huggingface.co fue RETIRADO por
# HF; el actual es el router de Inference Providers (provider hf-inference), que
# EXIGE HF_API_TOKEN y factura por uso. Mismo payload pipeline y misma respuesta
# {labels, scores}. Override por NLI_API_URL si HF vuelve a cambiarlo.
_NLI_API_URL = os.getenv(
    "NLI_API_URL", "https://router.huggingface.co/hf-inference/models/{model}")
# Cortocircuito de proceso: tras el PRIMER fallo del NLI (red/DNS, 5xx, 429, token
# inválido...) se deja de llamar a la red el resto de la ejecución y se registra
# UNA sola vez. Evita reintentar (y spamear el log con un traceback por anuncio) un
# servicio que ya sabemos caído. En CI/--once el proceso es efímero -> se reevalúa
# en cada run.
_NLI_UNAVAILABLE = False

# Caché de relevancia en memoria: (keyword, titulo_normalizado) -> "relevant"|"not_relevant".
# Evita re-llamar al NLI por el mismo título dentro de una pasada (Actions es stateless
# entre runs, así que basta con caché de proceso).
_RELEVANCE_CACHE: dict[tuple[str, str], str] = {}

# --- Categoría por NLI (Entrega D / S3) --------------------------------------
# Las REGLAS dan un resultado PROVISIONAL y el NLI lo VALIDA (confirma o corrige)
# usando sobre todo la DESCRIPCIÓN. Mismo motor zero-shot (HF) que el gate de
# relevancia. Reversible (category_nli.enabled) y DESACTIVADO por defecto.
# Conservador: solo mueve 'base' -> 'components'/'expansion' por MARGEN; ante la
# duda deja el resultado de reglas (nunca a not_game, nunca descarta).
_CATEGORY_NLI_ENABLED = os.getenv(
    "CATEGORY_NLI_ENABLED", "0") not in ("0", "false", "False", "")
try:
    _CATEGORY_NLI_MARGIN = float(os.getenv("CATEGORY_NLI_MARGIN", str(_NLI_MARGIN)))
except ValueError:
    _CATEGORY_NLI_MARGIN = _NLI_MARGIN
# Hipótesis en español (idioma de los anuncios). HF rellena {} de _NLI_HYP_TEMPLATE.
_CATEGORY_NLI_LABELS = {
    "base":       "un juego de mesa completo",
    "expansion":  "una expansión de un juego de mesa",
    "components": "componentes o accesorios sueltos de un juego de mesa",
}
_CATEGORY_LABEL_TO_CAT = {v: k for k, v in _CATEGORY_NLI_LABELS.items()}
# Caché en proceso: texto normalizado -> categoría ("" = indeterminado/no aporta).
_CATEGORY_NLI_CACHE: dict[str, str] = {}


def relevance_enabled():
    """True si el gate de relevancia está activo (relevance.enabled / RELEVANCE_ENABLED)."""
    return _RELEVANCE_ENABLED


def category_nli_enabled():
    """True si el NLI de categoría está activo (category_nli.enabled / env)."""
    return _CATEGORY_NLI_ENABLED


def is_risky_keyword(kw):
    """True si `kw` (una palabra o una frase, p.ej. 'rising sun') es una keyword
    ambigua conocida."""
    return _normalize(str(kw or "").strip()) in _RISKY_KEYWORDS


def detect_risky_keywords(alert):
    """Devuelve las keywords riesgosas presentes en alert["keywords"] (string),
    tanto de una palabra ('cities') como frases multi-palabra ('rising sun').
    Una frase se considera presente si la alerta busca TODAS sus palabras. Lista
    vacía si la alerta no tiene ninguna (caso normal)."""
    target = (alert or {}).get("keywords") or ""
    words = set(re.findall(r"\w+", _normalize(target)))
    out, seen = [], set()
    for key in _RISKY_KEYWORDS:                 # orden estable (dict insertion)
        if key in seen:
            continue
        parts = key.split()
        present = parts[0] in words if len(parts) == 1 \
            else all(p in words for p in parts)
        if present:
            seen.add(key)
            out.append(key)
    return out


def _match_exclusion(title, confusers):
    """True si el título contiene algún confusor (substring sobre texto normalizado)."""
    norm = _normalize(title)
    return any(c and _normalize(c) in norm for c in (confusers or []))


def _phrase_in_order(title, phrase):
    """True si las palabras de `phrase` aparecen CONTIGUAS y EN ORDEN en el título.
    Una keyword de una sola palabra no tiene orden -> siempre True. Ejemplo:
    'rising sun' está en orden en 'Rising Sun Monster Pack', pero NO en
    'Setting Sun Rising' (palabras sueltas / orden invertido)."""
    parts = (phrase or "").split()
    if len(parts) < 2:
        return True
    pat = r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b"
    return bool(re.search(pat, _normalize(title)))


def _nli_mark_down(reason):
    """Activa el cortocircuito del NLI para el resto de la ejecución y lo registra
    UNA vez (warning). Siempre lanza RuntimeError; el llamador cae a su respaldo
    (determinista en relevancia, reglas en categoría)."""
    global _NLI_UNAVAILABLE
    if not _NLI_UNAVAILABLE:
        _NLI_UNAVAILABLE = True
        log.warning("NLI no disponible (%s); se usa el respaldo (reglas/"
                    "determinista) durante el resto de la ejecución", reason)
    raise RuntimeError(reason)


def _nli_hf_zeroshot(text, candidate_labels, timeout=20):
    """HF zero-shot (Inference Providers, router) genérico: devuelve {label: score}
    o lanza RuntimeError si el servicio no está disponible (sin token, 401/403, 404
    modelo no servido, 503 cold-start, 429 cuota, timeout, red o formato inesperado).
    El token (HF_API_TOKEN, NUNCA hardcodeado) es OBLIGATORIO en el router. Tras el
    primer fallo, el cortocircuito (_NLI_UNAVAILABLE) hace que las siguientes
    llamadas fallen de inmediato sin tocar la red."""
    if _NLI_UNAVAILABLE:
        raise RuntimeError("NLI no disponible (cortocircuito de esta ejecución)")
    token = os.getenv("HF_API_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = _NLI_API_URL.format(model=_NLI_MODEL)
    payload = {
        "inputs": text,
        "parameters": {
            "candidate_labels": list(candidate_labels),
            "hypothesis_template": _NLI_HYP_TEMPLATE,
            "multi_label": False,
        },
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as e:
        _nli_mark_down(f"red/timeout: {e}")
    if r.status_code in (503, 429):
        _nli_mark_down(f"HTTP {r.status_code}")
    if r.status_code != 200:
        _nli_mark_down(f"HTTP {r.status_code}: {r.text[:120]}")
    data = r.json()
    if not isinstance(data, dict) or "labels" not in data or "scores" not in data:
        _nli_mark_down(f"respuesta inesperada: {str(data)[:120]}")
    return dict(zip(data["labels"], data["scores"]))


def _nli_hf_relevance(text, game_label, other_label, timeout=20):
    """Relevancia: dos hipótesis (juego buscado vs otro). Devuelve
    (score_game, score_other). Lanza RuntimeError si el servicio no está
    disponible (ver _nli_hf_zeroshot)."""
    scores = _nli_hf_zeroshot(text, [game_label, other_label], timeout)
    return scores.get(game_label, 0.0), scores.get(other_label, 0.0)


def nli_relevance_gate(title, desc, keyword):
    """¿El anuncio es EXACTAMENTE el juego de `keyword`, o es otro que contiene esa
    palabra/frase? Devuelve "relevant" | "not_relevant".

    La RELEVANCIA la decide el TÍTULO: el nombre del juego está ahí. `desc` se
    conserva en la firma por compatibilidad con el llamador (main.py) pero YA NO
    se usa para relevancia (la descripción puede mencionar otros juegos y
    contaminar la decisión; la descripción es señal de CATEGORÍA, no de relevancia).

    1) Caché por (keyword, título normalizado).
    2) NLI zero-shot (HF) sobre SOLO el título: decide por MARGEN (_NLI_MARGIN).
       El NLI entiende el orden semánticamente (caza "Setting Sun Rising" o un
       producto de dardos "Rising Sun" como "otro juego").
    3) Fallback determinista (sin servicio o margen insuficiente), conservador
       (ante la duda, dejar pasar):
         - título con un confusor conocido -> "not_relevant".
         - keyword multi-palabra cuyas palabras NO aparecen contiguas/en orden en
           el título -> "not_relevant" (p.ej. "Setting Sun Rising" para «rising
           sun»). Si aparecen en orden contiguo, es relevante por relevancia.
         - en cualquier otro caso -> "relevant".
    """
    kw = _normalize(str(keyword or "").strip())
    spec = _RISKY_KEYWORDS.get(kw)
    if not spec:
        return "relevant"          # no es riesgosa: no aplica

    cache_key = (kw, _normalize(title or ""))
    cached = _RELEVANCE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    confusers = spec.get("confusers") or []
    decision = None
    try:
        game_label = spec.get("game") or kw
        other_label = f"otro juego diferente que contiene «{kw}»"
        text = (title or "").strip()           # B2.0: relevancia SOLO por título
        s_game, s_other = _nli_hf_relevance(text, game_label, other_label)
        if s_other - s_game >= _NLI_MARGIN:
            decision = "not_relevant"
        elif s_game - s_other >= _NLI_MARGIN:
            decision = "relevant"
        # margen insuficiente -> indeterminado: cae al fallback determinista
    except RuntimeError:
        pass            # NLI no disponible: el cortocircuito ya avisó; fallback determinista

    if decision is None:
        if _match_exclusion(title, confusers):
            decision = "not_relevant"
        elif " " in kw and not _phrase_in_order(title, kw):
            decision = "not_relevant"          # frase en otro orden -> otro juego
        else:
            decision = "relevant"

    _RELEVANCE_CACHE[cache_key] = decision
    return decision


# --- Idioma CONCRETO del anuncio: es / ca / en / otro -----------------------
# Para el dataset de reentrenamiento queremos el idioma REAL del anuncio (no
# solo "foreign sí/no"). Estrategia CONSISTENTE con looks_foreign_language():
#   1) Si el gate lo marca foreign (fr/de/it/pt...) -> "otro".
#   2) Si no, se decide entre es/ca/en por marcadores INEQUÍVOCOS de cada
#      idioma, puntuando con vocabulario ESPECÍFICO (no compartido) para que un
#      anuncio catalán no sume a la vez en "es" por usar "de"/"la". _normalize()
#      conserva ç, è y l·l, señales fuertes de catalán.
# NO altera la clasificación ni el filtrado: solo etiqueta para almacenar.
# LIMITACIÓN CONOCIDA: separar es/ca con heurística no es perfecto. Ante empate
# o ausencia de señal se devuelve "es" (lo más común en Wallapop España); un
# único marcador inglés (probable TÍTULO de juego en inglés vendido por
# hispanohablante, p. ej. "The Lord of the Rings") tampoco basta para "en".
# Para más precisión, sustituir por una librería ligera (p. ej. langdetect).
_LANG_CA_VOCAB = [
    "amb", "què", "fins", "joc", "jocs", "taula", "tauler", "caixa", "cartes",
    "està", "també", "aquest", "aquesta", "molt", "preu", "venc", "tinc",
    "inclou", "els", "les", "com nou", "perfecte", "complet", "lliure",
    "nou de trinca",
]
_LANG_ES_VOCAB = [
    "los", "las", "con", "para", "muy", "nuevo", "nueva", "estado", "precio",
    "vendo", "juego", "juegos", "mesa", "caja", "tablero", "incluye",
    "completo", "completa", "como nuevo", "sin estrenar", "perfecto",
    "perfecta", "tambien", "sellado", "reservado", "negociable",
]
_LANG_EN_VOCAB = [
    "the", "and", "with", "for", "this", "are", "you", "your", "from", "have",
    "board game", "brand new", "like new", "shipping", "sealed", "includes",
    "condition", "english", "never played", "great condition", "selling",
]
_LANG_CA_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _LANG_CA_VOCAB) + r")\b")
_LANG_ES_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _LANG_ES_VOCAB) + r")\b")
_LANG_EN_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _LANG_EN_VOCAB) + r")\b")


def detect_language(title, description=""):
    """Idioma del anuncio: 'es' | 'ca' | 'en' | 'otro'. Consistente con
    looks_foreign_language() (si ese gate marca foreign -> 'otro')."""
    if looks_foreign_language(title, description):
        return "otro"
    norm = _normalize(f"{title} {description}")
    ca = len(_LANG_CA_RE.findall(norm))
    # ç y l·l no casan bien con \b (son letras / llevan '·'): se cuentan aparte
    # y, dentro de no-foreign, son señal fuerte de catalán.
    if "ç" in norm:
        ca += 1
    if "l·l" in norm:
        ca += 1
    es = len(_LANG_ES_RE.findall(norm))
    en = len(_LANG_EN_RE.findall(norm))

    if ca and ca >= es and ca >= en:
        return "ca"
    if en >= 2 and en > es:
        return "en"
    return "es"


# --- Detección ESTRUCTURAL de ráfaga de tags (spam SEO sin marcador) ---------
# Algunos vendedores pegan al final una ristra de nombres de juegos separados
# por comas (sin "Tags:" delante) para salir en más búsquedas. La detectamos por
# su FORMA: muchos elementos cortos seguidos, por comas y sin verbos. El umbral
# es ALTO a propósito: una lista de 8+ nombres es spam; listas cortas (un lote
# de pocos juegos, o componentes "tablero, fichas, cartas...") NO se tocan.
# Además solo se recorta si delante hay una frase con verbo (si no, la lista
# podría ser el contenido real del anuncio). Tunable: _TAG_BURST_MIN_ITEMS.
_TAG_BURST_MIN_ITEMS = 8

# Marcas de que un fragmento es PROSA (estructura de frase), no un tag suelto.
# Si un trozo entre comas contiene alguna, no cuenta como tag.
_CLAUSE_VERB_RE = re.compile(
    r"\b(vend\w*|incluy\w*|cont\w*|teng\w*|tien\w*|esta\w*|es|son|hay|"
    r"busc\w*|regal\w*|cambi\w*|doy|falta\w*|jug\w*|us[ao]\w*|usad\w*|"
    r"compr\w*|envi\w*|reserv\w*|qued\w*|sirve\w*|funciona\w*|acept\w*|"
    r"precio|estado|nuevo|nueva|seminuevo|completo|completa)\b")


def _find_tag_burst_start(description):
    """Índice (sobre el original) donde empieza una ráfaga de nombres separados
    por comas tipo spam SEO, o None. _normalize conserva longitud, así que los
    offsets coinciden con el texto original."""
    norm = _normalize(description)
    segs, start = [], 0
    for m in re.finditer(",", norm):
        segs.append((start, norm[start:m.start()]))
        start = m.start() + 1
    segs.append((start, norm[start:]))
    if len(segs) < _TAG_BURST_MIN_ITEMS:
        return None

    def _taglike(text):
        s = text.strip()
        if not s or len(s.split()) > 4:        # vacío o largo -> no es un tag
            return False
        return not _CLAUSE_VERB_RE.search(s)   # con verbo -> prosa, no tag

    # Racha de trozos "tag-like" pegada al final.
    i, run_start = len(segs) - 1, len(segs)
    while i >= 0 and _taglike(segs[i][1]):
        run_start = i
        i -= 1
    if len(segs) - run_start < _TAG_BURST_MIN_ITEMS:
        return None

    cut = segs[run_start][0]
    # La ráfaga puede arrancar a media frase (el 1er nombre va pegado al final
    # del trozo anterior, antes de la 1ª coma). Si tras el último punto del
    # prefijo solo queda un fragmento corto sin verbo, lo incluimos en el corte.
    seps = list(re.finditer(r"[.;\n]", norm[:cut]))
    last = seps[-1].end() if seps else 0
    tail = norm[last:cut]
    if not _CLAUSE_VERB_RE.search(tail) and len(tail.split()) <= 4:
        cut = last
    # Exigir prosa (un verbo) ANTES de la ráfaga: si no, la lista es el contenido.
    if not _CLAUSE_VERB_RE.search(norm[:cut]):
        return None
    return cut


def strip_tag_spam(description):
    """
    Recorta la descripción para quitar listas de nombres de OTROS juegos que el
    vendedor añade solo para salir en más búsquedas (no son lo que vende):
      1) Marcador explícito: 'Tags:', 'Similar a:', 'Parecido a:'...
      2) Ráfaga estructural: 8+ nombres cortos seguidos por comas y sin verbos,
         precedidos de una frase real. SOLO se aplica si el anuncio NO tiene
         vocabulario de lote (si lo tiene, esa lista podría ser los juegos
         reales del lote y no se toca).
    Si no detecta nada, devuelve la descripción igual.
    """
    if not description:
        return description
    # _normalize conserva la longitud -> los offsets valen sobre el original.
    m = _TAG_MARKERS_RE.search(_normalize(description))
    cut = m.start() if m else None
    if cut is None and not _has_lote_vocab(description):
        burst = _find_tag_burst_start(description)
        if burst is not None:
            cut = burst
    if cut is not None:
        return description[:cut].strip()
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


# Umbral de frecuencia (zipf 0..7): >= este valor = palabra COMUN -> "debil".
# 4.0 es conservador: solo palabras muy frecuentes (estaciones, cities, risk,
# azul...) son debiles; los nombres propios de juego (catan 2.2, inis 2.1,
# nostrum 2.6, frostpunk 0, wingspan 2.8) quedan "fuertes". Asi el matching no
# descarta de mas (no perdemos juegos); el ruido de palabras comunes lo filtra
# ademas el vocabulario de no-juego en classify_category.
_WEAK_ZIPF_THRESHOLD = 4.0


@functools.lru_cache(maxsize=4096)
def _word_freq(word):
    """Frecuencia zipf (0..7) de la palabra ORIGINAL (con tildes), como max entre
    es/en. None si no hay wordfreq. Base comun de is_weak y del desempate de
    especificidad en title_matches."""
    if zipf_frequency is None or not word:
        return None
    return max(zipf_frequency(word, "es"), zipf_frequency(word, "en"))


@functools.lru_cache(maxsize=4096)
def is_weak(word):
    """True si `word` es comun/ambigua (no basta por si sola para confirmar el
    juego buscado). Se evalua sobre la palabra ORIGINAL (con tildes), porque
    wordfreq no conoce las formas sin tilde. Sin wordfreq -> nunca debil."""
    z = _word_freq(word)
    return z is not None and z >= _WEAK_ZIPF_THRESHOLD


def _keyword_in_order(kw_norms, title_words):
    """S2 (orden multi-palabra): las palabras de la keyword que APARECEN en el
    título deben hacerlo en el MISMO ORDEN que en la keyword, aunque haya otras
    palabras en medio (orden "con huecos" = subsecuencia). Con 0-1 palabras
    presentes el orden es trivial -> True.

    Así 'rising sun' casa con 'Rising ... Sun' pero NO con 'Sun Rising', y a la vez
    NO rompe alertas reales como 'estaciones inis' -> 'Estaciones de Inis' (van en
    orden, con 'de' en medio) ni 'carcassonne posadas catedrales' ->
    'Carcassonne: Posadas y Catedrales'.
    """
    present = [n for n in kw_norms if n in title_words]
    if len(present) < 2:
        return True
    pos = 0
    for n in present:
        try:
            pos = title_words.index(n, pos) + 1
        except ValueError:
            return False                  # aparece, pero fuera de orden
    return True


def title_matches(target, title):
    """
    True si el TÍTULO contiene el juego buscado. Compara por palabra completa
    (así 'catan' no encaja dentro de otra palabra, pero 'Wingspan:' sí cuenta).

    Matching nucleo vs generico: una palabra COMUN del termino buscado
    (estaciones, borgoña, mare...) NO basta por si sola; hace falta que coincida
    una palabra distintiva (nombre propio: catan, inis...) o al menos DOS
    palabras. Si el termino es de una sola palabra, cualquier coincidencia vale
    (no hay alternativa mas distintiva). Evita colar 'Estacion de tren' por
    'estaciones' o 'Camisa Burgundy' por 'borgoña'.

    ORDEN (S2): si dos o mas palabras de la keyword aparecen en el titulo, deben
    hacerlo EN ORDEN (con huecos permitidos). Asi una keyword multi-palabra como
    'rising sun' NO casa con 'Sun Rising' (otro juego), sin romper titulos con
    palabras intercaladas como 'Las Estaciones de Inis'. Ver _keyword_in_order.
    """
    title_words = re.findall(r"\w+", _normalize(title))
    t_words = set(title_words)
    # Pares (original con tildes, normalizada) de las palabras significativas.
    raw = re.findall(r"\w+", target.lower())
    pairs = [(w, _normalize(w)) for w in raw if _normalize(w) not in _STOPWORDS]
    if not pairs:
        pairs = [(w, _normalize(w)) for w in raw]
    matched = [(orig, norm) for orig, norm in pairs if norm in t_words]
    if not matched:
        return False
    if not _keyword_in_order([norm for _, norm in pairs], title_words):
        return False                      # palabras presentes pero en otro orden
    if any(not is_weak(orig) for orig, norm in matched):
        # ESPECIFICIDAD (multi-palabra): una UNICA palabra fuerte no basta si es la
        # CABECERA GENERICA del termino (la mas comun) y quedan palabras MAS
        # distintivas sin coincidir. Asi 'castillos' de 'castillos burgundy borgoña'
        # NO cuela 'Castillos de Arena' (otro juego), pero 'inis' de 'estaciones
        # inis' sigue bastando (es la distintiva, no la generica). Sin wordfreq no
        # se aplica (todas las palabras se tratan como fuertes -> compat).
        if len(pairs) > 1 and len(matched) == 1:
            z = _word_freq(matched[0][0])
            if z is not None:
                others = [o for o, n in pairs if n != matched[0][1]]
                if any((_word_freq(o) or 0.0) < z for o in others):
                    return False          # solo coincide la palabra mas comun
        return True                       # coincide una palabra distintiva
    if len(pairs) == 1:
        return True                       # termino de 1 palabra: no hay opcion
    return len(matched) >= 2              # solo comunes: exigir >= 2


# ---------------------------------------------------------------------------
#  LLM helper — cascada con circuit breaker por proveedor
# ---------------------------------------------------------------------------
# En operacion normal SOLO se llama al PRIMER proveedor de la cascada. El resto
# son red de seguridad: un proveedor solo se salta hacia el siguiente cuando su
# circuit breaker esta abierto (429 sostenido -> cooldown) o cuando la llamada
# falla. Anadir mas proveedores NO ralentiza el caso bueno; solo da resiliencia.
#
# CONFIGURACION. Todo admite tres fuentes con esta prioridad:
#   variable de entorno  >  bot_settings.yaml (seccion 'llm')  >  valor por defecto
# La seccion 'llm' la aplica classifier.configure_from_settings(), que llama
# main.py al arrancar. Asi el orden y los modelos viven en bot_settings.yaml
# (comun a todos los usuarios) y las claves pueden ir como Secrets en CI.
#
# Claves de API (variable de entorno -> proveedor):
#   GROQ_API_KEY        -> groq          (console.groq.com)
#   CEREBRAS_API_KEY    -> cerebras      (cloud.cerebras.ai)
#   GEMINI_API_KEY      -> gemini        (aistudio.google.com)
#   OPENROUTER_API_KEY  -> openrouter    (openrouter.ai)
#   GH_MODELS_TOKEN     -> githubmodels  (PAT con permiso models:read)
#   LLM_API_KEY + LLM_BASE_URL -> openai (cualquier API compatible adicional)
#   OLLAMA_HOST         -> ollama        (local, por defecto localhost:11434)
#
# Orden de cascada (LLM_CASCADE o llm.cascade):
#   Por defecto: gemini,groq,rules  (ancla Gemini + respaldo Groq, ambos
#   gratis y sin tope diario ajustado; cerebras/openrouter/githubmodels
#   siguen soportados por el codigo pero fuera de la cascada por defecto:
#   roto / cuota insuficiente / mayor riesgo, ver bot_settings.yaml).
#   Ollama local: ollama,groq,...        Solo reglas: rules
#
# LLM_COOLDOWN (o llm.cooldown_seconds) = pausa por proveedor tras 429 (def. 600)

_GROQ_BASE         = "https://api.groq.com/openai/v1"
_GEMINI_BASE       = "https://generativelanguage.googleapis.com/v1beta"
_CEREBRAS_BASE     = "https://api.cerebras.ai/v1"
_OPENROUTER_BASE   = "https://openrouter.ai/api/v1"
_GITHUBMODELS_BASE = "https://models.github.ai/inference"

# Proveedores que hablan el dialecto de OpenAI (/chat/completions). 'openai' usa
# LLM_BASE_URL; el resto, su URL fija. Gemini y ollama van por su propia ruta.
_OPENAI_COMPAT_BASE = {
    "groq":         _GROQ_BASE,
    "cerebras":     _CEREBRAS_BASE,
    "openrouter":   _OPENROUTER_BASE,
    "githubmodels": _GITHUBMODELS_BASE,
}

_DEFAULT_MODELS = {
    "groq":         "llama-3.1-8b-instant",
    "cerebras":     "llama-3.3-70b",
    "gemini":       "gemini-2.5-flash-lite",
    "openrouter":   "meta-llama/llama-3.3-70b-instruct:free",
    "githubmodels": "openai/gpt-4o-mini",
    "openai":       "",
    "ollama":       "qwen2.5:3b",
}

# Variable de entorno que lleva la API key de cada proveedor.
_KEY_ENV = {
    "groq":         "GROQ_API_KEY",
    "cerebras":     "CEREBRAS_API_KEY",
    "gemini":       "GEMINI_API_KEY",
    "openrouter":   "OPENROUTER_API_KEY",
    "githubmodels": "GH_MODELS_TOKEN",
    "openai":       "LLM_API_KEY",
}

# Throttle: segundos minimos entre llamadas a cada proveedor (segun su RPM).
_DEFAULT_INTERVALS = {
    "ollama": 0.0, "groq": 2.1, "openai": 2.1, "gemini": 4.1,
    "cerebras": 2.1, "openrouter": 3.1, "githubmodels": 6.1,
}

# Rellenados por configure_from_settings() desde bot_settings.yaml (la env-var
# del mismo concepto siempre tiene prioridad sobre esto).
_SETTINGS_MODELS: dict[str, str] = {}
_SETTINGS_KEYS: dict[str, str] = {}

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

# Para que main.py pueda hacer "LLM activo: groq / …"
LLM_PROVIDER = LLM_CASCADE[0] if LLM_CASCADE else "rules"


def configure_relevance_from_settings(settings):
    """Aplica la seccion 'relevance' de bot_settings.yaml (gate NLI de relevancia
    para keywords ambiguas). Entorno > yaml > default. Idempotente."""
    global _RELEVANCE_ENABLED, _NLI_MODEL, _NLI_MARGIN
    rel = (settings or {}).get("relevance") or {}

    if "RELEVANCE_ENABLED" not in os.environ and rel.get("enabled") is not None:
        _RELEVANCE_ENABLED = bool(rel.get("enabled"))

    if "NLI_MODEL" not in os.environ and rel.get("model"):
        _NLI_MODEL = str(rel["model"]).strip()

    if "NLI_MARGIN" not in os.environ and rel.get("margin") is not None:
        try:
            _NLI_MARGIN = float(rel["margin"])
        except (TypeError, ValueError):
            log.warning("relevance.margin invalido: %s", rel.get("margin"))

    # Overrides opcionales de confusores por keyword (no borra los por defecto;
    # reemplaza la lista de las keywords indicadas).
    for kw, conf in (rel.get("confusers") or {}).items():
        k = _normalize(str(kw).strip())
        if k in _RISKY_KEYWORDS and isinstance(conf, list):
            _RISKY_KEYWORDS[k]["confusers"] = [str(c) for c in conf]


def configure_category_nli_from_settings(settings):
    """Aplica la sección 'category_nli' de bot_settings.yaml (NLI de categoría).
    Entorno > yaml > default. Idempotente. Por defecto DESACTIVADO."""
    global _CATEGORY_NLI_ENABLED, _CATEGORY_NLI_MARGIN
    cn = (settings or {}).get("category_nli") or {}
    if ("CATEGORY_NLI_ENABLED" not in os.environ
            and cn.get("enabled") is not None):
        _CATEGORY_NLI_ENABLED = bool(cn.get("enabled"))
    if ("CATEGORY_NLI_MARGIN" not in os.environ
            and cn.get("margin") is not None):
        try:
            _CATEGORY_NLI_MARGIN = float(cn["margin"])
        except (TypeError, ValueError):
            log.warning("category_nli.margin invalido: %s", cn.get("margin"))


def configure_from_settings(settings):
    """Aplica la seccion 'llm' de bot_settings.yaml (cascada, modelos, claves,
    cooldown). Una variable de entorno del mismo concepto SIEMPRE manda sobre
    esto (util para GitHub Secrets). Idempotente; la llama main.py al arrancar.

    Tambien aplica las secciones 'relevance' (gate NLI), 'language' (langdetect) y
    'category_nli' (NLI de categoría), por comodidad: main.py solo llama a
    configure_from_settings()."""
    global LLM_CASCADE, LLM_PROVIDER, _LLM_COOLDOWN, _BATCH_SIZE
    configure_relevance_from_settings(settings)
    configure_language_from_settings(settings)
    configure_category_nli_from_settings(settings)
    llm = (settings or {}).get("llm") or {}

    if "LLM_CASCADE" not in os.environ and "LLM_PROVIDER" not in os.environ:
        casc = llm.get("cascade")
        if casc:
            LLM_CASCADE = [str(p).strip().lower() for p in casc if str(p).strip()]
            LLM_PROVIDER = LLM_CASCADE[0] if LLM_CASCADE else "rules"

    for prov, model in (llm.get("models") or {}).items():
        if model:
            _SETTINGS_MODELS[str(prov).strip().lower()] = str(model).strip()

    for prov, key in (llm.get("keys") or {}).items():
        if key:
            _SETTINGS_KEYS[str(prov).strip().lower()] = str(key).strip()

    if "LLM_COOLDOWN" not in os.environ and llm.get("cooldown_seconds") is not None:
        try:
            _LLM_COOLDOWN = float(llm["cooldown_seconds"])
        except (TypeError, ValueError):
            log.warning("llm.cooldown_seconds invalido: %s", llm.get("cooldown_seconds"))

    if "LLM_BATCH_SIZE" not in os.environ and llm.get("batch_size") is not None:
        try:
            _BATCH_SIZE = max(1, int(llm["batch_size"]))
        except (TypeError, ValueError):
            log.warning("llm.batch_size invalido: %s", llm.get("batch_size"))


def get_ollama_model():
    """Modelo de Ollama efectivo (entorno > bot_settings.yaml > por defecto)."""
    return (os.getenv("LLM_MODEL")
            or _SETTINGS_MODELS.get("ollama")
            or _DEFAULT_MODELS.get("ollama")
            or "qwen2.5:3b")

# --- circuit breakers (un reloj por proveedor, en memoria) ---
try:
    _LLM_COOLDOWN = float(os.getenv("LLM_COOLDOWN", "600"))
except ValueError:
    _LLM_COOLDOWN = 600.0

# --- batching de clasificacion (Tarea 1) ---
# Nº de anuncios que se agrupan en UNA sola llamada al LLM. El cuello de botella
# del free tier es el nº de PETICIONES/minuto (no los tokens): agrupar baja las
# llamadas de ~200 a ~8 y evita disparar 429 en todos los proveedores a la vez.
# Override: variable LLM_BATCH_SIZE o llm.batch_size en bot_settings.yaml.
try:
    _BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "25"))
except ValueError:
    _BATCH_SIZE = 25
_BATCH_DESC_MAX = 280   # recorte de descripcion por anuncio (acota tokens/lote)

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
    return (os.getenv("LLM_MODEL")
            or _SETTINGS_MODELS.get(provider)
            or _DEFAULT_MODELS.get(provider, ""))


def _api_key(provider: str) -> str:
    env = _KEY_ENV.get(provider)
    if env and os.getenv(env):
        return os.getenv(env, "")
    return _SETTINGS_KEYS.get(provider, "")


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
    """Un POST por proveedor con politica de "fallo rapido":
    - 429 (rate limit): NO se reintenta. Abre el circuit breaker del proveedor
      (cooldown) y lanza, para que la cascada salte al siguiente y no se vuelva
      a llamar durante el cooldown.
    - 5xx (error transitorio del servidor): un reintento corto; si persiste,
      lanza para saltar al siguiente (sin abrir cooldown).
    - resto de 4xx / errores de red: lanza directamente (salta al siguiente)."""
    r = None
    for attempt in range(tries):
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 429:
            _trip_breaker(provider)          # rate limit: a cooldown y siguiente
            break
        if r.status_code >= 500 and attempt < tries - 1:
            wait = 3.0 * (attempt + 1)
            log.info("LLM %s: HTTP %s, reintento en %.0fs...",
                     provider, r.status_code, wait)
            time.sleep(wait)
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
    if provider in _OPENAI_COMPAT_BASE or provider == "openai":
        return _ask_openai_compat(provider, key, schema, messages, timeout)
    raise requests.RequestException("proveedor desconocido: '%s'" % provider)


_cascade_dead_until: float = 0.0   # reservado para uso futuro

def _all_breakers_open() -> bool:
    """True si todos los proveedores activos (no rules) están en cooldown."""
    active = [p for p in LLM_CASCADE if p != "rules"]
    return bool(active) and all(_breaker_open(p) for p in active)


def _ask(model, schema, messages, timeout=120):
    """Intenta los proveedores de LLM_CASCADE en orden hasta que uno responde.
    Si todos fallan, lanza RequestException para que el llamador use reglas.
    Si toda la cascada está en cooldown, falla inmediatamente sin reintentar."""
    if _all_breakers_open():
        # Toda la cascada en cooldown: no tiene sentido probar nada,
        # caemos directamente a reglas sin generar ruido en el log.
        raise requests.RequestException("toda la cascada en cooldown — usando reglas")
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
    """Groq, Cerebras, OpenRouter, GitHub Models y cualquier API compatible con
    OpenAI (provider='openai' via LLM_BASE_URL)."""
    base = _OPENAI_COMPAT_BASE.get(provider) or os.getenv("LLM_BASE_URL", "").rstrip("/")
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
    if provider == "openrouter":
        # Opcional pero recomendado por OpenRouter (atribucion; no es obligatorio).
        headers["HTTP-Referer"] = "https://github.com/wallabot"
        headers["X-Title"] = "Wallapop Alerts"
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
    cascade_str = " -> ".join(parts)
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
        if first == "gemini":
            r = requests.get(_GEMINI_BASE + "/models", timeout=8,
                             headers={"x-goog-api-key": key})
        else:
            base = _OPENAI_COMPAT_BASE.get(first) or os.getenv("LLM_BASE_URL", "").rstrip("/")
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


def _post_process_category(title, description, is_board_game, category,
                           includes_base_game):
    """Normaliza la respuesta cruda del LLM a una categoria de VALID. Misma
    logica para el camino de un anuncio y el de lotes (se factoriza para que
    ambos decidan IGUAL)."""
    if not is_board_game:
        return "not_game"
    cat = category or "unknown"
    if includes_base_game and cat in ("base", "expansion"):
        cat = "base"
    # Regla dura (rediseño jun 2026): sin vocabulario explícito de lote en el
    # texto limpio, NO puede ser 'lote' aunque lo diga el modelo. Evita el falso
    # 'lote' por mencionar varias expansiones de un mismo juego.
    if cat == "lote" and not _has_lote_vocab(f"{title} {description}"):
        cat = "base"
    return cat if cat in VALID else "unknown"


# ---------------------------------------------------------------------------
#  CLASIFICACIÓN POR REGLAS (sin LLM, rediseño jun 2026)
# ---------------------------------------------------------------------------
# La cascada LLM dejó de responder (429 sostenido en todos los proveedores
# gratuitos). En su lugar clasificamos por REGLAS sobre título + descripción,
# validado contra datos reales (ver 03_Diagnostico/tune_rules_only.py).

# Vocabulario que indica OTRO producto (no un juego de mesa) aunque el nombre
# coincida: libros, cine, videojuegos, ropa y el "long tail" de nombres comunes
# (sobre todo 'Mare Nostrum': perfume, reloj, seguros, maquetas...). Se busca en
# título + descripción (la descripción revela 'Mare Nostrum' = "Libro de...").
_NOT_GAME_VOCAB = (
    "libro", "libros", "novela", "novelas", "blasco", "ibanez", "folleto",
    "cine", "pelicula", "dvd", "bluray", "alquiler", "lamina", "acuarela",
    "botella", "maqueta", "maquetas", "puzzle", "puzle",
    "ps2", "ps3", "ps4", "ps5", "consola", "videojuego", "steam", "xbox",
    "nintendo", "switch", "playstation", "concert", "camiseta", "camisa",
    "polo", "guantes", "zapatillas", "esmalte", "bicicleta", "esqueje",
    "esquejes", "planta", "perfume", "edt", "edp", "colonia", "vinilo",
    "disco", "cuadro", "escultura", "pintura", "poster", "cartel", "reloj",
    "cronografo", "gemelos", "insignia", "seguros", "seguro", "poliza",
    "polizas", "carcasa", "pesca", "telescopica", "barco", "yachting",
    "dardos", "diana",   # set de dardos 'Rising Sun' (producto deportivo, no juego)
)

# Accesorios/piezas sueltas -> 'components' (no el juego completo).
_COMP_VOCAB = (
    "organizador", "organizadores", "inserto", "insertos", "separador",
    "separadores", "funda", "fundas", "sleeve", "sleeves", "protector",
    "protectores", "almacenamiento", "metacrilato", "neopreno", "tapete",
    "losetas", "loseta", "dados", "lanzador", "trofeo", "tablas", "recambio",
    "repuesto", "torre de dados", "bandeja", "bandejas", "fichas", "piezas",
    "recursos", "soportes", "impreso", "impresos", "impresa", "impresas",
    "mapa", "mapas",
)

# Señal POSITIVA fuerte de juego de mesa: tiene PRIORIDAD sobre _NOT_GAME_VOCAB
# (muchas descripciones de juegos dicen "videojuego" — p.ej. Frostpunk está
# basado en uno — o "libro de reglas"; no por eso dejan de ser juegos de mesa).
_GAME_SIGNAL_RE = re.compile(
    r"\bjuego de mesa\b|\bjuego de tablero\b|\bboard game\b")
# Si el TÍTULO dice claramente que es el juego, no lo degrades a 'components'
# por mencionar un accesorio: es un base CON extras.
_GAME_PRODUCT_RE = re.compile(r"\bjuego de mesa\b|\bjuego de tablero\b")

_EXPANSION_TITLE_RE = re.compile(
    r"\b(expansion|expansiones|ampliacion|ampliaciones)\b")
# Señales en el título de que INCLUYE la base (=> no es "solo expansión").
_BASE_INCLUSION_RE = re.compile(
    r"\bbase\b|\bincluye\b|\bcompleto\b|\bcompleta\b"
    r"|\bcon\s+(?:la|las|el|los|una|unas|sus|varias|dos|tres|\d+)?\s*expansion"
    r"|\by\s+(?:sus\s+|todas\s+las\s+|varias\s+|dos\s+|tres\s+)?expansion")


def _rule_expansion_by_title(title):
    """'expansion' si el título lo dice y NO hay señal de que incluya la base."""
    t = _normalize(title)
    if not (t.startswith(("expansion ", "ampliacion ", "promo "))
            or _EXPANSION_TITLE_RE.search(t)):
        return None
    if _BASE_INCLUSION_RE.search(t) or "+" in title:
        return None
    return "expansion"


# Frases INEQUÍVOCAS en la DESCRIPCIÓN de que SOLO se vende un accesorio o la
# caja, SIN el juego (el título suele ser solo el nombre del juego). Buscadas en
# texto normalizado. Deliberadamente específicas para no degradar un base que
# mencione un extra de pasada ("incluye organizador"): exigen "solo/no incluye/
# para el juego/encaja en el juego/cajas vacías", no la mera palabra del accesorio.
_COMPONENTS_ONLY_DESC = (
    "no incluye el juego", "no incluye juego", "no incluye la base",
    "sin el juego base", "sin la base", "no incluye ningun juego",
    "solo las cajas", "solo cajas",   # singular "solo la caja" se omite (ambiguo)
    "caja vacia", "cajas vacias", "solo el inserto", "solo los insertos",
    "solo insertos", "solo el organizador", "solo organizador",
    "solo las fundas", "solo fundas", "solo cartas", "solo el tablero",
    "solo manual", "solo instrucciones",
    "organizador de", "organizador para", "inserto para", "insertos para",
    "fundas para", "encaja en el juego", "encajan en el juego",
    "encaja perfecto en el juego", "encajan perfecto en el juego",
)


# Subconjunto DURO: frases tan decisivas ("no se vende el juego") que prevalecen
# incluso si el texto menciona "juego de mesa" (p.ej. "cajas de juego de mesa X,
# NO INCLUYE JUEGO"). El resto (soft) solo aplica si NO hay señal de juego completo.
# OJO: "solo la caja" (singular) se EXCLUYE a propósito: es ambiguo ("solo la
# caja TIENE desgaste" describe un base completo). El plural "solo las cajas" sí
# es inequívoco de que se venden cajas.
_COMPONENTS_ONLY_HARD = (
    "no incluye el juego", "no incluye juego", "no incluye nada",
    "no incluye ningun juego", "solo las cajas", "solo cajas",
    "caja vacia", "cajas vacias",
)


def _components_only_in_desc(description):
    """True si la DESCRIPCIÓN delata, por frase inequívoca, que SOLO se vende un
    accesorio/caja sin el juego (ver _COMPONENTS_ONLY_DESC)."""
    d = _normalize(description)
    return any(p in d for p in _COMPONENTS_ONLY_DESC)


def _components_hard_in_desc(description):
    """True si la DESCRIPCIÓN contiene una frase DURA de 'no se vende el juego'
    (prevalece sobre la señal de 'juego de mesa'); ver _COMPONENTS_ONLY_HARD."""
    d = _normalize(description)
    return any(p in d for p in _COMPONENTS_ONLY_HARD)


def _classify_by_rules(title, description):
    """Decide la categoría por reglas (título + descripción). Asume que el
    título YA coincide con el juego buscado (la relevancia la filtra
    title_matches). Devuelve 'base'|'expansion'|'components'|'lote'|'not_game'."""
    t = _normalize(title)
    full = _normalize(f"{title} {description}")
    is_game_signal = bool(_GAME_SIGNAL_RE.search(full))
    # No-juego (libro, ps5, perfume...), salvo señal positiva de juego de mesa.
    if not is_game_signal and any(w in full for w in _NOT_GAME_VOCAB):
        return "not_game"
    # Componentes: solo si el accesorio es el PRODUCTO, no un extra de un base.
    if any(w in t for w in _COMP_VOCAB):
        is_base_with_extra = (
            _GAME_PRODUCT_RE.search(t) or "+" in title
            or " e inserto" in t or " con inserto" in t
            or " con funda" in t or " con fundas" in t)
        if not is_base_with_extra:
            return "components"
    # Componentes delatados por la DESCRIPCIÓN (no por el título): frase
    # inequívoca de "solo accesorio / no incluye juego". Las frases DURAS ("no
    # incluye juego", "solo las cajas") prevalecen aunque el texto diga "juego de
    # mesa"; las soft solo si NO hay señal de juego completo. Siempre con la guarda
    # de que el título no sea claramente un base (ahí prevalece 'base').
    if not strong_base_signal(title, description):
        if (_components_hard_in_desc(description)
                or (not is_game_signal and _components_only_in_desc(description))):
            return "components"
    # Atajo a base (título claramente base y no es lote).
    if (not any(w in t for w in _LOTE_WORDS)
            and strong_base_signal(title, description)):
        return "base"
    # Lote: vocabulario explícito (regla dura).
    if _has_lote_vocab(full):
        return "lote"
    # Expansión por título.
    exp = _rule_expansion_by_title(title)
    if exp:
        return exp
    # Respaldo por frases explícitas en la DESCRIPCIÓN ("solo la expansión",
    # "solo los insertos", "no incluye el juego"...): reutiliza _fallback_category.
    fb = _fallback_category(title, description)
    if fb in ("expansion", "components"):
        return fb
    return "base"   # ante la duda, dejar pasar (preferencia del proyecto)


def _category_nli(title, description):
    """Clasifica la categoría por NLI (zero-shot HF) sobre TÍTULO + DESCRIPCIÓN,
    con la DESCRIPCIÓN como señal principal (ahí se delata 'solo el inserto',
    'fichas sueltas', 'solo la expansión'...). Devuelve 'base'|'expansion'|
    'components' por MARGEN (_CATEGORY_NLI_MARGIN), o None si el NLI no está
    disponible o no es concluyente. Caché en proceso por texto normalizado."""
    text = f"{title or ''}. {description or ''}".strip()
    key = _normalize(text)
    cached = _CATEGORY_NLI_CACHE.get(key)
    if cached is not None:
        return cached or None              # "" centinela de indeterminado
    decision = None
    try:
        scores = _nli_hf_zeroshot(text, list(_CATEGORY_NLI_LABELS.values()))
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] >= _CATEGORY_NLI_MARGIN:
            decision = _CATEGORY_LABEL_TO_CAT.get(ranked[0][0])
    except RuntimeError:
        pass            # NLI no disponible: el cortocircuito ya avisó; se mantienen las reglas
    _CATEGORY_NLI_CACHE[key] = decision or ""
    return decision


def _maybe_refine_category_nli(title, description, rules_cat):
    """VALIDACIÓN opcional por NLI (category_nli.enabled). Las REGLAS son el primer
    filtro; el NLI valida el caso de riesgo: reglas -> 'base' pero el texto tiene
    vocabulario de accesorio/expansión y HAY descripción. Solo entonces se gasta una
    llamada NLI, que puede mover 'base' -> 'components'/'expansion'. Conservador:
    ante la duda (NLI no disponible o sin margen) deja las reglas; nunca a not_game
    ni descarta. NO toca lote/not_game ni 'expansion'/'components' ya decididos por
    reglas (la rama de lotes vive aparte en main.evaluate())."""
    if not _CATEGORY_NLI_ENABLED or rules_cat != "base":
        return rules_cat
    desc = (description or "").strip()
    if not desc:
        return rules_cat                   # sin descripción el NLI no aporta
    # Gateo por vocabulario: solo llamamos al NLI si hay señal de accesorio/
    # expansión en el texto (si no, las reglas 'base' bastan y ahorramos la llamada).
    text_norm = _normalize(f"{title} {desc}")
    if not (any(w in text_norm for w in _COMP_VOCAB)
            or any(w in text_norm for w in _COMPONENT_HINT_WORDS)
            or any(w in text_norm for w in _EXPANSION_HINT_WORDS)):
        return rules_cat
    nli_cat = _category_nli(title, desc)
    if nli_cat in ("components", "expansion"):
        return nli_cat
    return rules_cat                       # 'base'/indeterminado -> reglas


def classify_category(title, description, use_llm=True, model="qwen2.5:3b"):
    """Clasifica la categoría: REGLAS como primer filtro (resultado provisional) y,
    si category_nli.enabled, el NLI lo VALIDA sobre la descripción (puede corregir
    'base' -> 'components'/'expansion'). Devuelve
    'base'|'expansion'|'components'|'lote'|'not_game'.

    `use_llm`/`model` se conservan por compatibilidad de firma pero ya no se usan:
    la cascada LLM quedó retirada (su código sigue en el módulo, inerte)."""
    desc = strip_tag_spam(description)
    cat = _classify_by_rules(title, desc)
    return _maybe_refine_category_nli(title, desc, cat)


# ---------------------------------------------------------------------------
#  TAREA 1 (POR LOTES): clasificar VARIOS anuncios en UNA sola llamada al LLM
# ---------------------------------------------------------------------------
# Mismo criterio que classify_category, pero agrupando N anuncios por peticion
# para no agotar la cuota por minuto del free tier. La red de seguridad es la
# misma: atajo determinista a 'base', y ante CUALQUIER fallo (LLM caido, JSON
# invalido o incompleto, indice ausente) ese anuncio cae a reglas
# (_fallback_category) — nunca se descarta ("ante la duda, dejar pasar").

_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_board_game": {"type": "boolean"},
                    "category": {"type": "string", "enum": list(VALID)},
                    "includes_base_game": {"type": "boolean"},
                },
                "required": ["index", "is_board_game", "category",
                             "includes_base_game"],
            },
        },
    },
    "required": ["items"],
}

_BATCH_PROMPT = _CATEGORY_PROMPT + """

AHORA recibes VARIOS anuncios numerados (cada uno empieza por "INDEX: n").
Clasifica CADA uno con el mismo criterio y devuelve un JSON con la clave
"items": una lista con un objeto por anuncio, cada objeto con su "index" (el
mismo numero que te doy), "is_board_game", "category" e "includes_base_game".
No te saltes ningun indice ni inventes indices nuevos. Responde SOLO en JSON."""


def classify_categories_batch(pairs, use_llm=True, model="qwen2.5:3b",
                              batch_size=None):
    """Clasifica una LISTA de (title, description) por REGLAS. Devuelve una lista
    de categorías ALINEADA con 'pairs'
    ('base'|'expansion'|'components'|'lote'|'not_game').

    Sin LLM ya no hay lotes ni cuota que gestionar: se clasifica anuncio a
    anuncio con classify_category. `use_llm`/`model`/`batch_size` se conservan
    por compatibilidad de firma pero ya no se usan."""
    return [classify_category(title or "", desc or "", use_llm, model)
            for title, desc in pairs]


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
    Rama 2 (título NO coincide): ¿es un LOTE que incluye el juego buscado?
    Por REGLAS (sin LLM): hace falta vocabulario explícito de lote Y que el
    juego buscado aparezca en el título o la descripción (donde se listan los
    juegos del lote). Devuelve dict {is_lote, includes_target, games}.

    `use_llm`/`model` se conservan por compatibilidad de firma; ya no se usan.
    """
    description = strip_tag_spam(description)
    full = f"{title} {description}"
    is_lote = _has_lote_vocab(full)
    # title_matches aplica el matching núcleo/genérico sobre título+descripción:
    # el juego buscado debe aparecer de verdad (no por una palabra común suelta).
    includes = is_lote and title_matches(target, full)
    return {"is_lote": is_lote, "includes_target": includes, "games": ""}


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
    # Lote (regla dura, rediseño jun 2026): vocabulario explícito de lote en
    # título o descripción. No basta un 'pack' suelto (p.ej. "pack de minis").
    if _has_lote_vocab(full):
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
