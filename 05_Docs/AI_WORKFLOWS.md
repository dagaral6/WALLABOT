# Workflows para agentes

## Cambio en backend Python

1. Leer `AI_BRIEF.md`.
2. Buscar símbolos con `rg`.
3. Abrir solo archivos de `01_Core/` relacionados.
4. Si afecta clasificación: revisar `classifier.py`, `main.py`, tests de `03_Diagnostico/`.
5. Ejecutar tests relevantes.
6. Mostrar diff.

## Cambio en configurador HTML

1. Si es cambio menor, editar `02_Herramienta/wallapop_config_v20.html`.
2. Si es cambio estructural, revisar fuente React si está disponible.
3. Respetar que v20 es la versión actual.
4. No tocar v15/v17/v18/v19 salvo referencia histórica.
5. **GitHub Pages sincronización**: después de editar v20, copiar también a `docs/index.html`
   (ambas deben quedar idénticas para que la URL pública sirva siempre la versión actualizada).

## Cambio en usuarios/configs

1. Preferir `manage.py`.
2. No editar `bot_settings.yaml` a ciegas.
3. No sobrescribir YAMLs comentados con serialización completa.
4. Verificar con `python manage.py list`.

## Cambio en GitHub Actions

1. Leer `05_Docs/DEPLOY_GITHUB_ACTIONS.md`.
2. Recordar que el workflow commitea `alerts.db` y `configs/`.
3. Mantener `git pull --rebase --autostash` antes de `git add`.
4. No romper el gate de sueño nocturno (01-07 Madrid, coincidir entre `bot_settings.yaml` y `.github/workflows/wallabot.yml`).

## Cambio en clasificador

1. Revisar `classifier.py`.
2. Revisar tests `test_cascade.py`, `test_llm_cloud.py`, `test_new_providers.py`, `test_batch.py` (cascada LLM, hoy inerte).
3. Mantener fail-fast ante 429.
4. Mantener fallback `rules` (también en la clasificación por lotes: índice ausente o JSON inválido → reglas, nunca se descarta).
5. Ante duda, preferir false positive a anuncio perdido.
6. Mantener el filtro de idioma (`looks_foreign_language`, solo es/ca/en) en `evaluate()` de `main.py`.

## Cambio en el gate de relevancia (NLI) o en BGG

Gate NLI de relevancia para keywords ambiguas (`_RISKY_KEYWORDS`, `nli_relevance_gate`):

1. Vive en `classifier.py`; se integra en `main.py:evaluate()` (rama 1, tras `title_matches`).
2. Decide SOLO sobre el TÍTULO. Soporta keywords de una palabra ("cities") y frases multi-palabra con orden ("rising sun", `_phrase_in_order`).
3. NLI vivo (Hugging Face, secret `HF_API_TOKEN`, `relevance.*` en `bot_settings.yaml`) con **fallback determinista** (confusores + regla de orden). Mantener siempre el fallback: ante la duda, dejar pasar.
4. Test: `py 03_Diagnostico/test_nli_relevance.py` (sin red; smoke vivo opcional con `HF_API_TOKEN`).

Refuerzo BGG (`bgg.py`, BoardGameGeek XMLAPI2):

1. Módulo AUTÓNOMO (no importa de `classifier`/`main`). Integración en `main.py:_refine_categories_with_bgg` (solo mueve base→expansion). Flag `bgg.enabled` (false por defecto).
2. Degradación elegante: ante red/timeout/202/429/parseo devuelve `None` y sigue como hoy. Caché en `01_Core/bgg_cache.json` (la commitea Actions vía `git add -A 01_Core`).
3. Test: `py 03_Diagnostico/test_bgg.py` (fixtures mockeadas; smoke real opcional con `BGG_SMOKE=1`).

## Validación de clasificador NLI (experimental)

Flujo en 4 fases para evaluar un clasificador basado en NLI (Natural Language Inference)
como alternativa a la cascada LLM actual, SIN tocar código de producción:

1. **Fase 0:** `py 03_Diagnostico/build_nli_dataset.py` — extrae ground truth de `alerts.db`
   (anuncios ya clasificados) a `03_Diagnostico/nli_dataset/cases.jsonl`. Puerta: ≥50 casos/categoría.
   Cada caso incluye `description` (clave para el NLI): los `keep` la tienen desde siempre; los
   `reject` solo a partir de jun 2026 (antes se guardaban con `description` NULL), así que los
   `reject` históricos saldrán sin descripción hasta que el bot los vuelva a ver y regrabe.
2. **Fase 1:** `py 03_Diagnostico/test_nli_poc.py` — viabilidad sobre 6 anuncios sintéticos.
   Requiere `HF_API_TOKEN` (gratis, Hugging Face Inference API). Puerta: >70% accuracy.
3. **Fase 2:** `py 03_Diagnostico/compare_nli_vs_current.py` — compara NLI masivo vs el sistema
   actual; matriz de confusión + métricas críticas (falsos rechazos). Requiere Fase 0.
4. **Fase 3:** `py 03_Diagnostico/test_nli_local_runtime.py` — mide tiempo de inferencia local
   (sentence-transformers) en condiciones de GitHub Actions. Requiere `transformers` + `torch`.

Ver `C:\Users\Pc\.claude\plans\expl-came-si-tocar-nada-parsed-sifakis.md` para el plan completo.

## Cambio en correo entrante (config_inbox.py)

1. La búsqueda IMAP en Gmail es por palabra completa, no por subcadena: no usar tokens parciales de palabras con tilde como criterio de búsqueda.
2. Si se añade un nuevo tipo de asunto, comprobarlo en vivo con `python config_inbox.py --dry-run` antes de asumir que el `SUBJECT` search lo encuentra.