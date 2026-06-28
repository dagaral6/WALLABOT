"""
build_gamedb.py
---------------
Compila boardgames_ranks_reducido.csv -> 01_Core/gamedb.json (base de datos
offline de juegos de mesa). Se ejecuta UNA vez (y cada vez que se actualice el
CSV); el JSON resultante se commitea y viaja con el repo, de modo que en runtime
(incluido GitHub Actions, sin red) la clasificación base/expansion es offline y
determinista. Sustituye a la consulta viva a BGG (cerrada/401 desde 2025).

Uso:  py 03_Diagnostico/build_gamedb.py

Entrada: 03_Diagnostico/boardgames_ranks_reducido.csv  (TSV: id, name, type, traduccion)
Salida:  01_Core/gamedb.json

Estructura del JSON (compacto, generado, no editar a mano):
  {
    "names": {"<nombre_normalizado>": 0|1, ...},   # 0=base, 1=expansion
    "exp_by_base": {"<base_norm>": ["<distintiva>", ...], ...}
  }

- "names" indexa nombre INGLÉS y "traduccion" (si existe), para reconocer el
  juego a partir del título del anuncio (en cualquiera de los dos idiomas).
- "exp_by_base" agrupa, por nombre de juego base normalizado, las partes
  DISTINTIVAS (>=2 palabras, >=6 caracteres) de sus expansiones, para detectar
  una expansión nombrada en el título/descripción de un anuncio de "base".
"""

import csv
import json
import os
import re
from pathlib import Path

# --- normalización (idéntica a bgg.py: minúsculas, sin tildes, alfanum+espacio) -
def _strip_accents(text):
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n"), ("à", "a"), ("è", "e"), ("ç", "c"), ("ü", "u")):
        text = text.replace(a, b)
    return text

def _norm(title):
    t = _strip_accents((title or "").lower())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def _distinctive(name):
    """Parte distintiva de una expansión: lo que va tras el primer ':' (o el
    nombre completo si no hay ':'), normalizado."""
    raw = name.split(":", 1)[1] if ":" in name else name
    return _norm(raw)

def _base_prefix(name):
    """Nombre del juego base implícito en una expansión: lo que va ANTES del
    primer ':' , normalizado. '' si no hay ':'."""
    return _norm(name.split(":", 1)[0]) if ":" in name else ""


def build_gamedb():
    csv_path = Path(__file__).parent / "boardgames_ranks_reducido.csv"
    output_path = Path(__file__).parent.parent / "01_Core" / "gamedb.json"

    print(f"Leyendo {csv_path} ...")

    names = {}                 # nombre_norm -> 0 (base) | 1 (expansion)
    exp_rows = []              # (name, traduccion) de expansiones, 2ª pasada
    rows = 0

    # El CSV es un export de Excel/Windows en cp1252 (Windows-1252), no UTF-8
    # (p.ej. el en-dash 0x96). El JSON de salida sí se escribe en UTF-8.
    with open(csv_path, encoding="cp1252") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows += 1
            name = (row.get("name") or "").strip()
            trad = (row.get("traduccion") or "").strip()
            gtype = (row.get("type") or "base").strip().lower()
            if not name:
                continue
            is_exp = 1 if gtype.startswith("exp") else 0

            for nm in (name, trad):
                if not nm:
                    continue
                key = _norm(nm)
                if not key:
                    continue
                # Ante colisión base/expansion, conserva 'base' (0): conservador,
                # no fuerza expansion sobre un nombre que también es un juego base.
                prev = names.get(key)
                if prev is None:
                    names[key] = is_exp
                elif prev == 1 and is_exp == 0:
                    names[key] = 0

            if is_exp:
                exp_rows.append((name, trad))

            if rows % 50000 == 0:
                print(f"  {rows} filas...")

    # 2ª pasada: agrupar distintivas de expansiones bajo su base (si el base
    # existe en 'names'). Solo distintivas robustas (>=2 palabras, >=6 chars).
    bases = {k for k, v in names.items() if v == 0}
    exp_by_base = {}
    for name, trad in exp_rows:
        for nm in (name, trad):
            if not nm or ":" not in nm:
                continue
            base = _base_prefix(nm)
            dist = _distinctive(nm)
            if not base or base not in bases:
                continue
            if len(dist) < 6 or len(dist.split()) < 2:
                continue
            lst = exp_by_base.setdefault(base, [])
            if dist not in lst:
                lst.append(dist)

    data = {"names": names, "exp_by_base": exp_by_base}

    print(f"Total: {rows} filas | {len(names)} nombres "
          f"({sum(1 for v in names.values() if v == 1)} expansiones) | "
          f"{len(exp_by_base)} bases con expansiones")

    print(f"Escribiendo {output_path} ...")
    os.makedirs(output_path.parent, exist_ok=True)
    # Compacto (archivo generado): sin indent, separadores mínimos.
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"OK gamedb.json escrito ({size_mb:.1f} MB)")


if __name__ == "__main__":
    build_gamedb()
