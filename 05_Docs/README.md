# Wallapop Alerts — Juegos de mesa

Alertas por email cuando aparece (o se vende) un juego de mesa en Wallapop,
con filtrado inteligente de base / expansión / componentes / lotes.

## Qué hace
- Vigila varias búsquedas, cada una con su **precio máximo**.
- Te avisa **solo de novedades** y de bajas (vendido/retirado).
- Te avisa de **bajadas de precio** de anuncios que ya te habían llegado, y
  **recupera** los que habías descartado por caros si bajan a tu presupuesto.
- Por defecto solo te llega el **juego base** (descarta expansiones y
  componentes sueltos como insertos, fundas, fichas...).
- Los **lotes** (varios juegos juntos) te llegan **aunque superen el precio**.
- Puedes configurar una alerta para que busque **expansiones** en su lugar.
- Filtra por **forma de entrega**: en mano dentro de un **radio de km** que
  tú eliges, con **envío** (a cualquier distancia), o ambas a la vez.
- Descarta automáticamente anuncios cuyo nombre coincide pero no son juegos de
  mesa (ropa, electrónica, medallas, vinilos, herramientas...).
- Ignora las listas de spam que los vendedores añaden para colarse en más
  búsquedas ("Tags:", "Similar a:", "Parecido a:"...): corta la descripción
  en esos marcadores y solo analiza la parte real.
- Recupera todos los resultados disponibles siguiendo la paginación de la API
  (antes solo obtenía la primera página, que podía tener solo 3-4 anuncios).
- **Multi-usuario**: cada persona configura sus alertas en el formulario HTML
  (publicado en GitHub Pages: https://dagaral6.github.io/WALLABOT/) y su
  config llega y se aplica sola por correo (un config y un correo de
  avisos por usuario). El formulario tiene también una pestaña **"Eliminar
  alertas"** que envía una orden de borrado al bot.
- **Descansa de madrugada**: por defecto no hace nada de **01:00 a 07:00**
  (hora de Madrid); configurable en `bot_settings.yaml`.

## Instalación (Windows / PowerShell)
```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLABOT\01_Core
pip install -r requirements.txt
```

## Ollama (clasificador local, gratis)
1. Instala Ollama: https://ollama.com/download
2. Descarga el modelo recomendado (una vez):
   ```powershell
   ollama pull qwen2.5:3b
   ```
   Si prefieres más precisión a cambio de algo más de RAM: `ollama pull llama3.1`
   (cámbialo en `bot_settings.yaml` → `llm.models.ollama`).
3. Ollama arranca automáticamente con Windows y corre en segundo plano.
   Si no está activo, el programa sigue funcionando con reglas de respaldo
   (algo menos preciso, pero sin perder anuncios cuyo título coincide).

> Si prefieres no usar LLM: pon `use_ai: false` en el config.

> **Sin Ollama** (p.ej. corriendo en la nube): el clasificador usa una
> **cascada de LLMs gratuitos**, configurable en `bot_settings.yaml` (sección
> `llm`) o por `LLM_CASCADE`. Por defecto: `gemini,groq,cerebras,openrouter,`
> `githubmodels,rules` (gana el primero que responde; `rules` es el último
> recurso, sin IA). Solo necesitas la clave de los proveedores que uses
> (`GEMINI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `OPENROUTER_API_KEY`,
> `GH_MODELS_TOKEN`). La cascada es **fail-fast**: un 429 pasa al siguiente
> proveedor sin esperar ni reintentar (los 5xx sí tienen un reintento corto),
> y un 429 sostenido manda al proveedor a cooldown. En GitHub Actions ya va
> configurado. **Advertencia (jun 2026):** Cerebras está roto (404 API);
> OpenRouter limita a 50 peticiones/día (insuficiente para pasadas frecuentes);
> GitHub Models requiere PAT (riesgo mayor). Los tres siguen funcionales si los
> activas editando la cascada, pero tuvieron que salir de la cascada por defecto.
> Detalles en `05_Docs/DEPLOY_GITHUB_ACTIONS.md`.

## Configuración
Hay **un config por usuario** en `01_Core/configs/<user_id>.yaml` (el tuyo es
`configs/dario.yaml`). Lo normal es no tocarlos a mano: cada usuario rellena
el formulario HTML y su config llega y se aplica solo por correo (ver
"Configs por correo"). Si editas uno a mano, el formato es idéntico.

1. `email.recipient` es el correo donde llegan los avisos de ese usuario.
   El remitente (`wallabot01@gmail.com`) y su App Password ya vienen puestos
   por el formulario.
2. Define tus alertas. Por cada juego:
   - `keywords`: lo que buscarías en Wallapop.
   - `max_price`: opcional. Los lotes lo ignoran siempre.
   - `want`: opcional. Por defecto `["base", "lote"]`. Para buscar una
     expansión concreta: `["expansion", "lote"]`.
   - `exclude`: opcional. Solo para bloquear variantes concretas por título
     (p.ej. `["junior"]`). La distinción base/expansión/componentes la hace
     el clasificador, no este campo.

## Zona y entrega (radio / envío)
El bloque `location` fija el **centro de búsqueda** y, opcionalmente, el radio
para entregas en mano. El bloque `delivery` decide qué formas de entrega
quieres recibir.

```yaml
location:
  latitude: 39.4685
  longitude: -0.3359
  radius_km: 50        # 0-50. Solo afecta a la entrega EN PERSONA.

delivery:
  in_person: true      # en mano, dentro del radio
  shipping: true       # con envío (la distancia se ignora)
```

Cómo se combinan:
- **Ambas en `true`** (o ambas en `false`) → sin filtro: vale cualquier
  anuncio, esté donde esté.
- **Solo `in_person`** → solo anuncios a `radius_km` o menos del centro. Un
  anuncio lejano queda fuera **aunque admita envío** (manda el radio).
- **Solo `shipping`** → solo anuncios que admiten envío; la distancia da igual.

Ante la duda (un anuncio sin coordenadas, o `radius_km` sin definir), el
anuncio **se deja pasar**: se prefiere un aviso de más a perder uno válido.

> Estos campos los genera automáticamente el configurador HTML. Si editas tu
> config a mano y omites `delivery`, el comportamiento es "sin filtro".

## Uso
**Desde `01_Core`:**
```powershell
# Deja corriendo: todos los usuarios, cada uno a su ritmo; el buzón se
# comprueba solo cada 5 min
python3 main.py

# Una sola pasada (buzón incluido) y salir
python3 main.py --once

# Opcional: registrar lo existente SIN enviar emails. Por defecto NO se usa:
# el primer email de una alerta nueva trae todo lo vigente, y luego solo novedades
python3 main.py --seed

# Forzar una pasada aunque sea horario de sueño (1-7h)
python3 main.py --once --force
```

> **24/7 sin PC (vía elegida):** el bot corre gratis como tarea horaria en
> **GitHub Actions** — guía en `05_Docs/DEPLOY_GITHUB_ACTIONS.md`. La vía
> Railway quedó descartada (SMTP solo en plan de pago); su doc se conserva
> como referencia. En local nada cambia, pero NO ejecutes `main.py` con el
> workflow activo (verías avisos duplicados).

## Configs por correo (automático)
El formulario tiene tres pestañas que abren un borrador de Gmail a
`wallabot01@gmail.com` según la operación: **Crear/editar** (reemplaza el
config completo, asunto `ALERTA WALLAPOP <nombre>`), **Añadir alertas**
(fusiona alertas nuevas con el config existente sin tocar el resto, asunto
`AÑADIR WALLAPOP <nombre>`) y **Eliminar alertas** (asunto
`BORRAR WALLAPOP <nombre>`, cada alerta con su motivo: comprado / ya no
interesa / duplicada / otro). El bot revisa ese buzón cada 5 minutos
(`bot_settings.yaml` → `inbox_check_minutes`):

- Solo acepta remitentes de la **lista blanca**: `bot_settings.yaml` →
  `allowed_senders` (mapa `correo → user_id`). Dar de alta a alguien es solo
  añadirlo ahí ANTES de que envíe su formulario; lo más cómodo es
  `python3 manage.py add-user <correo> <user_id>` (ver "Dar de alta usuarios").
- Hace **backup** del config anterior en `06_Backups/configs/` antes de
  aplicar, añadir o borrar, y responde con una confirmación al remitente.
- **Añadir** requiere que el usuario ya tenga un config existente; si no,
  el bot responde pidiendo crear uno primero con "Crear/editar". Las
  alertas nuevas se deduplican por nombre (en minúsculas) frente a las que
  ya tenía.
- Si llegan varios correos del mismo tipo y usuario, **gana el más reciente**.
- Un remitente fuera de la lista se ignora (queda registrado en el log).

Pasada manual sin esperar al bot:
```powershell
python3 config_inbox.py            # aplica lo pendiente
python3 config_inbox.py --dry-run  # solo mira, no toca nada
```

## Dar de alta usuarios (y quitar alertas)
> Guía detallada paso a paso (alta, modificar un alta y baja) en
> **`05_Docs/ALTA_USUARIOS.md`**. Resumen rápido abajo.

Para que alguien reciba avisos, su correo debe estar en la lista blanca de
`bot_settings.yaml`. `manage.py` lo gestiona sin editar el YAML a mano (con
backup y sin romper los comentarios). **Desde `01_Core`:**

```powershell
# Ver usuarios, sus configs, alertas y filas en la BD
python3 manage.py list

# Dar de alta un correo -> user_id (luego esa persona envía su formulario)
python3 manage.py add-user correo.de.marc@gmail.com marc

# Dar de baja (NO borra su config ni su BD)
python3 manage.py remove-user marc
```

Alta completa, paso a paso:
1. `add-user <correo> <user_id>` autoriza ese correo.
2. (Opcional pero recomendado) añade el usuario al array `USERS` y una
   `<option>` al `<select id="who">` de `02_Herramienta/wallapop_config_v20.html`
   para que pueda elegir su nombre en el desplegable.
3. Esa persona rellena el formulario y lo envía a `wallabot01@gmail.com`
   **desde ese correo**.
4. El bot la detecta (≤ 5 min), valida y crea `configs/<user_id>.yaml`.

**Eliminar una alerta activa:** una alerta es una entrada de la lista `alerts:`
del config. Para quitarla, edita `configs/<user_id>.yaml` y borra ese bloque
`- name: ...`, o regenera la config en el formulario sin esa alerta y reenvíala
(la del buzón sustituye a la anterior). Lo que esa alerta dejó en `alerts.db`
queda huérfano pero es inofensivo (ya no se consulta).

### Resumen de alertas activas (dónde sale)
Cada vez que el bot **aplica, añade o borra** alertas desde un correo del
formulario, responde al remitente con una confirmación que **siempre** incluye
la **lista completa de alertas activas** de ESE usuario (no solo la que acabas
de tocar), con un bloque copiable (una por línea) listo para pegar en la pestaña
**Eliminar alertas**. Lo controla `reply_confirmation: true` en
`bot_settings.yaml`.

> OJO: este resumen va en los **correos de confirmación** (respuesta a tu envío
> del formulario), **no** en los correos de **aviso de anuncios** (los que
> llegan cuando aparece algo en Wallapop). Si no lo ves: 1) revisa que miras la
> confirmación y no un aviso; 2) que `reply_confirmation` esté en `true`;
> 3) que el envío llegara desde un correo de la lista blanca (si no, se ignora);
> 4) la carpeta de Spam de Gmail.

## Horario de sueño (descanso nocturno)
Por defecto el bot **no hace nada de 01:00 a 07:00 (hora de Madrid)**: ni busca
ni revisa el buzón. Se configura en `bot_settings.yaml`:

```yaml
sleep_hours:
  enabled: true
  start: 1                 # empieza a dormir a esta hora
  end: 7                   # despierta a esta hora (no incluida)
  timezone: "Europe/Madrid"
```

- Para desactivarlo: `enabled: false`.
- Una pasada manual (`python3 main.py --once --force`, o el botón "Run workflow"
  de GitHub) se salta el sueño.
- En **GitHub Actions** el horario está además en el workflow (paso `gate`), que
  salta las pasadas de madrugada para no gastar minutos. Si cambias las horas,
  cámbialas en los dos sitios.

## Frecuencia
`check_interval_minutes` en el config de cada usuario (recomendado 5-15).
Cada ciclo revisa todas sus alertas; el email llega en cuanto detecta algo
nuevo.

## Herramientas de diagnóstico
**Desde `03_Diagnostico`:**
```powershell
# Ver, anuncio por anuncio, por qué se enviaría o no (no modifica nada)
python3 diagnostico.py
python3 diagnostico.py "catan"

# Comparar cuántos resultados da la API con distintos parámetros de búsqueda
python3 probe_inis.py
python3 probe_api.py

# Test del filtro de entrega (radio / envío). No usa red ni Ollama.
python3 test_delivery.py

# Test de la cascada de LLMs (orden, cooldown, circuit breaker). Sin red.
python3 test_cascade.py

# Test de los proveedores cloud (Groq/Gemini) y del adaptador. Sin red.
python3 test_llm_cloud.py

# Test de los proveedores nuevos (Cerebras/OpenRouter/GitHub Models) y de
# configure_from_settings (cascada/modelos/claves desde bot_settings.yaml). Sin red.
python3 test_new_providers.py

# Test de bajadas de precio y recuperación de descartados. Sin red.
python3 test_price_drops.py

# Test del comando AÑADIR (fusión incremental de alertas por correo). Sin red.
python3 test_add_alerts.py
```

## Cómo se decide cada anuncio (árbol de decisión)

La **relevancia** (¿es el juego que busco?) la decide el **TÍTULO**, no el LLM:
si alguna palabra del término buscado aparece en el título, el juego es correcto.
La tokenización ignora la puntuación pegada ("Wingspan:" cuenta como "wingspan").

```
¿El TÍTULO contiene alguna palabra del juego buscado?
 │
 ├─ SÍ  -> el juego es correcto. El LLM analiza título + descripción:
 │           1) ¿Es un JUEGO DE MESA? Si no (guantes, medallas,
 │              interruptores, vinilos...) -> descartar ("not_game")
 │           2) ¿Qué tipo de producto?
 │              · base / expansión / componentes / lote
 │              · categoría no incluida en 'want'  -> descartar
 │              · lote                              -> avisar (precio ignorado)
 │              · base/expansión deseada            -> avisar si precio encaja
 │         (si Ollama está apagado y el título coincide -> se acepta como base)
 │
 └─ NO  -> solo interesa si es un LOTE que incluya el juego buscado.
           Prefiltro barato (sin LLM): ¿aparece "lote", "pack", "varios"...?
            ├─ NO  -> descartar directamente (sin llamar al LLM)
            └─ SÍ  -> el LLM confirma si el lote incluye el juego buscado
                       · lote relevante  -> avisar (precio ignorado)
                       · resto           -> descartar
```

### Spam de "Tags:", "Similar a:" y similares
Muchos vendedores añaden al final de la descripción una lista de nombres de
otros juegos para aparecer en más búsquedas, precedida de marcadores como
"Tags:", "Similar a:", "Parecido a:", "Juegos similares:", "Te puede
interesar:"... El programa **corta la descripción en el primer marcador** antes
de analizarla. Así esos nombres no influyen en la clasificación ni en la
detección de lotes, sin descartar el anuncio ni perder la descripción real.

Ejemplo real: un lote de Earth Reborn, Eketorp y Raja cuya descripción termina
con "Similar a: HeroQuest, Descent, Inis, ...". Tras el corte, el detector de
lotes solo ve los juegos reales del pack y concluye que Inis no está incluido.

### Pistas de componentes y expansiones
Cuando el anuncio menciona palabras como "inserto", "separador",
"instrucciones", "fundas", "expansión" o "ampliación", el programa añade una
**pista** al prompt del LLM resaltando esa señal. Esto sesga al modelo hacia
clasificar mejor esos casos sin forzar la decisión: si el contexto deja claro
que es un juego base completo (p.ej. "incluye instrucciones en español"), el
LLM puede seguir diciendo base. Las pistas no descartan por sí solas; solo
aumentan la precisión del clasificador ante vocabulario de riesgo.

Si ves que algún tipo de anuncio sigue clasificándose mal, con el título y
la descripción del caso concreto se puede añadir como ejemplo al modelo y
mejorar la precisión en esa casuística.

### Por qué el título y no el LLM para la relevancia
Intentar que el LLM decida si el anuncio es del juego buscado resultó en que
un modelo de 3B marcaba anuncios válidos como irrelevantes con demasiada
frecuencia. El título es una señal fiable y barata; el LLM se reserva para lo
que sí requiere contexto (¿es un juego? ¿base o expansión? ¿lote?).

### Keywords ambiguas: gate de relevancia (NLI)
Algunas keywords son tan comunes que cuelan **otros juegos** que las contienen:
una palabra ("cities" → *Lost Cities*, *Underwater Cities*, *Cities of Sigmar*…)
o una frase ("rising sun" → *Setting Sun Rising*, dardos *Rising Sun*…). Para
ESAS keywords (definidas en `classifier.py` → `_RISKY_KEYWORDS`) hay un **gate de
relevancia** que decide, **solo a partir del título**, si el anuncio es de verdad
el juego buscado:
- **NLI vivo** (Hugging Face zero-shot, modelo multilingüe; secret `HF_API_TOKEN`
  en CI) cuando hay servicio: entiende el significado y el orden de las palabras.
- **Fallback determinista** si el NLI no responde: confusores conocidos + una
  regla de **orden contiguo** para las frases (p.ej. "Setting Sun Rising" no es
  "rising sun"). Ante la duda, **deja pasar**.

Es reversible (`relevance.enabled` en `bot_settings.yaml`) y solo se dispara en
alertas con keyword ambigua; el resto de anuncios no se ven afectados.

### Refuerzo opcional con BoardGameGeek (BGG)
`bgg.py` puede consultar BoardGameGeek (XMLAPI2) como "diccionario que se mantiene
solo": confirma si un título es un juego real y si BGG lo cataloga como base o
expansión, reforzando la distinción sin listas a mano. Es **refuerzo, no
autoridad** (si BGG no reconoce un título, no se descarta) y **está desactivado
por defecto** (`bgg.enabled: false`). Cachea en `bgg_cache.json` y degrada con
elegancia si BGG falla.

### Eficiencia con Ollama
Cada anuncio se clasifica **una sola vez** (la decisión se guarda en la BD).
En ciclos sucesivos, solo se clasifican los anuncios nuevos. Los anuncios
cuyo título no coincide y no parecen un lote se descartan sin llamar al LLM.

### Lotes y precio
En un lote el precio no es informativo (pagas por varios juegos), así que los
lotes relevantes se avisan **siempre**, ignorando `max_price`.

### Si Ollama está apagado
Un anuncio cuyo título coincide se acepta igualmente (como "base") para no
perder nada. Los lotes y la detección de no-juegos solo funcionan con Ollama
encendido.

## Limitaciones honestas
- La distinción base/expansión/componentes depende de cómo describa el
  vendedor el anuncio. El LLM acierta mucho más que las reglas de palabras,
  pero ningún sistema llega al 100%.
- Ante la duda, el sistema prefiere **dejar pasar** el anuncio antes que perder
  uno válido (mejor un falso positivo que una alerta que no llega).
- La búsqueda usa el orden por defecto de Wallapop (relevancia/distancia),
  no por más reciente. Los anuncios nuevos pueden aparecer más tarde en el
  ranking, pero se detectan igual al comparar con la base de datos.
- El filtro de distancia (radio en persona) lo calcula el programa con las
  coordenadas que Wallapop incluye en cada anuncio, no un parámetro de la API.
  Si un anuncio viniera sin coordenadas, se deja pasar (ante la duda, no
  perderlo).
- Términos cortos o ambiguos (p.ej. "root", "inis") pueden coincidir con
  productos ajenos a los juegos de mesa. El filtro "¿es un juego?" de Ollama
  los descarta, pero requiere que Ollama esté activo.
- Es una API no oficial: usa intervalos razonables (5-15 min).

## Si cambias la configuración
La BD guarda lo ya decidido con la lógica anterior. Si cambias `keywords`,
`max_price` o `want` de una alerta y quieres re-evaluar lo existente, borra
`alerts.db` y vuelve a ejecutar (con `--seed` si no quieres el aluvión
inicial). Ojo: la BD es compartida — borrarla resetea lo visto de **todos**
los usuarios.

## ⚠️ En exploración: alternativas de clasificación
**Ya en producción:** el **gate de relevancia por NLI** para keywords ambiguas
(ver "Keywords ambiguas: gate de relevancia (NLI)" más arriba) sí está activo por
defecto (`relevance.enabled: true`). El **refuerzo BGG** existe pero va desactivado
(`bgg.enabled: false`).

**Todavía experimental:** clasificar la **categoría** completa
(base/expansión/componentes/lote/no-juego) con NLI en vez de con reglas. Hay un
plan de 4 fases en `03_Diagnostico/` para evaluarlo (ver `AI_WORKFLOWS.md` sección
"Validación de clasificador NLI"). Eso NO está activado en producción aún.
