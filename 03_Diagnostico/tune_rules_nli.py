"""
tune_rules_nli.py
-----------------
Fase A del plan "reemplazar la cascada LLM por reglas + NLI".

Aplica el ARBOL COMPLETO de decision propuesto (reglas duras R1-R5 + NLI en
2 pasos) sobre el dataset real (03_Diagnostico/nli_dataset/cases.jsonl) y mide:
  - Accuracy global (acuerdo con lo que el sistema decidio en su dia).
  - Accuracy por categoria, con foco en 'not_game' (el punto debil: 23% en el
    NLI zero-shot de 5 vias).
  - FALSOS RECHAZOS: el sistema lo dejo pasar (es juego) pero el nuevo arbol lo
    marca 'not_game'. Metrica CRITICA (el proyecto prefiere dejar pasar).

NO toca 01_Core/: reutiliza los helpers de reglas de classifier.py por import,
pero implementa el arbol aqui para poder iterar hipotesis y umbrales sin tocar
produccion. El modelo NLI se carga UNA sola vez (singleton) — re-instanciarlo
por llamada costaba ~793s/484 casos.

IMPORTANTE: el dataset solo guarda el TITULO (seen_items no almacena la
descripcion), asi que reglas y NLI trabajan solo con el titulo. En la
integracion real (Fase B) si habra descripcion y las reglas que la usan
(R5 'solo insertos...') tendran mas senal.

    py tune_rules_nli.py                 # todo el dataset
    py tune_rules_nli.py 100             # primeros 100 (mas rapido)

Ajuste por variables de entorno (para iterar sin editar):
    NLI_MODEL       (def. joeddav/xlm-roberta-large-xnli)
    NLI_MARGIN      paso 1: not_game si (no-juego - juego) >= X  (def. 0.10)
    NLI_TH_TYPE     paso 2: si el tipo ganador < X -> base       (def. 0.40)
"""

import os
import re
import sys
import json
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402  (reutilizamos sus helpers de reglas)

try:
    from transformers import pipeline
except ImportError:
    pipeline = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATASET = os.path.join(BASE, "nli_dataset", "cases.jsonl")
OUTPUT = os.path.join(BASE, "nli_dataset", "tune_diffs.json")

MODEL = os.getenv("NLI_MODEL") or "joeddav/xlm-roberta-large-xnli"
TH_MARGIN = float(os.getenv("NLI_MARGIN", "0.10"))
TH_TYPE = float(os.getenv("NLI_TH_TYPE", "0.40"))

# Categorias que NO son "juego dejado pasar" (para medir falsos rechazos).
NON_GAME = {"not_game", "unknown", "foreign_language", None}

# --- NLI: hipotesis en español ----------------------------------------------
# Paso 1 (¿es el juego buscado o no?): estrategia S4 (ANCLA el nombre del juego
# buscado). El modelo no reconoce nombres propios ("Catan", "Mare Nostrum",
# "Castillos de Borgoña") como "un juego de mesa" generico -> marcaba not_game a
# juegos reales (los que el usuario busca). Solucion: meter el nombre del juego
# buscado (alert_name) en la hipotesis, asi distingue "Camisa Burgundy" (no es el
# juego "Castillos de Borgoña") de "Castillos de Borgoña precintado" (si lo es).
# Evita la negacion (que el modelo maneja mal). CONSERVADOR: not_game solo si una
# categoria de no-juego gana al juego buscado por un MARGEN (ante la duda, pasar).
BINARY_TEMPLATE = "Este anuncio vende {}."
NOT_GAME_LABELS = [
    "ropa, calzado o complementos de moda",
    "una planta o un producto de jardineria",
    "un aparato electronico o accesorio de movil",
    "un libro, comic, musica o pelicula",
    "decoracion, hogar u otro objeto",
]
# Paso 2 (3 vias): tipo de producto de juego de mesa. NO incluye 'lote' a
# proposito: 'lote' es REGLA DURA (R3 / _has_lote_vocab). Si llegamos al paso 2
# es porque R3 ya descarto lote, asi que el modelo no debe poder elegirlo (en
# produccion _post_process_category fuerza lo mismo: sin vocabulario de lote,
# nunca es lote aunque lo diga el modelo).
TYPE_TEMPLATE = "Este anuncio vende {}."
TYPE_LABELS = {
    "base":       "un juego de mesa completo y jugable por si solo",
    "expansion":  "solo una expansion que necesita el juego base para poder jugar",
    "components": "solo piezas sueltas, insertos, fundas o cartas, sin el juego",
}
_TYPE_LABEL_TO_CAT = {v: k for k, v in TYPE_LABELS.items()}

# Senal POSITIVA de juego en el titulo: si aparece, NO es not_game (salta el
# paso binario y va directo a clasificar el tipo).
_GAME_WORD_RE = re.compile(r"\bjuego\b|\bjuegos\b|\bboard\s*game\b")

# --- modelo NLI (singleton) -------------------------------------------------
_PIPE = None


def get_pipe():
    global _PIPE
    if pipeline is None:
        print("[FAIL] transformers no instalado.")
        sys.exit(1)
    if _PIPE is None:
        print(f"Cargando modelo {MODEL} (una sola vez)...")
        t0 = time.time()
        _PIPE = pipeline("zero-shot-classification", model=MODEL)
        print(f"  modelo listo en {time.time() - t0:.1f}s\n")
    return _PIPE


# --- reglas nuevas (se trasladaran a classifier.py en la Fase B) ------------
# R4: expansion por titulo. Solo marca 'expansion' si el titulo menciona
# expansion/ampliacion Y NO hay senal de que ADEMAS incluya el juego base
# (en ese caso es 'base': un base con extras sigue siendo base).
_EXPANSION_TITLE_RE = re.compile(
    r"\b(expansion|expansiones|ampliacion|ampliaciones)\b")

# Senales en el titulo de que INCLUYE la base (=> no es "solo expansion"):
#  - la palabra "base" suelta (p.ej. "Catan Base + Expansiones")
#  - "incluye/completo/completa"
#  - "con (la|las|sus|varias|2...) expansion(es)"  /  "y (sus|varias) expansiones"
_BASE_INCLUSION_RE = re.compile(
    r"\bbase\b"
    r"|\bincluye\b|\bcompleto\b|\bcompleta\b"
    r"|\bcon\s+(?:la|las|el|los|una|unas|sus|varias|dos|tres|\d+)?\s*expansion"
    r"|\by\s+(?:sus\s+|todas\s+las\s+|varias\s+|dos\s+|tres\s+)?expansion"
)


def rule_expansion_by_title(title):
    """R4: el titulo indica que es SOLO una expansion (sin senal de base)."""
    t = classifier._normalize(title)
    starts_exp = t.startswith(("expansion ", "ampliacion ", "promo "))
    if not starts_exp and not _EXPANSION_TITLE_RE.search(t):
        return None  # ni siquiera menciona expansion
    if _BASE_INCLUSION_RE.search(t):
        return None  # incluye la base -> probablemente 'base', decide NLI
    if "+" in title:
        return None  # "X + Expansion" sugiere base + extra -> decide NLI
    return "expansion"


# R5: accesorios/componentes por texto. Muchos "not_game" del ground truth son
# en realidad accesorios (insertos, cajas de almacenamiento, organizadores,
# fundas...) que aqui van a 'components' y se rechazan igual -> misma decision
# para el usuario. Incluye tanto vocabulario de pieza suelta como frases "solo".
_COMP_WORDS = (
    "inserto", "insertos", "organizador", "organizadores", "separador",
    "separadores", "funda", "fundas", "sleeve", "sleeves", "protector",
    "protectores", "almacenamiento", "caja 3d", "caja organizadora",
    "metacrilato", "neopreno", "tapete", "recambio", "repuesto",
    "solo los insertos", "solo insertos", "solo las fundas", "solo fundas",
    "solo cartas", "solo el tablero", "solo manual", "solo instrucciones",
    "no incluye el juego", "sin el juego base",
)


def rule_components(title):
    t = classifier._normalize(title)
    if any(p in t for p in _COMP_WORDS):
        return "components"
    return None


# --- arbol completo ---------------------------------------------------------
def classify(title, alert_name=""):
    """Devuelve (categoria, via) aplicando reglas R1-R5 y, si no deciden, NLI.
    alert_name = nombre del juego buscado (ancla la hipotesis del paso 1)."""
    desc = ""  # el dataset no tiene descripcion (ver cabecera)

    # R1: idioma extranjero.
    if classifier.looks_foreign_language(title, desc):
        return "foreign_language", "R1"

    # R2: atajo a base (titulo claramente base y no es lote).
    if (not any(w in classifier._normalize(title) for w in classifier._LOTE_WORDS)
            and classifier.strong_base_signal(title, desc)):
        return "base", "R2"

    # R3: vocabulario explicito de lote.
    if classifier._has_lote_vocab(f"{title} {desc}"):
        return "lote", "R3"

    # R4: expansion por titulo.
    r4 = rule_expansion_by_title(title)
    if r4:
        return r4, "R4"

    # R5: componentes por texto.
    r5 = rule_components(title)
    if r5:
        return r5, "R5"

    # --- NLI paso 1 (¿es el juego buscado?): S4 anclado, conservador ---
    pipe = get_pipe()
    # Si el titulo dice "juego/juegos", es juego: saltar la deteccion not_game.
    if not _GAME_WORD_RE.search(classifier._normalize(title)):
        game_label = (f"el juego de mesa {alert_name}".strip()
                      if alert_name else "un juego de mesa")
        labels = [game_label] + NOT_GAME_LABELS
        r = pipe(title, candidate_labels=labels,
                 hypothesis_template=BINARY_TEMPLATE)
        by_label = dict(zip(r["labels"], r["scores"]))
        if (r["labels"][0] != game_label
                and r["scores"][0] - by_label.get(game_label, 0.0) >= TH_MARGIN):
            return "not_game", "NLI1"

    # --- NLI paso 2 (3 vias: base/expansion/components; lote es R3): tipo ---
    r = pipe(title, candidate_labels=list(TYPE_LABELS.values()),
             hypothesis_template=TYPE_TEMPLATE)
    best_cat = _TYPE_LABEL_TO_CAT.get(r["labels"][0], "base")
    best_score = r["scores"][0]
    if best_score < TH_TYPE:
        return "base", "NLI2-lowconf"   # ante la duda, dejar pasar (usuario)
    return best_cat, "NLI2"


def load_dataset(limit=None):
    if not os.path.exists(DATASET):
        print(f"No existe {DATASET}. Ejecuta antes build_nli_dataset.py.")
        sys.exit(1)
    rows = []
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = load_dataset(limit)
    print(f"Modelo NLI: {MODEL}")
    print(f"Umbrales: margen_not_game={TH_MARGIN}  tipo={TH_TYPE}")
    print(f"Casos a evaluar: {len(rows)}\n")

    confusion = {}          # (actual, pred) -> n
    per_cat_total = {}      # actual -> n
    per_cat_hit = {}        # actual -> aciertos
    via_count = {}          # via -> n (R1..R5, NLI1, NLI2, NLI2-lowconf)
    false_rejections = 0
    diffs = []
    t0 = time.time()

    for i, row in enumerate(rows, 1):
        title = row.get("title") or ""
        actual = row.get("category") or "unknown"
        pred, via = classify(title, row.get("alert_name") or "")

        confusion[(actual, pred)] = confusion.get((actual, pred), 0) + 1
        per_cat_total[actual] = per_cat_total.get(actual, 0) + 1
        via_count[via] = via_count.get(via, 0) + 1
        if pred == actual:
            per_cat_hit[actual] = per_cat_hit.get(actual, 0) + 1
        else:
            diffs.append({"title": title, "actual": actual,
                          "pred": pred, "via": via})
        if actual not in NON_GAME and pred == "not_game":
            false_rejections += 1
        if i % 50 == 0:
            print(f"  procesados {i}/{len(rows)}...")

    elapsed = time.time() - t0
    n = len(rows)
    total_hits = sum(per_cat_hit.values())

    print(f"\n--- Resultados ({n} casos, {elapsed:.1f}s) ---")
    print(f"\nAccuracy global (acuerdo con el actual): "
          f"{total_hits}/{n} = {total_hits / n:.0%}")

    print("\nAccuracy por categoria del sistema actual:")
    for cat in sorted(per_cat_total):
        h, tot = per_cat_hit.get(cat, 0), per_cat_total[cat]
        print(f"  {cat:>16}: {h}/{tot} = {h / tot:.0%}")

    print("\nVia de decision (cuantos resuelve cada regla / NLI):")
    for via in sorted(via_count, key=lambda k: -via_count[k]):
        print(f"  {via:>14}: {via_count[via]}")

    print("\nMatriz de confusion (actual -> pred : n), top 15 discrepancias:")
    disc = sorted(((k, v) for k, v in confusion.items() if k[0] != k[1]),
                  key=lambda kv: -kv[1])
    for (actual, pred), c in disc[:15]:
        print(f"  {actual:>16} -> {pred:<12}: {c}")

    nm_hit = per_cat_hit.get("not_game", 0)
    nm_tot = per_cat_total.get("not_game", 0)
    print(f"\n[PUERTA] not_game: {nm_hit}/{nm_tot} = "
          f"{(nm_hit / nm_tot if nm_tot else 0):.0%}  (objetivo >= 80%)")
    print(f"[PUERTA] Falsos rechazos: {false_rejections}  (objetivo < 15)")
    print(f"[PUERTA] Accuracy global: {total_hits / n:.0%}  (objetivo >> 30%)")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(diffs, f, ensure_ascii=False, indent=2)
    print(f"\nDiscrepancias guardadas para revision manual: {OUTPUT} "
          f"({len(diffs)} casos)")

    ok = (nm_tot and nm_hit / nm_tot >= 0.80) and false_rejections < 15
    print("\nRESULTADO:", "PUERTA SUPERADA" if ok else
          "NO PASA — ajustar reglas/umbral (ver tune_diffs.json)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
