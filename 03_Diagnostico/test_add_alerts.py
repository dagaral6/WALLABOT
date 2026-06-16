# -*- coding: utf-8 -*-
"""Test del comando AÑADIR (incremental). No usa red.
Verifica _apply_add (merge sin tocar el resto, dedupe por nombre) y
_extract_added_alerts (parsea el bloque alerts: ignorando firmas)."""
import os, sys, tempfile, shutil
import yaml

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "01_Core")
sys.path.insert(0, CORE)
import config_inbox as ci

ok = True
def check(cond, msg):
    global ok
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond: ok = False

tmp = tempfile.mkdtemp(prefix="wallabot_add_")
ci.CONFIGS_DIR = tmp
ci.BACKUPS_DIR = os.path.join(tmp, "backups")

# Config de partida: email + location + 2 alertas
base = {
    "email": {"smtp_host": "smtp.gmail.com", "recipient": "dario@x.com"},
    "location": {"latitude": 39.47, "longitude": -0.37, "radius_km": 25},
    "use_ai": True,
    "alerts": [
        {"name": "Catan (base, hasta 25€)", "keywords": "catan", "max_price": 25},
        {"name": "Root", "keywords": "root"},
    ],
    "lote_bypass_price": True,
}
with open(os.path.join(tmp, "dario.yaml"), "w", encoding="utf-8") as f:
    yaml.safe_dump(base, f, allow_unicode=True, sort_keys=False)

# 1) Añadir una nueva (Wingspan) + una duplicada por nombre (CATAN en otro caso)
new_alerts = [
    {"name": "Wingspan (hasta 40€)", "keywords": "wingspan", "max_price": 40},
    {"name": "catan (BASE, hasta 25€)", "keywords": "catan"},  # ya existe (case-insensitive)
]
added, skipped, all_names = ci._apply_add("dario", new_alerts)
check(added == ["Wingspan (hasta 40€)"], "agrega solo la nueva: %s" % added)
check(len(skipped) == 1, "salta 1 duplicada: %s" % skipped)
check(len(all_names) == 3, "quedan 3 alertas: %s" % all_names)

# El archivo conserva email/location y suma la nueva
with open(os.path.join(tmp, "dario.yaml"), "r", encoding="utf-8") as f:
    after = yaml.safe_load(f)
names = [a["name"] for a in after["alerts"]]
check(after.get("email", {}).get("recipient") == "dario@x.com", "conserva email.recipient")
check(after.get("location", {}).get("radius_km") == 25, "conserva location")
check("Wingspan (hasta 40€)" in names, "Wingspan persistida")
check("Catan (base, hasta 25€)" in names and "Root" in names, "no borra las previas")

# 2) Re-añadir la misma: no duplica
added2, skipped2, all2 = ci._apply_add("dario", [{"name": "Wingspan (hasta 40€)", "keywords": "wingspan"}])
check(added2 == [] and len(all2) == 3, "no duplica al reenviar: added=%s total=%s" % (added2, len(all2)))

# 3) Config inexistente -> (None, [], None)
a3, s3, n3 = ci._apply_add("noexiste", new_alerts)
check(a3 is None and n3 is None, "config inexistente devuelve None")

# 4) _extract_added_alerts: marcador + alerts + firma basura al final
body = (
    "Anyadir alertas a la configuracion de Dario.\n"
    "Juegos: Azul\n\n"
    "----- config_dario.yaml -----\n"
    "alerts:\n"
    '  - name: "Azul (hasta 30€)"\n'
    '    keywords: "azul"\n'
    "    max_price: 30\n"
    "\n--\nEnviado desde mi iPhone\n"
)
extracted = ci._extract_added_alerts(body)
check(isinstance(extracted, list) and len(extracted) == 1, "extrae 1 alerta del cuerpo")
check(extracted and extracted[0].get("name") == "Azul (hasta 30€)", "nombre correcto: %s"
      % (extracted[0] if extracted else None))

shutil.rmtree(tmp, ignore_errors=True)
print("\n=== RESULTADO:", "TODO OK ===" if ok else "HAY FALLOS ===")
sys.exit(0 if ok else 1)
