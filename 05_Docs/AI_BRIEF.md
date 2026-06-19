# AI_BRIEF — Wallapop Alerts

Proyecto Python + HTML para alertas de juegos de mesa en Wallapop.

## Partes

- `01_Core/`: backend Python.
- `02_Herramienta/`: HTML configurador actual `wallapop_config_v20.html`.
- `docs/index.html`: copia de v20 publicada en GitHub Pages (formulario público); debe mantenerse idéntica a v20.
- `03_Diagnostico/`: scripts de diagnóstico y tests.
- `05_Docs/`: documentación larga.
- GitHub Actions ejecuta el bot cada 2 horas y commitea `alerts.db` + `configs/`.

## Backend principal

- `main.py`: orquesta ciclos, sueño nocturno, multi-config, novedades, bajas, bajadas de precio y notificaciones.
- `scraper.py`: API Wallapop + paginación.
- `classifier.py`: reglas + LLM cascade + circuit breaker + clasificación por lotes (`batch_size` en `bot_settings.yaml`, evita 429 en pasadas grandes).
- `database.py`: SQLite `alerts.db`. Guarda histórico de alertas eliminadas sin borrar filas (`deleted_reason`/`deleted_at`, `mark_alert_deleted()`).
- `notifier.py`: emails Gmail.
- `config_inbox.py`: lee configs por correo (crear/añadir/borrar; el borrado lleva un motivo por alerta y marca el histórico en la BD).
- `manage.py`: alta/baja/listado de usuarios.

## Reglas importantes

- Ante la duda, dejar pasar anuncios.
- El título decide relevancia; el LLM clasifica base/expansión/componentes/lote/no-juego.
- Solo interesan anuncios en español, catalán o inglés. `classifier.looks_foreign_language()` descarta el resto (se asume que un anuncio en otro idioma es el juego en ese idioma) — se llama en `evaluate()` de `main.py` antes de cualquier LLM.
- No editar configs comentados con dumps genéricos.
- No ejecutar localmente `main.py` con Actions activo salvo intención clara.
- No tocar secretos.
- No modificar `06_Backups`, `99_Obsoletos` ni `04_Logs` salvo petición explícita.

## Gotchas conocidos

- IMAP de Gmail busca por PALABRA COMPLETA, no por subcadena del header crudo: un token parcial de una palabra con tilde (p.ej. "ADIR" de "AÑADIR") nunca casa, aunque sea substring literal. `config_inbox.py` busca por la palabra completa común a los 3 asuntos (`"WALLAPOP"`) y excluye por `NOT FROM` los avisos que el propio bot se envía a sí mismo.

## Validaciones

- Backend: tests de `03_Diagnostico/`.
- Config inbox: `python3 config_inbox.py --dry-run`.
- Ciclo manual: `python3 main.py --once --force`.
- Usuarios: `python3 manage.py list`.

## Documentación larga

- `README.md`: uso e instalación.
- `CONTEXT.md`: arquitectura, decisiones, deploy, HTML, historial.
- `05_Docs/DEPLOY_GITHUB_ACTIONS.md`: workflow.
- `05_Docs/ALTA_USUARIOS.md`: usuarios.