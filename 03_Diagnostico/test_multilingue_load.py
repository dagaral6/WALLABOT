"""
test_multilingue_load.py
------------------------
Fase 0: Valida que el modelo multilingüe `joeddav/xlm-roberta-large-xnli`
carga correctamente y funciona en español.

Uso:
    py test_multilingue_load.py
"""

import sys
import time

try:
    from transformers import pipeline
except ImportError:
    print("[FAIL] transformers no instalado")
    sys.exit(1)

MODEL = "joeddav/xlm-roberta-large-xnli"

def test_load():
    """Intenta cargar el modelo."""
    print(f"Cargando {MODEL}...")
    t0 = time.time()
    try:
        clf = pipeline("zero-shot-classification", model=MODEL)
        elapsed = time.time() - t0
        print(f"[OK ] Modelo cargado en {elapsed:.1f}s")
        return clf
    except Exception as e:
        print(f"[FAIL] Error cargando modelo: {e}")
        sys.exit(1)


def test_inference(clf):
    """Intenta hacer una inferencia en español."""
    print("\nProbando inferencia en español...")
    text = "Vendo el juego de mesa Catan completo en buen estado."
    labels = [
        "un juego de mesa completo",
        "una expansion de un juego de mesa",
        "componentes o accesorios sueltos",
        "un lote de varios juegos",
        "algo que no es un juego de mesa",
    ]
    try:
        result = clf(text, candidate_labels=labels,
                     hypothesis_template="Este anuncio trata de {}.")
        print(f"[OK ] Inferencia exitosa")
        print(f"     Texto: {text}")
        print(f"     Top 3 resultados:")
        for i, (label, score) in enumerate(zip(result["labels"][:3],
                                                result["scores"][:3]), 1):
            print(f"       {i}. {label}: {score:.2%}")
        return True
    except Exception as e:
        print(f"[FAIL] Error en inferencia: {e}")
        return False


def main():
    print("=" * 70)
    print("FASE 0: Validación modelo multilingüe")
    print("=" * 70)

    clf = test_load()
    success = test_inference(clf)

    print("\n" + "=" * 70)
    if success:
        print("RESULTADO: [OK ] Modelo multilingüe listo para Fase 1")
        print("=" * 70)
        return 0
    else:
        print("RESULTADO: [FAIL] Problemas con el modelo")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
