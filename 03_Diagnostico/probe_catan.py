"""
probe_catan.py - sonda de SOLO LECTURA. No modifica nada.
Muestra la descripcion real y la respuesta CRUDA del LLM para los anuncios
de 'catan' cuyo titulo contiene 'colonos', y prueba titulos sinteticos.
"""
import sys, json
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))

import main, scraper, classifier

cfg = main.load_config()
cls = cfg.get("classifier", {})
MODEL = cls.get("model", "qwen2.5:3b")
USE_LLM = cls.get("use_llm", True)
print("Modelo:", MODEL, "| use_llm:", USE_LLM,
      "| Ollama activo:", classifier.ollama_available())


def raw_category(title, description):
    desc = classifier.strip_tag_spam(description)
    msgs = [{"role": "system", "content": classifier._CATEGORY_PROMPT}]
    for u, a in classifier._CATEGORY_FEWSHOT:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant",
                     "content": json.dumps(a, ensure_ascii=False)})
    um = f"TITULO: {title}\nDESCRIPCION: {desc or '(sin descripcion)'}"
    hints = classifier._suspicion_hints(title, desc)
    if hints:
        um += "\n\nPISTAS:\n- " + "\n- ".join(hints)
    msgs.append({"role": "user", "content": um})
    data = classifier._ask(MODEL, classifier._CATEGORY_SCHEMA, msgs)
    return data, hints


print("\n===== PRUEBAS SINTETICAS (mismo titulo, distintas descripciones) =====")
TITLE = "Los Colonos de Catan - El Juego"
SAMPLES = [
    "(sin descripcion)",
    "Juego completo, todas las piezas, buen estado.",
    "Vendo Los Colonos de Catan. Tambien tengo las expansiones Navegantes y Ciudades y Caballeros aparte.",
    "Juego base de Catan. Compatible con todas las expansiones.",
    "Edicion Los Colonos de Catan. Caja base, jugado pocas veces.",
]
for d in SAMPLES:
    desc = "" if d == "(sin descripcion)" else d
    data, hints = raw_category(TITLE, desc)
    final = classifier.classify_category(TITLE, desc, USE_LLM, MODEL)
    print("\n- desc:", d)
    print("  hints:", hints or "ninguna")
    print("  LLM crudo:", data)
    print("  -> categoria final:", final)


print("\n===== ANUNCIOS REALES DE 'catan' CON 'colonos' EN EL TITULO =====")
res = scraper.search(keywords="catan",
                     latitude=cfg["location"]["latitude"],
                     longitude=cfg["location"]["longitude"],
                     min_price=None, max_price=None)
print("Wallapop devuelve", len(res), "resultados.")
hits = [it for it in res
        if "colonos" in classifier._normalize(it.get("title", ""))]
if not hits:
    print("Ahora mismo no aparece ningun 'colonos' (los resultados rotan).")
for it in hits[:4]:
    title = it.get("title", "")
    desc = it.get("description", "") or ""
    data, hints = raw_category(title, desc)
    final = classifier.classify_category(title, desc, USE_LLM, MODEL)
    print("\n----------------------------------------------------------------")
    print("TITULO:", title)
    print("PRECIO:", it.get("price"))
    print("DESCRIPCION (real):", repr(desc[:600]))
    print("DESCRIPCION (sin tags):", repr(classifier.strip_tag_spam(desc)[:600]))
    print("title_matches:", classifier.title_matches("catan", title))
    print("hints:", hints or "ninguna")
    print("LLM crudo:", data)
    print("-> categoria final:", final)
print("\nFIN.")
