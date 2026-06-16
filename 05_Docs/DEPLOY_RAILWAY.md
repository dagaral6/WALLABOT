# Despliegue 24/7 en Railway — DESCARTADO (jun 2026)

> **AVISO**: esta via se descarto. Railway bloquea el SMTP saliente en los
> planes Free, Trial y Hobby; solo el plan **Pro (20 $/mes)** lo permite
> (confirmado en docs.railway.com/networking/outbound-networking). Este
> documento decia antes que el plan Hobby bastaba: era INCORRECTO. El bot
> no puede enviar correos por Gmail desde Railway sin pagar Pro.
> **El despliegue elegido es GitHub Actions**: ver `DEPLOY_GITHUB_ACTIONS.md`.
> Se conserva este documento porque el codigo sigue soportando el modo
> DATA_DIR por si algun dia se retoma (Railway Pro u otra PaaS con volumen).

Guia para tener el bot corriendo en la nube sin depender del PC.
El codigo ya esta adaptado: en local funciona igual que siempre; el "modo
cloud" se activa solo al definir la variable de entorno `DATA_DIR`.

## Que cambia entre local y Railway

| | Local (PC) | Railway |
|---|---|---|
| Configs | `01_Core/configs/` | volumen `/data/configs` |
| Base de datos | `01_Core/alerts.db` | volumen `/data/alerts.db` |
| Backups | `06_Backups/configs/` | volumen `/data/backups/configs` |
| Credenciales | YAMLs | YAMLs + overrides por variables de entorno |
| LLM | Ollama localhost:11434 | Groq / Gemini via `LLM_PROVIDER` (capa gratis) |

La primera vez que arranca con el volumen vacio, lo siembra con los configs
del repo (`dario.yaml`). A partir de ahi, los configs nuevos llegan por
correo y viven en el volumen: **sobreviven a los redeploys**.

## Variables de entorno

| Variable | Obligatoria | Valor | Para que |
|---|---|---|---|
| `DATA_DIR` | Si | `/data` | Activa el modo cloud y apunta al volumen |
| `TZ` | Recomendada | `Europe/Madrid` | Hora local en logs y backups |
| `ALLOWED_SENDERS` | Recomendada | `correo:uid,correo:uid` | Anyade remitentes a la lista blanca SIN redeploy |
| `LLM_PROVIDER` | Recomendada | `groq` (o `gemini`) | Clasificador LLM en la nube; sin esto, reglas de respaldo |
| `GROQ_API_KEY` | Con groq | clave de console.groq.com | Credencial del proveedor |
| `GEMINI_API_KEY` | Con gemini | clave de aistudio.google.com | Credencial del proveedor |
| `LLM_MODEL` | Opcional | p.ej. `llama-3.1-8b-instant` | Cambiar el modelo cloud por defecto |
| `LLM_MIN_INTERVAL` | Opcional | `2.1` | Segundos minimos entre llamadas LLM |
| `GMAIL_APP_PASSWORD` | Opcional | app password | Prioridad sobre los YAML (unica fuente si rotas la clave) |
| `INBOX_CHECK_MINUTES` | Opcional | `5` | Frecuencia de revision del buzon |
| `OLLAMA_HOST` | Opcional | `http://host:11434` | Apuntar a un Ollama remoto si algun dia existe |

`ALLOWED_SENDERS` se SUMA a lo que haya en `bot_settings.yaml`. Ejemplo:
`micorreo@gmail.com:dario,correodemarc@gmail.com:marc`

## LLM en la nube (Groq / Gemini)

En Railway no hay Ollama, pero el clasificador funciona igual con un
proveedor cloud de capa GRATUITA. `classifier.py` elige el proveedor con
`LLM_PROVIDER`; los prompts, schemas y respaldos son exactamente los mismos.

| Proveedor | Donde sacar la clave | Modelo por defecto | Capa gratis (aprox.) |
|---|---|---|---|
| `groq` (recomendado) | console.groq.com -> API Keys | `llama-3.1-8b-instant` | ~14.000 peticiones/dia, 30/min |
| `gemini` | aistudio.google.com -> Get API key | `gemini-2.5-flash-lite` | ~1.000 peticiones/dia, 15/min |

Notas importantes:
- Con proveedor cloud no se usa el modelo de Ollama (que ahora vive en
  `bot_settings.yaml` -> `llm.models.ollama`); el modelo cloud se fija en
  `bot_settings.yaml` -> `llm.models.<proveedor>`, con `LLM_MODEL` o el
  defecto del proveedor.
- Hay throttle automatico (2,1 s groq / 4,1 s gemini) y reintentos ante
  HTTP 429: el primer ciclo grande tarda unos minutos mas; los siguientes
  solo clasifican novedades (un punyado de llamadas).
- **"Groq" no es "Grok"**: Grok es el modelo de xAI (API de pago). Si algun
  dia se quiere: `LLM_PROVIDER=openai`, `LLM_BASE_URL=https://api.x.ai/v1`,
  `LLM_API_KEY=<clave xAI>`, `LLM_MODEL=<modelo grok vigente>`.
- Si un modelo por defecto desaparece (404 en logs), define `LLM_MODEL` con
  uno vigente. Si aparecen muchos 429 seguidos, sube `LLM_MIN_INTERVAL`.
- Calidad: llama-3.1-8b (Groq) rinde igual o mejor que el qwen2.5:3b local.

## Pasos (una sola vez)

### 1. Repo en GitHub (PRIVADO, obligatorio)
El proyecto contiene la app password de wallabot01 (en los YAMLs, en
CONTEXT.md y embebida por disenyo en el formulario HTML). El repo DEBE ser
privado.

Git NO esta instalado en el PC (comprobado jun 2026). Dos caminos:

**Opcion A (recomendada): GitHub Desktop**
1. Instala https://desktop.github.com e inicia sesion con tu cuenta GitHub.
2. File -> Add local repository -> `C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP`
   (ofrecera "create a repository here": acepta, valores por defecto).
3. Haz el commit inicial -> **Publish repository** -> marca
   **Keep this code private** -> Publish.

**Opcion B: Git por linea de comandos**
1. Instala https://git-scm.com/download/win
2. ```powershell
   cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP
   git init -b main
   git add -A
   git commit -m "Wallapop Alerts: multi-config + buzon + Railway"
   git remote add origin https://github.com/TU_USUARIO/wallabot.git
   git push -u origin main
   ```

El `.gitignore` ya excluye BD, logs, backups y obsoletos.

### 2. Cuenta y proyecto en Railway
1. https://railway.app -> "Login with GitHub".
2. Plan **Pro** (20 $/mes) — OBLIGATORIO para SMTP: Railway bloquea los
   puertos SMTP salientes (25/465/587) en Free, Trial y Hobby.
3. New Project -> "Deploy from GitHub repo" -> selecciona el repo.
4. En Settings del servicio, region **EU (Amsterdam)** si te lo ofrece
   (mas cerca de Wallapop).

### 3. Volumen (persistencia)
En el canvas del proyecto: click derecho sobre el servicio ->
**Attach Volume** -> Mount path: `/data`.

### 4. Variables
Servicio -> pestanya **Variables** -> anyade:
- `DATA_DIR` = `/data`
- `TZ` = `Europe/Madrid`
- `ALLOWED_SENDERS` = `tucorreo@gmail.com:dario,correodemarc@gmail.com:marc`
- `LLM_PROVIDER` = `groq`
- `GROQ_API_KEY` = (tu clave de console.groq.com -> API Keys -> Create)

### 5. Redeploy y comprobacion
Deployments -> Redeploy (para que tome volumen + variables). En los logs
debe verse:
```
Modo cloud: datos persistentes en /data
Volumen sembrado con los configs del repo: dario.yaml
Configs cargadas: dario
LLM activo: groq / llama-3.1-8b-instant
Iniciado en modo multi-config...
```
Si en su lugar sale "LLM NO disponible (...)", revisa `LLM_PROVIDER` y la
API key; el bot funciona igualmente con las reglas de respaldo mientras
tanto.

### 6. Prueba de extremo a extremo
1. Rellena el formulario HTML y envia el correo (desde un remitente de la
   lista blanca).
2. En 5 minutos como mucho: log "Config de '...' aplicada", respuesta
   "Configuracion aplicada" al remitente, y el primer email de anuncios.

## Actualizar el codigo
`git push` a `main` -> Railway redeploya solo. Configs y BD no se pierden
(viven en el volumen, no en la imagen).

## Limitaciones y riesgos conocidos
- **LLM**: resuelto via `LLM_PROVIDER` (Groq/Gemini, capa gratis). Sin
  proveedor o sin clave, el bot sigue funcionando con las reglas de
  respaldo (mas ruido). `OLLAMA_HOST` sigue disponible para un Ollama
  remoto si algun dia existe.
- **IP de datacenter**: Wallapop podria limitar peticiones desde IPs cloud.
  Si aparecen 403/429 en los logs, habra que anyadir cabeceras o proxy.
- **SMTP saliente**: requiere plan Pro (20 $/mes); bloqueado en Free,
  Trial y Hobby. Motivo principal del descarte de Railway.
- **Coste real estimado**: 0,5-2 $/mes de uso (proceso ligero, sin LLM).

## Volver a local
En el PC no existe `DATA_DIR`, asi que el codigo usa las rutas de siempre
sin tocar nada. OJO: la BD del PC y la del volumen son INDEPENDIENTES; no
ejecutes ambos a la vez o cada uno notificara por su cuenta (duplicados).
