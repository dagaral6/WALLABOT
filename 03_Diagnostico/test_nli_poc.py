"""
test_nli_poc.py
---------------
Fase 1 del plan de validacion NLI. Prueba de concepto AISLADA: comprueba si un
modelo NLI (HF Inference API, zero-shot) distingue las categorias del proyecto
sobre un puñado de anuncios sinteticos escritos a mano.

NO toca la base de datos, NO importa classifier.py, NO toca produccion. Solo
mide si el enfoque es minimamente viable antes de gastar cuota en la Fase 2.

Patron de los tests de 03_Diagnostico/: standalone, [OK]/[FAIL], sys.exit.
Aqui un FAIL puede ser por modelo (confunde categorias) o por servicio (503/429
/timeout). Se distinguen para no descartar NLI por un cold-start pasajero.

    python test_nli_poc.py
    # opcional, antes de ejecutar:
    #   set HF_API_TOKEN=hf_...   (Windows)   /   export HF_API_TOKEN=hf_... (bash)

Puerta de paso (ver plan): >70% de aciertos en este micro-set y sin timeouts
sistematicos.
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import nli_common  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Casos de control escritos a mano: (titulo, descripcion, categoria_esperada).
# Cubren los 4 ejes + un negativo (not_game) + un ambiguo.
CASES = [
    ("Catan juego de mesa",
     "Juego base completo, como nuevo, con todas las cartas.", "base"),
    ("Wingspan Europa",
     "Solo la expansion, necesitas el juego base para jugar.", "expansion"),
    ("Insertos para Catan",
     "Solo los organizadores de plastico, no incluye el juego.", "components"),
    ("Lote de 5 juegos de mesa",
     "Vendo lote: Catan, Carcassonne, Dixit, Azul y Splendor.", "lote"),
    ("Guantes de montaña talla L",
     "Guantes tecnicos poco uso, nada que ver con juegos.", "not_game"),
    ("Meeples de madera sueltos",
     "Bolsa de fichas de madera de repuesto, varios colores.", "components"),
]

THRESHOLD = 0.70  # puerta de paso de accuracy de la Fase 1


def main():
    model = os.getenv("NLI_MODEL") or nli_common.HF_MODELS[0]
    print(f"Modelo NLI: {model}")
    print(f"(prueba multilingue con NLI_MODEL={nli_common.HF_MODELS[1]} si "
          f"falla en español)\n")

    hits, service_fails, total = 0, 0, len(CASES)
    for title, desc, expected in CASES:
        text = f"{title}. {desc}"
        try:
            cat, score, _ = nli_common.classify_nli_hf(text, model=model)
        except nli_common.NLIUnavailable as e:
            service_fails += 1
            print(f"[SVC ] {title!r} -> NLI no disponible: {e}")
            continue
        ok = (cat == expected)
        hits += int(ok)
        print(("[OK ] " if ok else "[FAIL] ") +
              f"{title!r} esperado={expected} obtenido={cat} score={score:.2f}")

    print()
    if service_fails == total:
        print("RESULTADO: SERVICIO NO DISPONIBLE (todos 503/429/timeout). "
              "No es un fallo del modelo; reintentar mas tarde o revisar "
              "HF_API_TOKEN. No descartar NLI por esto.")
        return 2

    answered = total - service_fails
    acc = hits / answered if answered else 0.0
    print(f"Aciertos: {hits}/{answered} respondidos "
          f"({service_fails} sin servicio). Accuracy = {acc:.0%}")
    if acc >= THRESHOLD:
        print(f"RESULTADO: TODO OK (>= {THRESHOLD:.0%}) -> pasa a Fase 2")
        return 0
    print(f"RESULTADO: FALLA (< {THRESHOLD:.0%}). El modelo confunde "
          f"categorias; probar el multilingue o no seguir a la Fase 2.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
