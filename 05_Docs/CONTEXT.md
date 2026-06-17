# CONTEXT.md — Wallapop Alerts

## Qué es el proyecto

Aplicación Python que monitoriza anuncios de Wallapop buscando juegos de mesa
y envía alertas por Gmail cuando aparecen artículos nuevos o se venden.
Tiene dos partes:

1. **Backend Python** — scraper + clasificador + notificador, **multi-config**:
   un YAML por usuario en `01_Core/configs/` (en el PC de Darío)
2. **Herramienta HTML** — formulario que genera el YAML y lo envía por correo a
   `wallabot01@gmail.com`; el backend lo detecta en el buzón y lo aplica solo
   (`config_inbox.py`)

---

## Estructura de carpetas

**Raíz:** `C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\`

| Carpeta | Contenido |
|---|---|
| `01_Core/` | Backend Python: `main.py`, `manage.py` (admin CLI), `scraper.py`, `classifier.py`, `notifier.py`, `database.py`, `config_inbox.py`, `bot_settings.yaml`, `configs/` (un YAML por usuario), `alerts.db`, `requirements.txt` |
| `02_Herramienta/` | Configurador HTML autocontenido (`wallapop_config_v17.html`, vanilla JS, sin build); zip del fuente React antiguo y `wallapop_config_v15.html` (histórico) |
| `03_Diagnostico/` | Scripts de diagnóstico y tests: `diagnostico.py`, `check_db.py`, `probe_api.py`, `probe_catan.py`, `probe_inis.py`, `verify_fix.py`, `migrate_multiconfig.py`, y tests sin red `test_delivery.py`, `test_cascade.py`, `test_llm_cloud.py`, `test_new_providers.py`, `test_price_drops.py` |
| `04_Logs/` | `raw_wallapop_response.json`, `output.txt` |
| `05_Docs/` | `CONTEXT.md`, `README.md`, `DEPLOY_GITHUB_ACTIONS.md`, `DEPLOY_RAILWAY.md` |
| `06_Backups/` | Copias de seguridad de versiones anteriores |
| `99_Obsoletos/` | Archivos descontinuados |

**Python:** `C:\Users\Pc\AppData\Local\Python\bin\python3.exe` (Python 3.14)
**LLM local (Ollama):** modelo activo `qwen2.5:3b`; alternativas: `llama3.2:3b`, `llama3.1`

---

## Backend Python

### Archivos de `01_Core/`

| Archivo | Función |
|---|---|
| `main.py` | Orquestador y scheduler **multi-config**: tick de 60 s, cada usuario corre según su `check_interval_minutes`; comprueba el buzón y recarga configs al vuelo. **Ventana de sueño** (`_is_sleeping()`, `_sleep_config()`, `_now_hour()`). Al arrancar llama a `classifier.configure_from_settings()` (cascada/modelos/claves desde `bot_settings.yaml`). `process_alert()` detecta **novedades**, **bajadas de precio** y **recuperación** de anuncios antes descartados por caros, y bajas. Funciones: `evaluate()`, `process_alert(user_id, ...)`, `run_cycle()`, `load_all_configs()`, `_check_inbox()`, `_use_ai()`, `_price_ok()`, `_delivery_ok()`, `_haversine_km()`, `_hard_excluded()`. Flags `--seed`, `--once`, `--force`. |
| `manage.py` | **Administración por CLI** sin editar YAML a mano. `list`, `add-user <correo> <user_id>` (backup + idempotente), `remove-user <correo|user_id>`. No toca configs ni BD al quitar un usuario. |
| `scraper.py` | Búsqueda en la API de Wallapop con paginación completa via `meta.next_page`. Parámetros: `max_items=500`, `max_pages=10`, `page_pause=2s`, `retries=3`. `_normalize_item()` devuelve `id`, `title`, `description`, `price`, `url`, `image`, **`is_shippable`**, **`lat`**, **`lon`**. |
| `classifier.py` | Híbrido regex + LLM en **cascada con circuit breaker**. Orden por defecto `groq,cerebras,gemini,openrouter,githubmodels,rules` (configurable en `bot_settings.yaml` → `llm.cascade` o por `LLM_CASCADE`). `_ask()` recorre los proveedores hasta que uno responde; un 429 sostenido manda al proveedor a *cooldown* (`LLM_COOLDOWN`/`llm.cooldown_seconds`, 600 s); `rules` es el terminal. Proveedores OpenAI-compatibles (`_OPENAI_COMPAT_BASE`): `groq`, `cerebras`, `openrouter`, `githubmodels` y `openai` (LLM_BASE_URL); más `gemini` (ruta propia) y `ollama` (local). `configure_from_settings()` aplica modelos/claves/orden del YAML (la env-var SIEMPRE manda); `get_ollama_model()` da el modelo local. Categorías: `base`, `expansion`, `components`, `lote`, `not_game`, `unknown`. |
| `database.py` | SQLite (`alerts.db`, tabla `seen_items`). Guarda categoría **y precio** por anuncio. Funciones: `get_known_ids`, `get_kept_rows`, **`get_rejected_rows`**, `add_items`, `delete_items`, **`update_prices`**, **`promote_to_keep`** (recuperar un rechazado a `keep` actualizando precio). |
| `notifier.py` | Gmail SMTP. `build_html()` arma tres secciones: novedades, **⬇️ bajada de precio** (precio anterior tachado → nuevo; marca "ahora dentro de tu presupuesto" si se recupera) y bajas. `notify(..., price_drops=None)`. Toda la config se lee de `config["email"]`. |
| `config_inbox.py` | Extractor IMAP. Dos tipos de correo: **APLICAR** (`ALERTA WALLAPOP <nombre>` + YAML tras `----- config_x.yaml -----`) y **BORRAR** (`BORRAR WALLAPOP <nombre>` + nombres tras `----- ALERTAS A ELIMINAR -----`, o `TODAS`). Valida remitente, hace backup y escritura atómica. La confirmación SIEMPRE incluye la lista de alertas activas (copiable). Ejecutable suelto (`python config_inbox.py [--dry-run]`). |
| `bot_settings.yaml` | Ajustes del bot: credenciales IMAP, lista blanca `correo → user_id`, `inbox_check_minutes`, `sleep_hours`, `reply_confirmation` y **sección `llm`** (cascada, modelos por proveedor, claves y `cooldown_seconds`, comunes a todos los usuarios). **Nunca lo tocan los correos entrantes.** |
| `configs/<user_id>.yaml` | Un config por usuario (ej. `dario.yaml`). El filtro de IA es un único `use_ai: true/false`; el orden/modelos del LLM viven en `bot_settings.yaml`. En la BD cada alerta va como `user_id/nombre`. |

### Principios de clasificación

- **Ante la duda, dejar pasar** (preferir false positive a missed listing)
- `strip_tag_spam()` elimina secciones SEO de las descripciones: "Similar a:", "Tags:", "Parecido a:", "Juegos similares:", "Te puede interesar:"
- `_suspicion_hints()` inyecta pistas contextuales al prompt LLM si aparece vocabulario de componentes/expansiones
- `title_matches` tokeniza con `re.findall(r"\w+", ...)` para matching robusto
- `order_by=newest` **eliminado** del API — recorta resultados drásticamente; la paginación completa es esencial

### Filtro de entrega (radio / envío)

Implementado en `main.py` como filtro **post-hoc** (se aplica después del scraping,
antes de clasificar con el LLM). La API de Wallapop ya devuelve resultados de
toda España; el programa filtra usando los datos que incluye cada anuncio.

Campos que usa de cada anuncio (capturados en `scraper._normalize_item`):
- `is_shippable` → `shipping.item_is_shippable AND shipping.user_allows_shipping`
- `lat` / `lon` → `location.latitude` / `location.longitude`

Lógica (`_delivery_ok`):

| Config delivery | Comportamiento |
|---|---|
| Ambas en `true` (o ambas en `false`) | Sin filtro — pasa todo |
| Solo `in_person: true` | Solo anuncios a `≤ radius_km` km del centro (Haversine) |
| Solo `shipping: true` | Solo anuncios con `is_shippable=True` (distancia ignorada) |

Ante la duda (sin coordenadas del anuncio, sin `radius_km` definido): **dejar pasar**.

Función de distancia: `_haversine_km(lat1, lon1, lat2, lon2)` — devuelve `None`
si algún dato falta.

### Ventana de sueño (no buscar de madrugada)

El bot **no hace nada** (ni busca en Wallapop ni revisa el buzón) durante una
franja configurable. Por defecto, **01:00–07:00 hora de Madrid**.

Configuración en `bot_settings.yaml`:
```yaml
sleep_hours:
  enabled: true
  start: 1                 # hora (en 'timezone') a la que empieza a dormir
  end: 7                   # hora a la que despierta (NO incluida)
  timezone: "Europe/Madrid"
```

- `start == end` o `enabled: false` → nunca duerme. Soporta franjas que cruzan
  medianoche (p. ej. `start: 23`, `end: 7`).
- La hora se calcula con `zoneinfo` (de ahí `tzdata` en `requirements.txt`, para
  que funcione también en Windows). Si `zoneinfo` faltara, cae a la hora local
  del sistema, que para una máquina en España o para Actions (`TZ=Europe/Madrid`)
  ya es la correcta.
- **Las ejecuciones manuales se saltan el sueño**: `python main.py --force`, o el
  botón "Run workflow" de GitHub (define `GITHUB_EVENT_NAME=workflow_dispatch`).
- Override por entorno: `SLEEP_HOURS_ENABLED=0/1`.

**Doble control en GitHub Actions.** Como cada pasada es un proceso efímero, el
horario se aplica en DOS sitios que deben mantenerse coherentes:
1. `main.py` (in-process): `--once` sale sin hacer nada si toca dormir.
2. `.github/workflows/wallabot.yml` (paso `gate`): calcula la hora de Madrid con
   `TZ=Europe/Madrid date +%H` y **salta los pasos caros** (setup-python, pip
   install, scraping, commit) durante el sueño, para no gastar minutos de Actions.
   El cron sigue siendo horario; el gate decide. Las horas (1–7) están
   *hardcodeadas* en el workflow porque no puede leer el YAML sin PyYAML instalado.

### Schema de un config de usuario (`configs/<user_id>.yaml`, v15)

```yaml
email:
  smtp_host: "smtp.gmail.com"
  smtp_port: 587
  sender: "wallabot01@gmail.com"         # cuenta bot dedicada (hardcodeada)
  app_password: "zbmj kkzj cezy shkg"    # app password de wallabot01
  recipient: "wallabot01@gmail.com"      # cambia aquí para enviar a otro email

check_interval_minutes: 30

location:
  latitude: 39.4685
  longitude: -0.3359
  radius_km: 50                          # radio para entregas EN PERSONA (0-50 km)

delivery:
  in_person: true    # en mano, dentro del radio
  shipping: true     # con envío, distancia ignorada
  # nada marcado (ambos false) = sin filtro, equivale a ambos true

use_ai: true             # IA (cascada de LLM) sí/no. El ORDEN y los MODELOS
                         # de la cascada viven en bot_settings.yaml (sección llm)

alerts:
  - name: "Nombre descriptivo"
    keywords: "palabras clave"
    max_price: 25        # opcional; lotes lo ignoran siempre
    min_price: 0         # opcional
    want: ["base","lote"] # opcional; default ["base","lote"]
    exclude: ["junior"]  # opcional; solo por título, no para expansiones

lote_bypass_price: true
```

### Bajadas de precio y recuperación

En cada ciclo, `process_alert()` guarda el precio de cada anuncio y lo compara
con el último visto:
- **Anuncio ya notificado que baja de precio** (cualquier bajada respecto al
  último precio) → entra en la sección "⬇️ bajada de precio" del email; el
  precio guardado se actualiza. Si sube, se actualiza la referencia sin avisar.
- **Anuncio antes descartado por superar `max_price`** que ahora baja y entra en
  presupuesto → se "recupera" (pasa a `keep`, se notifica con la etiqueta
  "ahora dentro de tu presupuesto"). Solo si su categoría está en `want`.

DB: `update_prices()` refresca precios; `promote_to_keep()` recupera rechazados.

### Borrado de alertas por correo

Además de aplicar configs, el buzón acepta órdenes de borrado:
- Asunto `BORRAR WALLAPOP <nombre>`, cuerpo con `----- ALERTAS A ELIMINAR -----`
  y un nombre de alerta por línea (o `TODAS`).
- `config_inbox._apply_delete()` quita esas alertas del YAML del usuario (backup
  + escritura atómica, preservando el resto). `TODAS` deja la lista vacía (en
  pausa) sin borrar el archivo.
- La pestaña **"Eliminar alertas"** del formulario genera ese correo. Las
  confirmaciones del bot (aplicar y borrar) incluyen la lista de alertas activas,
  copiable para pegarla en esa pestaña.

### Imports y rutas

Todos los scripts de `03_Diagnostico/` tienen al inicio:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "01_Core"))
```
`main.py` resuelve `configs/`, `bot_settings.yaml` y `alerts.db` con
`os.path.dirname(os.path.abspath(__file__))`. `load_config()` sin ruta cae al
primer YAML de `configs/` (compat para los scripts de diagnóstico, que operan
sobre un solo usuario).
Ejecutar siempre desde `01_Core/` o con rutas absolutas.

---

## Emails del proyecto

| Papel | Dirección | Dónde está |
|---|---|---|
| **Remitente (from)** | `wallabot01@gmail.com` | `configs/<user_id>.yaml:email.sender` + hardcodeado en `config.ts` del formulario |
| **Destinatario (to)** | `wallabot01@gmail.com` (por defecto) | `configs/<user_id>.yaml:email.recipient` + generado por el formulario HTML |
| **App Password** | `zbmj kkzj cezy shkg` | `configs/<user_id>.yaml:email.app_password` + `bot_settings.yaml:imap.app_password` + hardcodeado en `config.ts` |

Cada usuario define su destinatario en su propio config (sección 1 del formulario).
El remitente y la app password están hardcodeados en el formulario: el receptor nunca los ve.
La cuenta `wallabot01` se usa además por IMAP para leer las configs entrantes.

---

## Extracción automática de configs (buzón IMAP)

El formulario termina abriendo un borrador de Gmail dirigido a
`wallabot01@gmail.com` con asunto `ALERTA WALLAPOP <NOMBRE>` y cuerpo:
resumen legible + línea marcador `----- config_<nombre>.yaml -----` + YAML
completo. `config_inbox.py` convierte ese correo en un config aplicado:

1. **IMAP** (`imap.gmail.com:993`, misma app password que SMTP) busca correos
   **no leídos** con ese asunto. Sin colisión con las alertas del propio bot,
   que usan asunto `[Wallapop] ...`.
2. **Lista blanca**: valida el remitente contra `allowed_senders` de
   `bot_settings.yaml` (mapa `correo → user_id`). Remitente desconocido →
   se marca leído, queda en el log y NO se aplica ni se responde.
3. **Extracción**: toma todo lo posterior a la línea marcador. Prefiere la
   **parte HTML** del correo (la versión texto de Gmail parte las líneas
   largas y rompería el YAML); deshace `format=flowed` en text/plain y
   recorta líneas finales (firmas, citas) hasta que el YAML parsea y pasa la
   validación de schema (`email`, `location`, `alerts`).
4. **Aplicación**: backup del config anterior del usuario en
   `06_Backups/configs/<user_id>_<timestamp>.yaml` y escritura atómica de
   `configs/<user_id>.yaml` con cabecera de metadatos en comentarios.
5. **Cierre**: marca el correo como leído y responde "Configuración
   aplicada ✓" al remitente (desactivable: `reply_confirmation: false`).

Si llegan varios correos del mismo usuario se procesan en orden y **el más
reciente gana**. La identidad es el remitente, no el nombre del formulario:
Marc puede escribir "Marc" o "Marcos" sin duplicar su config.

**Integración:** `main.py` llama al extractor cada `inbox_check_minutes`
(5 por defecto) dentro de su tick de 60 s; si aplica algo, recarga los
configs y lanza un ciclo inmediato para ese usuario. `bot_settings.yaml` se
relee en cada pasada: la lista blanca se puede editar sin reiniciar el bot.

**Uso manual:**

```
python config_inbox.py            # una pasada real
python config_inbox.py --dry-run  # simula: no escribe, no marca, no responde
```

**Primer ciclo de un usuario/alerta nuevos:** sin seed — el primer email
contiene todo lo vigente que pase los filtros; a partir de ahí, solo
novedades (decisión de Darío, jun 2026).

---

## Administración de usuarios y alertas

### Dar de alta un usuario (lo más sencillo)

> Procedimiento completo (alta, modificar un alta, baja) en
> `05_Docs/ALTA_USUARIOS.md`.

El cuello de botella es la **lista blanca** de `bot_settings.yaml`: un correo que
no esté ahí se ignora. `manage.py` lo automatiza sin tocar el YAML a mano (con
backup en `06_Backups/configs/` y preservando comentarios):

```
python 01_Core/manage.py add-user correo.de.marc@gmail.com marc
python 01_Core/manage.py list                  # comprobar estado
python 01_Core/manage.py remove-user marc       # baja (no borra config ni BD)
```

Flujo completo de alta:
1. `add-user <correo> <user_id>` → autoriza ese correo.
2. Esa persona genera su config en el formulario HTML y la envía a
   `wallabot01@gmail.com` **desde ese correo**.
3. El bot la detecta en el buzón (≤ `inbox_check_minutes`), la valida y escribe
   `configs/<user_id>.yaml`. A partir de ahí recibe avisos.

> El `user_id` decide el nombre del archivo (`configs/<user_id>.yaml`) y el
> prefijo en la BD. Una persona puede tener **varios correos** apuntando al mismo
> `user_id`. `add-user` es idempotente (no duplica un correo ya presente).

### Eliminar una alerta activa

No hay borrado "en caliente": una alerta es una entrada de la lista `alerts:` del
config del usuario. Para quitarla:
- **Editar** `configs/<user_id>.yaml` y borrar ese bloque `- name: ...`, **o**
- **Regenerar** la config desde el formulario sin esa alerta y reenviarla (la
  ingesta del buzón sobrescribe el config del usuario).

Las filas que esa alerta dejó en `alerts.db` (`<user_id>/<nombre>`) quedan
**huérfanas pero inofensivas**: ya no se consultan, no generan avisos ni errores.
No se editan los configs por código a propósito: `dario.yaml` está muy comentado
a mano y un `yaml.dump` se cargaría los comentarios.

---

## Despliegue 24/7 (Railway) — DESCARTADO

> Railway bloquea SMTP saliente salvo en plan Pro (20 $/mes): inviable
> gratis. **Vía elegida: GitHub Actions** (sección siguiente). El modo
> `DATA_DIR` se conserva en el código por si se retoma una PaaS.

Guía completa: `05_Docs/DEPLOY_RAILWAY.md`. En la raíz del repo:
`railway.json` (startCommand `python 01_Core/main.py`, restart ALWAYS),
`Procfile`, `requirements.txt`, `.python-version` (3.12) y `.gitignore`.

Modo cloud = variable `DATA_DIR` definida (en Railway: `/data`, un volumen):
- `database.DB_PATH` → `$DATA_DIR/alerts.db`
- `CONFIGS_DIR` (main + config_inbox) → `$DATA_DIR/configs`
- Backups → `$DATA_DIR/backups/configs`
- Primer arranque con volumen vacío: `_bootstrap_data_dir()` (main.py) lo
  siembra con los configs del repo.

Overrides por entorno (prioridad sobre los YAML y sobre la sección `llm` de
bot_settings.yaml): `GMAIL_APP_PASSWORD`, `ALLOWED_SENDERS`
(`correo:uid,correo:uid`, se SUMAN a la lista blanca), `INBOX_CHECK_MINUTES`,
`OLLAMA_HOST`, `TZ`, y para el clasificador LLM: `LLM_CASCADE` (orden de la
cascada, p. ej. `groq,cerebras,gemini,openrouter,githubmodels,rules`),
`LLM_PROVIDER` (compat: si no hay `LLM_CASCADE`, equivale a `<proveedor>,rules`),
`LLM_MODEL`, `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `GEMINI_API_KEY` /
`OPENROUTER_API_KEY` / `GH_MODELS_TOKEN` / `LLM_API_KEY`+`LLM_BASE_URL`,
`LLM_MIN_INTERVAL`, `LLM_COOLDOWN`, `SLEEP_HOURS_ENABLED`.

Sin `DATA_DIR`, el comportamiento local es idéntico al de siempre. En
Railway el LLM corre en la nube (`LLM_PROVIDER=groq` recomendado, capa
gratuita; con proveedor cloud se ignora el modelo de Ollama de
`bot_settings.yaml` (`llm.models.ollama`)); sin proveedor/clave → reglas de
respaldo. Riesgo conocido: Wallapop podría limitar IPs de datacenter
(vigilar 403/429 en logs). El repo DEBE ser privado (contiene la app
password).

---

## Despliegue elegido: GitHub Actions (cron) — jun 2026

Guía completa: `05_Docs/DEPLOY_GITHUB_ACTIONS.md`. Workflow:
`.github/workflows/wallabot.yml`.

El bot corre como tarea programada **cada hora (minuto 17)** en una
máquina efímera de GitHub: `config_inbox.py` (buzón) → `main.py --once`
(ciclo completo) → `git add -A 01_Core` + commit + push del **estado**
(`alerts.db` + `configs/`), que es como persiste entre ejecuciones. Sin
cambios de backend: reutiliza `--once`, el modo standalone del inbox y
los overrides por entorno (`GMAIL_APP_PASSWORD`, `GROQ_API_KEY`,
`GEMINI_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`, `GH_MODELS_TOKEN`,
`ALLOWED_SENDERS` como GitHub Secrets; el orden de la cascada vive en
`bot_settings.yaml`, no en el workflow). `.gitignore`
dejó de ignorar `alerts.db` a propósito.

Claves operativas: presupuesto 2.000 min/mes en repo privado (~1.450
consumidos a cadencia horaria; si se agota, GitHub pausa Actions hasta el
mes siguiente); latencia real de avisos 30-90 min (cron de GitHub se
retrasa en horas punta); pasada manual con "Run workflow" (Actions);
NO ejecutar `main.py` en local con el workflow activo (BDs divergen);
`workflow_dispatch` disponible; concurrencia serializada (grupo
`wallabot`). El paso `gate` salta las pasadas de 01:00–07:00 Madrid (ventana
de sueño), ahorrando ~6 ejecuciones/día (~25% del consumo). Backups de configs
en CI se pierden a propósito: el historial git ES el backup.

---

## Herramienta HTML de configuración

### Archivo final

**`02_Herramienta/wallapop_config_v15.html`** — regenerado (jun 2026) tras
perderse el original: 164 KB, compilado con esbuild + Tailwind por CDN
(necesita internet para estilos y para el buscador de municipios; el
original de 440 KB era 100% autocontenido vía Parcel)

### Secciones del formulario

| Sección | Contenido |
|---|---|
| Identidad | Desplegable `<select id="who">` (usuarios del array `USERS`): elige el nombre y rellena el `recipient`. El correo se muestra en un campo **editable**; si lo cambias, se guarda en esa copia del HTML (`localStorage`, clave `wallabot_email_overrides`) y avisa de cambiarlo también en el `USERS` oficial |
| Cargar | Cargar un `config.yaml` existente para editar |
| 2 — Zona y frecuencia | Intervalo de minutos · Accesos rápidos (Valencia, Tavernes, Palomares) · Buscador de municipios (OpenStreetMap/Nominatim) · Slider radio 0-50 km · Opciones de entrega (En persona / Con envío) |
| 3 — Juegos | Lista dinámica: nombre, keywords, precio máx/mín, categorías `want`, exclusiones |
| 4 — Filtro inteligente | Usar IA on/off (`use_ai`) |
| Enviar a wallabot | Genera YAML y abre borrador en Gmail |

### Constantes fijas (no visibles en el formulario)

```
SENDER_EMAIL        = "wallabot01@gmail.com"
SENDER_APP_PASSWORD = "zbmj kkzj cezy shkg"
RECIPIENT_EMAIL     = "wallabot01@gmail.com"   ← destino del botón "Enviar a wallabot"
```

### Mecanismo de envío

Al pulsar **Enviar a wallabot**, la pestaña navega a:

```
https://mail.google.com/mail/?view=cm&fs=1&tf=1&to=wallabot01@gmail.com&su=...&body=...
```

Gmail se abre con el borrador ya redactado. El usuario revisa y pulsa Enviar.
Sin servicios externos ni cuentas adicionales.

### Accesos rápidos de zona

| Municipio | Latitud | Longitud |
|---|---|---|
| Valencia (por defecto) | 39.4699 | -0.3763 |
| Tavernes de la Valldigna | 39.0716 | -0.2678 |
| Palomares del Campo | 39.9458 | -2.5978 |

El buscador de municipios usa Nominatim (OpenStreetMap) con debounce de 350 ms
y filtro `countrycodes=es`. Funciona solo con conexión a internet.

---

## Stack técnico del formulario

- **React 19** + TypeScript + **Tailwind CSS 3.4.1** + **shadcn/ui**
- Bundler: **Parcel 2** → **html-inline** (produce un único HTML autocontenido)
- Fuente: **Plus Jakarta Sans** (Google Fonts, requiere conexión al cargar)
- Tema: turquesa `hsl(173 80% 40%)`, fondo blanco/gris claro, tarjetas con hover lift

### Build pipeline (entorno sandbox Linux de Claude)

```bash
# El zip fuente NO incluye tsconfig.json ni .postcssrc — crearlos antes del primer build:

# tsconfig.json: paths @/* -> ./src/*  (ver 05_Docs para contenido exacto)
# .postcssrc: {"plugins": {"tailwindcss": {}, "autoprefixer": {}}}

cd /home/claude/wallapop-src/wallapop-config

# Primera vez:
pnpm install --force --config.dangerouslyAllowAllBuilds=true

# Build:
pnpm exec parcel build index.html --dist-dir dist --no-source-maps
pnpm exec html-inline dist/index.html > bundle.html
cp bundle.html /mnt/user-data/outputs/wallapop_config_vXX.html
```

> **pnpm-workspace.yaml** debe tener solo `packages: ['.']` — los placeholders
> en `allowBuilds` del zip original rompen la instalación.

### Estructura del código fuente

```
src/
├── App.tsx                    # estado, validación, handleSend, layout
├── index.css                  # tema (vars CSS, Plus Jakarta, animaciones)
├── lib/
│   └── config.ts              # tipos, CITIES, buildYAML, validate,
│                              # configToState, buildSummary, effectiveDelivery
└── components/
    ├── bits.tsx               # SectionCard, Field, Pill, inputCls, Meeple
    ├── GameCard.tsx           # tarjeta de juego estilo Wallapop
    ├── MunicipalitySearch.tsx # buscador Nominatim con debounce
    └── YamlPreview.tsx        # panel terminal oscuro con syntax highlighting
index.html
tailwind.config.js
package.json
pnpm-workspace.yaml
```

### Función `effectiveDelivery` (config.ts)

```ts
// Nada marcado = ambas activas (sin filtro de entrega)
export function effectiveDelivery(g: GeneralCfg): { inPerson: boolean; shipping: boolean } {
  if (!g.inPerson && !g.shipping) return { inPerson: true, shipping: true };
  return { inPerson: g.inPerson, shipping: g.shipping };
}
```

El YAML generado incluye:
```yaml
location:
  latitude: ...
  longitude: ...
  radius_km: 25

delivery:
  in_person: false
  shipping: false
```

---

## Herramientas de diagnóstico (`03_Diagnostico/`)

| Script | Función |
|---|---|
| `diagnostico.py` | Muestra anuncio por anuncio por qué se acepta/rechaza. No modifica nada. |
| `check_db.py` | Lee y muestra el contenido de `alerts.db`. |
| `probe_api.py` | Compara parámetros de búsqueda en la API. Guarda respuesta en `04_Logs/`. |
| `probe_catan.py` | Prueba de búsqueda específica para "catan". |
| `probe_inis.py` | Prueba de búsqueda específica para "inis". |
| `verify_fix.py` | Verifica que los imports cross-folder funcionan. |
| `test_delivery.py` | Test unitario del filtro de entrega (21 casos, sin red ni Ollama). |
| `migrate_multiconfig.py` | One-shot idempotente: migró `config.yaml` → `configs/dario.yaml` y prefijó la BD con `dario/` (ejecutado jun 2026; la BD estaba vacía). |
| `test_railway_paths.py` | Simula Railway en local (define `DATA_DIR` y overrides de entorno) y verifica rutas, siembra del volumen y lista blanca. Sin red. |
| `test_llm_cloud.py` | Verifica sin red el adaptador LLM multi-proveedor (groq/gemini/ollama): endpoints, cabeceras, modelo efectivo, modo JSON, mapeo de mensajes a Gemini, parseo tolerante y reintento ante 429. |
| `test_cascade.py` | Verifica sin red la **cascada**: que al fallar un proveedor se pasa al siguiente, que al agotarse cae en reglas (`unknown`), y que el circuit breaker saca de la rotación a un proveedor en cooldown. |

---

## Historial de versiones del HTML

| Ver. | Cambio |
|---|---|
| v3 | Primera versión React/shadcn completa (tema parchment vintage) |
| v4 | Envío via FormSubmit con adjunto real; remitente fijo |
| v5 | Remitente wallabot01 oculto; sección correo simplificada |
| v6 | Rediseño UI estilo Wallapop (turquesa, Plus Jakarta Sans, tarjetas limpias) |
| v7 | Cambio a `mailto:` (eliminado FormSubmit) |
| v8 | Gmail compose URL en pestaña nueva |
| v9 | EmailJS integrado (envío automático, sin adjunto) |
| v10 | FormSubmit reimplementado con fetch limpio — Gmail lo bloquea definitivamente |
| v11 | Solución definitiva: Gmail compose URL, pestaña actual navega al correo |
| v12 | Fix: una sola navegación via `window.location.href` |
| v13 | Destinatario cambiado a `wallabot01@gmail.com` |
| v14 | Textos pulidos: "wallabot Alerts", subtítulo, placeholders con ejemplos reales, color `--gold` → turquesa |
| v15 | Zona rediseñada: accesos rápidos (Valencia / Tavernes / Palomares) + buscador Nominatim + slider radio 0-50 km + opciones de entrega. Backend: `scraper.py` captura `is_shippable`/`lat`/`lon`; `main.py` aplica filtro post-hoc con `_delivery_ok` + `_haversine_km`. Config: `location.radius_km` + bloque `delivery`. ← **versión actual** |

> **Backend (jun 2026), sin cambio de HTML:** multi-config (`configs/<user_id>.yaml`,
> BD con prefijo por usuario) + extracción automática del buzón (`config_inbox.py`
> + `bot_settings.yaml`). Migración ejecutada con `migrate_multiconfig.py`.

---

## Decisiones de diseño relevantes

- **Filtro de entrega post-hoc** (no parámetro de API): la API de Wallapop devuelve
  anuncios de toda España sin parámetro de distancia fiable. Cada anuncio ya incluye
  `location.latitude/longitude` y `shipping.item_is_shippable`, así que el filtrado
  se hace en Python tras el scraping. Más robusto y sin depender de parámetros no
  documentados.

- **`order_by=newest` eliminado**: limitaba los resultados a 3-4 por página; sin él
  la paginación completa devuelve 200+ resultados.

- **LLM solo para clasificar, título para relevancia**: el LLM de 3B tiene demasiados
  falsos negativos al juzgar relevancia; el título es señal fiable y barata.

- **Gmail compose URL** (no EmailJS ni FormSubmit): FormSubmit bloqueado por Gmail,
  EmailJS free sin adjuntos, `mailto:` no puede adjuntar. La URL de compose de Gmail
  con `window.location.href` es la solución definitiva.

- **`window.open` evitado**: devuelve `null` incluso con éxito, generando navegación
  duplicada. Se usa `window.location.href` en su lugar.

- **Identidad por remitente, no por nombre**: la lista blanca de `bot_settings.yaml`
  mapea `correo → user_id`; el nombre escrito en el formulario solo decora. Así no
  hay duplicados si alguien cambia cómo escribe su nombre.

- **`bot_settings.yaml` fuera del alcance de los correos**: lista blanca y
  credenciales IMAP viven en un archivo que el extractor nunca sobrescribe —
  un config entrante no puede autoautorizarse ni cambiar la seguridad del bot.

- **Parte HTML del correo preferida a text/plain**: Gmail parte las líneas largas
  en la versión texto (rompería el YAML); la parte HTML conserva cada línea en su
  `<div>`. Fallback a text/plain con unfold de `format=flowed` y recorte
  progresivo de líneas finales para sobrevivir a firmas.

- **BD multi-usuario sin cambiar el schema**: el prefijo `user_id/` en
  `alert_name` separa lo visto por cada usuario; `database.py` no se tocó.

- **LLM en cascada con circuit breaker tras una sola función**: todo el tráfico
  LLM pasa por `classifier._ask()`, que recorre la cascada (`LLM_CASCADE` o
  `bot_settings.yaml` → `llm.cascade`; por defecto
  `groq,cerebras,gemini,openrouter,githubmodels,rules`) en orden hasta que un
  proveedor responde. Si uno devuelve
  429 sostenido entra en *cooldown* (`LLM_COOLDOWN`, 600 s) y se salta hasta que
  expira; al agotarse la cascada (`rules`) se usa la red de seguridad de reglas
  (`classify_category` → `unknown`, que `evaluate()` trata como `base`). Con
  proveedor cloud se ignora el modelo de Ollama (definido a nivel bot) y se
  aplican throttle por proveedor + reintentos ante 429. Groq y compatibles usan
  modo `json_object` + instrucción con las claves del schema; Gemini usa
  `responseSchema` nativo. El orden por defecto pone **Groq primero** y vive en
  `bot_settings.yaml` (sección `llm`); la cascada y los proveedores están
  cubiertos por `test_cascade.py`, `test_llm_cloud.py` y `test_new_providers.py`.

- **Estado del bot versionado en git (patrón commit-back)**: para GitHub
  Actions, `alerts.db` y `configs/` viven en el propio repo y el workflow
  los commitea al final de cada pasada. Elegido frente a caché/artifacts
  de Actions (expiran, no fiables como estado). Coste asumido: ~720
  commits/mes y repo que crece; beneficio: cero infraestructura externa y
  el historial git actúa de backup de los configs.
