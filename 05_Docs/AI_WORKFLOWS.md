# Workflows para agentes

## Cambio en backend Python

1. Leer `AI_BRIEF.md`.
2. Buscar símbolos con `rg`.
3. Abrir solo archivos de `01_Core/` relacionados.
4. Si afecta clasificación: revisar `classifier.py`, `main.py`, tests de `03_Diagnostico/`.
5. Ejecutar tests relevantes.
6. Mostrar diff.

## Cambio en configurador HTML

1. Si es cambio menor, editar `02_Herramienta/wallapop_config_v18.html`.
2. Si es cambio estructural, revisar fuente React si está disponible.
3. Respetar que v18 es la versión actual.
4. No tocar v15/v17 salvo referencia histórica.

## Cambio en usuarios/configs

1. Preferir `manage.py`.
2. No editar `bot_settings.yaml` a ciegas.
3. No sobrescribir YAMLs comentados con serialización completa.
4. Verificar con `python manage.py list`.

## Cambio en GitHub Actions

1. Leer sección deploy en `CONTEXT.md`.
2. Recordar que el workflow commitea `alerts.db` y `configs/`.
3. Mantener `git pull --rebase --autostash` antes de `git add`.
4. No romper el gate de sueño nocturno.

## Cambio en clasificador

1. Revisar `classifier.py`.
2. Revisar tests `test_cascade.py`, `test_llm_cloud.py`, `test_new_providers.py`.
3. Mantener fail-fast ante 429.
4. Mantener fallback `rules`.
5. Ante duda, preferir false positive a anuncio perdido.