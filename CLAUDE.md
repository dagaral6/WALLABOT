# Wallapop Alerts — instrucciones para agentes

## Regla principal

Trabaja siempre con mínimo contexto.

No leas el repositorio completo salvo que el usuario lo pida explícitamente. Antes de abrir archivos, localiza lo relevante usando `rg`, `git grep`, `find` o búsquedas dirigidas.

El objetivo es hacer cambios pequeños, seguros y verificables, evitando consumir contexto con carpetas, logs, backups o documentación histórica innecesaria.

---

## Idioma y estilo

* Responde en español.
* Sé directo, técnico y práctico.
* No rellenes con explicaciones largas si basta con una decisión clara.
* Antes de editar, explica brevemente qué archivos crees que tocarás y por qué.
* Si hay varias opciones, recomienda una y justifica brevemente.
* No pegues archivos completos en la conversación salvo petición explícita.
* Al final de cada tarea, entrega resumen, archivos tocados, comandos ejecutados, riesgos y siguiente paso recomendado.

---

## Estructura del repositorio

* `01_Core/`: backend Python.

  * Archivos principales:

    * `main.py`
    * `scraper.py`
    * `classifier.py`
    * `database.py`
    * `notifier.py`
    * `config_inbox.py`
    * `manage.py`

* `02_Herramienta/`: configurador HTML.

  * Archivo actual principal:

    * `wallapop_config_v18.html`

* `03_Diagnostico/`: scripts de diagnóstico y pruebas.

* `05_Docs/`: documentación larga y documentación auxiliar para agentes.

* `04_Logs/`: logs. No leer por defecto.

* `06_Backups/`: backups. No modificar ni leer por defecto.

* `99_Obsoletos/`: versiones antiguas u obsoletas. No modificar ni leer por defecto.

---

## Archivos y carpetas que NO debes leer por defecto

No abras ni explores estos elementos salvo petición explícita:

* `alerts.db`
* `04_Logs/`
* `06_Backups/`
* `99_Obsoletos/`
* versiones antiguas del HTML
* respuestas crudas de Wallapop
* zips históricos
* documentación larga completa si basta con `05_Docs/AI_BRIEF.md`
* archivos grandes, generados o binarios
* credenciales, secretos o tokens

Motivo: reducen rendimiento, consumen contexto y pueden mezclar estado actual con historial obsoleto.

---

## Documentación recomendada para empezar

Antes de abrir muchos archivos, consulta primero:

1. `05_Docs/AI_BRIEF.md`, si existe.
2. `05_Docs/AI_WORKFLOWS.md`, si existe.
3. `05_Docs/AI_NO_READ_BY_DEFAULT.md`, si existe.
4. Después usa `rg` o `git grep` para localizar símbolos, funciones o rutas relevantes.

No uses `README.md` o `CONTEXT.md` completos como primera fuente salvo que la tarea lo requiera.

---

## Flujo obligatorio de trabajo

Para cualquier cambio de código:

1. Entiende el objetivo.
2. Localiza archivos relevantes con `rg` o `git grep`.
3. Lee solo los archivos mínimos necesarios.
4. Propón un plan breve antes de editar.
5. Aplica el cambio mínimo.
6. Ejecuta validaciones relevantes.
7. Revisa `git diff`.
8. Resume lo hecho.

No hagas cambios amplios, refactors grandes o reestructuraciones salvo petición explícita.

---

## Reglas de edición

* No reescribas archivos completos si basta con un patch pequeño.
* No cambies formato global, indentación masiva o estilo de archivos no relacionados.
* No renombres funciones, clases o archivos salvo que sea necesario.
* No introduzcas dependencias nuevas sin explicar por qué.
* No hagas commit salvo petición explícita.
* No ejecutes comandos destructivos.
* No borres datos, bases de datos, logs ni configuraciones sin confirmación explícita.
* No modifiques secretos, tokens, passwords ni credenciales.
* Si encuentras credenciales, avisa sin reproducirlas.

---

## Seguridad y secretos

Nunca debes:

* Mostrar credenciales.
* Copiar credenciales.
* Mover credenciales.
* Modificar credenciales.
* Hardcodear secretos.
* Incluir tokens o passwords en documentación, logs o respuestas.

Si detectas credenciales en archivos del repo:

1. Avisa.
2. No las pegues en la respuesta.
3. Recomienda moverlas a GitHub Secrets, variables de entorno o mecanismo seguro equivalente.
4. No hagas cambios automáticos sobre ellas salvo petición explícita.

---

## Comandos útiles

### Estado del repo

```powershell
git status
git diff
git diff --stat
```

### Buscar código

```powershell
rg "texto_a_buscar"
git grep "texto_a_buscar"
```

### Backend

```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\01_Core
python main.py --once --force
python config_inbox.py --dry-run
python manage.py list
```

### Diagnóstico

```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\03_Diagnostico
python test_delivery.py
python test_cascade.py
python test_llm_cloud.py
python test_new_providers.py
python test_price_drops.py
python test_add_alerts.py
python diagnostico.py
```

---

## Validaciones según tipo de cambio

### Si tocas backend Python

Ejecuta los tests o diagnósticos relacionados en `03_Diagnostico/`.

Si el cambio afecta a ejecución general:

```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\01_Core
python main.py --once --force
```

Solo ejecutes `main.py` si tiene sentido y no interfiere con GitHub Actions o ejecución en producción.

### Si tocas configuración por correo

Ejecuta:

```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\01_Core
python config_inbox.py --dry-run
```

### Si tocas usuarios

Ejecuta:

```powershell
cd C:\Users\Pc\Desktop\PROYECTOS\WALLAPOP\01_Core
python manage.py list
```

### Si tocas clasificador

Revisa especialmente:

* `classifier.py`
* `main.py`
* tests relacionados con cascade, LLM, proveedores y reglas

Mantén estas reglas:

* Ante la duda, preferir falso positivo a anuncio perdido.
* Mantener fallback por reglas.
* Mantener comportamiento seguro ante errores de LLM.
* No romper circuit breaker ni gestión de 429.

### Si tocas configurador HTML

Trabaja sobre:

* `02_Herramienta/wallapop_config_v18.html`

No modifiques versiones antiguas salvo petición explícita.

### Si tocas GitHub Actions

Recuerda que el workflow puede persistir estado como:

* `alerts.db`
* `configs/`

No rompas el flujo de commit-back ni la lógica de sueño nocturno.

---

## Reglas sobre Git

* El usuario revisa, commitea y sincroniza con GitHub Desktop.
* No hagas commit salvo petición explícita.
* No hagas push.
* No cambies de rama salvo petición explícita.
* Antes de terminar, muestra el estado con:

```powershell
git status
git diff --stat
```

Si procede, muestra también un diff resumido.

---

## Formato final obligatorio

Al terminar una tarea, responde con esta estructura:

```markdown
## Resumen

- Qué se ha cambiado.
- Por qué se ha cambiado.

## Archivos modificados

- `ruta/archivo`: descripción breve.

## Comandos ejecutados

- `comando`: resultado breve.

## Validación

- Tests pasados, checks realizados o motivo por el que no se ejecutaron.

## Riesgos

- Posibles efectos secundarios o puntos a revisar.

## Siguiente paso recomendado

- Qué debería revisar o probar el usuario ahora.
```

---

## Prompt interno de trabajo

Antes de editar, sigue mentalmente este patrón:

```text
Objetivo: ¿qué cambio exacto pide el usuario?
Ámbito: ¿backend, HTML, configs, usuarios, GitHub Actions o documentación?
Búsqueda: ¿qué símbolos/rutas debo localizar con rg?
Archivos mínimos: ¿cuáles necesito abrir?
Plan: ¿cuál es el cambio mínimo?
Validación: ¿qué test o comando confirma que funciona?
Riesgo: ¿qué puede romperse?
```

---

## Prioridad máxima

Reducir consumo de contexto, evitar exploración innecesaria y aplicar cambios mínimos, seguros y revisables.