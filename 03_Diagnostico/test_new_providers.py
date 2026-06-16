"""
test_new_providers.py
---------------------
Verifica SIN RED el cableado de los proveedores OpenAI-compatibles anadidos
(Cerebras, OpenRouter, GitHub Models) y la configuracion desde bot_settings.yaml
(classifier.configure_from_settings).

Comprueba:
  1) Cada proveedor, cuando es el primero de la cascada, apunta a su endpoint
     correcto, manda el modelo por defecto esperado y la cabecera Authorization.
  2) OpenRouter anade ademas HTTP-Referer y X-Title.
  3) configure_from_settings aplica cascada/modelos/claves de la seccion 'llm'
     SOLO si no hay variable de entorno equivalente (la env-var manda).

No toca la red: sustituye _post_with_retry por un stub que captura la llamada.

    python test_new_providers.py
"""

import os
import sys
import importlib

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

# Partimos de un entorno limpio: sin cascada/claves de entorno, para poder
# probar configure_from_settings. Las iremos poniendo en cada bloque.
for _k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_CASCADE", "LLM_COOLDOWN",
           "GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
           "OPENROUTER_API_KEY", "GH_MODELS_TOKEN", "LLM_API_KEY",
           "LLM_BASE_URL"):
    os.environ.pop(_k, None)
os.environ["LLM_MIN_INTERVAL"] = "0"   # sin throttle en el test

import classifier  # noqa: E402
importlib.reload(classifier)

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


class _FakeResp:
    """Imita lo justo de requests.Response para _ask_openai_compat."""
    def __init__(self, content):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


_CAPTURED = {}


def _stub_post(provider, url, headers, payload, timeout, tries=2):
    _CAPTURED.clear()
    _CAPTURED.update(provider=provider, url=url, headers=headers, payload=payload)
    # Respuesta valida para classify_category (is_board_game/category/...).
    return _FakeResp('{"is_board_game": true, "category": "expansion", '
                     '"includes_base_game": false}')


classifier._post_with_retry = _stub_post


def _run_one(provider, key_env):
    """Pone a 'provider' como primero de la cascada con una clave de prueba y
    clasifica un anuncio, devolviendo lo capturado por el stub."""
    os.environ["LLM_CASCADE"] = provider + ",rules"
    os.environ[key_env] = "test-" + provider
    importlib.reload(classifier)
    classifier._post_with_retry = _stub_post   # re-aplicar tras el reload
    cat = classifier.classify_category(
        "Wingspan Europa", "Solo la expansion, necesitas el base.",
        use_llm=True)
    os.environ.pop(key_env, None)
    os.environ.pop("LLM_CASCADE", None)
    return cat, dict(_CAPTURED)


# --- 1) Cerebras -----------------------------------------------------------
cat, cap = _run_one("cerebras", "CEREBRAS_API_KEY")
check("cerebras: clasifica con la respuesta del LLM", cat == "expansion", cat)
check("cerebras: endpoint correcto",
      cap.get("url") == "https://api.cerebras.ai/v1/chat/completions",
      cap.get("url"))
check("cerebras: modelo por defecto llama-3.3-70b",
      cap.get("payload", {}).get("model") == "llama-3.3-70b",
      cap.get("payload", {}).get("model"))
check("cerebras: cabecera Authorization Bearer",
      cap.get("headers", {}).get("Authorization", "").startswith("Bearer "))
check("cerebras: modo JSON",
      cap.get("payload", {}).get("response_format") == {"type": "json_object"})


# --- 2) OpenRouter ---------------------------------------------------------
cat, cap = _run_one("openrouter", "OPENROUTER_API_KEY")
check("openrouter: endpoint correcto",
      cap.get("url") == "https://openrouter.ai/api/v1/chat/completions",
      cap.get("url"))
check("openrouter: modelo :free por defecto",
      cap.get("payload", {}).get("model") == "meta-llama/llama-3.3-70b-instruct:free",
      cap.get("payload", {}).get("model"))
check("openrouter: cabeceras HTTP-Referer y X-Title",
      "HTTP-Referer" in cap.get("headers", {}) and "X-Title" in cap.get("headers", {}),
      list(cap.get("headers", {}).keys()))


# --- 3) GitHub Models ------------------------------------------------------
cat, cap = _run_one("githubmodels", "GH_MODELS_TOKEN")
check("githubmodels: endpoint correcto",
      cap.get("url") == "https://models.github.ai/inference/chat/completions",
      cap.get("url"))
check("githubmodels: modelo por defecto openai/gpt-4o-mini",
      cap.get("payload", {}).get("model") == "openai/gpt-4o-mini",
      cap.get("payload", {}).get("model"))


# --- 4) configure_from_settings -------------------------------------------
for _k in ("LLM_CASCADE", "LLM_PROVIDER", "CEREBRAS_API_KEY"):
    os.environ.pop(_k, None)
importlib.reload(classifier)
classifier._post_with_retry = _stub_post
classifier.configure_from_settings({"llm": {
    "cascade": ["cerebras", "gemini", "rules"],
    "models": {"cerebras": "qwen-3-32b"},
    "keys": {"cerebras": "csk-from-yaml"},
}})
check("settings: cascada aplicada desde bot_settings.yaml",
      classifier.LLM_CASCADE == ["cerebras", "gemini", "rules"],
      classifier.LLM_CASCADE)
check("settings: LLM_PROVIDER = primer eslabon", classifier.LLM_PROVIDER == "cerebras")
check("settings: modelo por proveedor desde YAML",
      classifier._cloud_model("cerebras") == "qwen-3-32b",
      classifier._cloud_model("cerebras"))
check("settings: API key desde YAML cuando no hay env",
      classifier._api_key("cerebras") == "csk-from-yaml",
      classifier._api_key("cerebras"))

# La env-var debe MANDAR sobre el YAML.
os.environ["CEREBRAS_API_KEY"] = "csk-from-env"
check("settings: la variable de entorno manda sobre el YAML",
      classifier._api_key("cerebras") == "csk-from-env",
      classifier._api_key("cerebras"))
os.environ.pop("CEREBRAS_API_KEY", None)

os.environ["LLM_CASCADE"] = "groq,rules"
importlib.reload(classifier)
classifier.configure_from_settings({"llm": {"cascade": ["cerebras", "rules"]}})
check("settings: LLM_CASCADE de entorno ignora el cascade del YAML",
      classifier.LLM_CASCADE == ["groq", "rules"],
      classifier.LLM_CASCADE)
os.environ.pop("LLM_CASCADE", None)


print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
