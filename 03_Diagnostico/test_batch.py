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


# --- 5) check_lote por reglas (rama 2) ------------------------------------
lote = classifier.check_lote("catan", "Lote de juegos de mesa",
                             "Vendo juntos Catan, Risk y Azul. Se venden en lote.")
check("lote con el juego buscado -> includes_target",
      lote["is_lote"] and lote["includes_target"], lote)
lote2 = classifier.check_lote("mare nostrum", "Lote de novelas",
                              "Varias novelas de Blasco Ibanez, se venden juntas.")
check("lote sin el juego buscado -> no includes_target",
      not lote2["includes_target"], lote2)


print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
