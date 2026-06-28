"""
test_gamedb.py
--------------
Tests del modulo 01_Core/gamedb.py (base de datos OFFLINE de juegos de mesa que
sustituye a bgg.py). Patron de 03_Diagnostico/: standalone, [OK]/[FAIL],
sys.exit (no usa pytest).

    py 03_Diagnostico/test_gamedb.py

Requiere que 01_Core/gamedb.json exista (generarlo con build_gamedb.py). Si no
existe, gamedb degrada a vacio y categorize() devuelve None: los tests que
dependen de datos reales se marcan como omitidos, no como fallo.
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import gamedb            # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# --- 1) Flag enabled / configure_from_settings -----------------------------
gamedb.configure_from_settings({"gamedb": {"enabled": True}})
check("configure(gamedb.enabled:true)", gamedb.bgg_enabled() is True)
gamedb.configure_from_settings({"gamedb": {"enabled": False}})
check("configure(gamedb.enabled:false)", gamedb.bgg_enabled() is False)
# compatibilidad con la seccion 'bgg'
gamedb.configure_from_settings({"bgg": {"enabled": True}})
check("configure(bgg.enabled:true) compat", gamedb.bgg_enabled() is True)

# Desactivado -> categorize SIEMPRE None (no consulta la BD)
gamedb.configure_from_settings({"bgg": {"enabled": False}})
check("disabled -> categorize None", gamedb.categorize("Catan", "") is None)

# --- 2) Normalizacion -------------------------------------------------------
check("_norm tildes/mayus/simbolos",
      gamedb._norm("  Catán!!  ") == "catan")
check("_norm colapsa espacios",
      gamedb._norm("A   B") == "a b")

# A partir de aqui necesitamos la BD real y el flag activo.
gamedb.configure_from_settings({"gamedb": {"enabled": True}})
db = gamedb._get_db()
HAS_DB = bool(db.get("names"))

if not HAS_DB:
    print("\n[AVISO] gamedb.json no encontrado o vacio; "
          "omitidos los tests con datos reales. Ejecuta build_gamedb.py.")
else:
    # --- 3) Base puro -> None ------------------------------------------------
    check("base 'Catan' -> None", gamedb.categorize("Catan") is None)
    check("base con ruido -> None",
          gamedb.categorize("Scythe juego de mesa como nuevo") is None)

    # --- 4) Expansion por titulo (ingles y traduccion) ----------------------
    check("exp titulo ingles -> expansion",
          gamedb.categorize("Scythe Invaders from Afar") == "expansion")
    check("exp titulo traduccion -> expansion",
          gamedb.categorize("Carcassonne Posadas y Catedrales") == "expansion")

    # --- 5) Expansion nombrada en la DESCRIPCION de un base -----------------
    check("base + exp en descripcion -> expansion",
          gamedb.categorize("Catan",
                            "incluye la expansion Ciudades y Caballeros") == "expansion")

    # --- 6) Compatibilidad: NO debe marcar ----------------------------------
    check("base + 'compatible con ...' -> None",
          gamedb.categorize("Catan",
                            "compatible con Ciudades y Caballeros") is None)

    # --- 7) Inexistente -> None ---------------------------------------------
    check("titulo no reconocido -> None",
          gamedb.categorize("Cosa Inexistente XYZ", "algo") is None)

    # --- 8) Nunca lanza -----------------------------------------------------
    try:
        gamedb.categorize("", "")
        gamedb.categorize(None, None)
        ok = True
    except Exception as e:
        ok = False
        print(f"   excepcion inesperada: {e}")
    check("categorize('' / None) no lanza", ok)


print()
if fails:
    print(f"RESULTADO: {len(fails)} FALLOS -> {fails}")
    sys.exit(1)
print("RESULTADO: TODO OK")
