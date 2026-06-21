"""
analyze_matching.py
-------------------
Analisis del MATCHING titulo<->keyword para disenar la deteccion de not_game
sin NLI (matching nucleo vs generico).

Para cada caso del dataset muestra que palabras de la KEYWORD del juego buscado
aparecen en el titulo, agrupado por categoria (not_game vs juego real). Objetivo:
ver si los not_game (ropa/plantas) coinciden solo por una palabra GENERICA
(burgundy, inis, mare...) mientras los juegos coinciden por la palabra NUCLEO o
por varias.

Solo lectura del dataset. No toca produccion.

    py analyze_matching.py
"""

import os
import re
import sys
import json
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402  (para _normalize y _STOPWORDS)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATASET = os.path.join(BASE, "nli_dataset", "cases.jsonl")

# alert_name (como aparece en el dataset) -> keyword real (de configs/dario.yaml).
ALERT_KEYWORDS = {
    "dario/Catan": "catan",
    "dario/Castilllos de Burgundy": "castillos burgundy borgoña",
    "dario/Mare Nostrum": "mare nostrum",
    "dario/Carcassonne: Posadas y Catedrales": "carcassonne posadas catedrales",
    "dario/Las Estaciones de Inis": "estaciones inis",
    "dario/Frostpunk (hasta 90€)": "frostpunk",
}

GAME_CATS = {"base", "expansion", "components", "lote"}


def kw_words(keyword):
    return [w for w in re.findall(r"\w+", classifier._normalize(keyword))
            if w not in classifier._STOPWORDS]


def matched_words(keyword, title):
    tw = set(re.findall(r"\w+", classifier._normalize(title)))
    return [w for w in kw_words(keyword) if w in tw]


def main():
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Por alerta: contar, para not_game vs juego, que palabra coincide y cuantas.
    for alert in sorted(ALERT_KEYWORDS):
        kw = ALERT_KEYWORDS[alert]
        sub = [r for r in rows if r.get("alert_name") == alert]
        if not sub:
            continue
        print(f"\n=== {alert}  (keyword: '{kw}' -> nucleo {kw_words(kw)}) ===")
        for label, cats in (("NOT_GAME", {"not_game"}), ("JUEGO", GAME_CATS)):
            grp = [r for r in sub if (r.get("category") or "") in cats]
            if not grp:
                continue
            by_word = Counter()
            by_count = Counter()
            for r in grp:
                m = matched_words(kw, r.get("title") or "")
                by_count[len(m)] += 1
                by_word["+".join(sorted(m)) or "(ninguna)"] += 1
            print(f"  {label} ({len(grp)} casos):")
            print(f"    nº palabras que coinciden: "
                  + ", ".join(f"{k}->{v}" for k, v in sorted(by_count.items())))
            top = ", ".join(f"{w}:{c}" for w, c in by_word.most_common(6))
            print(f"    combinaciones top: {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
