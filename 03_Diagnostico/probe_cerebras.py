# -*- coding: utf-8 -*-
"""Diagnostico puntual: prueba la clave de Cerebras contra su endpoint real.
No imprime la clave; solo el codigo de estado y un fragmento de la respuesta."""
import os, sys, yaml, requests

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "01_Core")
with open(os.path.join(CORE, "bot_settings.yaml"), "r", encoding="utf-8") as f:
    s = yaml.safe_load(f)

llm = s.get("llm", {})
key = (llm.get("keys") or {}).get("cerebras", "") or os.getenv("CEREBRAS_API_KEY", "")
model = (llm.get("models") or {}).get("cerebras", "llama-3.3-70b")
print("clave presente:", bool(key), "| longitud:", len(key), "| modelo:", model)

try:
    r = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": "di hola"}],
              "max_completion_tokens": 5, "temperature": 0},
        timeout=20,
    )
    print("HTTP:", r.status_code)
    print("respuesta (160c):", r.text[:160])
except Exception as e:
    print("EXCEPCION:", repr(e))

# Tambien listamos los modelos que la clave puede ver
try:
    rm = requests.get("https://api.cerebras.ai/v1/models",
                      headers={"Authorization": "Bearer " + key}, timeout=20)
    print("models HTTP:", rm.status_code)
    if rm.status_code == 200:
        ids = [m.get("id") for m in rm.json().get("data", [])]
        print("modelos disponibles:", ids)
    else:
        print("models respuesta (160c):", rm.text[:160])
except Exception as e:
    print("EXCEPCION models:", repr(e))
