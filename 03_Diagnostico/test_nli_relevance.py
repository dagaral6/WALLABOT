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

# Guardamos la _nli_hf_relevance REAL antes de monkeypatchearla, para restaurarla
# antes del smoke opcional (que sí quiere llamar al servicio de verdad).
_REAL_NLI = classifier._nli_hf_relevance

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

# Keywords MULTI-PALABRA ('rising sun'): presente si la alerta busca esas palabras.
check("is_risky_keyword('rising sun')",
      classifier.is_risky_keyword("rising sun") is True)
check("is_risky_keyword('Rising Sun') (mayus)",
      classifier.is_risky_keyword("Rising Sun") is True)
check("detect_risky_keywords(rising sun)",
      classifier.detect_risky_keywords({"keywords": "rising sun"}) == ["rising sun"])
check("detect_risky_keywords(rising sun cmon) -> [rising sun]",
      classifier.detect_risky_keywords(
          {"keywords": "rising sun cmon"}) == ["rising sun"])
check("detect_risky_keywords(sun) (solo una palabra de la frase) -> []",
      classifier.detect_risky_keywords({"keywords": "sun"}) == [])

# _phrase_in_order: orden CONTIGUO de la frase en el título.
check("_phrase_in_order('Rising Sun Monster Pack', 'rising sun')",
      classifier._phrase_in_order("Rising Sun Monster Pack", "rising sun") is True)
check("_phrase_in_order('Setting Sun Rising', 'rising sun') -> False",
      classifier._phrase_in_order("Setting Sun Rising", "rising sun") is False)
check("_phrase_in_order('cities of doom', 'cities') (una palabra) -> True",
      classifier._phrase_in_order("cities of doom", "cities") is True)


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


# --- 2b) Fallback determinista: regla de ORDEN para frases multi-palabra ----
# (NLI sigue forzado a no disponible desde _force_nli_unavailable()). Sin
# confusores a mano para "rising sun": decide la regla de orden contiguo.
ORDEN = [
    # frase en orden contiguo -> relevante por relevancia (la categoria, aparte)
    ("Rising Sun Monster Pack", "miniaturas del juego", "rising sun", "relevant"),
    ("Rising Sun CMON completo", "juego base", "rising sun", "relevant"),
    # palabras sueltas / orden invertido -> otro juego
    ("Setting Sun Rising", "wargame", "rising sun", "not_relevant"),
    ("Paper Wars #80 - Setting Sun Rising", "revista", "rising sun", "not_relevant"),
]
for title, desc, kw, expected in ORDEN:
    classifier._RELEVANCE_CACHE.clear()
    got = classifier.nli_relevance_gate(title, desc, kw)
    check(f"orden gate({title!r}) -> {expected}", got == expected, f"obtenido={got}")


# --- 2c) B2.0: el NLI de relevancia puntua SOLO el titulo (desc ignorada) ----
_captured = {}
def _capture_text(text, game_label, other_label, timeout=20):
    _captured["text"] = text
    return (0.9, 0.1)            # score_game > score_other -> relevant
classifier._nli_hf_relevance = _capture_text
classifier._RELEVANCE_CACHE.clear()
classifier.nli_relevance_gate("Cities Devir", "esta desc menciona lost cities", "cities")
check("B2.0: el NLI puntua solo el titulo (sin descripcion)",
      _captured.get("text") == "Cities Devir", f"text={_captured.get('text')!r}")


# --- 2d) NLI vivo (mockeado): caza confusores SIN diccionario a mano ---------
# Los 4 titulos reales de "cities" de la revision NO estan en la lista de
# confusores y el caso de dardos "rising sun" si esta en orden contiguo: el
# fallback determinista los dejaria pasar (ante la duda). Con el NLI vivo
# disponible (aqui mockeado para que diga "otro juego"), se marcan not_relevant.
def _nli_says_other(text, game_label, other_label, timeout=20):
    return (0.1, 0.9)           # score_other > score_game -> not_relevant
classifier._nli_hf_relevance = _nli_says_other

NLI_OTHER = [
    # cities (revision jun 2026): confusores que NO estan en la lista a mano
    ("Dicemaster Cities of Doom", "cities"),
    ("Ticket to Ride: Large Cities", "cities"),
    ("7 Wonders + Expansiones Cities", "cities"),
    ("Galen y Doralia cities sigmar", "cities"),
    # rising sun: dardos con la frase en orden contiguo (lo resuelve el NLI vivo)
    ("Dardos Target Rising Sun G8", "rising sun"),
]
for title, kw in NLI_OTHER:
    classifier._RELEVANCE_CACHE.clear()
    got = classifier.nli_relevance_gate(title, "", kw)
    check(f"NLI vivo gate({title!r}) -> not_relevant", got == "not_relevant",
          f"obtenido={got}")

# Positivo con NLI vivo: el juego buscado de verdad -> relevant.
def _nli_says_game(text, game_label, other_label, timeout=20):
    return (0.9, 0.1)
classifier._nli_hf_relevance = _nli_says_game
classifier._RELEVANCE_CACHE.clear()
check("NLI vivo gate('Rising Sun CMON') -> relevant",
      classifier.nli_relevance_gate("Rising Sun CMON", "", "rising sun") == "relevant")

# Restauramos: el resto del fichero (regresion y smoke) usa la NLI real / fallback.
classifier._nli_hf_relevance = _REAL_NLI
classifier._RELEVANCE_CACHE.clear()


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
