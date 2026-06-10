"""
diagnostico.py
--------------
Herramienta de depuración. Para una alerta de tu config.yaml, consulta Wallapop
AHORA y muestra, anuncio por anuncio, por qué se enviaría o no:
  - precio vs límite
  - si el título coincide con el juego buscado
  - categoría que decide el LLM (base/expansion/components/lote)
  - si el anuncio YA estaba en la base de datos (por eso no se reenvía)
  - la decisión final y el motivo en lenguaje claro

NO modifica nada (solo lee). Úsalo así desde la carpeta del proyecto:

    python3 diagnostico.py                # usa la primera alerta (Wingspan)
    python3 diagnostico.py "catan"        # filtra la alerta cuyo nombre/keywords
                                          # contenga ese texto
"""

import sys
io_ok = True
try:
    sys.stdout.reconfigure(encoding="utf-8")  # evita errores con € y acentos
except Exception:
    io_ok = False

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))

import main
import scraper
import database
import classifier


def pick_alert(config, needle=None):
    alerts = config["alerts"]
    if not needle:
        return alerts[0]
    needle = needle.lower()
    for a in alerts:
        if needle in a["name"].lower() or needle in a["keywords"].lower():
            return a
    print(f"No encontré ninguna alerta que contenga '{needle}'. "
          f"Uso la primera: {alerts[0]['name']}")
    return alerts[0]


def reason(item, alert, cfg, in_db, t_match, category, decision):
    want = alert.get("want") or ["base", "lote"]
    if in_db:
        return "YA estaba registrado → no se reenvía (esto es normal)"
    if decision == "keep":
        if category == "lote":
            return "se ENVIARÍA (lote, precio ignorado)"
        return "se ENVIARÍA"
    # rechazos
    if category == "not_game":
        return "no es un juego de mesa (otro producto que coincide en el nombre)"
    if not t_match and category != "lote":
        return ("el título no contiene el juego buscado y no es un lote "
                "relevante")
    if category not in want:
        return f"clasificado como '{category}', no está en want={want}"
    if not main._price_ok(item, alert):
        mx = alert.get("max_price")
        return f"precio {item.get('price')} EUR supera el límite {mx} EUR"
    return f"rechazado (categoría {category})"


def main_diag():
    config = main.load_config()
    needle = sys.argv[1] if len(sys.argv) > 1 else None
    alert = pick_alert(config, needle)
    name = alert["name"]
    target = alert["keywords"]
    mx = alert.get("max_price")
    want = alert.get("want") or ["base", "lote"]

    cls = config.get("classifier", {})
    use_llm = cls.get("use_llm", True)
    model = cls.get("model", "qwen2.5:3b")

    print("=" * 64)
    print(f"DIAGNÓSTICO de la alerta: {name}")
    print(f"  buscando: '{target}'  | límite precio: {mx} EUR | want: {want}")
    ollama = classifier.ollama_available()
    print(f"  Ollama activo: {'SÍ' if ollama else 'NO (se usa respaldo)'}")
    print("=" * 64)

    database.init_db()
    known = database.get_known_ids(name)
    kept = database.get_kept_rows(name)
    print(f"En la base de datos para esta alerta: {len(known)} anuncios "
          f"registrados ({len(kept)} de ellos avisados en su día).\n")

    results = scraper.search(
        keywords=target,
        latitude=config["location"]["latitude"],
        longitude=config["location"]["longitude"],
        min_price=None, max_price=None,
    )
    print(f"Wallapop devuelve AHORA {len(results)} resultados para '{target}'.\n")

    would_send = 0
    for i, it in enumerate(results, 1):
        t_match = classifier.title_matches(target, it.get("title", ""))
        # categoría (solo si el título coincide; si no, miramos lote)
        if t_match:
            category = classifier.classify_category(
                it.get("title", ""), it.get("description", ""), use_llm, model)
            if category == "unknown":
                category = "base"
        elif classifier.looks_like_lote(it.get("title", ""),
                                        it.get("description", "")):
            lote = classifier.check_lote(
                target, it.get("title", ""), it.get("description", ""),
                use_llm, model)
            category = "lote" if (lote["is_lote"] and lote["includes_target"]) \
                else "(otro juego)"
        else:
            category = "(otro juego)"
        decision, _cat = main.evaluate(it, alert, config)
        in_db = it["id"] in known
        if decision == "keep" and not in_db:
            would_send += 1

        print(f"[{i}] {it.get('title','(sin título)')}")
        print(f"    precio: {it.get('price')} EUR   (límite {mx} EUR)")
        print(f"    título coincide: {'sí' if t_match else 'no'}")
        print(f"    categoría (LLM): {category}")
        print(f"    ¿ya en la BD?: {'sí' if in_db else 'no'}")
        print(f"    DECISIÓN: {decision.upper()}  → "
              f"{reason(it, alert, config, in_db, t_match, category, decision)}")
        print()

    print("-" * 64)
    print(f"Resumen: de {len(results)} anuncios, se ENVIARÍAN AHORA "
          f"{would_send} (los nuevos que pasan todos los filtros).")
    print("Si el número de 'ya en la BD' es alto, por eso recibiste pocos "
          "emails: ya estaban registrados.")
    print("Si ves anuncios válidos rechazados por precio, sube 'max_price' en "
          "config.yaml.")
    print("Si ves un anuncio MAL clasificado, copia su título y descripción y "
          "pásamelos para afinar el modelo.")


if __name__ == "__main__":
    main_diag()
