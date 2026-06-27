"""
test_category_nli.py
--------------------
Tests del NLI de categoría (Fase 4 / Entrega D): las REGLAS dan un resultado
provisional y el NLI lo VALIDA (puede mover 'base' -> 'components'/'expansion').

Cubre SIN RED (NLI mockeado vía classifier._nli_hf_zeroshot):
  - con category_nli.enabled=false -> comportamiento IDÉNTICO a reglas.
  - con true y NLI 'components'/'expansion' -> base pasa a esa categoría
    (casos reales: insertos, monster pack, cajas vacías).
  - conservador: NLI 'base' o sin margen -> se mantienen las reglas.
  - fallback: NLI no disponible -> reglas.
  - gateo por coste: NO se llama al NLI sin descripción, sin vocab de accesorio/
    expansión, o cuando las reglas no dijeron 'base' (components/lote ya decididos).

Patrón de 03_Diagnostico/: standalone, [OK]/[FAIL], sys.exit (no usa pytest).
    py 03_Diagnostico/test_category_nli.py
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
_REAL_ZS = classifier._nli_hf_zeroshot
calls = {"n": 0}


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def _mock_cat(cat, hi=0.9, lo=0.05):
    """_nli_hf_zeroshot mockeado: hace ganar la etiqueta de `cat`. Cuenta llamadas."""
    labels = classifier._CATEGORY_NLI_LABELS

    def _fn(text, candidate_labels, timeout=20):
        calls["n"] += 1
        return {labels[k]: (hi if k == cat else lo) for k in labels}
    classifier._nli_hf_zeroshot = _fn
    classifier._CATEGORY_NLI_CACHE.clear()


def _mock_flat():
    def _fn(text, candidate_labels, timeout=20):
        calls["n"] += 1
        return {lab: 0.33 for lab in candidate_labels}   # empate -> sin margen
    classifier._nli_hf_zeroshot = _fn
    classifier._CATEGORY_NLI_CACHE.clear()


def _mock_unavailable():
    def _fn(text, candidate_labels, timeout=20):
        calls["n"] += 1
        raise RuntimeError("test: NLI no disponible")
    classifier._nli_hf_zeroshot = _fn
    classifier._CATEGORY_NLI_CACHE.clear()


# (title, description) donde las REGLAS dan 'base' pero la DESCRIPCIÓN delata
# componentes/expansión sin frases que las reglas ya cacen.
CASES_COMP = [
    ("Frostpunk",
     "Vendo el inserto de metacrilato que hice para organizar las fichas y los recursos."),
    ("Rising Sun",
     "Solo el Monster Pack, miniaturas y fichas sueltas, no es el juego completo."),
    ("Catan",
     "Vendo solo las cajas y los separadores, sin componentes dentro."),
]
CASE_EXP = ("Catan",
            "Es la expansion Navegantes, necesitas el juego base para jugar.")


# --- 0) Sanity: por REGLAS estos casos son 'base' --------------------------
classifier._CATEGORY_NLI_ENABLED = False
for t, d in CASES_COMP + [CASE_EXP]:
    check(f"reglas: {t!r} -> base", classifier.classify_category(t, d) == "base")


# --- 1) enabled=false: idéntico a reglas, sin llamar al NLI -----------------
_mock_cat("components"); calls["n"] = 0
classifier._CATEGORY_NLI_ENABLED = False
for t, d in CASES_COMP:
    check(f"NLI off: {t!r} sigue base", classifier.classify_category(t, d) == "base")
check("NLI off: 0 llamadas al NLI", calls["n"] == 0, f"calls={calls['n']}")


# --- 2) enabled=true + NLI 'components'/'expansion': base -> esa categoría --
classifier._CATEGORY_NLI_ENABLED = True
classifier._CATEGORY_NLI_MARGIN = 0.15
for t, d in CASES_COMP:
    _mock_cat("components")
    got = classifier.classify_category(t, d)
    check(f"NLI components: {t!r} base->components", got == "components", f"got={got}")

_mock_cat("expansion")
check("NLI expansion: Catan+desc base->expansion",
      classifier.classify_category(*CASE_EXP) == "expansion")


# --- 3) Conservador: NLI 'base' o sin margen -> reglas (base) ---------------
_mock_cat("base")
check("NLI dice base -> se queda base",
      classifier.classify_category(*CASES_COMP[0]) == "base")
_mock_flat()
check("NLI sin margen -> base (reglas)",
      classifier.classify_category(*CASES_COMP[0]) == "base")


# --- 4) Fallback: NLI no disponible -> reglas (base) ------------------------
_mock_unavailable()
check("NLI no disponible -> base (reglas)",
      classifier.classify_category(*CASES_COMP[0]) == "base")


# --- 5) Gateo por coste: NO se llama al NLI cuando no aporta ----------------
_mock_cat("components"); calls["n"] = 0
check("sin descripción -> base y 0 llamadas",
      classifier.classify_category("Frostpunk", "") == "base" and calls["n"] == 0,
      f"calls={calls['n']}")

_mock_cat("components"); calls["n"] = 0
check("desc sin vocab accesorio/expansión -> base y 0 llamadas",
      classifier.classify_category(
          "Frostpunk", "Juego en perfecto estado, poco usado, completo.") == "base"
      and calls["n"] == 0, f"calls={calls['n']}")

_mock_cat("components"); calls["n"] = 0
got = classifier.classify_category("Inserto Frostpunk", "solo el inserto 3D")
check("reglas ya 'components' (título) -> NLI no se llama",
      got == "components" and calls["n"] == 0, f"got={got} calls={calls['n']}")

_mock_cat("components"); calls["n"] = 0
got = classifier.classify_category(
    "Lote de juegos de mesa", "Vendo juntos Catan, Risk y Azul, se venden en lote.")
check("reglas 'lote' -> NLI no se llama (no toca lotes)",
      got == "lote" and calls["n"] == 0, f"got={got} calls={calls['n']}")


# --- 6) configure_category_nli_from_settings -------------------------------
classifier.configure_category_nli_from_settings({"category_nli": {"enabled": False}})
check("settings desactiva el NLI de categoría",
      classifier.category_nli_enabled() is False)
classifier.configure_category_nli_from_settings(
    {"category_nli": {"enabled": True, "margin": 0.3}})
check("settings activa y ajusta margen",
      classifier.category_nli_enabled() is True
      and abs(classifier._CATEGORY_NLI_MARGIN - 0.3) < 1e-9)


# --- 7) Cortocircuito del NLI: un fallo corta la red el resto de la pasada ---
classifier._nli_hf_zeroshot = _REAL_ZS       # motor real, con requests.post mockeado
classifier._NLI_UNAVAILABLE = False
classifier._CATEGORY_NLI_CACHE.clear()
classifier._CATEGORY_NLI_ENABLED = True
post_calls = {"n": 0}
_real_post = classifier.requests.post


def _boom_post(*a, **k):
    post_calls["n"] += 1
    raise classifier.requests.RequestException("DNS fail (test)")


classifier.requests.post = _boom_post
r1 = classifier.classify_category(*CASES_COMP[0])     # 1ª: intenta red, falla, activa breaker
r2 = classifier.classify_category(*CASES_COMP[1])     # 2ª: cortocircuito, sin red
classifier.requests.post = _real_post
check("breaker NLI: 1ª toca la red, 2ª no; ambas caen a reglas (base)",
      post_calls["n"] == 1 and classifier._NLI_UNAVAILABLE is True
      and r1 == "base" and r2 == "base",
      f"posts={post_calls['n']} r1={r1} r2={r2}")


# restaura
classifier._nli_hf_zeroshot = _REAL_ZS
classifier._CATEGORY_NLI_ENABLED = False
classifier._CATEGORY_NLI_CACHE.clear()
classifier._NLI_UNAVAILABLE = False


print()
if fails:
    print(f"RESULTADO: {len(fails)} FALLOS -> {fails}")
    sys.exit(1)
print("RESULTADO: TODO OK")
sys.exit(0)
