"""
diag_binary.py
--------------
Diagnostico del PASO 1 (¿es juego de mesa o no?) del arbol reglas+NLI.

En la corrida completa, el binario actual (2 hipotesis con negacion) acerto
0/212 not_game: nunca marca 'not_game'. Sospecha: los modelos NLI manejan mal
las NEGACIONES ("...que no tiene nada que ver..."). Este script compara, sobre
una muestra real de not_game vs juegos, tres estrategias SOLO con hipotesis
positivas, e imprime los scores para elegir estrategia y umbral con datos.

    py diag_binary.py            # 20 not_game + 20 juegos
    py diag_binary.py 40         # 40 + 40

NO toca produccion. Solo lee el dataset.
"""

import os
import sys
import json
import statistics as st

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

try:
    from transformers import pipeline
except ImportError:
    print("[FAIL] transformers no instalado.")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATASET = os.path.join(BASE, "nli_dataset", "cases.jsonl")
MODEL = os.getenv("NLI_MODEL") or "joeddav/xlm-roberta-large-xnli"

TEMPLATE = "Este anuncio vende {}."

# Estrategia 1 (actual): 2 hipotesis con negacion, single-label (softmax).
S1_LABELS = [
    "un juego de mesa o un accesorio de un juego de mesa",
    "un producto que no tiene nada que ver con juegos de mesa",
]
# Estrategia 2: UNA hipotesis positiva, multi_label -> P(es juego de mesa).
S2_LABEL = "un juego de mesa o un accesorio de un juego de mesa"
# Estrategia 3: hipotesis POSITIVAS concretas (juego vs categorias de no-juego),
# single-label; not_game si gana cualquier etiqueta de no-juego.
S3_LABELS = {
    "un juego de mesa": "game",
    "ropa, calzado o complementos": "not_game",
    "una planta o producto de jardin": "not_game",
    "un aparato electronico o accesorio de movil": "not_game",
    "un libro, comic, musica o pelicula": "not_game",
    "decoracion, hogar u otro objeto": "not_game",
}


def load_groups(n):
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    not_game = [r for r in rows if (r.get("category") or "") == "not_game"]
    games = [r for r in rows if (r.get("category") or "") in
             ("base", "expansion", "components", "lote")]
    return not_game[:n], games[:n]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    not_game, games = load_groups(n)
    print(f"Modelo: {MODEL}")
    print(f"Muestra: {len(not_game)} not_game + {len(games)} juegos\n")
    print("Cargando modelo...")
    clf = pipeline("zero-shot-classification", model=MODEL)
    print("listo.\n")

    def scores(title):
        # S1: gana juego(+) o no-juego(-)? score del ganador
        r1 = clf(title, candidate_labels=S1_LABELS,
                 hypothesis_template=TEMPLATE)
        s1_is_game = (r1["labels"][0] == S1_LABELS[0])
        # S2: P(es juego) independiente
        r2 = clf(title, candidate_labels=[S2_LABEL],
                 hypothesis_template=TEMPLATE, multi_label=True)
        s2_game = r2["scores"][0]
        # S3: gana categoria juego o no-juego?
        r3 = clf(title, candidate_labels=list(S3_LABELS),
                 hypothesis_template=TEMPLATE)
        s3_kind = S3_LABELS[r3["labels"][0]]
        return s1_is_game, s2_game, s3_kind

    def run(group, name, expect_game):
        print(f"=== {name} (esperado: {'juego' if expect_game else 'NO juego'}) ===")
        s2_vals, s1_ok, s3_ok = [], 0, 0
        for r in group:
            title = (r.get("title") or "")[:55]
            s1_is_game, s2_game, s3_kind = scores(r.get("title") or "")
            s2_vals.append(s2_game)
            s1_ok += int(s1_is_game == expect_game)
            s3_ok += int((s3_kind == "game") == expect_game)
            print(f"  s1={'JUEGO' if s1_is_game else 'no '} "
                  f"s2={s2_game:.2f} s3={s3_kind:<8} | {title}")
        print(f"  --> aciertos S1={s1_ok}/{len(group)}  "
              f"S3={s3_ok}/{len(group)}  "
              f"S2 media={st.mean(s2_vals):.2f} "
              f"min={min(s2_vals):.2f} max={max(s2_vals):.2f}\n")
        return s2_vals

    s2_ng = run(not_game, "NOT_GAME", expect_game=False)
    s2_g = run(games, "JUEGOS", expect_game=True)

    print("=== Resumen S2 (P de 'es juego') ===")
    print(f"  not_game: media={st.mean(s2_ng):.2f}  "
          f"(un umbral bajo deberia separar)")
    print(f"  juegos:   media={st.mean(s2_g):.2f}")
    print("  Si las medias estan bien separadas, S2 con umbral intermedio "
          "es el mejor binario. Si no, mirar S3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
