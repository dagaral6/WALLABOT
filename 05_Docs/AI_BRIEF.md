# AI_BRIEF — Wallapop Alerts

Proyecto Python + HTML para alertas de juegos de mesa en Wallapop.

## Partes

- `01_Core/`: backend Python.
- `02_Herramienta/`: HTML configurador actual `wallapop_config_v18.html`.
- `03_Diagnostico/`: scripts de diagnóstico y tests.
- `05_Docs/`: documentación larga.
- GitHub Actions ejecuta el bot cada hora y commitea `alerts.db` + `configs/`.

## Backend principal

- `main.py`: orquesta ciclos, sueño nocturno, multi-config, novedades, bajas, bajadas de precio y notificaciones.
- `scraper.py`: API Wallapop + paginación.
- `classifier.py`: reglas + LLM cascade + circuit breaker.
- `database.py`: SQLite `alerts.db`.
- `notifier.py`: emails Gmail.
- `config_inbox.py`: lee configs por correo.
- `manage.py`: alta/baja/listado de usuarios.

## Reglas importantes

- Ante la duda, dejar pasar anuncios.
- El título decide relevancia; el LLM clasifica base/expansión/componentes/lote/no-juego.
- No editar configs comentados con dumps genéricos.
- No ejecutar localmente `main.py` con Actions activo salvo intención clara.
- No tocar secretos.
- No modificar `06_Backups`, `99_Obsoletos` ni `04_Logs` salvo petición explícita.

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