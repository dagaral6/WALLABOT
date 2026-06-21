"""
tune_rules_only.py
------------------
Fase A2: valida un clasificador SOLO REGLAS (sin NLI) sobre el dataset real,
con foco en la decision de cara al usuario:

  - RUIDO COLADO: anuncios not_game que acabarian como base/lote (se ENVIARIAN).
  - JUEGOS PERDIDOS: juegos base/lote marcados como no-juego (falsos rechazos).

Tres mecanismos, derivados del analisis de datos (analyze_matching.py):
  1. Matching: una palabra DEBIL (generica/ambigua: color, palabra comun) no
     basta sola si la keyword tiene alguna palabra fuerte (Inis<-estaciones,
     Burgundy<-color de ropa).
  2. Exclusion por vocabulario de NO-JUEGO (Mare Nostrum<-libros/maquetas/cine,
     Catan<-PS5/consola).
  3. Componentes ampliados (Catan<-organizador/dados/losetas/cartas...).

Reutiliza helpers de 01_Core/classifier.py (normalize, lote, base, foreign).
Solo lectura del dataset.

    py tune_rules_only.py
"""

import os
import re
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATASET = os.path.join(BASE, "nli_dataset", "cases.jsonl")
OUTPUT = os.path.join(BASE, "nli_dataset", "rules_diffs.json")

ALERT_KEYWORDS = {
    "dario/Catan": "catan",
    "dario/Castilllos de Burgundy": "castillos burgundy borgoña",
    "dario/Mare Nostrum": "mare nostrum",
    "dario/Carcassonne: Posadas y Catedrales": "carcassonne posadas catedrales",
    "dario/Las Estaciones de Inis": "estaciones inis",
    "dario/Frostpunk (hasta 90€)": "frostpunk",
}

# Palabras DEBILES: genericas/ambiguas que no bastan solas para confirmar que el
# anuncio es el juego buscado, SI la keyword tiene ademas alguna palabra fuerte.
# (Si la keyword entera es debil -p.ej. "risk", "cities"- entonces cualquier
# coincidencia vale: no hay alternativa.)
WEAK_WORDS = {
    "burgundy", "borgona", "estaciones", "posadas", "catedrales", "viaje",
    "cities", "risk", "mare",   # 'mare' comun (mar); 'nostrum' queda fuerte
}

# Vocabulario de NO-JUEGO: si aparece, el anuncio es OTRO producto (no el juego
# de mesa) aunque el nombre coincida. En forma normalizada (sin tildes).
NOT_GAME_VOCAB = {
    "libro", "libros", "novela", "novelas", "blasco", "ibanez", "folleto",
    "cine", "pelicula", "dvd", "bluray", "alquiler", "lamina", "acuarela",
    "botella", "maqueta", "maquetas", "puzzle", "puzle",
    "ps2", "ps3", "ps4", "ps5", "consola", "videojuego", "steam", "xbox",
    "nintendo", "switch", "playstation", "concert", "camiseta", "camisa",
    "polo", "guantes", "zapatillas", "esmalte", "bicicleta", "esqueje",
    "esquejes", "planta",
    # long tail de productos que comparten nombre (sobre todo "Mare Nostrum"):
    "perfume", "edt", "edp", "colonia", "vinilo", "disco", "cuadro",
    "escultura", "pintura", "poster", "cartel", "reloj", "cronografo",
    "gemelos", "insignia", "seguros", "seguro", "poliza", "polizas",
    "carcasa", "pesca", "telescopica", "barco", "yachting",
}

# Si el titulo deja claro que es el JUEGO (completo), no lo degrades a
# 'components' aunque mencione un accesorio: es un base CON extras.
_GAME_PRODUCT_RE = re.compile(r"\bjuego de mesa\b|\bjuego de tablero\b")

# Señal POSITIVA fuerte de juego de mesa. Tiene PRIORIDAD sobre el vocabulario
# de no-juego: muchas descripciones de juegos mencionan "videojuego" (Frostpunk
# esta basado en uno), "libro de reglas", etc. Si el anuncio dice claramente que
# es un juego de mesa/tablero, NO lo marques not_game por esas palabras.
_GAME_SIGNAL_RE = re.compile(
    r"\bjuego de mesa\b|\bjuego de tablero\b|\bboard game\b")

# Vocabulario de COMPONENTES/accesorios (pieza suelta, no el juego completo).
COMP_VOCAB = {
    "organizador", "organizadores", "inserto", "insertos", "separador",
    "separadores", "funda", "fundas", "sleeve", "sleeves", "protector",
    "protectores", "almacenamiento", "metacrilato", "neopreno", "tapete",
    "losetas", "loseta", "dados", "lanzador", "trofeo", "tablas",
    "recambio", "repuesto", "torre de dados", "bandeja", "bandejas",
    "fichas", "piezas", "recursos", "soportes", "impreso", "impresos",
    "impresa", "impresas", "mapa", "mapas",
}

_EXPANSION_RE = re.compile(r"\b(expansion|expansiones|ampliacion|ampliaciones)\b")
_BASE_INCLUSION_RE = re.compile(
    r"\bbase\b|\bincluye\b|\bcompleto\b|\bcompleta\b"
    r"|\bcon\s+(?:la|las|el|los|una|unas|sus|varias|dos|tres|\d+)?\s*expansion"
    r"|\by\s+(?:sus\s+|todas\s+las\s+|varias\s+|dos\s+|tres\s+)?expansion")

GAME_CATS = {"base", "expansion", "components", "lote"}
WANT_SENT = {"base", "lote"}        # lo que el usuario suele querer recibir
NO_SEND = {"no_title_match", "not_game", "components", "foreign_language"}


def kw_words(keyword):
    return [w for w in re.findall(r"\w+", classifier._normalize(keyword))
            if w not in classifier._STOPWORDS]


def is_relevant(keyword, title):
    """True si el titulo coincide con el juego por una palabra FUERTE (o la
    keyword es toda debil y coincide cualquiera)."""
    kw = kw_words(keyword)
    tw = set(re.findall(r"\w+", classifier._normalize(title)))
    matched = [w for w in kw if w in tw]
    if not matched:
        return False
    strong_in_kw = [w for w in kw if w not in WEAK_WORDS]
    if not strong_in_kw:
        return True
    return any(w in tw for w in strong_in_kw)


def rule_expansion(title):
    t = classifier._normalize(title)
    if not (t.startswith(("expansion ", "ampliacion ", "promo "))
            or _EXPANSION_RE.search(t)):
        return None
    if _BASE_INCLUSION_RE.search(t) or "+" in title:
        return None
    return "expansion"


def classify(title, keyword, desc=""):
    # La RELEVANCIA (¿es el juego buscado?) se decide por TITULO.
    if not is_relevant(keyword, title):
        return "no_title_match"
    if classifier.looks_foreign_language(title, desc):
        return "foreign_language"
    t = classifier._normalize(title)
    full = classifier._normalize(f"{title} {desc}")
    # Señal positiva de juego de mesa: tiene PRIORIDAD sobre el vocabulario de
    # no-juego (evita marcar not_game un Frostpunk "basado en el videojuego").
    is_game_signal = bool(_GAME_SIGNAL_RE.search(full))
    # Vocabulario de no-juego: sobre TITULO+DESCRIPCION (la desc revela el long
    # tail: 'Mare Nostrum' cuya desc dice "Libro de Blasco Ibanez").
    if not is_game_signal and any(w in full for w in NOT_GAME_VOCAB):
        return "not_game"
    # 'components' solo si el accesorio es el PRODUCTO, no un extra de un base.
    if any(w in t for w in COMP_VOCAB):
        is_base_with_extra = (_GAME_PRODUCT_RE.search(t) or "+" in title
                              or " e inserto" in t or " con inserto" in t
                              or " con funda" in t or " con fundas" in t)
        if not is_base_with_extra:
            return "components"
    if (not any(w in t for w in classifier._LOTE_WORDS)
            and classifier.strong_base_signal(title, desc)):
        return "base"
    if classifier._has_lote_vocab(f"{title} {desc}"):
        return "lote"
    exp = rule_expansion(title)
    if exp:
        return exp
    return "base"   # ante la duda, dejar pasar (decision del usuario)


def main():
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    per_cat_total, per_cat_hit = {}, {}
    ruido_colado = 0       # not_game del dataset -> base/lote (se enviaria)
    juegos_perdidos = 0    # base/lote del dataset -> no se envia (falso rechazo)
    diffs = []

    for r in rows:
        title = r.get("title") or ""
        actual = r.get("category") or "unknown"
        kw = ALERT_KEYWORDS.get(r.get("alert_name"), "")
        pred = classify(title, kw)

        per_cat_total[actual] = per_cat_total.get(actual, 0) + 1
        # "acierto" flexible: not_game del dataset cuenta como acertado si el
        # nuevo NO lo enviaria (no_title_match/not_game/components).
        hit = (pred == actual
               or (actual == "not_game" and pred in NO_SEND))
        if hit:
            per_cat_hit[actual] = per_cat_hit.get(actual, 0) + 1
        else:
            diffs.append({"title": title, "actual": actual, "pred": pred,
                          "alert": r.get("alert_name")})

        if actual == "not_game" and pred in WANT_SENT:
            ruido_colado += 1
        if actual in WANT_SENT and pred in NO_SEND:
            juegos_perdidos += 1

    n = len(rows)
    print(f"Casos: {n}\n")
    print("Acierto por categoria (not_game = 'no se enviaria'):")
    for cat in sorted(per_cat_total):
        h, tot = per_cat_hit.get(cat, 0), per_cat_total[cat]
        print(f"  {cat:>16}: {h}/{tot} = {h / tot:.0%}")

    ng = per_cat_total.get("not_game", 0)
    ng_ok = per_cat_hit.get("not_game", 0)
    print(f"\n[CLAVE] not_game filtrado (no se enviaria): {ng_ok}/{ng} = "
          f"{(ng_ok / ng if ng else 0):.0%}")
    print(f"[CLAVE] RUIDO COLADO (not_game -> base/lote, se enviaria): "
          f"{ruido_colado}")
    print(f"[CLAVE] JUEGOS PERDIDOS (base/lote -> no se envia): "
          f"{juegos_perdidos}  (critico, objetivo ~0)")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(diffs, f, ensure_ascii=False, indent=2)
    print(f"\nDiscrepancias: {OUTPUT} ({len(diffs)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
