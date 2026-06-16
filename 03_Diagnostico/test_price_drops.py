"""
test_price_drops.py
-------------------
Verifica SIN RED la deteccion de BAJADAS DE PRECIO y la RECUPERACION de
anuncios antes descartados por caros, en main.process_alert.

Usa una base de datos SQLite temporal y sustituye scraper.search y
notifier.notify por stubs. La IA va desactivada (use_ai: false), asi que la
clasificacion es 100% determinista y no toca la red.

Tres ciclos sobre una alerta "catan" con max_price 30:
  Ciclo 1: aparecen A(25, entra), B(50, rechazado por caro), D(20, entra).
  Ciclo 2: A baja a 18 (bajada), B baja a 28 (recuperado), D igual.
  Ciclo 3: A y B desaparecen -> ambos como "vendidos/retirados".

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


# --- captura de notificaciones --------------------------------------------
_LAST = {}


def _fake_notify(config, alert_name, new_items, sold_items, price_drops=None):
    _LAST.clear()
    _LAST.update(new=list(new_items), sold=list(sold_items),
                 drops=list(price_drops or []))


notifier.notify = _fake_notify


def _ids(items):
    return sorted((it.get("id") or it.get("item_id")) for it in items)


# --- Ciclo 1: alta ---------------------------------------------------------
scraper.search = lambda **kw: [
    _item("a", "Catan base", 25),
    _item("b", "Catan base completo", 50),   # caro -> rechazado por precio
    _item("d", "Catan base", 20),
]
main.process_alert(USER, CONFIG, ALERT, notify_enabled=True)
check("ciclo1: nuevos = a, d", _ids(_LAST["new"]) == ["a", "d"], _ids(_LAST["new"]))
check("ciclo1: sin bajadas", _LAST["drops"] == [])
check("ciclo1: sin vendidos", _LAST["sold"] == [])

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
main.process_alert(USER, CONFIG, ALERT, notify_enabled=True)
check("ciclo2: sin nuevos", _LAST["new"] == [])
check("ciclo2: bajadas = a, b", _ids(_LAST["drops"]) == ["a", "b"], _ids(_LAST["drops"]))
check("ciclo2: sin vendidos", _LAST["sold"] == [])

drops_by_id = {it["id"]: it for it in _LAST["drops"]}
check("ciclo2: a baja 25 -> 18",
      drops_by_id["a"].get("old_price") == 25 and drops_by_id["a"].get("price") == 18,
      (drops_by_id["a"].get("old_price"), drops_by_id["a"].get("price")))
check("ciclo2: b marcado como recuperado", drops_by_id["b"].get("recovered") is True)

kept = database.get_kept_rows(key)
check("ciclo2: b pasa a keep", "b" in kept, sorted(kept))
check("ciclo2: precio de a actualizado a 18", kept.get("a", {}).get("price") == 18)
check("ciclo2: precio de b actualizado a 28", kept.get("b", {}).get("price") == 28)


# --- Ciclo 3: A y B desaparecen -------------------------------------------
scraper.search = lambda **kw: [_item("d", "Catan base", 20)]
main.process_alert(USER, CONFIG, ALERT, notify_enabled=True)
check("ciclo3: sin nuevos", _LAST["new"] == [])
check("ciclo3: sin bajadas", _LAST["drops"] == [])
check("ciclo3: vendidos = a, b", _ids(_LAST["sold"]) == ["a", "b"], _ids(_LAST["sold"]))


# --- limpieza --------------------------------------------------------------
try:
    os.unlink(_tmp.name)
except OSError:
    pass

print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
