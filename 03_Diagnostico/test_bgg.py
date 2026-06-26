"""
test_bgg.py
-----------
Tests del modulo 01_Core/bgg.py (refuerzo BoardGameGeek) y de su integracion en
main.py:_refine_categories_with_bgg. Patron de 03_Diagnostico/: standalone,
[OK]/[FAIL], sys.exit (no usa pytest).

    python test_bgg.py
    # smoke real opcional (NO afecta al exit code):
    #   set BGG_SMOKE=1   (Windows)   -> consulta BGG de verdad (necesita internet)

Cubre SIN RED (mockeando requests.get con fixtures XML):
  - parseo de /search: boardgame->base, boardgameexpansion->expansion.
  - exact -> laxo (segundo intento) cuando el exact no devuelve nada.
  - caché hit/miss (el hit NO vuelve a llamar a la red), centinela not_found + TTL.
  - escritura atomica (se crea bgg_cache.json).
  - degradacion a None ante error de red, 202/429 agotados, timeout, XML invalido.
  - integracion main._refine_categories_with_bgg: enabled=false -> idéntico;
    enabled=true + lookup->expansion -> base pasa a expansion.
"""

import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

import requests          # noqa: E402
import bgg               # noqa: E402
import main              # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# --- Fixtures XML (XMLAPI2 /search) ----------------------------------------
XML_BASE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<items total="1">'
    '  <item type="boardgame" id="13">'
    '    <name type="primary" value="Catan"/>'
    '    <yearpublished value="1995"/>'
    '  </item>'
    '</items>'
)
XML_EXP = (
    '<items total="1">'
    '  <item type="boardgameexpansion" id="205">'
    '    <name type="primary" value="Rising Sun: Kami Unbound"/>'
    '  </item>'
    '</items>'
)
XML_EMPTY = '<items total="0"></items>'
XML_BROKEN = '<items total="1"><item type="boardgame" id="1">'   # sin cerrar


# --- Mock de red: cola de respuestas, cuenta llamadas ----------------------
class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeNet:
    """Sustituye a bgg.requests.get. Devuelve respuestas de una cola; si el
    elemento es una Exception, la lanza (para simular errores de red)."""
    def __init__(self):
        self.queue = []
        self.calls = 0

    def __call__(self, url, params=None, timeout=None, headers=None):
        self.calls += 1
        if not self.queue:
            raise AssertionError("FakeNet: cola vacia (llamada de red inesperada)")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_TMPDIR = tempfile.mkdtemp(prefix="bgg_test_")
net = FakeNet()


def setup_module():
    """Aisla cada escenario: red mockeada, caché en tmp, sin sleeps reales."""
    bgg.requests.get = net
    bgg.time.sleep = lambda *a, **k: None
    bgg._MAX_RETRIES = 2
    bgg._RETRY_WAIT = 0.0
    bgg._CACHE_TTL_DAYS = 30


def reset(queue):
    """Caché vacia + cola de respuestas para el siguiente escenario."""
    bgg._CACHE = None
    bgg._CACHE_PATH = os.path.join(_TMPDIR, "bgg_cache.json")
    try:
        os.remove(bgg._CACHE_PATH)
    except OSError:
        pass
    net.queue = list(queue)
    net.calls = 0


setup_module()


# --- 1) Parseo y mapeo de tipos --------------------------------------------
reset([FakeResp(200, XML_BASE)])
r = bgg.lookup("Catan")
check("boardgame -> base", r == {"bgg_id": "13", "name": "Catan", "kind": "base"},
      f"r={r}")

reset([FakeResp(200, XML_EXP)])
r = bgg.lookup("Rising Sun Kami Unbound")
check("boardgameexpansion -> expansion",
      r is not None and r["kind"] == "expansion" and r["bgg_id"] == "205", f"r={r}")


# --- 2) exact -> laxo (segundo intento) ------------------------------------
reset([FakeResp(200, XML_EMPTY), FakeResp(200, XML_BASE)])
r = bgg.lookup("Catan algo raro")
check("exact vacio -> reintenta laxo y encuentra base",
      r is not None and r["kind"] == "base", f"r={r} calls={net.calls}")
check("exact->laxo hace 2 llamadas de red", net.calls == 2, f"calls={net.calls}")


# --- 3) No encontrado -> None + centinela cacheado -------------------------
reset([FakeResp(200, XML_EMPTY), FakeResp(200, XML_EMPTY)])
r = bgg.lookup("Cosa Que No Existe BGG")
check("sin candidatos -> None", r is None, f"r={r}")
prev = net.calls
r2 = bgg.lookup("Cosa Que No Existe BGG")    # debe salir de caché (not_found fresco)
check("not_found cacheado -> None sin red", r2 is None and net.calls == prev,
      f"calls={net.calls} prev={prev}")


# --- 4) Caché hit: la 2a consulta NO llama a la red ------------------------
reset([FakeResp(200, XML_BASE)])
bgg.lookup("Catan")
calls_after_first = net.calls
bgg.lookup("CATAN  ")                          # misma clave normalizada
check("caché hit (mismo titulo normalizado) -> 0 red extra",
      net.calls == calls_after_first, f"calls={net.calls}")
check("escritura atomica: bgg_cache.json existe",
      os.path.exists(bgg._CACHE_PATH))


# --- 5) TTL: not_found caducado se reconsulta ------------------------------
reset([FakeResp(200, XML_EMPTY), FakeResp(200, XML_EMPTY),
       FakeResp(200, XML_BASE)])
bgg.lookup("Titulo Caducable")                 # cachea not_found (2 llamadas)
# Forzamos el centinela a una fecha vieja (caducada).
key = bgg._cache_key("Titulo Caducable")
bgg._get_cache()[key] = {"not_found": True, "ts": "2000-01-01"}
r = bgg.lookup("Titulo Caducable")             # caducado -> reconsulta -> base
check("not_found caducado -> reconsulta y encuentra", r is not None and r["kind"] == "base",
      f"r={r}")


# --- 6) Degradacion elegante: nunca lanza, devuelve None -------------------
reset([requests.RequestException("boom red"),
       requests.RequestException("boom red")])
check("error de red -> None (no lanza)", bgg.lookup("Catan") is None)

reset([FakeResp(202), FakeResp(202), FakeResp(202),     # exact: 202 agotado
       FakeResp(202), FakeResp(202), FakeResp(202)])     # laxo: 202 agotado
check("HTTP 202 agotado -> None", bgg.lookup("Catan") is None)

reset([FakeResp(429), FakeResp(429), FakeResp(429),
       FakeResp(429), FakeResp(429), FakeResp(429)])
check("HTTP 429 agotado -> None", bgg.lookup("Catan") is None)

reset([FakeResp(500), FakeResp(500)])
check("HTTP 500 -> None", bgg.lookup("Catan") is None)

reset([FakeResp(200, XML_BROKEN), FakeResp(200, XML_BROKEN)])
check("XML invalido -> None", bgg.lookup("Catan") is None)


# --- 7) Normalizacion de titulos -------------------------------------------
check("_cache_key normaliza tildes/mayus/simbolos",
      bgg._cache_key("  Catán!! ") == "catan")
cleaned = bgg._clean_title("🔥 Catan juego de mesa 30€ HAGO ENVIOS")
check("_clean_title quita ruido/precio/emoji",
      "Catan" in cleaned and "30" not in cleaned and "mesa" not in cleaned.lower(),
      f"cleaned={cleaned!r}")


# --- 8) Integracion main._refine_categories_with_bgg -----------------------
ITEMS = [
    {"id": "a", "title": "Frostpunk"},
    {"id": "b", "title": "Rising Sun Kami Unbound"},
    {"id": "c", "title": "Inserto Frostpunk"},
]
CATS = ["base", "base", "components"]

# enabled=false -> identico (no toca nada, ni llama a lookup)
bgg._BGG_ENABLED = False
out = main._refine_categories_with_bgg(ITEMS, CATS)
check("BGG off: categorias identicas", out == CATS, f"out={out}")

# enabled=true: lookup mockeado. 'b' es expansion -> base pasa a expansion;
# 'a' es base (se queda base); 'c' es components (no se toca aunque BGG opine).
def _fake_lookup(title):
    if "kami unbound" in title.lower():
        return {"bgg_id": "205", "name": "Rising Sun: Kami Unbound", "kind": "expansion"}
    if "frostpunk" in title.lower():
        return {"bgg_id": "300", "name": "Frostpunk: The Board Game", "kind": "base"}
    return None

_orig_lookup = bgg.lookup
bgg.lookup = _fake_lookup
bgg._BGG_ENABLED = True
out = main._refine_categories_with_bgg(ITEMS, CATS)
check("BGG on: 'b' base->expansion", out == ["base", "expansion", "components"],
      f"out={out}")

# lookup que no reconoce -> NO degrada (base se queda base)
bgg.lookup = lambda title: None
out2 = main._refine_categories_with_bgg(ITEMS, CATS)
check("BGG on pero sin reconocer -> base intacto (dejar pasar)",
      out2 == CATS, f"out2={out2}")

bgg.lookup = _orig_lookup
bgg._BGG_ENABLED = False

# configure_from_settings respeta el flag del yaml
bgg.configure_from_settings({"bgg": {"enabled": True}})
check("configure_from_settings(enabled:true)", bgg.bgg_enabled() is True)
bgg.configure_from_settings({"bgg": {"enabled": False}})
check("configure_from_settings(enabled:false)", bgg.bgg_enabled() is False)


# --- 9) Smoke real opcional (no afecta al exit code) -----------------------
if os.getenv("BGG_SMOKE"):
    print("\n[smoke BGG real] BGG_SMOKE presente; consultando BGG de verdad...")
    # restauramos la red real (el resto del fichero usaba el mock)
    import importlib
    importlib.reload(bgg)
    try:
        r = bgg.lookup("Catan")
        print(f"  lookup('Catan') -> {r}")
        r2 = bgg.lookup("Rising Sun")
        print(f"  lookup('Rising Sun') -> {r2}")
    except Exception as e:    # el smoke nunca debe tumbar el test
        print(f"  [SVC] BGG no disponible: {e}")
else:
    print("\n[smoke BGG real] omitido (sin BGG_SMOKE). Tests con fixtures mockeadas.")


print()
if fails:
    print(f"RESULTADO: {len(fails)} FALLOS -> {fails}")
    sys.exit(1)
print("RESULTADO: TODO OK")
sys.exit(0)
