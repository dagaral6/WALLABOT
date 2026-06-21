"""
compare_nli_vs_current.py
-------------------------
Fase 2 del plan de validacion NLI. Compara el clasificador NLI (modelo LOCAL
con transformers) contra la categoria que el sistema ACTUAL (reglas + cascada
LLM) ya asigno a cada anuncio, usando el dataset generado en la Fase 0.

Mide:
  - Accuracy global y por categoria (acuerdo con el sistema actual).
  - Matriz de confusion en texto.
  - Tasa de falso positivo en 'not_game'/'unknown' (clasificar como juego algo
    que no lo es). El proyecto prioriza "ante la duda, dejar pasar", asi que un
    NLI demasiado estricto seria PEOR que el actual aunque su accuracy global
    parezca buena. Por eso se reporta aparte.
  - Tiempo total (para estimar viabilidad en GitHub Actions).

Recuerda: el dataset es ground truth DEBIL (lo que el sistema actual decidio,
no verdad verificada). Mide "acuerdo", no correccion absoluta.

    python compare_nli_vs_current.py            # todo el dataset
    python compare_nli_vs_current.py 100        # primeros 100 casos (mas rapido)
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

# Categorias que, si el sistema actual NO las trata como juego, NO deben acabar
# clasificadas como juego por NLI (eso seria un anuncio colado de mas... pero
# OJO: el proyecto prefiere dejar pasar, asi que lo critico es lo contrario:
# que NLI NO rechace como not_game algo que el actual SI dejo pasar).
NON_GAME = {"not_game", "unknown", None}


def load_dataset(limit=None):
    if not os.path.exists(DATASET):
        print(f"No existe {DATASET}. Ejecuta antes build_nli_dataset.py "
              "(Fase 0).")
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

    confusion = {}          # (actual, nli) -> n
    per_cat_total = {}      # actual -> n
    per_cat_hit = {}        # actual -> aciertos
    svc_fails = 0
    # Critico: el actual lo dejo pasar (es juego) pero NLI lo rechaza (not_game).
    false_rejections = 0
    t0 = time.time()

    for i, row in enumerate(rows, 1):
        title = row.get("title") or ""
        actual = row.get("category") or "unknown"
        try:
            nli_cat, _score, _ = nli_common.classify_nli_local(title, model=model)
        except nli_common.NLIUnavailable as e:
            svc_fails += 1
            if svc_fails <= 5:
                print(f"  [SVC] caso {i}: {e}")
            continue

        confusion[(actual, nli_cat)] = confusion.get((actual, nli_cat), 0) + 1
        per_cat_total[actual] = per_cat_total.get(actual, 0) + 1
        if nli_cat == actual:
            per_cat_hit[actual] = per_cat_hit.get(actual, 0) + 1
        if actual not in NON_GAME and nli_cat == "not_game":
            false_rejections += 1

    elapsed = time.time() - t0
    answered = len(rows) - svc_fails

    print(f"\n--- Resultados ({answered} respondidos, {svc_fails} sin "
          f"servicio, {elapsed:.1f}s) ---")
    if answered == 0:
        print("RESULTADO: SERVICIO NO DISPONIBLE. Reintentar (cold start/cuota).")
        return 2

    total_hits = sum(per_cat_hit.values())
    print(f"\nAccuracy global (acuerdo con el actual): "
          f"{total_hits}/{answered} = {total_hits / answered:.0%}")

    print("\nAccuracy por categoria del sistema actual:")
    for cat in sorted(per_cat_total):
        h, n = per_cat_hit.get(cat, 0), per_cat_total[cat]
        print(f"  {cat:>10}: {h}/{n} = {h / n:.0%}")

    print("\nMatriz de confusion (actual -> nli : n):")
    for (actual, nli_cat), n in sorted(confusion.items(),
                                       key=lambda kv: -kv[1]):
        mark = "" if actual == nli_cat else "   <-- discrepancia"
        print(f"  {actual:>10} -> {nli_cat:<10}: {n}{mark}")

    print(f"\nFalsos rechazos (el actual lo dejo pasar, NLI dice not_game): "
          f"{false_rejections}")
    print("  ^ Metrica CRITICA: el proyecto prefiere dejar pasar. Un valor "
          "alto descalifica NLI aunque la accuracy global sea buena.")

    print("\nRESULTADO: revisar contra la puerta de paso del plan "
          "(accuracy no >5-10 pts por debajo del actual Y pocos falsos "
          "rechazos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
