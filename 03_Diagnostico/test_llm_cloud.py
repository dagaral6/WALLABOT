"""
test_llm_cloud.py
-----------------
Verifica SIN RED el adaptador multi-proveedor del clasificador (groq /
gemini / ollama): construccion de peticiones, cabeceras, modelo efectivo,
modo JSON, mapeo de mensajes para Gemini, parseo tolerante y reintento ante
HTTP 429. Stubbea requests.post/get con respuestas enlatadas.

    python test_llm_cloud.py
"""

import os
import sys
import json
import importlib

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402

fails = []
calls = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise classifier.requests.HTTPError("HTTP %d" % self.status_code)


def fake_post_factory(responses):
    state = {"i": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        calls.append({"url": url, "headers": headers or {}, "json": json})
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]
    return fake_post


def reload_as(provider, **env):
    """Recarga classifier con el proveedor y entorno indicados."""
    for k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "GEMINI_API_KEY",
              "LLM_API_KEY", "LLM_BASE_URL", "LLM_MIN_INTERVAL"):
        os.environ.pop(k, None)
    os.environ["LLM_PROVIDER"] = provider
    os.environ["LLM_MIN_INTERVAL"] = "0"
    os.environ.update(env)
    importlib.reload(classifier)
    calls.clear()


# ----------------------------------------------------------------- GROQ ----
reload_as("groq", GROQ_API_KEY="test-key")

GROQ_ANSWER = {"is_board_game": True, "category": "expansion",
               "includes_base_game": False}
groq_body = {"choices": [{"message": {"content":
             "```json\n" + json.dumps(GROQ_ANSWER) + "\n```"}}]}

classifier.requests.post = fake_post_factory([FakeResp(200, groq_body)])
cat = classifier.classify_category(
    "Catan Navegantes", "Solo la expansion; necesitas el juego base.",
    use_llm=True, model="qwen2.5:3b")

check("groq: clasifica usando la respuesta del LLM", cat == "expansion", cat)
c = calls[-1]
check("groq: endpoint correcto",
      c["url"] == "https://api.groq.com/openai/v1/chat/completions", c["url"])
check("groq: cabecera Authorization Bearer",
      c["headers"].get("Authorization") == "Bearer test-key")
check("groq: ignora el modelo de Ollama del config",
      c["json"]["model"] == "llama-3.1-8b-instant", c["json"]["model"])
check("groq: modo JSON activado",
      c["json"].get("response_format") == {"type": "json_object"})
check("groq: instruccion final con las claves del schema",
      c["json"]["messages"][-1]["role"] == "system"
      and "is_board_game" in c["json"]["messages"][-1]["content"])

# 429 abre el circuit breaker (no se reintenta). Con cascada [groq, rules],
# si groq devuelve 429, el breaker se abre y la cascada cae a rules (seguridad):
os.environ["LLM_CASCADE"] = "groq,rules"
os.environ["GROQ_API_KEY"] = "test-key"
importlib.reload(classifier)
classifier.requests.post = fake_post_factory([
    FakeResp(429, {}, {}),  # groq: 429 abre breaker -> cascada salta a rules
])
cat = classifier.classify_category(
    "Catan Navegantes", "Solo la expansion.", use_llm=True, model="x")
check("groq: 429 abre breaker -> cascada cae a rules (unknown)",
      cat == "unknown", cat)

classifier.requests.get = lambda *a, **k: FakeResp(200)
ok, desc = classifier.llm_available()
check("groq: llm_available OK con clave", ok and "groq" in desc, desc)


# --------------------------------------------------------------- GEMINI ----
reload_as("gemini", GEMINI_API_KEY="gem-key")

GEM_ANSWER = {"is_lote": True, "includes_target": True,
              "games": "Catan, Azul"}
gem_body = {"candidates": [{"content": {"parts": [
            {"text": json.dumps(GEM_ANSWER)}]}}]}

classifier.requests.post = fake_post_factory([FakeResp(200, gem_body)])
res = classifier.check_lote("catan", "Lote de juegos",
                            "Vendo juntos Catan y Azul, precio del conjunto.",
                            use_llm=True, model="qwen2.5:3b")

check("gemini: devuelve el lote parseado",
      res == GEM_ANSWER or (res["is_lote"] and res["includes_target"]), res)
c = calls[-1]
check("gemini: endpoint generateContent con el modelo por defecto",
      "generativelanguage.googleapis.com" in c["url"]
      and "gemini-2.5-flash-lite:generateContent" in c["url"], c["url"])
check("gemini: cabecera x-goog-api-key",
      c["headers"].get("x-goog-api-key") == "gem-key")
gc = c["json"].get("generationConfig") or {}
check("gemini: responseSchema + JSON nativo",
      gc.get("responseMimeType") == "application/json"
      and gc.get("responseSchema") == classifier._LOTE_SCHEMA)
check("gemini: system -> systemInstruction",
      "systemInstruction" in c["json"])
roles = [m["role"] for m in c["json"]["contents"]]
check("gemini: few-shot mapeado a user/model",
      roles[:3] == ["user", "model", "user"] and roles[-1] == "user", roles)

# ----------------------------------------------------- OLLAMA (defecto) ----
reload_as("ollama")
classifier.requests.get = lambda *a, **k: FakeResp(200)
ok, desc = classifier.llm_available()
check("ollama: sigue siendo el proveedor por defecto",
      classifier.LLM_PROVIDER == "ollama" and ok and "ollama" in desc, desc)

print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
