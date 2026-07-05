"""
diag_nli.py
-----------
Verifica si el NLI vivo (Hugging Face) está REALMENTE operativo, no solo
configurado. Tres niveles:

  1. CONFIG   : lee bot_settings.yaml y muestra el estado EFECTIVO de
                relevance / category_nli (enabled, modelo, margen) y si
                HF_API_TOKEN está presente en el entorno.
  2. FUNCIONAL: (--live) hace UNA llamada real al endpoint HF y reporta si
                responde (scores) o el error exacto (401 token, 404 modelo no
                servido, timeout...). OJO: el router de HF FACTURA por uso;
                cada --live gasta 1-2 llamadas.

Uso:
    py 03_Diagnostico/diag_nli.py            # solo config (sin red, gratis)
    py 03_Diagnostico/diag_nli.py --live     # config + prueba real (1-2 llamadas)

En GitHub Actions no hace falta ejecutarlo: basta buscar en el log de una pasada
el warning "NLI no disponible (...)". Si aparece, el NLI está caído esa pasada;
si NO aparece y hubo keywords risky/refinamiento, respondió.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import yaml          # noqa: E402
import classifier    # noqa: E402


def _load_settings():
    path = os.path.join(CORE, "bot_settings.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    live = "--live" in sys.argv
    settings = _load_settings()
    classifier.configure_from_settings(settings)   # aplica relevance/category_nli/...

    tok = os.getenv("HF_API_TOKEN")
    print("=" * 68)
    print("NIVEL 1 — CONFIGURACIÓN EFECTIVA")
    print("=" * 68)
    print(f"  relevance.enabled     : {classifier.relevance_enabled()}")
    print(f"  category_nli.enabled  : {classifier.category_nli_enabled()}")
    print(f"  modelo NLI            : {classifier._NLI_MODEL}")
    print(f"  margen relevancia     : {classifier._NLI_MARGIN}")
    print(f"  margen categoría      : {classifier._CATEGORY_NLI_MARGIN}")
    print(f"  endpoint              : {classifier._NLI_API_URL}")
    print(f"  HF_API_TOKEN presente : {'SÍ' if tok else 'NO'}"
          + ("" if tok else "  <-- sin token, el router HF da 401 -> fallback"))

    if not live:
        print("\n(Sin --live no se hace ninguna llamada de red. Añade --live para "
              "la prueba funcional real, que gasta 1-2 llamadas facturables.)")
        return 0

    print("\n" + "=" * 68)
    print("NIVEL 2 — PRUEBA FUNCIONAL (llamada real al endpoint)")
    print("=" * 68)
    if not tok:
        print("  ABORTADO: no hay HF_API_TOKEN en el entorno. Expórtalo primero:")
        print('    (PowerShell)  $env:HF_API_TOKEN="hf_xxx"')
        print("  o mira los logs de Actions (allí sí está el Secret).")
        return 1

    # Reseteamos el cortocircuito por si una prueba previa lo activó en el proceso.
    classifier._NLI_UNAVAILABLE = False
    try:
        scores = classifier._nli_hf_zeroshot(
            "Juego de mesa Lost Cities Roll & Write de Devir.",
            ["el juego de mesa Cities de Devir",
             "otro juego diferente que contiene «cities»"])
        print("  ✅ El endpoint RESPONDE. Scores devueltos:")
        for label, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
            print(f"       {sc:6.3f}  {label}")
        print("\n  => El NLI vivo está OPERATIVO. La relevancia y la categoría "
              "usan el modelo, no solo el fallback.")
        return 0
    except RuntimeError as e:
        print(f"  ❌ El endpoint NO responde: {e}")
        print("     El bot cae al fallback determinista (relevancia) / reglas "
              "(categoría). Revisa: token válido, modelo servido (404 = no), cuota.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
