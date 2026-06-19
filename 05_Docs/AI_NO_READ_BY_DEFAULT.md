# Archivos/carpetas que el agente no debe leer por defecto

No leer salvo petición explícita:

- `alerts.db`
- `04_Logs/`
- `06_Backups/`
- `99_Obsoletos/`
- versiones antiguas del HTML (v15/v17/v18/v19): ya no existen en el repo, borradas; la actual es `wallapop_config_v20.html` (histórico solo en `git log` o `CONTEXT.md`)
- respuestas crudas de Wallapop
- zips históricos
- documentación larga completa si basta con `AI_BRIEF.md`

Motivo: ruido, coste de tokens y riesgo de confundir estado histórico con estado actual.