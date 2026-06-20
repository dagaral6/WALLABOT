# Despliegue gratis con GitHub Actions (cron) — VIA ELEGIDA (jun 2026)

El bot corre como tarea programada en GitHub Actions: 100% gratis, sin
tarjeta, sin servidor. A cambio, deja de ser un proceso continuo y pasa a
ejecutarse **una vez cada 2 horas**.

## Como funciona

Cada 2 horas (minuto 33), GitHub arranca una maquina limpia que:
1. Descarga el repo (que contiene el estado: `alerts.db` + `configs/`)
2. Instala Python 3.12 y dependencias (con cache, ~40 s)
3. `config_inbox.py` — revisa el buzon de wallabot01, aplica configs
   nuevos de la lista blanca y responde "Configuracion aplicada"
4. `main.py --once` — una pasada completa: scrapeo, filtro de entrega,
   clasificacion con LLM (cascada Gemini→Groq→…) y envio de avisos por Gmail
5. **Commitea el estado de vuelta al repo** (`git add -A 01_Core` + push):
   asi la siguiente ejecucion sabe que anuncios ya se vieron
6. La maquina se destruye

El flujo del usuario no cambia: formulario -> correo a wallabot01 ->
config aplicado + confirmacion -> avisos. Todo automatico.

El workflow vive en `.github/workflows/wallabot.yml`. No hubo que tocar
el backend: se reutilizan `--once`, el modo standalone de config_inbox y
todos los overrides por variables de entorno.

## Secretos (Settings -> Secrets and variables -> Actions)

| Secreto | Valor | Para que |
|---|---|---|
| `GMAIL_APP_PASSWORD` | app password de wallabot01 | SMTP + IMAP |
| `GEMINI_API_KEY` | clave de aistudio.google.com | clasificador LLM (1o de la cascada, recomendado) |
| `GROQ_API_KEY` | clave `gsk_...` de console.groq.com | clasificador LLM (2o, respaldo) |
| `CEREBRAS_API_KEY` | clave de cloud.cerebras.ai | clasificador LLM (respaldo, roto actualmente) |
| `OPENROUTER_API_KEY` | clave de openrouter.ai | clasificador LLM (respaldo) |
| `GH_MODELS_TOKEN` | PAT con permiso `models:read` | clasificador LLM (respaldo) |
| `ALLOWED_SENDERS` | `correo:uid,correo:uid` | lista blanca de remitentes |

No hace falta crear todos: el bot solo usa el **primero de la cascada** que
tenga clave; los que falten se saltan. El **orden** de la cascada vive en
`01_Core/bot_settings.yaml` (sección `llm`), no en el workflow (puedes forzarlo
en CI descomentando `LLM_CASCADE` en `.github/workflows/wallabot.yml`).

> **OJO con GitHub Models:** GitHub **no permite** crear secretos cuyo nombre
> empiece por `GITHUB_`. Por eso el secreto se llama **`GH_MODELS_TOKEN`** (y la
> variable de entorno que lee el bot también). Crea un *Personal Access Token*
> (fine-grained o classic) con permiso `models:read`.

Los secretos tienen prioridad sobre los YAML del repo (codigo ya
preparado). `ALLOWED_SENDERS` como secreto ademas evita exponer correos
personales en los logs.

## Presupuesto de minutos (repo privado: 2.000 min/mes gratis)

Cada ejecucion factura minimo 1 minuto y redondea hacia arriba (~2 min
reales por pasada). A cadencia horaria: ~720 pasadas x 2 min = ~1.450
min/mes -> cabe con holgura. Si se agota el presupuesto, GitHub **pausa
Actions hasta el mes siguiente** (no cobra): el bot quedaria mudo.

- Ver consumo: github.com -> Settings (perfil) -> Billing -> Usage.
- Cambiar la cadencia: editar el `cron` en `wallabot.yml`. Ejemplos:
  - `"33 */2 * * *"` cada 2 horas (actual, recomendado)
  - `"17 * * * *"` cada hora (~1.450 min/mes, mas cerca del limite de 2.000)
  - `"*/30 8-23 * * *"` cada 30 min solo de dia (~justo, vigilar consumo)
- NO bajar de 30 min: el presupuesto no da y GitHub ademas retrasa o
  salta ejecuciones en horas de carga.

## Forzar una pasada (sin esperar a la hora)

GitHub -> repo -> pestanya **Actions** -> workflow "wallabot" ->
**Run workflow** -> Run. Tambien desde el navegador del movil. Util tras
enviar un formulario para no esperar al siguiente tick.

## Limitaciones conocidas (aceptadas al elegir esta via)

- **Latencia**: avisos y confirmaciones llegan con 30-90 min de retraso
  tipico (cadencia horaria + el cron de GitHub puede retrasarse 5-30 min
  o saltarse alguna ejecucion en horas punta).
- **IPs de datacenter** (Azure, muy usadas por scrapers): riesgo de que
  Wallapop limite o bloquee. Vigilar 403/429 en los logs del workflow.
- **Gmail desde IPs rotatorias**: cada pasada sale de una IP distinta;
  las app passwords suelen pasar, pero Google podria marcar la cuenta.
- **El repo engorda**: ~720 commits/mes de estado (BD pequenya: asumible).
- **`check_interval_minutes` pasa a ser decorativo**: todos los usuarios
  corren a la cadencia del workflow.
- El auto-apagado de crons por inactividad (60 dias) no aplica: los
  commits de estado del propio workflow cuentan como actividad.

## Convivencia con el modo local (IMPORTANTE)

`alerts.db` ahora esta versionada en git (es el estado del bot).
Reglas para no romper nada:

1. **No ejecutar `main.py` en el PC mientras Actions este activo**: las
   dos BDs divergirian y habria avisos duplicados o perdidos.
2. Antes de trabajar en el codigo en local: **Fetch/Pull** en GitHub
   Desktop (el workflow habra commiteado estado nuevo).
3. Para desarrollo local con scrapeo real, desactivar antes el workflow:
   Actions -> wallabot -> "..." -> **Disable workflow** (y reactivarlo al
   terminar). Los tests de diagnostico (`test_*.py`) no tocan la BD real
   y pueden correrse siempre.
4. Si un dia el push del estado falla por conflicto (rarisimo, el grupo
   de concurrencia lo evita), la pasada se pierde y la siguiente la
   rehace: puede duplicar algun aviso de esa hora. Sin mas consecuencia.

## Railway (descartado)

Railway bloquea SMTP salvo en plan Pro (20 $/mes) — ver
`DEPLOY_RAILWAY.md`. El proyecto de Railway creado durante las pruebas
debe BORRARSE: el worker sigue vivo, lee el buzon (consume los correos
de configs marcandolos como leidos) y compite con GitHub Actions.
Railway -> proyecto -> Settings -> Danger -> Delete project.
