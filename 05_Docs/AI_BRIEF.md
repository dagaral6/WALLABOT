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
- `gamedb.py`: refuerzo OPCIONAL de categoría con una base de datos **OFFLINE** de juegos (`01_Core/gamedb.json`, compilada por `03_Diagnostico/build_gamedb.py` desde un dump CSV). Sustituye a `bgg.py` (la XMLAPI2 de BoardGameGeek cerró el acceso anónimo, 401, en 2025). `gamedb.categorize(título, descripción)` identifica el juego del título (índice de nombres inglés + traducción) y detecta **expansión** por el propio título o porque la **descripción** nombra una expansión concreta del juego base (guarda anti-«compatible»). Sin red ni token → determinista en GitHub Actions; degradación elegante. Reversible (`bgg.enabled` en `bot_settings.yaml`; se lee por compatibilidad). `main.py` lo importa como `import gamedb as bgg`. `bgg.py` se conserva en el repo sin uso.
- `database.py`: SQLite `alerts.db`. Guarda histórico de alertas eliminadas sin borrar filas (`deleted_reason`/`deleted_at`, `mark_alert_deleted()`).
- `notifier.py`: emails Gmail.
- `config_inbox.py`: lee configs por correo (crear/añadir/borrar; el borrado lleva un motivo por alerta y marca el histórico en la BD).
- `manage.py`: alta/baja/listado de usuarios.

## Reglas importantes

- Ante la duda, dejar pasar anuncios.
- El **título** decide la relevancia (`classifier.title_matches`), que además exige **orden** en keywords multi-palabra (subsecuencia con huecos, `_keyword_in_order`: "rising sun" ≠ "sun rising", sin romper "Estaciones de Inis" ni "Posadas y Catedrales") y **especificidad**: en un término multi-palabra, una sola coincidencia no basta si es la palabra más genérica (mayor frecuencia `wordfreq`, `_word_freq`) habiendo otras más distintivas sin casar ("castillos burgundy borgoña" ≠ "Castillos de Arena", pero "inis" sí basta en "estaciones inis"). Las **reglas** clasifican base/expansión/componentes/lote/no-juego (`_classify_by_rules`), y marcan **componentes** desde la DESCRIPCIÓN por frases inequívocas de "solo accesorio / no incluye juego" (`_components_only_in_desc`/`_components_hard_in_desc`), sin depender del NLI.
- Para keywords **ambiguas** (una palabra común como "cities", una frase como "rising sun", o "carcassone", que cuela juegos distintos de la marca como "La Niebla sobre Carcassonne"), un **gate NLI vivo** afina la relevancia SOBRE EL TÍTULO (`nli_relevance_gate`, `_RISKY_KEYWORDS`; soporta multi-palabra con orden), con fallback determinista (sin confusores → "relevant", 0 regresiones sin servicio). Se integra en `main.py:evaluate()` (rama 1, tras `title_matches`). `carcassone` se apoya solo en el NLI vivo: validar con `03_Diagnostico/diag_carcassone_nli.py` que no rechaza ediciones legítimas del base. La rama de lotes (`check_lote`) además VETA los "lotes" de cajas vacías/componentes (frase dura de `_components_hard_in_desc`).
- La **categoría** la deciden las reglas (resultado provisional); si `category_nli.enabled`, el NLI la **valida** sobre la descripción y puede mover `base`→`componentes`/`expansión` (`_maybe_refine_category_nli`). Gateado por coste (solo cuando reglas=base + hay descripción + vocabulario de accesorio/expansión) y conservador: ante la duda mantiene las reglas, nunca descarta ni marca no-juego, no toca lotes.
- Solo interesan anuncios en español, catalán o inglés. `classifier.looks_foreign_language()` descarta el resto combinando **vocabulario** de listas y, como señal SECUNDARIA, **langdetect** sobre la DESCRIPCIÓN (umbral alto; el título no se usa, da falsos positivos por nombres propios) — se llama en `evaluate()` de `main.py` antes de cualquier LLM. Reversible (`language.*`).
- No editar configs comentados con dumps genéricos.
- No ejecutar localmente `main.py` con Actions activo salvo intención clara.
- No tocar secretos.
- No modificar `06_Backups`, `99_Obsoletos` ni `04_Logs` salvo petición explícita.

## Gotchas conocidos

- IMAP de Gmail busca por PALABRA COMPLETA, no por subcadena del header crudo: un token parcial de una palabra con tilde (p.ej. "ADIR" de "AÑADIR") nunca casa, aunque sea substring literal. `config_inbox.py` busca por la palabra completa común a los 3 asuntos (`"WALLAPOP"`) y excluye por `NOT FROM` los avisos que el propio bot se envía a sí mismo.
- Normalización Unicode: `classifier._normalize` aplica **NFC** antes de comparar. Algunos títulos de Wallapop llegan en forma descompuesta (NFD: la "ñ" como `n`+tilde combinante), que sin NFC parte la palabra ("borgoña"→"borgon"+"a") y rompe el matching. NFC solo unifica representaciones equivalentes; conserva las marcas de otros idiomas (è, ç, ü…) usadas por el filtro de idioma.

## Validaciones

- Backend: tests de `03_Diagnostico/` (p.ej. `test_batch.py`, `test_nli_relevance.py`, `test_bgg.py`, `test_gamedb.py`, `test_idioma.py`, `test_category_nli.py`). Sin red (NLI mockeado; `gamedb` es offline).
- Verificar el NLI vivo (¿responde de verdad, o solo está configurado?): `py 03_Diagnostico/diag_nli.py` (estado efectivo de `relevance`/`category_nli` y presencia de `HF_API_TOKEN`, sin red) o `--live` (una llamada real al endpoint HF; requiere token, factura por uso).
- Config inbox: `python3 config_inbox.py --dry-run`.
- Ciclo manual: `python3 main.py --once --force`.
- Usuarios: `python3 manage.py list`.
- Validación NLI (experimental): 4 fases en `03_Diagnostico/` para evaluar un clasificador basado en NLI como alternativa a LLM cloud (ver `AI_WORKFLOWS.md` sección "Validación de clasificador NLI").

## Documentación larga

- `README.md`: uso e instalación, instalación de Ollama, configuración, multi-usuario, deploy.
- `05_Docs/DEPLOY_GITHUB_ACTIONS.md`: workflow GitHub Actions, Secrets, cadencia.
- `05_Docs/DEPLOY_RAILWAY.md`: (histórico, vía descartada).
- `05_Docs/ALTA_USUARIOS.md`: gestión de usuarios paso a paso.