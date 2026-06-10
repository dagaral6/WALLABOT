"""
test_delivery.py
----------------
Test del filtro de entrega (radio / envío) de main._delivery_ok.
Comprueba las 4 combinaciones de delivery + casos límite (datos ausentes).
No necesita red ni Ollama: usa anuncios sintéticos.

Ejecutar:  python test_delivery.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "01_Core"))
import main  # noqa: E402

CASA = {"latitude": 39.4685, "longitude": -0.3359}


def cfg(in_person, shipping, radius=50):
    loc = dict(CASA)
    if radius is not None:
        loc["radius_km"] = radius
    return {"location": loc, "delivery": {"in_person": in_person,
                                          "shipping": shipping}}


# Anuncios sintéticos (distancias reales a CASA):
CERCA = {"id": "cerca",  "lat": 39.47, "lon": -0.37, "is_shippable": False}   # ~3 km
MEDIO = {"id": "medio",  "lat": 39.68, "lon": -0.27, "is_shippable": False}   # ~24 km
LEJOS = {"id": "lejos",  "lat": 40.41, "lon": -3.70, "is_shippable": False}   # ~305 km
LEJOS_ENV = {"id": "lejosE", "lat": 40.41, "lon": -3.70, "is_shippable": True}  # ~305 km + envío
SIN_COORD = {"id": "nc", "lat": None, "lon": None, "is_shippable": False}     # sin coords


def expect(label, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'FALLA'}] {label}: {got}  (esperado {want})")
    return ok


def main_test():
    todo_ok = True

    print("== AMBOS activos (true, true) -> todo pasa ==")
    c = cfg(True, True)
    for it in (CERCA, MEDIO, LEJOS, LEJOS_ENV, SIN_COORD):
        todo_ok &= expect(it["id"], main._delivery_ok(it, c), True)

    print("== NINGUNO activo (false, false) -> sin filtro, todo pasa ==")
    c = cfg(False, False)
    for it in (CERCA, MEDIO, LEJOS, LEJOS_ENV, SIN_COORD):
        todo_ok &= expect(it["id"], main._delivery_ok(it, c), True)

    print("== Solo EN PERSONA (radio 50) -> pasan <=50 km; el envío lejano NO ==")
    c = cfg(True, False, radius=50)
    todo_ok &= expect("cerca 3km",   main._delivery_ok(CERCA, c), True)
    todo_ok &= expect("medio 24km",  main._delivery_ok(MEDIO, c), True)
    todo_ok &= expect("lejos 305km", main._delivery_ok(LEJOS, c), False)
    todo_ok &= expect("lejos+envío (radio manda)", main._delivery_ok(LEJOS_ENV, c), False)
    todo_ok &= expect("sin coords (ante duda, pasa)", main._delivery_ok(SIN_COORD, c), True)

    print("== Solo EN PERSONA (radio 10) -> medio (24km) queda fuera ==")
    c = cfg(True, False, radius=10)
    todo_ok &= expect("cerca 3km",  main._delivery_ok(CERCA, c), True)
    todo_ok &= expect("medio 24km", main._delivery_ok(MEDIO, c), False)

    print("== Solo ENVÍO -> solo los que admiten envío (distancia ignorada) ==")
    c = cfg(False, True)
    todo_ok &= expect("cerca sin envío",  main._delivery_ok(CERCA, c), False)
    todo_ok &= expect("lejos sin envío",  main._delivery_ok(LEJOS, c), False)
    todo_ok &= expect("lejos CON envío",  main._delivery_ok(LEJOS_ENV, c), True)

    print("== Solo EN PERSONA pero SIN radius_km -> ante la duda, pasa ==")
    c = cfg(True, False, radius=None)
    todo_ok &= expect("lejos 305km sin radio", main._delivery_ok(LEJOS, c), True)

    print()
    print("RESULTADO:", "TODO OK" if todo_ok else "HAY FALLOS")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main_test())
