"""
test_weak_heuristic.py
----------------------
Valida la heuristica AUTOMATICA para decidir palabras 'debiles' (genericas, no
bastan solas) vs 'fuertes' (nombre propio del juego), usando wordfreq.

Idea: una palabra comun del idioma (zipf alto) es DEBIL; un nombre propio raro
(zipf bajo) es FUERTE. Asi, al anadir un juego nuevo, no hay que declarar nada:
si se llama con una palabra comun (Risk, Cities) se trata como debil
automaticamente; si es un nombre propio (Catan, Carcassonne) como fuerte.

zipf_frequency: 0 = no existe, ~3 = poco comun, ~5-7 = muy comun.

Requiere:  py -m pip install wordfreq
Uso:       py 03_Diagnostico/test_weak_heuristic.py
"""

import sys

try:
    from wordfreq import zipf_frequency
except ImportError:
    print("[FALTA] Instala wordfreq:  py -m pip install wordfreq")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Umbral: zipf >= THRESHOLD -> palabra comun -> DEBIL.
THRESHOLD = 3.5

# Palabras de las keywords reales, clasificadas a mano segun lo esperado.
EXPECTED_STRONG = ["catan", "carcassonne", "frostpunk", "inis", "nostrum"]
EXPECTED_WEAK = ["mare", "estaciones", "castillos", "posadas", "catedrales",
                 "cities", "risk", "burgundy", "borgona", "borgoña"]
# Otros juegos populares (riesgo futuro: nombres que son palabras comunes EN).
OTHER = ["wingspan", "scythe", "azul", "splendor", "root", "dune", "brass"]


def kind(word):
    z = max(zipf_frequency(word, "es"), zipf_frequency(word, "en"))
    return ("DEBIL" if z >= THRESHOLD else "fuerte"), z


def show(title, words):
    print(f"\n{title}")
    for w in words:
        k, z = kind(w)
        print(f"  {w:14} zipf={z:.1f} -> {k}")


def main():
    print(f"Umbral DEBIL: zipf >= {THRESHOLD}")
    show("Esperado FUERTE (nombre propio del juego):", EXPECTED_STRONG)
    show("Esperado DEBIL (palabra comun/ruido):", EXPECTED_WEAK)
    show("Otros juegos (riesgo: nombre = palabra comun):", OTHER)

    ok = all(kind(w)[0] == "fuerte" for w in EXPECTED_STRONG) and \
        all(kind(w)[0] == "DEBIL" for w in EXPECTED_WEAK if w != "borgoña")
    print("\nRESULTADO:",
          "heuristica separa bien las keywords actuales" if ok else
          "revisar: algun caso no encaja (ver arriba)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
