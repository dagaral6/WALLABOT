"""
test_price_drops.py
-------------------
Verifica SIN RED lo que devuelve main.process_alert: deteccion de NUEVOS,
BAJADAS y SUBIDAS de precio, RECUPERACION de anuncios antes descartados por
caros, y que los RETIRADOS se borran de la BD SIN notificarse.

Usa una base de datos SQLite temporal y sustituye scraper.search por un stub.
La IA va desactivada (use_ai: false), asi que la clasificacion es 100%
determinista y no toca la red. process_alert ya NO envia correos: devuelve un
dict {name, new, drops, rises}; aqui inspeccionamos ese dict directamente.

Cuatro ciclos sobre una alerta "catan" con max_price 30:
  Ciclo 1: aparecen A(25, entra), B(50, rechazado por caro), D(20, entra).
  Ciclo 2: A baja a 18 (bajada), B baja a 28 (recuperado), D igual.
  Ciclo 3: A sube a 24 (subida), B y D igual.
  Ciclo 4: A y B desaparecen -> se BORRAN de la BD y NO se notifican.

    python test_price_drops.py
"""

import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import database  # noqa: E402
import scraper    # noqa: E402
import notifier   # noqa: E402
import main       # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


# --- BD temporal -----------------------------------------------------------
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
database.DB_PATH = _tmp.name
database.init_db()

CONFIG = {
    "location": {"latitude": 39.46, "longitude": -0.37, "radius_km": 50},
    "delivery": {"in_person": True, "shipping": True},   # sin filtro de entrega
    "use_ai": False,                                     # reglas, sin red
}
ALERT = {"name": "Catan", "keywords": "catan", "max_price": 30,
         "want": ["base", "lote"]}
USER = "tester"


def _item(i, title, price):
    return {"id": i, "title": title, "description": "", "price": price,
            "url": "https://es.wallapop.com/item/" + i,
            "is_shippable": True, "lat": 39.46, "lon": -0.37}


def _ids(items):
    return sorted((it.get("id") or it.get("item_id")) for it in items)


# --- Ciclo 1: alta ---------------------------------------------------------
scraper.search = lambda **kw: [
    _item("a", "Catan base", 25),
    _item("b", "Catan base completo", 50),   # caro -> rechazado por precio
    _item("d", "Catan base", 20),
]
res = main.process_alert(USER, CONFIG, ALERT)
check("ciclo1: nuevos = a, d", _ids(res["new"]) == ["a", "d"], _ids(res["new"]))
check("ciclo1: sin bajadas", res["drops"] == [])
check("ciclo1: sin subidas", res["rises"] == [])

key = USER + "/Catan"
kept = database.get_kept_rows(key)
rej = database.get_rejected_rows(key)
check("ciclo1: BD keep = a, d", sorted(kept) == ["a", "d"], sorted(kept))
check("ciclo1: BD reject = b (caro)", sorted(rej) == ["b"], sorted(rej))
check("ciclo1: precio guardado de b = 50", rej.get("b", {}).get("price") == 50)


# --- Ciclo 2: A baja, B se recupera ---------------------------------------
scraper.search = lambda **kw: [
    _item("a", "Catan base", 18),            # 25 -> 18 (bajada)
    _item("b", "Catan base completo", 28),   # 50 -> 28 (entra en presupuesto)
    _item("d", "Catan base", 20),            # igual
]
res = main.process_alert(USER, CONFIG, ALERT)
check("ciclo2: sin nuevos", res["new"] == [])
check("ciclo2: bajadas = a, b", _ids(res["drops"]) == ["a", "b"], _ids(res["drops"]))
check("ciclo2: sin subidas", res["rises"] == [])

drops_by_id = {it["id"]: it for it in res["drops"]}
check("ciclo2: a baja 25 -> 18",
      drops_by_id["a"].get("old_price") == 25 and drops_by_id["a"].get("price") == 18,
      (drops_by_id["a"].get("old_price"), drops_by_id["a"].get("price")))
check("ciclo2: b marcado como recuperado", drops_by_id["b"].get("recovered") is True)

kept = database.get_kept_rows(key)
check("ciclo2: b pasa a keep", "b" in kept, sorted(kept))
check("ciclo2: precio de a actualizado a 18", kept.get("a", {}).get("price") == 18)
check("ciclo2: precio de b actualizado a 28", kept.get("b", {}).get("price") == 28)


# --- Ciclo 3: A sube de precio --------------------------------------------
scraper.search = lambda **kw: [
    _item("a", "Catan base", 24),            # 18 -> 24 (subida)
    _item("b", "Catan base completo", 28),   # igual
    _item("d", "Catan base", 20),            # igual
]
res = main.process_alert(USER, CONFIG, ALERT)
check("ciclo3: sin nuevos", res["new"] == [])
check("ciclo3: sin bajadas", res["drops"] == [])
check("ciclo3: subidas = a", _ids(res["rises"]) == ["a"], _ids(res["rises"]))
rises_by_id = {it["id"]: it for it in res["rises"]}
check("ciclo3: a sube 18 -> 24",
      rises_by_id["a"].get("old_price") == 18 and rises_by_id["a"].get("price") == 24,
      (rises_by_id["a"].get("old_price"), rises_by_id["a"].get("price")))
check("ciclo3: precio de a actualizado a 24",
      database.get_kept_rows(key).get("a", {}).get("price") == 24)


# --- Ciclo 4: A y B desaparecen -> se borran, NO se notifican -------------
scraper.search = lambda **kw: [_item("d", "Catan base", 20)]
res = main.process_alert(USER, CONFIG, ALERT)
check("ciclo4: sin nuevos", res["new"] == [])
check("ciclo4: sin bajadas", res["drops"] == [])
check("ciclo4: sin subidas", res["rises"] == [])
kept = database.get_kept_rows(key)
check("ciclo4: a y b borrados de la BD", sorted(kept) == ["d"], sorted(kept))


# --- limpieza --------------------------------------------------------------
try:
    os.unlink(_tmp.name)
except OSError:
    pass

print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
