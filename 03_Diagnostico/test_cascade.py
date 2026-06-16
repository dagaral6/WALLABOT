"""
test_cascade.py
---------------
Verifica SIN RED la CASCADA de proveedores LLM del clasificador.

Comprueba tres cosas ("revisa que el fallback funcione"):
  1) Si el primer proveedor falla, se pasa AL SIGUIENTE de LLM_CASCADE.
  2) Si TODOS fallan, la cascada se agota en 'rules' y classify_category
     devuelve 'unknown' (que main.py trata como la red de seguridad).
  3) El circuit breaker saca de la rotacion a un proveedor en cooldown:
     _ask ni siquiera lo intenta y pasa directo al siguiente.

No toca la red: sustituye las funciones internas por stubs.

    python test_cascade.py
"""

import os
import sys
import importlib

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

# Cascada de prueba: groq -> gemini -> rules (con ambas claves presentes).
for _k in ("LLM_PROVIDER", "LLM_MODEL"):
    os.environ.pop(_k, None)
os.environ["LLM_CASCADE"] = "groq,gemini,rules"
os.environ["GROQ_API_KEY"] = "test-groq"
os.environ["GEMINI_API_KEY"] = "test-gemini"
os.environ["LLM_MIN_INTERVAL"] = "0"
os.environ["LLM_COOLDOWN"] = "600"

import classifier  # noqa: E402
importlib.reload(classifier)
import requests  # noqa: E402

_orig_ask_provider = classifier._ask_provider

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


# El LLM responde 'expansion' a proposito: asi distinguimos su respuesta del
# atajo determinista a 'base' (que NO debe dispararse con este titulo).
LLM_ANSWER = {"is_board_game": True, "category": "expansion",
              "includes_base_game": False}

check("cascada leida del entorno",
      classifier.LLM_CASCADE == ["groq", "gemini", "rules"],
      classifier.LLM_CASCADE)
check("LLM_PROVIDER = primer eslabon", classifier.LLM_PROVIDER == "groq")


# --- 1) groq falla -> gemini responde -------------------------------------
order = []
def stub_fail_groq(provider, model, schema, messages, timeout=120):
    order.append(provider)
    if provider == "groq":
        raise requests.RequestException("groq caido (simulado)")
    if provider == "gemini":
        return LLM_ANSWER
    raise requests.RequestException("no deberia llegar a " + provider)
classifier._ask_provider = stub_fail_groq

cat = classifier.classify_category(
    "Wingspan Europa", "En buen estado, jugado pocas veces.",
    use_llm=True, model="qwen2.5:3b")
check("groq falla -> se usa gemini (fallback)", cat == "expansion", cat)
check("orden de intentos = [groq, gemini]", order == ["groq", "gemini"], order)


# --- 2) todos fallan -> 'unknown' (red de seguridad) ----------------------
order2 = []
def stub_all_fail(provider, model, schema, messages, timeout=120):
    order2.append(provider)
    raise requests.RequestException(provider + " caido (simulado)")
classifier._ask_provider = stub_all_fail

cat2 = classifier.classify_category(
    "Wingspan Europa", "En buen estado.", use_llm=True, model="x")
check("todos fallan -> categoria 'unknown'", cat2 == "unknown", cat2)
check("se intentaron groq y gemini antes de rendirse",
      order2 == ["groq", "gemini"], order2)


# --- 3) circuit breaker: un proveedor en cooldown se salta ----------------
classifier._ask_provider = _orig_ask_provider   # restaurar el real (mira breaker)
classifier._breaker_until.clear()
check("breaker cerrado al inicio", not classifier._breaker_open("groq"))
classifier._trip_breaker("groq")
check("breaker de groq ABIERTO tras trip", classifier._breaker_open("groq"))

classifier._ask_gemini = lambda *a, **k: LLM_ANSWER
_called = {"groq": False}
def boom_groq(*a, **k):
    _called["groq"] = True
    raise requests.RequestException("groq no deberia llamarse en cooldown")
classifier._ask_openai_compat = boom_groq

res = classifier._ask("x", classifier._CATEGORY_SCHEMA,
                      [{"role": "user", "content": "hola"}])
check("en cooldown, _ask NO llama a groq y cae en gemini",
      res == LLM_ANSWER and not _called["groq"], (res, _called))

print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
