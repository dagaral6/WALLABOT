"""
build_nli_dataset.py
---------------------
Fase 0 del plan de validacion NLI. Vuelca a JSONL los anuncios YA
clasificados por el sistema actual (reglas + cascada LLM), para usarlos
despues como referencia al comparar un clasificador NLI alternativo.

IMPORTANTE: esto es ground truth DEBIL. Es lo que el sistema actual decidio
(con sus propios errores incluidos), no una verdad absoluta verificada a
mano. Sirve para medir "acuerdo con el comportamiento actual", no accuracy
real.

Solo lectura de alerts.db (get_kept_rows / get_rejected_rows hacen SELECT).
No modifica la base de datos ni codigo de produccion.

    python build_nli_dataset.py
"""

import os
import sys
import json
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import database  # noqa: E402

OUT_DIR = os.path.join(BASE, "nli_dataset")
OUT_PATH = os.path.join(OUT_DIR, "cases.jsonl")

MIN_PER_CATEGORY = 50  # puerta de paso de la Fase 0 (ver plan)

# Categorias que main.py asigna ANTES de llamar a classify_category (rechazo
# por titulo o exclusion manual, ver evaluate()/_hard_excluded en main.py).
# NUNCA pasaron por el clasificador: no son comparables con NLI y se excluyen
# del dataset, pero se cuentan aparte para que el reporte no sea enganoso.
PRE_CLASSIFIER_CATEGORIES = {"no_title_match", "excluded"}


def _alert_names(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT alert_name FROM seen_items").fetchall()
    return sorted(r[0] for r in rows)


def main():
    db_path = database.DB_PATH
    if not os.path.exists(db_path):
        print(f"No existe {db_path}; nada que volcar.")
        return 1

    names = _alert_names(db_path)
    print(f"Alertas encontradas en alerts.db: {names}")

    cases = []
    for alert_name in names:
        kept = database.get_kept_rows(alert_name)
        rejected = database.get_rejected_rows(alert_name)
        for row in kept.values():
            cases.append({
                "alert_name": alert_name,
                "title": row.get("title"),
                "description": row.get("description"),
                "category": row.get("category"),
                "decision": row.get("decision"),
            })
        for row in rejected.values():
            cases.append({
                "alert_name": alert_name,
                "title": row.get("title"),
                "description": row.get("description"),
                "category": row.get("category"),
                "decision": row.get("decision"),
            })

    pre_filter = [c for c in cases if c["category"] in PRE_CLASSIFIER_CATEGORIES]
    relevant = [c for c in cases if c["category"] not in PRE_CLASSIFIER_CATEGORIES]

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in relevant:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\nCasos pre-filtrados por titulo (nunca llegaron al clasificador, "
          f"NO se incluyen en el dataset): {len(pre_filter)}")

    counts = {}
    for c in relevant:
        cat = c["category"] or "unknown"
        counts[cat] = counts.get(cat, 0) + 1

    print(f"\nTotal casos relevantes para el clasificador: {len(relevant)} "
          f"-> {OUT_PATH}")
    print("Casos por categoria:")
    fails = []
    for cat, n in sorted(counts.items()):
        ok = n >= MIN_PER_CATEGORY
        print(("[OK ] " if ok else "[FAIL] ") + f"{cat}: {n}")
        if not ok:
            fails.append(cat)

    print()
    if fails:
        print("RESULTADO: FALLAN (volumen insuficiente) ->", ", ".join(fails))
        print("No hay suficientes casos para medir nada con confianza en estas "
              "categorias. Con 1 sola alerta activa, la Fase 2 (comparacion "
              "masiva) no sera estadisticamente significativa todavia; valorar "
              "acumular mas datos con el tiempo, o tratar la Fase 2 como "
              "orientativa/cualitativa mientras tanto. La Fase 1 (POC sintetico) "
              "no depende de este volumen y puede ejecutarse igualmente.")
    else:
        print("RESULTADO: TODO OK")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
