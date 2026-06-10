import sqlite3, sys, os
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core", "alerts.db")
con = sqlite3.connect(_DB)
cur = con.cursor()
tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")]
print("Tablas:", tables)
found = False
for t in tables:
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
    print(f"\nTabla {t} -> columnas: {cols}")
    try:
        rows = cur.execute(f"SELECT * FROM {t}").fetchall()
        print(f"  filas totales: {len(rows)}")
        for row in rows:
            if any(isinstance(v, str) and "colonos" in v.lower() for v in row):
                print("  >>> COINCIDENCIA 'colonos':", row)
                found = True
    except Exception as e:
        print("  (no se pudo leer)", e)
con.close()
print("\nEN_BD:", found)
print("FIN_DB")
