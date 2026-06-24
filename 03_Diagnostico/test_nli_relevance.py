"""
test_nli_relevance.py
---------------------
Regresion del GATE DE RELEVANCIA para keywords ambiguas (Cities, Risk...).
Ver 01_Core/classifier.py (_RISKY_KEYWORDS, nli_relevance_gate) y la integracion
en 01_Core/main.py:evaluate().

Patron de 03_Diagnostico/: standalone, [OK]/[FAIL], sys.exit (no usa pytest).

    python test_nli_relevance.py
    # opcional (smoke NLI vivo, no afecta al resultado):
    #   set HF_API_TOKEN=hf_...   (Windows)

Cubre SIN RED (deterministico, reproducible):
  - is_risky_keyword / detect_risky_keywords sobre alertas reales.
  - _match_exclusion y la rama de fallback de nli_relevance_gate.
  - Regresion contra nli_dataset/cases.jsonl: ninguna alerta real es riesgosa,
    asi que el gate es INERTE -> 0 rechazos nuevos (no rompe lo que ya funciona).
El smoke NLI vivo (HF) es opcional e informativo: no cuenta para el exit code.
"""

import json
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

CASES_JSONL = os.path.join(BASE, "nli_dataset", "cases.jsonl")
DARIO_YAML = os.path.join(CORE, "configs", "dario.yaml")

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def _force_nli_unavailable():
    """Monkeypatch: hace que el NLI 'no responda' para probar el fallback
    deterministico sin depender de la red ni de HF."""
    def _boom(*a, **k):
        raise RuntimeError("test: NLI deshabilitado")
    classifier._nli_hf_relevance = _boom
    classifier._RELEVANCE_CACHE.clear()


# --- 1) Deteccion de keywords riesgosas ------------------------------------
check("is_risky_keyword('cities')", classifier.is_risky_keyword("cities") is True)
check("is_risky_keyword('Cities') (mayus/acentos)",
      classifier.is_risky_keyword("Cities") is True)
check("is_risky_keyword('catan') -> False",
      classifier.is_risky_keyword("catan") is False)

check("detect_risky_keywords(cities)",
      classifier.detect_risky_keywords({"keywords": "cities"}) == ["cities"])
check("detect_risky_keywords(castillos burgundy borgoña) -> []",
      classifier.detect_risky_keywords(
          {"keywords": "castillos burgundy borgoña"}) == [])
check("detect_risky_keywords(catan) -> []",
      classifier.detect_risky_keywords({"keywords": "catan"}) == [])


# --- 2) Fallback deterministico (NLI no disponible) ------------------------
_force_nli_unavailable()
conf = classifier._RISKY_KEYWORDS["cities"]["confusers"]
check("_match_exclusion('Lost Cities precintado')",
      classifier._match_exclusion("Lost Cities precintado", conf) is True)
check("_match_exclusion('Underwater Cities')",
      classifier._match_exclusion("Underwater Cities", conf) is True)
check("_match_exclusion('Cities (Devir) negociacion') -> False",
      classifier._match_exclusion("Cities (Devir) negociacion", conf) is False)

# nli_relevance_gate cayendo al deterministico (confusor -> not_relevant)
SINTETICOS = [
    ("Lost Cities de Knizia", "Juego de cartas, como nuevo", "cities", "not_relevant"),
    ("Underwater Cities precintado", "estrategia", "cities", "not_relevant"),
    ("Between Two Cities", "juego de losetas", "cities", "not_relevant"),
    ("Cities of Sigmar Warhammer", "miniaturas", "cities", "not_relevant"),
    ("Cities, juego de Devir", "negociacion de recursos, completo", "cities", "relevant"),
    ("Cities precintado nuevo", "juego de mesa", "cities", "relevant"),
]
for title, desc, kw, expected in SINTETICOS:
    classifier._RELEVANCE_CACHE.clear()
    got = classifier.nli_relevance_gate(title, desc, kw)
    check(f"gate({title!r}) -> {expected}", got == expected, f"obtenido={got}")

# Keyword NO riesgosa: siempre relevante (el gate no aplica)
classifier._RELEVANCE_CACHE.clear()
check("gate(Catan base, 'catan') -> relevant",
      classifier.nli_relevance_gate("Catan base completo", "", "catan") == "relevant")


# --- 3) Regresion contra cases.jsonl: gate INERTE en alertas reales --------
def _load_dario_keywords():
    try:
        import yaml
    except ImportError:
        return None
    with open(DARIO_YAML, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {a["name"]: a.get("keywords", "")
            for a in (data.get("alerts") or []) if a.get("name")}


name_to_kw = _load_dario_keywords()
if name_to_kw is None:
    print("[SKIP] regresion cases.jsonl: PyYAML no disponible")
elif not os.path.exists(CASES_JSONL):
    print(f"[SKIP] regresion cases.jsonl: no existe {CASES_JSONL}")
else:
    rows = []
    with open(CASES_JSONL, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    touched, resolved, names_seen = 0, 0, set()
    for r in rows:
        name = (r.get("alert_name") or "").split("/", 1)[-1]
        names_seen.add(name)
        kw = name_to_kw.get(name)
        if kw is None:
            continue                      # alerta no presente en dario.yaml actual
        resolved += 1
        if classifier.detect_risky_keywords({"keywords": kw}):
            touched += 1

    check(f"regresion cases.jsonl: gate inerte ({len(rows)} filas, "
          f"{resolved} resueltas, {len(names_seen)} alertas)",
          touched == 0, f"tocadas={touched}")

    # Sanity: la alerta 'Cities' de dario SI seria riesgosa (aunque no este en el
    # dataset). Confirma que el gate no es inerte por un bug, sino por los datos.
    cities_kw = name_to_kw.get("Cities")
    if cities_kw is not None:
        check("sanity: alerta 'Cities' de dario es riesgosa",
              bool(classifier.detect_risky_keywords({"keywords": cities_kw})))


# --- 4) Smoke NLI vivo (opcional, NO afecta al exit code) ------------------
if os.getenv("HF_API_TOKEN"):
    print("\n[smoke NLI vivo] HF_API_TOKEN presente; probando _nli_hf_relevance...")
    try:
        game = classifier._RISKY_KEYWORDS["cities"]["game"]
        other = "otro juego diferente que contiene la palabra «cities»"
        s_g, s_o = classifier._nli_hf_relevance(
            "Lost Cities de Knizia, juego de cartas", game, other)
        print(f"  Lost Cities -> score_game={s_g:.2f} score_otro={s_o:.2f} "
              f"(se espera otro > game)")
        s_g2, s_o2 = classifier._nli_hf_relevance(
            "Cities, juego de negociacion de Devir, completo", game, other)
        print(f"  Cities Devir -> score_game={s_g2:.2f} score_otro={s_o2:.2f} "
              f"(se espera game > otro)")
    except RuntimeError as e:
        print(f"  [SVC] NLI no disponible (no descarta el enfoque): {e}")
else:
    print("\n[smoke NLI vivo] omitido (sin HF_API_TOKEN). El gate usa el "
          "fallback deterministico.")


print()
if fails:
    print(f"RESULTADO: {len(fails)} FALLOS -> {fails}")
    sys.exit(1)
print("RESULTADO: TODO OK")
sys.exit(0)
