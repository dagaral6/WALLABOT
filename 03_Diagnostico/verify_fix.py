import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))

import classifier as c

title = "Los Colonos de Catan - El Juego"
descs = [
    "",
    "Juego completo, todas las piezas.",
    "Vendo Los Colonos de Catan. Tambien tengo las expansiones Navegantes y Ciudades aparte.",
    "Juego base. Compatible con todas las expansiones.",
]
print("== CASO REPORTADO ==")
print("strong_base_signal(titulo):", c.strong_base_signal(title))
for d in descs:
    r_llm = c.classify_category(title, d, use_llm=True, model="qwen2.5:3b")
    r_no = c.classify_category(title, d, use_llm=False)
    print("  use_llm=True -> %-9s | use_llm=False -> %-9s | desc: %r"
          % (r_llm, r_no, d[:45]))

print("\n== CONTROLES (no deben romperse) ==")
print("expansion real ->",
      c.classify_category("Catan Navegantes",
                          "Solo la expansion, necesitas el juego base.",
                          use_llm=False))
print("componentes ->",
      c.classify_category("Insertos para Catan",
                          "Solo los insertos, no incluye el juego.",
                          use_llm=False))
print("cartas (sufijo NO debe disparar) -> strong_base_signal:",
      c.strong_base_signal("Catan: El Juego de Cartas"))
print("no-juego que coincide -> strong_base_signal:",
      c.strong_base_signal("Interruptor Somfy Inis Uno"))
print("\nOK")
