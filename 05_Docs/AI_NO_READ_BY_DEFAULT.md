# Archivos/carpetas que el agente no debe leer por defecto

No leer salvo petición explícita:

- `alerts.db`
- `04_Logs/`
- `06_Backups/`
- `99_Obsoletos/`
- versiones antiguas del HTML: `wallapop_config_v15.html`, `wallapop_config_v17.html`, `wallapop_config_v18.html`, `wallapop_config_v19.html` (la actual es `wallapop_config_v20.html`)
- respuestas crudas de Wallapop
- zips históricos
- documentación larga completa si basta con `AI_BRIEF.md`

Motivo: ruido, coste de tokens y riesgo de confundir estado histórico con estado actual.