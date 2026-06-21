"""
nli_common.py
-------------
Helpers COMPARTIDOS por la validacion NLI (Fases 1 y 2 del plan). NO es codigo
de produccion: no se importa desde 01_Core, vive solo en 03_Diagnostico.

Define:
  - Las hipotesis / etiquetas en lenguaje natural por categoria del proyecto
    (base, expansion, components, lote, not_game).
  - Un wrapper sobre la Hugging Face Inference API (zero-shot / NLI) que maneja
    explicitamente cold-start (503), cuota agotada (429) y timeout.
  - El mapeo de la etiqueta ganadora de vuelta a la categoria interna.

El token de HF se lee de la variable de entorno HF_API_TOKEN (NUNCA se hardcodea
aqui). Si no esta, la API publica suele funcionar igual pero con cuota mas baja.
"""

import os
import requests

try:
    from transformers import pipeline
except ImportError:
    pipeline = None

# Categorias internas del clasificador (ver 01_Core/classifier.py).
# Mapeo categoria -> etiqueta en lenguaje natural (en español, el idioma de los
# anuncios). El orden no importa; HF puntua todas y gana la de mayor score.
LABELS = {
    "base":       "un juego de mesa completo",
    "expansion":  "una expansion de un juego de mesa",
    "components": "componentes o accesorios sueltos de un juego de mesa",
    "lote":       "un lote de varios juegos de mesa",
    "not_game":   "algo que no es un juego de mesa",
}

# Plantilla de hipotesis NLI. HF rellena {} con cada etiqueta de LABELS.
HYPOTHESIS_TEMPLATE = "Este anuncio trata de {}."

# Modelos NLI candidatos a probar (Fase 1). El primero es el clasico en ingles;
# el segundo es multilingue (mejor para español/catalan). La Fase 1 decide cual.
HF_MODELS = [
    "facebook/bart-large-mnli",
    "joeddav/xlm-roberta-large-xnli",
]

HF_API_URL = "https://api-inference.huggingface.co/models/{model}"

# Etiqueta -> categoria interna (inverso de LABELS).
_LABEL_TO_CAT = {v: k for k, v in LABELS.items()}


class NLIUnavailable(Exception):
    """El modelo NLI no respondio de forma utilizable (503/429/timeout/red)."""


def _headers():
    token = os.getenv("HF_API_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def classify_nli_hf(text, model=None, timeout=30):
    """Clasifica `text` (titulo + descripcion) en una categoria interna usando
    la HF Inference API en modo zero-shot. Devuelve (categoria, score, raw).

    Lanza NLIUnavailable ante 503 (modelo cargando), 429 (cuota), timeout o
    error de red, para que el llamador registre el fallo (en produccion esto
    seria el punto donde la cascada salta al siguiente eslabon).
    """
    model = model or HF_MODELS[0]
    url = HF_API_URL.format(model=model)
    payload = {
        "inputs": text,
        "parameters": {
            "candidate_labels": list(LABELS.values()),
            "hypothesis_template": HYPOTHESIS_TEMPLATE,
            "multi_label": False,
        },
    }
    try:
        r = requests.post(url, headers=_headers(), json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise NLIUnavailable(f"red/timeout: {e}")

    if r.status_code == 503:
        raise NLIUnavailable("503 modelo cargando (cold start)")
    if r.status_code == 429:
        raise NLIUnavailable("429 cuota agotada")
    if r.status_code != 200:
        raise NLIUnavailable(f"HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    # Respuesta zero-shot: {"labels": [...], "scores": [...]} ordenado desc.
    if not isinstance(data, dict) or "labels" not in data:
        raise NLIUnavailable(f"respuesta inesperada: {str(data)[:200]}")

    best_label = data["labels"][0]
    best_score = data["scores"][0]
    category = _LABEL_TO_CAT.get(best_label, "unknown")
    return category, best_score, data


def classify_nli_local(text, model=None, timeout=None):
    """Clasifica `text` usando un modelo NLI LOCAL (transformers.pipeline,
    sin pasar por HF Inference API). Devuelve (categoria, score, raw).

    Requiere transformers instalado. Lanza NLIUnavailable si el modelo falla
    a cargar o si transformers no esta disponible.
    """
    if pipeline is None:
        raise NLIUnavailable("transformers no instalado; no se puede usar "
                             "classify_nli_local()")
    model = model or HF_MODELS[0]
    try:
        clf = pipeline("zero-shot-classification", model=model)
    except Exception as e:
        raise NLIUnavailable(f"no se pudo cargar el modelo {model}: {e}")

    try:
        result = clf(text, candidate_labels=list(LABELS.values()),
                     hypothesis_template=HYPOTHESIS_TEMPLATE)
    except Exception as e:
        raise NLIUnavailable(f"error en la inferencia: {e}")

    best_label = result["labels"][0]
    best_score = result["scores"][0]
    category = _LABEL_TO_CAT.get(best_label, "unknown")
    return category, best_score, result
