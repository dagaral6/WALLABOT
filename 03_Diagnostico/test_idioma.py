"""
test_idioma.py
--------------
Tests del filtro de idioma (classifier.looks_foreign_language) tras la Fase 2:
  - vocabulario italiano ampliado (caza la fuga real "Raccoglitori Carte ...").
  - señal SECUNDARIA langdetect (conservadora, umbral alto), mockeada para ser
    determinista.
  - el override _PLAYABLE_OK manda sobre AMBAS señales.
  - degradación elegante (sin langdetect) y configuración por settings.

Patrón de 03_Diagnostico/: standalone, [OK]/[FAIL], sys.exit (no usa pytest).

    py 03_Diagnostico/test_idioma.py
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

import classifier  # noqa: E402

fails = []
_REAL_DETECT = classifier._detect_langs   # por si está instalado de verdad


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


class _Lang:
    """Imita un resultado de langdetect.detect_langs (objeto con .lang y .prob)."""
    def __init__(self, lang, prob):
        self.lang, self.prob = lang, prob


def _mock_detect(lang, prob):
    classifier._detect_langs = lambda text: [_Lang(lang, prob)]


# --- 1) Vocabulario (langdetect DESACTIVADO para aislar la señal de vocab) ---
classifier._detect_langs = None
check("vocab amplia caza 'Raccoglitori Carte Risorse - I Coloni Di Catan'",
      classifier.looks_foreign_language(
          "Raccoglitori Carte Risorse - I Coloni Di Catan", "") is True)
check("vocab existente sigue: 'gioco da tavolo ottime condizioni'",
      classifier.looks_foreign_language(
          "Catan", "Bellissimo gioco da tavolo, ottime condizioni") is True)
check("español permitido -> NO foreign",
      classifier.looks_foreign_language(
          "Catan juego de mesa", "Completo y en perfecto estado, en español") is False)
check("override: italiano pero 'reglas en español' -> NO foreign",
      classifier.looks_foreign_language(
          "Gioco da tavolo Catan", "Caja en italiano pero reglas en español") is False)
check("sin langdetect, título corto español -> NO foreign (degradación)",
      classifier.looks_foreign_language("Para Mario Frostpunk", "") is False)


# --- 2) Señal langdetect (mockeada): SOLO descripción, longitud mínima ------
classifier._LANGDETECT_ENABLED = True
classifier._LANGDETECT_MIN_PROB = 0.95
classifier._LANGDETECT_MIN_DESC = 40
# Título neutro (no vocab) y descripción larga neutra (sin vocab ni playable-ok):
# así el resultado depende SOLO de la señal langdetect mockeada.
TIT = "Articulo a la venta"
DESC = "texto de relleno suficientemente largo para superar el minimo requerido"

_mock_detect("it", 0.99)
check("langdetect it 0.99 (descripción larga) -> foreign",
      classifier.looks_foreign_language(TIT, DESC) is True)

_mock_detect("it", 0.86)
check("langdetect it 0.86 (< umbral) -> NO foreign",
      classifier.looks_foreign_language(TIT, DESC) is False)

_mock_detect("pt", 0.99)
check("langdetect pt 0.99 -> foreign",
      classifier.looks_foreign_language(TIT, DESC) is True)

_mock_detect("es", 0.99)
check("langdetect es 0.99 -> NO foreign (idioma permitido)",
      classifier.looks_foreign_language(TIT, DESC) is False)

_mock_detect("en", 0.99)
check("langdetect en 0.99 -> NO foreign (idioma permitido)",
      classifier.looks_foreign_language(TIT, DESC) is False)

# El TÍTULO no alimenta a langdetect: un título extranjero con descripción corta
# NO se marca por langdetect (evita falsos positivos tipo 'Camel Up Carcassonne').
_mock_detect("it", 0.99)
check("título ruidoso + desc corta -> langdetect NO aplica",
      classifier.looks_foreign_language("Camel Up Carcassonne", "vendo") is False)

# Override manda sobre langdetect
_mock_detect("it", 0.99)
check("override gana a langdetect (it 0.99 + 'reglas en español')",
      classifier.looks_foreign_language(
          TIT, DESC + ", incluye reglas en español") is False)

# Descripción demasiado corta (< MIN_DESC) -> langdetect no se usa
_mock_detect("it", 0.99)
check("descripción corta (<40) -> langdetect no aplica -> NO foreign",
      classifier.looks_foreign_language(TIT, "vendo barato") is False)

# Desactivado por flag
classifier._LANGDETECT_ENABLED = False
_mock_detect("it", 0.99)
check("langdetect desactivado por flag -> NO foreign (solo vocab)",
      classifier.looks_foreign_language(TIT, DESC) is False)
classifier._LANGDETECT_ENABLED = True


# --- 3) configure_language_from_settings ------------------------------------
classifier.configure_language_from_settings({"language": {"langdetect_min_prob": 0.5}})
check("settings ajusta el umbral a 0.5", abs(classifier._LANGDETECT_MIN_PROB - 0.5) < 1e-9)
classifier.configure_language_from_settings({"language": {"langdetect_enabled": False}})
check("settings desactiva langdetect", classifier._LANGDETECT_ENABLED is False)
# restaura
classifier._LANGDETECT_ENABLED = True
classifier._LANGDETECT_MIN_PROB = 0.95
classifier._detect_langs = _REAL_DETECT


print()
if fails:
    print(f"RESULTADO: {len(fails)} FALLOS -> {fails}")
    sys.exit(1)
print("RESULTADO: TODO OK")
sys.exit(0)
