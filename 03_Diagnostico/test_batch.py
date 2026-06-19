"""
test_batch.py
-------------
Verifica SIN RED la clasificacion POR LOTES (Tarea 1) y que Cerebras se integra
en la cascada con el mismo fail-fast en 429.

Comprueba:
  1) classify_categories_batch agrupa VARIOS anuncios en UNA sola llamada al LLM
     y mapea bien indice -> categoria.
  2) Si el LLM omite un indice (JSON incompleto), ESE anuncio cae a reglas
     (_fallback_category), no se descarta; el resto se respeta.
  3) Si el LLM falla o devuelve JSON mal formado, TODO el lote cae a reglas.
  4) 'cerebras' es un eslabon valido de la cascada y, ante 429, abre su circuit
     breaker y la cascada salta al siguiente proveedor (fail-fast).

No toca la red: sustituye las funciones internas por stubs.

    python test_batch.py
"""

import os
import sys
import importlib

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

for _k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BATCH_SIZE"):
    os.environ.pop(_k, None)
os.environ["LLM_CASCADE"] = "gemini,rules"
os.environ["GEMINI_API_KEY"] = "test-gemini"
os.environ["LLM_MIN_INTERVAL"] = "0"
os.environ["LLM_COOLDOWN"] = "600"

import classifier  # noqa: E402
importlib.reload(classifier)
import requests  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


# Anuncios que NO disparan el atajo determinista a 'base' (asi pasan al LLM):
#  - "Solo la expansion" / "no incluye el juego" bloquean el atajo.
PAIRS = [
    ("Wingspan Europa", "Solo la expansion, necesitas el base."),   # -> expansion
    ("Guantes Inis Talla L", "Guantes de montaña, poco uso."),      # -> not_game
    ("Insertos para Catan", "Solo los insertos, no incluye el juego."),  # -> components
]


# --- 1) batching: una sola llamada para varios anuncios -------------------
calls = {"n": 0}
def stub_ask_ok(model, schema, msgs):
    calls["n"] += 1
    return {"items": [
        {"index": 0, "is_board_game": True,  "category": "expansion",
         "includes_base_game": False},
        {"index": 1, "is_board_game": False, "category": "base",
         "includes_base_game": False},
        {"index": 2, "is_board_game": True,  "category": "components",
         "includes_base_game": False},
    ]}
classifier._ask = stub_ask_ok

cats = classifier.classify_categories_batch(PAIRS, use_llm=True)
check("una sola llamada al LLM para 3 anuncios", calls["n"] == 1, calls["n"])
check("categorias del lote correctas",
      cats == ["expansion", "not_game", "components"], cats)


# --- 2) indice omitido por el LLM -> ese anuncio cae a reglas --------------
# pairs cuyo fallback por reglas es predecible:
PAIRS2 = [
    ("Wingspan", "Juego en buen estado."),                       # LLM idx0
    ("Root", "Juego de estrategia."),                            # idx1 OMITIDO
    ("Insertos para Root", "Solo los insertos, no incluye el juego."),  # idx2 OMITIDO
]
def stub_ask_partial(model, schema, msgs):
    return {"items": [
        {"index": 0, "is_board_game": True, "category": "base",
         "includes_base_game": True},
    ]}
classifier._ask = stub_ask_partial

cats2 = classifier.classify_categories_batch(PAIRS2, use_llm=True)
# idx0 del LLM -> base ; idx1 ausente -> reglas("Root"...) = unknown ;
# idx2 ausente -> reglas("...no incluye el juego / solo los insertos") = components
check("indice presente usa la respuesta del LLM", cats2[0] == "base", cats2)
check("indice omitido cae a reglas (no se descarta)",
      cats2[1] == "unknown" and cats2[2] == "components", cats2)


# --- 3) LLM caido / JSON mal formado -> TODO el lote a reglas --------------
def stub_ask_boom(model, schema, msgs):
    raise requests.RequestException("LLM caido (simulado)")
classifier._ask = stub_ask_boom
cats3 = classifier.classify_categories_batch(PAIRS2, use_llm=True)
check("LLM caido -> lote completo a reglas",
      cats3 == ["unknown", "unknown", "components"], cats3)

def stub_ask_badjson(model, schema, msgs):
    raise ValueError("JSON mal formado (simulado)")
classifier._ask = stub_ask_badjson
cats3b = classifier.classify_categories_batch(PAIRS2, use_llm=True)
check("JSON mal formado -> lote completo a reglas",
      cats3b == ["unknown", "unknown", "components"], cats3b)


# --- 4) cerebras en la cascada + fail-fast en 429 -------------------------
os.environ["LLM_CASCADE"] = "cerebras,gemini,rules"
os.environ["CEREBRAS_API_KEY"] = "test-cerebras"
os.environ["GEMINI_API_KEY"] = "test-gemini"
importlib.reload(classifier)
classifier._breaker_until.clear()

check("cerebras es un eslabon valido de la cascada",
      classifier.LLM_CASCADE == ["cerebras", "gemini", "rules"],
      classifier.LLM_CASCADE)

LLM_ANSWER = {"is_board_game": True, "category": "expansion",
              "includes_base_game": False}
order = []
def stub_provider(provider, model, schema, messages, timeout=120):
    order.append(provider)
    if provider == "cerebras":
        classifier._trip_breaker("cerebras")   # 429 sostenido: a cooldown
        raise requests.RequestException("cerebras 429 (simulado)")
    if provider == "gemini":
        return LLM_ANSWER
    raise requests.RequestException("no deberia llegar a " + provider)
classifier._ask_provider = stub_provider

cat4 = classifier.classify_category(
    "Wingspan Europa", "Solo la expansion, necesitas el base.", use_llm=True)
check("cerebras 429 -> la cascada salta a gemini", cat4 == "expansion", cat4)
check("cerebras se intenta primero", order[:1] == ["cerebras"], order)
check("circuit breaker de cerebras ABIERTO tras 429",
      classifier._breaker_open("cerebras"))


print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
