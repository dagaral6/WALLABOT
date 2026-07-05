"""
diag_carcassone_nli.py
----------------------
Valida el gate de relevancia NLI para la keyword 'carcassone' ANTES de confiar en
él. Carcassonne es un juego popular con muchas ediciones legítimas (base, 2.0, Big
Box, 20 aniversario...): marcarlo como keyword ambigua (`_RISKY_KEYWORDS`) hace que
el NLI decida sobre cada anuncio, y hay que confirmar que NO rechaza esas ediciones
legítimas (falsos negativos = anuncios buenos perdidos).

Qué hace: pasa por `classifier.nli_relevance_gate(title, "", "carcassone")` todos los
anuncios KEEP de las alertas de Carcassonne en `alerts.db` (solo lectura) y lista los
que el gate marcaría 'not_relevant'. Revisa esa lista: si hay Carcassonnes legítimos,
NO actives el gate (revierte la entrada 'carcassone' de `_RISKY_KEYWORDS`).

Requiere HF_API_TOKEN (el gate real usa el NLI vivo). OJO: una llamada por título
único → ~decenas de llamadas facturables. Sin token, el gate cae al fallback
determinista (sin confusores → todo 'relevant') y este diagnóstico no aporta.

Uso:
    (PowerShell)  $env:HF_API_TOKEN="hf_xxx"; py 03_Diagnostico/diag_carcassone_nli.py
"""
import os
import sys
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import classifier  # noqa: E402

DB = os.path.normpath(os.path.join(CORE, "alerts.db"))
KEYWORD = "carcassone"           # la keyword risky (grafía de la alerta)
TARGET_CASE = "niebla"           # caso que DEBERÍA salir not_relevant


def main():
    if not os.getenv("HF_API_TOKEN"):
        print("Sin HF_API_TOKEN: el gate caería al fallback (todo 'relevant') y "
              "este diagnóstico no valida nada. Exporta el token y reintenta.")
        return 1
    if not os.path.exists(DB):
        print(f"No encuentro la BD: {DB}")
        return 1

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT DISTINCT title, description FROM seen_items "
        "WHERE decision='keep' AND lower(alert_name) LIKE '%carcass%'").fetchall()
    con.close()

    if not rows:
        print("No hay KEEP de alertas Carcassonne en la BD (nada que validar).")
        return 0

    relevant, not_relevant = [], []
    for r in rows:
        title = r["title"] or ""
        verdict = classifier.nli_relevance_gate(title, "", KEYWORD)
        (not_relevant if verdict == "not_relevant" else relevant).append(title)

    print(f"KEEP de Carcassonne evaluados: {len(rows)}")
    print(f"  relevant (se mantienen):     {len(relevant)}")
    print(f"  not_relevant (se DESCARTAN): {len(not_relevant)}")
    print("\n--- Marcados NOT_RELEVANT (revísalos: ¿alguno es Carcassonne legítimo?) ---")
    for t in not_relevant:
        flag = "  <-- caso objetivo (correcto)" if TARGET_CASE in t.lower() else ""
        print(f"  · {t}{flag}")
    if not not_relevant:
        print("  (ninguno)")

    print("\nCRITERIO: si en la lista NOT_RELEVANT solo aparecen anuncios que de "
          "verdad NO son el Carcassonne base (p.ej. 'Niebla sobre Carcassonne', "
          "productos ajenos), el gate es seguro. Si aparece una edición legítima "
          "del base, revierte la entrada 'carcassone' de _RISKY_KEYWORDS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
