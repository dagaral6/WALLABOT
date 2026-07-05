"""
test_batch.py
-------------
Verifica SIN RED el clasificador por REGLAS (rediseño jun 2026, sin LLM):

  1) classify_categories_batch / classify_category asignan la categoria correcta
     por reglas sobre titulo + descripcion (base/expansion/components/lote/not_game).
  2) Vocabulario de no-juego (libro, ps5...) -> not_game, salvo SEÑAL POSITIVA de
     juego de mesa (Frostpunk "basado en el videojuego" sigue siendo 'base').
  3) 'components' no degrada un base CON extras ("... + Inserto").
  4) Matching nucleo vs generico (title_matches): una palabra comun no basta
     sola; un nombre propio (o >=2 palabras) si.
  5) check_lote (rama 2) por reglas: vocabulario de lote + juego buscado presente.

    python test_batch.py
"""

import os
import sys
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import classifier  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


# --- 1) clasificacion por reglas (lote de varios anuncios) -----------------
PAIRS = [
    ("Catan", "Juego de mesa Catan completo, en buen estado."),        # base
    ("Mare Nostrum", "Libro de Vicente Blasco Ibanez, 1977."),         # not_game
    ("Organizador Catan", "Inserto de madera, solo el organizador."),  # components
    ("Catan Navegantes", "Solo la expansion, necesitas el base."),     # expansion
    ("Lote juegos", "Se venden juntos Catan, Risk y Azul. Lote."),     # lote
]
cats = classifier.classify_categories_batch(PAIRS)
check("categorias por reglas correctas",
      cats == ["base", "not_game", "components", "expansion", "lote"], cats)


# --- 2) vocabulario no-juego vs señal positiva de juego de mesa ------------
check("libro -> not_game",
      classifier.classify_category("Mare Nostrum", "Libro de Blasco Ibanez")
      == "not_game")
check("videojuego PS5 -> not_game",
      classifier.classify_category("Catan", "Edicion de consola para PS5")
      == "not_game")
check("'juego de mesa basado en el videojuego' -> base (señal positiva gana)",
      classifier.classify_category(
          "Frostpunk", "Juego de mesa basado en el aclamado videojuego.")
      == "base")


# --- 3) componentes no degrada un base CON extras -------------------------
check("base + inserto sigue siendo base",
      classifier.classify_category(
          "Castillos de Borgoña + Inserto", "Juego de mesa completo con inserto.")
      == "base")
check("solo inserto -> components",
      classifier.classify_category("Inserto para Catan", "Solo el inserto.")
      == "components")


# --- 4) matching nucleo vs generico (title_matches) -----------------------
if classifier.zipf_frequency is None:
    print("[SKIP] matching debil: wordfreq no instalado")
else:
    check("palabra comun sola NO basta ('estaciones' de 'estaciones inis')",
          classifier.title_matches("estaciones inis", "Estacion de tren Norte")
          is False)
    check("nombre propio si vale ('inis')",
          classifier.title_matches("estaciones inis", "Las Estaciones de Inis")
          is True)
    check("keyword de 1 palabra: cualquier coincidencia vale",
          classifier.title_matches("catan", "Camiseta Catan") is True)
    check(">=2 palabras comunes valen ('castillos'+'borgoña')",
          classifier.title_matches("castillos burgundy borgoña",
                                    "Los Castillos de Borgoña") is True)


# --- 4b) ORDEN multi-palabra (S2): las palabras de la keyword presentes deben
# aparecer EN ORDEN (con huecos), no reordenadas. No depende de wordfreq.
check("orden: 'rising sun' NO casa con 'Sun Rising'",
      classifier.title_matches("rising sun", "Sun Rising juego de mesa") is False)
check("orden: 'rising sun' SI casa con 'Rising Sun'",
      classifier.title_matches("rising sun", "Rising Sun CMON completo") is True)
check("orden: 'rising sun' NO casa con 'Setting Sun Rising'",
      classifier.title_matches("rising sun", "Paper Wars Setting Sun Rising") is False)
check("orden con huecos: 'estaciones inis' SI casa con 'Estaciones de Inis'",
      classifier.title_matches("estaciones inis", "Las Estaciones de Inis") is True)
check("orden con huecos: 'carcassonne posadas catedrales' SI casa",
      classifier.title_matches("carcassonne posadas catedrales",
                               "Carcassonne: Posadas y Catedrales") is True)
check("orden: 'mare nostrum' NO casa con 'Nostrum Mare' (reordenado)",
      classifier.title_matches("mare nostrum", "Nostrum Mare edicion") is False)


# --- 5) check_lote por reglas (rama 2) ------------------------------------
lote = classifier.check_lote("catan", "Lote de juegos de mesa",
                             "Vendo juntos Catan, Risk y Azul. Se venden en lote.")
check("lote con el juego buscado -> includes_target",
      lote["is_lote"] and lote["includes_target"], lote)
lote2 = classifier.check_lote("mare nostrum", "Lote de novelas",
                              "Varias novelas de Blasco Ibanez, se venden juntas.")
check("lote sin el juego buscado -> no includes_target",
      not lote2["includes_target"], lote2)


# --- 6) auditoría de falsos positivos (jul 2026) --------------------------
# 6a) ESPECIFICIDAD (title_matches): una sola palabra genérica de un término
# multi-palabra no basta si es la más común habiendo otras más distintivas.
if classifier.zipf_frequency is not None:
    check("especificidad: 'castillos burgundy borgoña' NO casa 'Castillos de Arena'",
          classifier.title_matches("castillos burgundy borgoña",
                                   "Castillos de Arena") is False)
    check("especificidad: 'inis' (distintiva) SÍ basta en 'estaciones inis'",
          classifier.title_matches("estaciones inis", "Inis edición Devir") is True)

# 6b) NFC: una ñ descompuesta (NFD: n + tilde combinante) debe casar igual.
_nfd_titulo = unicodedata.normalize("NFD", "Castillos de Borgoña")  # ñ -> n + U+0303
check("NFC: Borgoña descompuesta casa como borgona",
      classifier.title_matches("castillos burgundy borgoña", _nfd_titulo) is True)

# 6c) COMPONENTES delatados por la DESCRIPCIÓN (título limpio):
check("desc 'organizador de...' -> components",
      classifier.classify_category("Castillos de Borgoña",
                                   "Organizador de losetas hexagonales.") == "components")
check("desc 'no incluye juego / solo las cajas' -> components",
      classifier.classify_category("2 Cajas Castillos Borgoña",
                                   "No incluye juego. Solo las cajas.") == "components")
check("falso amigo 'solo la caja tiene desgaste' + juego completo -> base",
      classifier.classify_category(
          "Camel Up", "Juego de mesa completo, solo la caja tiene desgaste.") == "base")

# 6d) SPAM de tags por PUNTOS (ráfaga sin marcador) se recorta.
_spam = ("Juego completo en buen estado. catan. azul. root. brass. dune. "
         "nemesis. wingspan. scythe. everdell. gloomhaven.")
check("tags por puntos: ráfaga recortada",
      len(classifier.strip_tag_spam(_spam)) < len(_spam))
check("prosa por puntos NO se recorta",
      classifier.strip_tag_spam("Vendo Catan. Está completo. Envío a península.")
      == "Vendo Catan. Está completo. Envío a península.")

# 6e) check_lote: un "lote" de solo CAJAS VACÍAS no incluye el juego.
_cajas = classifier.check_lote(
    "camel up", "Cajas vacías juegos de mesa",
    "Se venden cajas vacías de varios juegos de mesa. Caja del Camel Up.")
check("lote de cajas vacías -> no includes_target", not _cajas["includes_target"], _cajas)


print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
