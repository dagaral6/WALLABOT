Trabaja en modo revisión interactiva del proyecto por fases.

Objetivo:
$ARGUMENTS

## Propósito del comando

Este comando sirve para revisar el proyecto en su estado actual, dividirlo en fases funcionales o técnicas, explicar cómo funciona cada fase y recoger feedback del usuario.

No implementes cambios durante esta revisión.

Tu misión es:

1. Auditar el estado actual del proyecto con contexto mínimo.
2. Decidir tú las fases principales del proyecto.
3. Revisar una fase cada vez.
4. Explicar de forma clara cómo funciona esa fase actualmente.
5. Preguntar al usuario si valida el estado actual o quiere cambios.
6. Guardar el feedback del usuario durante la conversación.
7. Al terminar todas las fases, entregar un plan estructurado para aplicar los cambios solicitados.

---

## Regla principal

Aunque la revisión sea global, no leas el repositorio completo.

Haz una revisión eficiente:

* Usa `git status`.
* Usa `git diff --stat` si hay cambios pendientes.
* Usa `rg`, `git grep` o búsquedas dirigidas.
* Lee primero documentación corta si existe:

  * `CLAUDE.md`
  * `05_Docs/AI_BRIEF.md`
  * `05_Docs/AI_WORKFLOWS.md`
  * `05_Docs/AI_NO_READ_BY_DEFAULT.md`
* Lee `README.md` o `CONTEXT.md` solo si es necesario para entender arquitectura, instalación o decisiones históricas.
* No abras logs, backups, obsoletos, bases de datos, binarios ni archivos grandes salvo petición explícita.

---

## Restricciones

* No implementes cambios.
* No edites archivos.
* No hagas commit.
* No hagas push.
* No cambies de rama.
* No modifiques secretos, tokens, passwords ni credenciales.
* Si encuentras credenciales, avisa sin reproducirlas.
* No conviertas la revisión en una lectura masiva del repo.
* No propongas refactors grandes sin justificar impacto y prioridad.

---

## Fase 0 — Auditoría inicial

Antes de dividir el proyecto en fases, revisa el estado real.

Ejecuta o inspecciona, si procede:

```powershell
git status
git diff --stat
git branch --show-current
```

Después localiza estructura y componentes relevantes con búsquedas dirigidas.

Determina:

* Qué partes principales tiene el proyecto.
* Qué flujos funcionales existen.
* Qué módulos parecen críticos.
* Qué tests o diagnósticos existen.
* Qué documentación parece fuente de verdad.
* Qué zonas no deben tocarse por defecto.
* Si hay cambios pendientes sin commitear.
* Si hay riesgos visibles: secretos, archivos generados, logs, backups, obsoletos, estado versionado o workflows automáticos.

Entrega una auditoría breve de 5-12 líneas.

---

## Fase 1 — División del proyecto en fases

Después de la auditoría inicial, divide tú el proyecto en fases lógicas.

Las fases deben representar partes funcionales o técnicas del proyecto, no tareas de implementación.

Ejemplos de fases posibles:

* Ingesta / scraping de anuncios.
* Clasificación de anuncios.
* LLM cascade / proveedores externos.
* Persistencia en base de datos.
* Gestión de usuarios/configs.
* Notificaciones.
* Configurador HTML.
* GitHub Actions / ejecución programada.
* Tests y diagnóstico.
* Documentación y mantenimiento.

Adapta las fases al estado real del repo.

Formato:

```markdown
## Fases detectadas

### Fase 1 — Nombre de la fase

**Qué cubre:**  
Descripción breve.

**Archivos/áreas probables:**  
- `ruta/archivo_o_carpeta`

**Por qué es una fase independiente:**  
Motivo.

### Fase 2 — Nombre de la fase

...
```

Después de mostrar las fases detectadas, pregunta:

```text
¿Te parece bien esta división de fases?

Puedes responder:
- "aprobar"
- "cambiar orden"
- "añadir fase ..."
- "eliminar fase ..."
- "renombrar fase ..."
- "unir fases ..."
- "dividir fase ..."
```

No empieces a revisar fase por fase hasta que el usuario apruebe o ajuste la división.

---

## Revisión fase por fase

Una vez aprobada la división, revisa una fase cada vez.

Para cada fase:

1. Localiza los archivos relevantes con búsquedas dirigidas.
2. Lee solo los archivos necesarios.
3. Explica cómo funciona actualmente.
4. Identifica puntos fuertes.
5. Identifica riesgos, deuda técnica o posibles mejoras.
6. Pregunta al usuario si valida el estado actual o quiere cambios.
7. Registra el feedback antes de avanzar a la siguiente fase.

No implementes nada.

---

## Formato obligatorio para cada fase

Usa este formato:

```markdown
## Revisión de fase X — Nombre de la fase

### Qué cubre esta fase

- Explicación breve de qué parte del proyecto representa.

### Cómo funciona actualmente

- Resumen claro del flujo actual.
- Componentes principales.
- Dependencias relevantes.
- Entradas y salidas de esta fase.

### Archivos revisados

- `ruta/archivo`: motivo de revisión.

### Estado actual

- Qué parece estar bien.
- Qué parece frágil.
- Qué parece incompleto o mejorable.

### Riesgos o deuda técnica

- Riesgo 1.
- Riesgo 2.

### Posibles mejoras detectadas

- Mejora 1.
- Mejora 2.

### Pregunta interactiva

¿Validas el estado actual de esta fase o quieres introducir cambios?

Puedes responder:
- "validado"
- "quiero cambiar ..."
- "añade mejora ..."
- "elimina mejora ..."
- "profundiza en ..."
- "marca esto como prioridad alta/media/baja"
```

Después de hacer la pregunta, espera la respuesta del usuario.

No avances a la siguiente fase hasta recibir respuesta.

---

## Gestión del feedback del usuario

Cuando el usuario dé feedback sobre una fase:

1. Resume lo que ha pedido.
2. Añádelo al registro acumulado de cambios solicitados.
3. Clasifícalo por:

   * fase afectada
   * tipo de cambio
   * prioridad si el usuario la indica
   * riesgo estimado
   * archivos probables
4. Pregunta si puede avanzar a la siguiente fase.

Formato del registro:

```markdown
## Registro acumulado de cambios solicitados

### Fase X — Nombre de la fase

- **Cambio solicitado:** ...
- **Motivo:** ...
- **Prioridad:** alta/media/baja/no indicada.
- **Riesgo estimado:** bajo/medio/alto.
- **Archivos probables:** `ruta/archivo`, `ruta/carpeta`.
```

Si el usuario valida la fase sin cambios, registra:

```markdown
### Fase X — Nombre de la fase

- Estado validado por el usuario.
- Sin cambios solicitados.
```

---

## Avance entre fases

Después de registrar la decisión del usuario, pregunta:

```text
¿Avanzo a la siguiente fase?

Puedes responder:
- "sí"
- "no"
- "vuelve a la fase anterior"
- "profundiza antes de avanzar"
- "terminar revisión y generar plan"
```

Solo avanza si el usuario responde afirmativamente o pide continuar.

---

## Finalización de la revisión

Cuando se hayan revisado todas las fases, o cuando el usuario pida terminar, genera un plan estructurado para aplicar los cambios solicitados.

No implementes todavía.

El plan final debe ordenar los cambios por:

1. Riesgo.
2. Dependencias entre fases.
3. Impacto funcional.
4. Facilidad de validación.
5. Prioridad indicada por el usuario.

---

## Formato obligatorio del plan final

```markdown
# Plan estructurado de cambios

## Resumen ejecutivo

- Estado general del proyecto.
- Número de fases revisadas.
- Número de fases validadas sin cambios.
- Número de fases con cambios solicitados.
- Riesgos principales.

## Cambios solicitados por fase

### Fase X — Nombre de la fase

- **Cambio:** ...
- **Motivo:** ...
- **Prioridad:** alta/media/baja.
- **Riesgo:** bajo/medio/alto.
- **Archivos probables:** ...
- **Validación necesaria:** ...

## Orden recomendado de implementación

### Bloque 1 — Cambios seguros / preparatorios

- Cambio 1.
- Cambio 2.

### Bloque 2 — Cambios funcionales principales

- Cambio 1.
- Cambio 2.

### Bloque 3 — Tests, documentación y limpieza

- Cambio 1.
- Cambio 2.

## Plan de validación

- Tests o diagnósticos a ejecutar.
- Comprobaciones manuales.
- Riesgos que deben revisarse antes de commit.

## Documentación afectada

- `ruta/documento`: motivo.
- O "No se detecta documentación afectada".

## Siguiente paso recomendado

- Comando sugerido para implementar el primer bloque.
```

---

## Regla de eficiencia

No intentes entender todo el proyecto leyendo todo.

Haz esto:

```text
mapear → dividir fases → revisar fase actual → preguntar → registrar feedback → avanzar → generar plan final
```

No hagas esto:

```text
leer todo → resumir todo → proponer implementación inmediata
```

---

## Prioridad máxima

La prioridad es crear una revisión guiada e interactiva del proyecto, fase por fase, acumulando feedback del usuario y terminando con un plan claro de implementación.

No implementes nada hasta que el usuario lo pida explícitamente después de recibir el plan final.