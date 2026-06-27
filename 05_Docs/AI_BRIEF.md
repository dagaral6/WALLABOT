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
- `classifier.py`: clasificación por **reglas** deterministas (base/expansión/componentes/lote/no-juego) + dos usos del **NLI VIVO** (Hugging Face zero-shot, mismo motor `_nli_hf_zeroshot`, secret `HF_API_TOKEN`): **gate de relevancia** (`relevance.*`) para keywords ambiguas y **validación de categoría OPCIONAL** (`category_nli.*`) que, sobre la descripción, corrige `base`→`expansión`/`componentes` (las reglas siguen siendo el primer filtro). La cascada LLM cloud + circuit breaker + clasificación por lotes (`batch_size`) sigue en el código pero **inerte** (retirada).
- `bgg.py`: refuerzo OPCIONAL con BoardGameGeek (XMLAPI2). `bgg.categorize(título, descripción)` confirma si es un juego real y detecta expansión por el título o porque la **descripción** nombra una expansión concreta del juego base (expansiones del base vía `thing`, con guarda anti-«compatible»); caché persistente en `bgg_cache.json`, degradación elegante. Reversible (`bgg.enabled` en `bot_settings.yaml`).
- `database.py`: SQLite `alerts.db`. Guarda histórico de alertas eliminadas sin borrar filas (`deleted_reason`/`deleted_at`, `mark_alert_deleted()`).
- `notifier.py`: emails Gmail.
- `config_inbox.py`: lee configs por correo (crear/añadir/borrar; el borrado lleva un motivo por alerta y marca el histórico en la BD).
- `manage.py`: alta/baja/listado de usuarios.

## Reglas importantes

- Ante la duda, dejar pasar anuncios.
- El **título** decide la relevancia (`classifier.title_matches`), que además exige **orden** en keywords multi-palabra (subsecuencia con huecos, `_keyword_in_order`: "rising sun" ≠ "sun rising", sin romper "Estaciones de Inis" ni "Posadas y Catedrales"); las **reglas** clasifican base/expansión/componentes/lote/no-juego (`_classify_by_rules`).
- Para keywords **ambiguas** (una palabra común como "cities" o una frase como "rising sun"), un **gate NLI vivo** afina la relevancia SOBRE EL TÍTULO (`nli_relevance_gate`, `_RISKY_KEYWORDS`; soporta multi-palabra con orden), con fallback determinista. Se integra en `main.py:evaluate()` (rama 1, tras `title_matches`).
- La **categoría** la deciden las reglas (resultado provisional); si `category_nli.enabled`, el NLI la **valida** sobre la descripción y puede mover `base`→`componentes`/`expansión` (`_maybe_refine_category_nli`). Gateado por coste (solo cuando reglas=base + hay descripción + vocabulario de accesorio/expansión) y conservador: ante la duda mantiene las reglas, nunca descarta ni marca no-juego, no toca lotes.
- Solo interesan anuncios en español, catalán o inglés. `classifier.looks_foreign_language()` descarta el resto combinando **vocabulario** de listas y, como señal SECUNDARIA, **langdetect** sobre la DESCRIPCIÓN (umbral alto; el título no se usa, da falsos positivos por nombres propios) — se llama en `evaluate()` de `main.py` antes de cualquier LLM. Reversible (`language.*`).
- No editar configs comentados con dumps genéricos.
- No ejecutar localmente `main.py` con Actions activo salvo intención clara.
- No tocar secretos.
- No modificar `06_Backups`, `99_Obsoletos` ni `04_Logs` salvo petición explícita.

## Gotchas conocidos

- IMAP de Gmail busca por PALABRA COMPLETA, no por subcadena del header crudo: un token parcial de una palabra con tilde (p.ej. "ADIR" de "AÑADIR") nunca casa, aunque sea substring literal. `config_inbox.py` busca por la palabra completa común a los 3 asuntos (`"WALLAPOP"`) y excluye por `NOT FROM` los avisos que el propio bot se envía a sí mismo.

## Validaciones

- Backend: tests de `03_Diagnostico/` (p.ej. `test_batch.py`, `test_nli_relevance.py`, `test_bgg.py`, `test_idioma.py`, `test_category_nli.py`). Sin red (NLI/BGG mockeados).
- Config inbox: `python3 config_inbox.py --dry-run`.
- Ciclo manual: `python3 main.py --once --force`.
- Usuarios: `python3 manage.py list`.
- Validación NLI (experimental): 4 fases en `03_Diagnostico/` para evaluar un clasificador basado en NLI como alternativa a LLM cloud (ver `AI_WORKFLOWS.md` sección "Validación de clasificador NLI").

## Documentación larga

- `README.md`: uso e instalación, instalación de Ollama, configuración, multi-usuario, deploy.
- `05_Docs/DEPLOY_GITHUB_ACTIONS.md`: workflow GitHub Actions, Secrets, cadencia.
- `05_Docs/DEPLOY_RAILWAY.md`: (histórico, vía descartada).
- `05_Docs/ALTA_USUARIOS.md`: gestión de usuarios paso a paso.