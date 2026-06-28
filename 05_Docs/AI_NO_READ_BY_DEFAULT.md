# Archivos/carpetas que el agente no debe leer por defecto

No leer salvo petición explícita:

- `alerts.db`
- `01_Core/gamedb.json`: base de datos OFFLINE de juegos (~5 MB, generada por `03_Diagnostico/build_gamedb.py`; archivo grande, no aporta como lectura — editar el builder, no el JSON)
- `03_Diagnostico/boardgames_ranks_reducido.csv`: dump CSV fuente de `gamedb.json` (~178k filas; no abrir entero, ver `build_gamedb.py`)
- `01_Core/bgg_cache.json`: caché del antiguo módulo `bgg.py` (en desuso desde la migración a `gamedb.py`; como `alerts.db`, no aporta como lectura)
- `04_Logs/`
- `06_Backups/`
- `99_Obsoletos/`
- `03_Diagnostico/nli_dataset/`: output temporal de `build_nli_dataset.py` (se regenera en cada Fase 0)
- `03_Diagnostico/wallapop_revision_keep.html` y sus exports `.jsonl`/`.csv`: HTML de revisión manual generado por `build_review_html.py` desde `alerts.db` (se regenera; no aporta como lectura)
- versiones antiguas del HTML (v15/v17/v18/v19): ya no existen en el repo, borradas; la actual es `wallapop_config_v20.html` (histórico solo en `git log`)
- respuestas crudas de Wallapop
- zips históricos
- documentación larga completa si basta con `AI_BRIEF.md`

Motivo: ruido, coste de tokens y riesgo de confundir estado histórico con estado actual.