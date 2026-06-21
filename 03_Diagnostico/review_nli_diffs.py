"""
review_nli_diffs.py
-------------------
Fase 2B: Ejecuta NLI contra el dataset real y guarda los casos donde
NLI difiere del sistema actual en un JSON para revisión manual.

Uso:
    py review_nli_diffs.py                    # todo el dataset
    py review_nli_diffs.py 100                # primeros 100 casos
    set NLI_MODEL=joeddav/xlm-roberta-large-xnli && py review_nli_diffs.py

Genera: nli_dataset/diffs.json
  Cada objeto: {title, actual_category, nli_category, nli_score, match}
"""

import os
import sys
import json
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import nli_common  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATASET = os.path.join(BASE, "nli_dataset", "cases.jsonl")
OUTPUT = os.path.join(BASE, "nli_dataset", "diffs.json")

NON_GAME = {"not_game", "unknown", None}


def load_dataset(limit=None):
    if not os.path.exists(DATASET):
        print(f"No existe {DATASET}. Ejecuta primero build_nli_dataset.py")
        sys.exit(1)
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    model = os.getenv("NLI_MODEL") or nli_common.HF_MODELS[0]
    rows = load_dataset(limit)

    print(f"Modelo NLI: {model}")
    print(f"Casos a evaluar: {len(rows)}\n")

    diffs = []          # Casos donde NLI ≠ actual (para revisar)
    matches = 0         # Casos donde acuerdan
    svc_fails = 0
    false_rejections = 0
    t0 = time.time()

    for i, row in enumerate(rows, 1):
        title = row.get("title") or ""
        actual = row.get("category") or "unknown"

        try:
            nli_cat, nli_score, _ = nli_common.classify_nli_local(title, model=model)
        except nli_common.NLIUnavailable as e:
            svc_fails += 1
            if svc_fails <= 5:
                print(f"  [SVC] caso {i}: {e}")
            continue

        if nli_cat == actual:
            matches += 1
        else:
            # Guardar para revisión manual
            diffs.append({
                "title": title,
                "actual_category": actual,
                "nli_category": nli_cat,
                "nli_score": float(nli_score),
                "match": False,
            })

        # Falsos rechazos (métrica crítica)
        if actual not in NON_GAME and nli_cat == "not_game":
            false_rejections += 1

        if i % 50 == 0:
            print(f"  Procesados {i}/{len(rows)}...")

    elapsed = time.time() - t0
    answered = len(rows) - svc_fails

    print(f"\n--- Resultados ({answered} respondidos, {svc_fails} sin servicio, {elapsed:.1f}s) ---")

    if answered == 0:
        print("RESULTADO: SERVICIO NO DISPONIBLE")
        return 2

    total_hits = matches
    print(f"\nAccuracy global (acuerdo con el actual): "
          f"{total_hits}/{answered} = {total_hits / answered:.0%}")

    print(f"\nCasos con discrepancias (para revisar): {len(diffs)}")
    print(f"Falsos rechazos: {false_rejections}")

    # Guardar diffs en JSON
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(diffs, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado en: {OUTPUT}")
    print(f"Total de discrepancias a revisar: {len(diffs)}")

    print("\nRESULTADO: revisa {OUTPUT} manualmente")
    return 0


if __name__ == "__main__":
    sys.exit(main())
