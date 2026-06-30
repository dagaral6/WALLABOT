---
description: Revisión interactiva del proyecto por fases usando AskUserQuestion
allowed-tools: Read, Grep, Glob, Bash, AskUserQuestion
---

Trabaja en modo revisión interactiva guiada del proyecto usando preguntas interactivas de Claude Code.

## Objetivo

Revisar el proyecto completo en su estado actual, dividirlo en fases funcionales o técnicas, explicar cada fase mediante un flujo guiado, recoger feedback del usuario con preguntas interactivas tipo pop-up y generar al final un plan estructurado de cambios.

No implementes cambios durante esta revisión.

---

## Propósito

Este comando sirve para revisar el proyecto completo en su estado actual, dividirlo en fases funcionales/técnicas y recorrerlas una a una usando `AskUserQuestion`.

El objetivo no es modificar código, sino:

1. Entender el estado actual del proyecto con contexto mínimo.
2. Dividir el proyecto en fases lógicas.
3. Explicar cada fase una por una.
4. Usar `AskUserQuestion` para que el usuario valide la fase o solicite cambios.
5. Guardar el feedback acumulado.
6. Continuar automáticamente con la siguiente fase cuando el usuario responda.
7. Al terminar, entregar un plan estructurado de implementación con todos los cambios solicitados.

---

## Regla principal

Aunque la revisión sea global, no leas el repositorio completo.

Trabaja con contexto mínimo:

- Usa `git status`.
- Usa `git diff --stat` si hay cambios pendientes.
- Usa `rg`, `git grep` y búsquedas dirigidas.
- Lee primero:
  - `CLAUDE.md`
  - `05_Docs/AI_BRIEF.md`
  - `05_Docs/AI_WORKFLOWS.md`
  - `05_Docs/AI_NO_READ_BY_DEFAULT.md`
- Lee `README.md` o `CONTEXT.md` solo si es necesario para entender arquitectura o decisiones históricas.
- No abras `04_Logs/`, `06_Backups/`, `99_Obsoletos/`, bases de datos, binarios, archivos grandes ni credenciales salvo petición explícita.

---

## Restricciones

- No edites archivos.
- No implementes cambios.
- No hagas commit.
- No hagas push.
- No cambies de rama.
- No ejecutes comandos destructivos.
- No modifiques secretos, tokens, passwords ni credenciales.
- Si detectas credenciales, avisa sin reproducirlas.
- No conviertas la revisión en una lectura masiva del repo.

---

## Uso obligatorio de AskUserQuestion

Cuando necesites una decisión del usuario, no hagas una pregunta normal en texto.

Debes invocar la herramienta `AskUserQuestion` de Claude Code para mostrar una pregunta interactiva tipo pop-up con opciones.

Reglas:

- Usa `AskUserQuestion` después de proponer la división inicial de fases.
- Usa `AskUserQuestion` al terminar la revisión de cada fase.
- Usa `AskUserQuestion` después de registrar feedback para decidir si avanzar, profundizar o terminar.
- Usa `AskUserQuestion` antes de generar el plan final si aún quedan fases pendientes.
- Cada pregunta debe tener entre 2 y 4 opciones claras.
- No continúes a la siguiente fase hasta recibir respuesta mediante `AskUserQuestion`.
- Si la herramienta se llama `AskUser` en esta versión de Claude Code, usa `AskUser`.
- Si ninguna herramienta interactiva está disponible, dilo explícitamente y usa preguntas normales como fallback.

No escribas frases como “responde con...” como mecanismo principal. La interacción principal debe hacerse mediante `AskUserQuestion`.

---

## Flujo interactivo obligatorio

Debes trabajar como un proceso guiado.

### Paso 1 — Auditoría inicial breve

Primero revisa el estado general:

```powershell
git status
git diff --stat
git branch --show-current
```

Después localiza la estructura del proyecto con búsquedas dirigidas y documentación corta.

Entrega una auditoría breve:

```markdown
## Auditoría inicial

- Rama actual:
- Cambios pendientes:
- Componentes detectados:
- Documentación útil:
- Tests/diagnósticos detectados:
- Riesgos iniciales:
```

---

### Paso 2 — División inicial en fases

Divide tú el proyecto en fases funcionales o técnicas.

Ejemplos orientativos:

- Scraping / ingesta de anuncios.
- Clasificación por reglas.
- LLM cascade / proveedores.
- Base de datos y persistencia.
- Gestión de usuarios/configs.
- Notificaciones.
- Configurador HTML.
- GitHub Actions / ejecución programada.
- Tests y diagnóstico.
- Documentación y mantenimiento.

Adapta las fases al estado real del repo.

Presenta la lista así:

```markdown
## Fases detectadas

1. Nombre de fase — descripción breve.
2. Nombre de fase — descripción breve.
3. Nombre de fase — descripción breve.
```

Después usa `AskUserQuestion`.

Pregunta:

```text
¿Qué quieres hacer con esta división inicial de fases?
```

Opciones:

1. Aprobar división y empezar Fase 1.
2. Ajustar fases antes de empezar.
3. Profundizar en la división propuesta.
4. Terminar y generar resumen inicial.

Interpretación:

- Si el usuario elige aprobar, empieza automáticamente la revisión de la Fase 1.
- Si elige ajustar fases, pide el ajuste concreto, actualiza la división y vuelve a usar `AskUserQuestion`.
- Si elige profundizar, explica mejor la división y vuelve a usar `AskUserQuestion`.
- Si elige terminar, genera un resumen inicial sin plan de implementación completo.

No revises ninguna fase concreta hasta que el usuario apruebe o ajuste la división.

---

## Paso 3 — Revisión fase por fase

Cuando el usuario apruebe la división, empieza por la Fase 1.

Para cada fase:

1. Localiza los archivos relevantes con `rg`, `git grep` o búsqueda por nombre.
2. Lee solo los archivos necesarios.
3. Explica cómo funciona actualmente.
4. Resume puntos fuertes.
5. Resume problemas, riesgos o deuda técnica.
6. Propón posibles cambios, sin implementarlos.
7. Usa `AskUserQuestion` para que el usuario decida.
8. Registra el feedback.
9. Continúa automáticamente con la siguiente fase si la respuesta permite avanzar.

---

## Formato obligatorio para cada fase

```markdown
## Fase X/Y — Nombre de la fase

### Cómo funciona actualmente

- Explicación breve del flujo.
- Entradas.
- Procesos principales.
- Salidas.
- Dependencias relevantes.

### Archivos revisados

- `ruta/archivo`: motivo.

### Estado actual

- Correcto:
  - ...
- Mejorable:
  - ...
- Riesgos:
  - ...

### Posibles cambios detectados

- Cambio posible 1.
- Cambio posible 2.
- Cambio posible 3.
```

Después de mostrar este resumen, usa `AskUserQuestion`.

Pregunta:

```text
¿Qué quieres hacer con esta fase?
```

Opciones:

1. Validar fase y continuar.
2. Registrar cambios para esta fase.
3. Profundizar más en esta fase.
4. Terminar revisión y generar plan final.

Interpretación:

- Si elige opción 1, registra la fase como validada y continúa automáticamente con la siguiente fase.
- Si elige opción 2, pide el cambio concreto, regístralo y vuelve a usar `AskUserQuestion`.
- Si elige opción 3, profundiza solo en esa fase con contexto mínimo y vuelve a usar `AskUserQuestion`.
- Si elige opción 4, detén la revisión y genera el plan final con lo revisado hasta ahora.

No hagas una pregunta normal en texto en este punto. Usa `AskUserQuestion`.

---

## Cómo actuar según la respuesta del usuario

### Si el usuario valida la fase

Registra:

```markdown
### Feedback registrado — Fase X

- Estado validado por el usuario.
- Sin cambios solicitados.
```

Después continúa automáticamente con la siguiente fase.

---

### Si el usuario quiere registrar cambios

Pide el cambio concreto usando `AskUserQuestion` si puedes expresarlo con opciones, o pregunta en texto solo si necesitas que el usuario escriba contenido libre.

Registra el cambio así:

```markdown
### Feedback registrado — Fase X

- Cambio solicitado:
- Motivo:
- Prioridad: no indicada / baja / media / alta.
- Riesgo estimado: bajo / medio / alto.
- Archivos probables:
- Validación probable:
```

Después usa `AskUserQuestion`.

Pregunta:

```text
Cambio registrado. ¿Qué quieres hacer ahora?
```

Opciones:

1. Añadir otro cambio a esta fase.
2. Validar fase y continuar.
3. Profundizar más en esta fase.
4. Terminar revisión y generar plan final.

---

### Si el usuario quiere profundizar

Haz una revisión más concreta solo sobre ese punto, con contexto mínimo.

Después vuelve a usar `AskUserQuestion` con las mismas opciones de decisión de fase.

---

### Si el usuario quiere terminar

Detén el recorrido de fases y genera el plan final con lo revisado y registrado hasta ahora.

---

## Registro acumulado

Mantén durante toda la conversación un registro acumulado con esta estructura:

```markdown
# Registro acumulado de revisión

## Fase X — Nombre

### Estado
- Validada / Con cambios solicitados / Pendiente.

### Cambios solicitados
- Cambio:
- Motivo:
- Prioridad:
- Riesgo:
- Archivos probables:
- Validación:

### Riesgos marcados
- Riesgo:
- Motivo:
```

No hace falta mostrar el registro completo en cada respuesta salvo que ayude. Pero debes usarlo para generar el plan final.

---

## Paso 4 — Plan final

Cuando se revisen todas las fases o el usuario pida terminar, genera un plan estructurado de implementación.

No implementes todavía.

Formato:

```markdown
# Plan estructurado de implementación

## Resumen ejecutivo

- Fases revisadas:
- Fases validadas sin cambios:
- Fases con cambios solicitados:
- Riesgos principales:
- Prioridad general recomendada:

## Cambios solicitados por fase

### Fase X — Nombre

- Cambio:
- Motivo:
- Prioridad:
- Riesgo:
- Archivos probables:
- Validación necesaria:

## Orden recomendado de implementación

### Bloque 1 — Cambios seguros/preparatorios

- ...

### Bloque 2 — Cambios funcionales principales

- ...

### Bloque 3 — Tests, documentación y limpieza

- ...

## Plan de validación

- Tests a ejecutar:
- Diagnósticos:
- Comprobaciones manuales:
- Riesgos a revisar antes de commit:

## Documentación afectada

- Documento:
- Motivo:

## Siguiente paso recomendado

- Comando recomendado para empezar a implementar el primer bloque.
```

---

## Regla de interacción

La revisión debe sentirse como un flujo guiado de Claude Code, no como una lista de preguntas manuales.

No presentes todas las fases en detalle de una sola vez.

No generes el plan final hasta que:

- todas las fases hayan sido revisadas, o
- el usuario pida explícitamente terminar y generar plan.

Después de cada decisión importante, usa `AskUserQuestion`.

Cuando el usuario responda, continúa desde el punto exacto donde se quedó.

---

## Regla de eficiencia

No intentes entender todo el proyecto leyendo todo.

Haz esto:

```text
mapear → dividir fases → usar AskUserQuestion → revisar fase actual → registrar feedback → avanzar → generar plan final
```

No hagas esto:

```text
leer todo → resumir todo → preguntar en texto normal → proponer implementación inmediata
```

---

## Prioridad máxima

Crear un proceso de revisión guiado, fase por fase, que use `AskUserQuestion` para que el usuario valide, corrija o añada cambios, y que al final produzca un plan estructurado sin haber modificado código.
