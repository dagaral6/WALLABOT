# Wallabot — Contexto de cambios (jun 2026)

## Resumen ejecutivo

Wallabot (scraper + clasificador de juegos de mesa en Wallapop) ha recibido mejoras de captura, filtrado y clasificación:

1. **Captura de texto original** — Wallapop auto-traduce anuncios; ahora capturamos el texto del vendedor sin traducción.
2. **Filtro de categoría nativa** — descarta automáticamente ropa, libros, videojuegos, etc.
3. **Detección de idioma mejorada** — gate de idioma extranjero robusto con override playable-in-spanish.
4. **Almacenamiento de metadatos** — descripción, idioma detectado y categoría nativa de Wallapop por anuncio.
5. **Dataset etiquetado** — 378 anuncios revisados manualmente (317 correctos, 61 errores anotados).

## Cambios en código

### scraper.py
- **ACCEPT_LANGUAGE configurable** (línea ~18): por defecto `None` (sin traducción automática). Wallapop devuelve el texto original del vendedor. Reversible: `ACCEPT_LANGUAGE = "es-ES,es;q=0.9"` para volver a traducir.
- **_extract_category_id(raw)**: extracción robusta del `category_id` nativo de Wallapop (tolera `category_id`, `categoryId`, `category.id`, `taxonomy`…).
- **search(…, category_ids=None)**: parámetro server-side para filtrar búsquedas por categoría nativa (p. ej. solo juegos de mesa).

### database.py
- **Columnas nuevas**: `description TEXT` (texto del anuncio, solo keep), `language TEXT` (es/ca/en/otro), `category_id TEXT` (categoría nativa).
- **Migración suave**: `_REQUIRED_COLS` y `init_db()` añaden columnas sin perder datos.
- **add_items(…)**: guarda descripción solo en filas keep; guarda idioma y category_id en todas.

### classifier.py
- **looks_foreign_language(title, desc)** reescrito: vocabulario ampliado (italiano, alemán, portugués, neerlandés) + declaración explícita ("edición italiana", "en alemán") + override `_PLAYABLE_OK_RE` (no marca foreign si es "independiente del idioma" o tiene reglas en español).
- **detect_language(title, desc)**: es/ca/en/otro (usa looks_foreign_language como gate; separa es/ca/en por vocabulario específico).

### main.py
- **configure_search(settings)**: lee `search.category_ids` de `bot_settings.yaml` y fija el filtro global de categoría.
- **process_alert()**: (1) filtra server-side por `category_ids` al scraper, (2) filtra post-hoc antes de clasificar (red de seguridad), (3) asigna `it["language"]` vía `classifier.detect_language()` a todos los items.
- **Log de ciclo**: incluye "fuera por categoría" en el resumen.

### bot_settings.yaml
- **search.category_ids**: lista de IDs nativos de Wallapop a los que restringir búsquedas (juegos de mesa). Por defecto `[12579, 12461]` (confirmado con datos reales). Vacío = sin filtro.

### 03_Diagnostico/build_review_html.py
- Generador del HTML de revisión interactiva (para etiquetar dataset).
- Lee keep rows con descripción, idioma y category_id nativo.
- Exporta/importa JSONL con esos campos.
- Permite marcar "bien clasificado" y anotar motivos de error.

### 03_Diagnostico/probe_original_text.py
- Valida que Wallapop devuelve el texto original sin la cabecera Accept-Language.
- Compara búsquedas con/sin cabecera, anuncio a anuncio.

### 03_Diagnostico/probe_categories.py
- Descubre `category_id` nativos de Wallapop para una keyword.
- Muestra distribución de IDs y títulos de ejemplo.

---

## Dataset etiquetado

**Ubicación**: `/mnt/user-data/uploads/wallapop_revision_keep.jsonl` (exportado del HTML).

- **378 registros keep** (anuncios notificados).
- **Campos**: item_id, title, description, language, category_id, category (del bot), decision, price, url, alert_name, bien_clasificado (bool), motivo (texto), revisado (bool).
- **Calidad**: 317 bien clasificados (84%), 61 mal (16%) con motivo anotado.

**Errores por tipo** (61 total):
- **30 "Cities"**: keyword ambigua entra en otros juegos (Lost Cities, Underwater Cities, Between Two Cities, Cities of Sigmar). Problema de relevancia.
- **11 idioma**: italiano/neerlandés sin override (ya arreglado con el nuevo gate).
- **10 componentes**: insertos, cajas vacías, monedas clasificados como base.
- **9 expansión**: expansiones Catan clasificadas como base.
- **1 otro**: lote no detectado.

**Categoría nativa de Wallapop** (confirmada con datos):
- `12579` = Juegos de mesa (base puro).
- `12461` = Juegos y juguetes (Catan, Carcassonne, etc.; algo de ruido de juguete que el gate de título descarta).
- Excluidos: `12463` (Libros), `24200` (Videojuegos), `18000` (Coleccionismo), `12465` (Moda), `200` (Inmobiliaria), etc.

---

## Estrategias aún pendientes (no implementadas)

### 1. Componentes/accesorios — gate determinista
**Problema**: 10 errores. Insertos, cajas vacías, monedas se clasifican como base.

**Solución**: regla anclada al título + fraseo "compatible con".
- Detecta sustantivos de accesorio al inicio/dominante del título: `inserto`, `caja/box`, `monedas`, `miniaturas`, `fundas`, `kit`, `upgrade`, `marcadores`.
- Si no hay señal de juego completo ("juego base", "big box", "incluye el juego") → marca componentes, sin LLM.
- Fraseo "compatible con", "para el juego X", "recambio" → accesorio.
- Inhibidor: si hay "juego base/completo" → no dispara.

**Impacto**: ~10 aciertos. Coste: 0 llamadas LLM. Riesgo: bajo (trigger específicos, inhibidor claro).

### 2. Expansión — gate determinista + patrón nº de jugadores
**Problema**: 9 errores. Expansiones Catan ("Navegantes", "Ciudades y Caballeros", "5-6 Jugadores") se clasifican como base.

**Solución**: regla por dependencia del base + patrón de nº de jugadores.
- Dependencia: "expansión/ampliación **para** el juego X", "requiere el juego base", "necesita el básico" → expansión.
- Patrón "[Juego] 5-6 jugadores" / "5 y 6 jugadores" → casi siempre expansión clásica de jugadores.
- Vocabulario de expansión (`expansión`, `ampliación`, `exp.`, `add-on`, `escenario`) como refuerzo, nunca único criterio.
- Inhibidor: "incluye base", "Big Box", "base + exp" → base.

**Impacto**: ~9 aciertos. Coste: 0 llamadas LLM. Riesgo: bajo.

### 3. Relevancia (Cities) — NLI para keywords ambiguas  ✅ IMPLEMENTADO (jun 2026)
**Problema**: 30 errores (66% de la alerta "Cities"). "Cities" entra en Lost Cities, Underwater Cities, Between Two Cities, Cities of Sigmar, etc.

**Solución implementada**: gate de relevancia híbrido (NLI zero-shot + fallback determinista), selectivo y reversible.
- `classifier.py`: `_RISKY_KEYWORDS` (keyword → nombre canónico + confusores), `is_risky_keyword()`, `detect_risky_keywords(alert)`, `nli_relevance_gate(title, desc, keyword)`, `_match_exclusion()`. El gate consulta el NLI zero-shot de Hugging Face (modelo multilingüe `joeddav/xlm-roberta-large-xnli`, token `HF_API_TOKEN`) decidiendo por **margen** de score; si el NLI no responde (503/429/timeout/sin token) o el margen es insuficiente, cae al **fallback determinista** (lista de confusores). Caché en memoria por (keyword, título normalizado).
- `main.py:evaluate()`: en la RAMA 1 (título coincide), si la alerta tiene keyword riesgosa y `relevance.enabled`, llama al gate; `not_relevant` → `reject/no_title_match`. No cambia la firma de `evaluate()`. `_hard_excluded` (alert `exclude`) sigue corriendo antes como red adicional.
- `bot_settings.yaml`: sección `relevance` (enabled, model, margin, overrides de confusores). Aplicada por `configure_from_settings()`.
- Test: `03_Diagnostico/test_nli_relevance.py` (standalone). Validado: gate INERTE sobre las 484 filas de `cases.jsonl` (0 rechazos nuevos en las 6 alertas reales) + sintéticos de Cities (Lost/Underwater/Between Two/Sigmar → not_relevant; Cities Devir → relevant).

**Impacto**: cubre los ~30 errores de "Cities". Coste: NLI solo en keywords riesgosas (hoy "Cities") y solo sobre títulos que ya matchearon, con caché; 0 llamadas si no hay token (modo determinista). Riesgo: bajo. "Risk" queda fuera por defecto (variantes legítimas: Risk Legacy, Star Wars...).

---

## Arquitectura actual

```
scraper.py (captura original, sin traducción automática)
    ↓
    ├─ category_id nativo (robusto)
    ├─ title, description (original)
    └─ validate con category_ids server-side
         ↓
classifier.py (puertas en cascada)
    ├─ gate: looks_foreign_language (idioma)
    ├─ gate: [PENDING] componentes (regla)
    ├─ gate: [PENDING] expansión (regla)
    ├─ gate: relevancia/Cities (NLI HF zero-shot + exclusión)  [hecho]
    ├─ classify: base/expansion/lote (LLM o reglas)
    └─ detect_language: es/ca/en/otro
         ↓
database.py (guarda metadatos)
    ├─ description (solo keep)
    ├─ language (todas)
    └─ category_id (todas)
         ↓
notifier.py (envía emails)
```

---

## Validación

- **Idioma**: 11/11 extranjeros cazados, 0 falsos positivos españoles, 10/10 casos sintéticos generales.
- **Categoría**: 0 libros/videojuegos/ropa en keep; todos los keep son 12579 o 12461.
- **Dataset**: 378 keep etiquetados (317 OK, 61 con motivo).

---

## Próximos pasos

1. **Inmediato**: implementar componentes + expansión (reglas deterministas, sin NLI).
2. **Fase 2** ✅ hecho: relevancia/Cities con NLI (gate de keywords riesgosas + fallback determinista). Ver "Estrategias" §3.
3. **Fase 3 (largo plazo)**: fine-tuning de NLI local sobre los 378 keep para reemplazar cascada LLM cloud (reduce coste y latencia).

---

## Archivos clave

- `01_Core/scraper.py`, `classifier.py`, `database.py`, `main.py` — motor.
- `01_Core/bot_settings.yaml` — `search.category_ids` (configuración por defecto confirmada).
- `03_Diagnostico/build_review_html.py` — generador del HTML de revisión interactivo.
- `03_Diagnostico/probe_original_text.py`, `probe_categories.py` — diagnósticos.
- `/mnt/user-data/uploads/wallapop_revision_keep.jsonl` — dataset etiquetado (459 registros).

---

## Notas para Claude Code

- **No tocar**: secretos, workflows de GitHub Actions, notifier.py, config_inbox.py, manage.py.
- **Patrón de cambio**: pequeño, seguro, verificable contra el dataset etiquetado.
- **Regresión**: cualquier cambio debe probarse contra el JSONL (378 keep, 61 errores) sin romper aciertos previos.
- **NLI**: cuando se implemente, usar `sentence-transformers` para local o reutilizar cascada existente con parámetro `use_nli_for_relevance`.
