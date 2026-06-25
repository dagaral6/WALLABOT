"""
database.py
-----------
SQLite. Guarda CADA anuncio visto por alerta junto con su categoría, el precio
y la decisión tomada (keep/reject). Así:
  - Cada listing se clasifica UNA sola vez (no repetimos llamadas al LLM).
  - Detectamos novedades (ids nuevos) y bajas (ids que desaparecen).
  - Detectamos BAJADAS DE PRECIO: el precio guardado se actualiza en cada ciclo
    y se compara con el actual (update_prices / promote_to_keep).
"""

import os
import logging
import sqlite3
from contextlib import contextmanager

log = logging.getLogger(__name__)

# En despliegues cloud (Railway), DATA_DIR apunta al volumen persistente.
DB_PATH = os.path.join(
    os.getenv("DATA_DIR") or os.path.dirname(os.path.abspath(__file__)),
    "alerts.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    alert_name TEXT NOT NULL,
    item_id    TEXT NOT NULL,
    title      TEXT,
    price      REAL,
    url        TEXT,
    category    TEXT,
    decision    TEXT,                      -- 'keep' | 'reject'
    description TEXT,                       -- texto del anuncio (keep y reject)
    language    TEXT,                       -- idioma detectado: es | ca | en | otro
    category_id TEXT,                       -- categoría NATIVA Wallapop (no la del bot)
    first_seen  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (alert_name, item_id)
);
"""

# Columnas que deben existir (para migrar bases antiguas sin perder datos).
# deleted_reason/deleted_at marcan el HISTORICO de alertas eliminadas: las filas
# no se borran, solo se anotan (base para una futura capa de consulta).
# description/language: texto del anuncio (en keep y reject) e idioma detectado
# (es/ca/en/otro), para el dataset de reentrenamiento del clasificador/NLI.
# category_id: categoría NATIVA de Wallapop (la del vendedor), para filtrar/ver
# lo que no es juego de mesa (libros, CDs, videojuegos...).
_REQUIRED_COLS = {"category": "TEXT", "decision": "TEXT",
                  "deleted_reason": "TEXT", "deleted_at": "TEXT",
                  "description": "TEXT", "language": "TEXT",
                  "category_id": "TEXT"}

# Motivos validos al eliminar una alerta (fuente unica de verdad; el HTML y
# config_inbox.py usan estos mismos valores internos).
VALID_DELETE_REASONS = ("comprado", "ya_no_interesa", "duplicada", "otro")


@contextmanager
def _conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=None):
    db_path = db_path or DB_PATH
    with _conn(db_path) as c:
        c.executescript(SCHEMA)
        # Migración suave: añade columnas que falten si la tabla es antigua.
        existing = {row["name"] for row in
                    c.execute("PRAGMA table_info(seen_items)").fetchall()}
        for col, coltype in _REQUIRED_COLS.items():
            if col not in existing:
                c.execute(f"ALTER TABLE seen_items ADD COLUMN {col} {coltype}")


def get_known_ids(alert_name, db_path=None):
    db_path = db_path or DB_PATH
    """Todos los ids ya vistos (keep + reject): los que NO hay que reclasificar."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT item_id FROM seen_items WHERE alert_name = ?",
            (alert_name,)).fetchall()
    return {r["item_id"] for r in rows}


def get_kept_rows(alert_name, db_path=None):
    db_path = db_path or DB_PATH
    """Items que SÍ notificamos en su día -> {id: row}. Para detectar ventas
    y BAJADAS DE PRECIO (comparando el precio guardado con el actual)."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM seen_items WHERE alert_name = ? AND decision = 'keep'",
            (alert_name,)).fetchall()
    return {r["item_id"]: dict(r) for r in rows}


def get_rejected_rows(alert_name, db_path=None):
    db_path = db_path or DB_PATH
    """Items vistos y RECHAZADOS -> {id: row}. Sirve para 'resucitar' los que se
    descartaron por precio si ahora bajan dentro del presupuesto."""
    with _conn(db_path) as c:
        rows = c.execute(
            "SELECT * FROM seen_items WHERE alert_name = ? AND decision = 'reject'",
            (alert_name,)).fetchall()
    return {r["item_id"]: dict(r) for r in rows}


def update_prices(alert_name, id_price_pairs, db_path=None):
    db_path = db_path or DB_PATH
    """Actualiza el precio guardado de varios anuncios ya existentes.
    id_price_pairs: iterable de (item_id, nuevo_precio)."""
    pairs = [(p, alert_name, i) for (i, p) in id_price_pairs]
    if not pairs:
        return
    with _conn(db_path) as c:
        c.executemany(
            "UPDATE seen_items SET price = ? WHERE alert_name = ? AND item_id = ?",
            pairs)


def promote_to_keep(alert_name, id_price_pairs, db_path=None):
    db_path = db_path or DB_PATH
    """Marca como 'keep' (y actualiza precio) anuncios antes rechazados que ahora
    entran (bajada de precio que cruza el max_price). id_price_pairs: (id, precio)."""
    pairs = [(p, alert_name, i) for (i, p) in id_price_pairs]
    if not pairs:
        return
    with _conn(db_path) as c:
        c.executemany(
            "UPDATE seen_items SET decision = 'keep', price = ? "
            "WHERE alert_name = ? AND item_id = ?",
            pairs)


def add_items(alert_name, decided_items, db_path=None):
    db_path = db_path or DB_PATH
    """
    Inserta anuncios ya clasificados.
    decided_items: lista de tuplas (item_dict, category, decision).

    Además de los campos de siempre guarda:
      - description: el texto del anuncio (item_dict['description']) en TODAS las
        filas, sea 'keep' o 'reject'. Antes solo se guardaba en 'keep'; ahora
        también en 'reject' para que el dataset de reentrenamiento tenga contexto
        de los anuncios descartados (components/expansion/lote/not_game), que es
        donde más se necesita. Cadena vacía se normaliza a NULL.
      - language: idioma detectado (item_dict['language']: es/ca/en/otro) en
        TODAS las filas. Lo calcula main.evaluate()/process_alert vía
        classifier.detect_language antes de llamar aquí.
      - category_id: categoría NATIVA de Wallapop (item_dict['category_id']) en
        TODAS las filas; se guarda como texto (o NULL si no vino en el payload).
    """
    if not decided_items:
        return

    def _cat(it):
        v = it.get("category_id")
        return str(v) if v not in (None, "") else None

    with _conn(db_path) as c:
        c.executemany(
            """INSERT OR IGNORE INTO seen_items
               (alert_name, item_id, title, price, url, category, decision,
                description, language, category_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(alert_name, it["id"], it["title"], it["price"], it["url"],
              cat, dec,
              (it.get("description") or None),
              it.get("language"), _cat(it))
             for (it, cat, dec) in decided_items])


def delete_items(alert_name, item_ids, db_path=None):
    db_path = db_path or DB_PATH
    if not item_ids:
        return
    with _conn(db_path) as c:
        c.executemany(
            "DELETE FROM seen_items WHERE alert_name = ? AND item_id = ?",
            [(alert_name, iid) for iid in item_ids])


def mark_alert_deleted(alert_name, reason, db_path=None):
    """Marca (NO borra) el HISTORICO de una alerta eliminada por el usuario.
    Anota deleted_reason/deleted_at en TODAS las filas de 'alert_name', sea cual
    sea su decision ('keep' o 'reject'): asi conservamos qué anuncios se vieron
    y por qué dejó de interesar la alerta (comprado, ya_no_interesa...).

    'alert_name' viene con el prefijo "<user_id>/<nombre>", igual que en el resto
    del código. Si 'reason' no es un motivo válido, se guarda 'otro' y se avisa.
    Devuelve el número de filas marcadas."""
    db_path = db_path or DB_PATH
    init_db(db_path)                       # garantiza columnas deleted_* (migra)

    r = (reason or "").strip().lower()
    if r not in VALID_DELETE_REASONS:
        log.warning("Motivo de borrado no válido %r para '%s'; uso 'otro'.",
                    reason, alert_name)
        r = "otro"

    with _conn(db_path) as c:
        cur = c.execute(
            "UPDATE seen_items SET deleted_reason = ?, deleted_at = datetime('now') "
            "WHERE alert_name = ?",
            (r, alert_name))
        return cur.rowcount
