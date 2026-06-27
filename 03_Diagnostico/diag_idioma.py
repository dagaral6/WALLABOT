"""
diag_idioma.py
--------------
DIAGNÓSTICO (no toca producción): ¿cuántos anuncios NOTIFICADOS (decision='keep')
están en realidad en un idioma NO permitido (it/fr/de/pt/nl...) y se colaron pese
a classifier.looks_foreign_language?

Como detect_language usa el MISMO gate que el filtro, esos anuncios quedan
guardados como 'es' en la BD: para encontrarlos hay que volver a detectar el
idioma con un detector REAL (langdetect) sobre título + descripción.

Para cada keep:
  - idioma detectado por langdetect (con probabilidad),
  - veredicto del gate ACTUAL (looks_foreign_language: True = lo descartaría),
  - si saltó el override _PLAYABLE_OK (posible causa de que se colara),
  - si había ALGUNA señal foreign en el texto (_FOREIGN_LANG/_DECL).

Uso:
    py 03_Diagnostico/diag_idioma.py
    py 03_Diagnostico/diag_idioma.py --list      # lista todos los sospechosos
Requiere: pip install langdetect
"""

import os
import sys
import sqlite3

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402

try:
    from langdetect import detect_langs, DetectorFactory
    from langdetect.lang_detect_exception import LangDetectException
    DetectorFactory.seed = 0           # determinista
except ImportError:
    print("Falta langdetect. Instala:  py -m pip install langdetect")
    sys.exit(2)

ALLOWED = {"es", "ca", "en"}           # idiomas que SÍ interesan
DB_PATH = os.path.join(CORE, "alerts.db")
PROB_MIN = 0.80                        # confianza mínima para marcar sospechoso
SHOW = "--list" in sys.argv


def detect(text):
    """(lang, prob) del idioma más probable, o (None, 0.0) si no se puede."""
    try:
        langs = detect_langs((text or "")[:600])
    except LangDetectException:
        return None, 0.0
    if not langs:
        return None, 0.0
    top = langs[0]
    return top.lang, top.prob


def main():
    if not os.path.exists(DB_PATH):
        print("No existe", DB_PATH)
        return 1
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT alert_name, title, description, language FROM seen_items "
        "WHERE decision='keep'").fetchall()
    con.close()

    by_lang = {}
    suspects = []
    for r in rows:
        title = r["title"] or ""
        desc = r["description"] or ""
        lang, prob = detect(f"{title}. {desc}")
        by_lang[lang] = by_lang.get(lang, 0) + 1
        if lang and lang not in ALLOWED and prob >= PROB_MIN:
            gate = classifier.looks_foreign_language(title, desc)
            norm = classifier._normalize(f"{title} {desc}")
            override = bool(classifier._PLAYABLE_OK_RE.search(norm))
            any_foreign = bool(classifier._FOREIGN_LANG_RE.search(norm)
                               or classifier._FOREIGN_DECL_RE.search(norm))
            suspects.append((r["alert_name"], title, lang, prob,
                             gate, override, any_foreign))

    print("=" * 70)
    print(f" KEEP analizados: {len(rows)}  |  sospechosos (no es/ca/en, "
          f"prob>={PROB_MIN}): {len(suspects)}")
    print("=" * 70)
    print("\nIdioma detectado por langdetect en los KEEP:")
    for lang, c in sorted(by_lang.items(), key=lambda kv: -kv[1]):
        print(f"  {str(lang):6} -> {c}")

    # Resumen de por qué se colaron los sospechosos
    n_gate_ko = sum(1 for s in suspects if not s[4])      # gate NO lo cazaría
    n_override = sum(1 for s in suspects if s[5])         # override saltó
    n_sin_senal = sum(1 for s in suspects if not s[6])    # sin señal foreign
    print(f"\nDe los {len(suspects)} sospechosos:")
    print(f"  - el gate ACTUAL NO los descartaría: {n_gate_ko}")
    print(f"  - el override _PLAYABLE_OK saltó (posible causa): {n_override}")
    print(f"  - sin NINGUNA señal del vocabulario foreign: {n_sin_senal}")

    print("\nEjemplos (idioma detectado | gate=descartaría? | override | señal foreign):")
    for an, title, lang, prob, gate, override, anyf in suspects[: (None if SHOW else 20)]:
        print(f"  [{lang} {prob:.2f}] gate={'SÍ' if gate else 'no':3} "
              f"ovr={'sí' if override else 'no':3} sig={'sí' if anyf else 'no':3} "
              f"| {title[:60]}")
    if not SHOW and len(suspects) > 20:
        print(f"  ... ({len(suspects)-20} más; usa --list para verlos todos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
