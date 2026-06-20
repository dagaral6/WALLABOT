"""
test_nli_local_runtime.py
-------------------------
Fase 3 del plan de validacion NLI. Mide si correr un modelo NLI LOCAL (sin API
externa) dentro de un runner de GitHub Actions es viable en TIEMPO y TAMAÑO.

La segunda pata de la cascada hibrida propuesta era: si la HF Inference API se
agota (cuota), caer a un modelo NLI local cargado en el propio runner. Eso solo
tiene sentido si descargar + cargar + inferir cabe holgadamente en el job de
Actions (minutos limitados en el plan gratuito) y no se redescarga en cada run.

Este script NO toca produccion ni la BD. Requiere la libreria `transformers`
(zero-shot pipeline). Si no esta instalada, lo dice y termina sin fallar el
proceso global (es una medicion opcional, no un test de regresion).

    pip install transformers torch        # solo para esta medicion
    python test_nli_local_runtime.py

Puerta de paso (ver plan): el tiempo total (descarga 1a vez + carga + inferencia
del volumen real por ciclo) cabe con margen en el timeout del job de Actions.
"""

import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import nli_common  # noqa: E402

# Nº de anuncios que aproxima un ciclo real (alinear con llm.batch_size del
# bot_settings.yaml, 25 por defecto; aqui multiplicamos para simular varias
# alertas por pasada).
SIM_ITEMS = int(os.getenv("NLI_SIM_ITEMS", "50"))


def main():
    try:
        from transformers import pipeline
    except ImportError:
        print("transformers no instalado. Esta medicion es opcional:")
        print("  pip install transformers torch")
        print("RESULTADO: OMITIDO (sin transformers)")
        return 0

    model = os.getenv("NLI_MODEL") or nli_common.HF_MODELS[1]  # multilingue
    labels = list(nli_common.LABELS.values())

    print(f"Modelo local: {model}")
    print(f"Simulando {SIM_ITEMS} anuncios por ciclo\n")

    t0 = time.time()
    clf = pipeline("zero-shot-classification", model=model)
    t_load = time.time() - t0
    print(f"Descarga + carga del modelo: {t_load:.1f}s")

    sample = "Catan juego de mesa base completo, como nuevo."
    texts = [sample] * SIM_ITEMS

    t1 = time.time()
    for t in texts:
        clf(t, candidate_labels=labels,
            hypothesis_template=nli_common.HYPOTHESIS_TEMPLATE)
    t_infer = time.time() - t1
    print(f"Inferencia {SIM_ITEMS} anuncios: {t_infer:.1f}s "
          f"({t_infer / SIM_ITEMS:.2f}s/anuncio)")

    total = t_load + t_infer
    print(f"\nTotal estimado por ciclo (1a vez, sin cache): {total:.1f}s")
    print("Nota: con cache del modelo entre runs, t_load baja mucho; medir "
          "tambien el caso con cache antes de decidir.")
    print("\nRESULTADO: comparar 'Total' contra el timeout del job de Actions "
          "(.github/workflows/wallabot.yml). Debe caber con MARGEN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
