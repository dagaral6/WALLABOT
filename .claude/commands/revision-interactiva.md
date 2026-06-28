Trabaja en modo revisión interactiva guiada del proyecto.

## Objetivo

Revisar el proyecto completo en su estado actual, dividirlo en fases funcionales o técnicas, explicar cada fase de forma interactiva, recoger feedback del usuario y generar al final un plan estructurado de cambios.

No implementes cambios durante esta revisión.

## Propósito

Este comando sirve para revisar el proyecto completo en su estado actual, dividirlo en fases funcionales/técnicas y recorrerlas una a una con preguntas interactivas al usuario.

No implementes cambios durante esta revisión.

El objetivo no es modificar código, sino:

1. Entender el estado actual del proyecto con contexto mínimo.
2. Dividir el proyecto en fases lógicas.
3. Explicar cada fase una por una.
4. Preguntar al usuario si valida la fase o quiere cambios.
5. Guardar el feedback acumulado.
6. Continuar automáticamente con la siguiente fase cuando el usuario responda.
7. Al terminar, entregar un plan estructurado de implementación con todos los cambios solicitados.

---

## Regla principal

Aunque la revisión sea global, no leas el repositorio completo.

Trabaja con contexto mínimo:

* Usa `git status`.
* Usa `git diff --stat` si hay cambios pendientes.
* Usa `rg`, `git grep` y búsquedas dirigidas.
* Lee primero:

  * `CLAUDE.md`
  * `05_Docs/AI_BRIEF.md`
  * `05_Docs/AI_WORKFLOWS.md`
  * `05_Docs/AI_NO_READ_BY_DEFAULT.md`
* Lee `README.md` o `CONTEXT.md` solo si es necesario para entender arquitectura o decisiones históricas.
* No abras `04_Logs/`, `06_Backups/`, `99_Obsoletos/`, bases de datos, binarios, archivos grandes ni credenciales salvo petición explícita.

---

## Restricciones

* No edites archivos.
* No implementes cambios.
* No hagas commit.
* No hagas push.
* No cambies de rama.
* No ejecutes comandos destructivos.
* No modifiques secretos, tokens, passwords ni credenciales.
* Si detectas credenciales, avisa sin reproducirlas.
* No conviertas la revisión en una lectura masiva del repo.

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

### Paso 2 — División inicial en fases

Divide tú el proyecto en fases funcionales o técnicas.

Ejemplos orientativos:

* Scraping / ingesta de anuncios.
* Clasificación por reglas.
* LLM cascade / proveedores.
* Base de datos y persistencia.
* Gestión de usuarios/configs.
* Notificaciones.
* Configurador HTML.
* GitHub Actions / ejecución programada.
* Tests y diagnóstico.
* Documentación y mantenimiento.

Adapta las fases al estado real del repo.

Presenta la lista así:

```markdown
## Fases detectadas

1. Nombre de fase — descripción breve.
2. Nombre de fase — descripción breve.
3. Nombre de fase — descripción breve.
```

Después pregunta:

```text
¿Apruebas esta división de fases?

Responde:
- "aprobar" para empezar la revisión fase por fase.
- "cambiar orden: ..." para reordenarlas.
- "añadir fase: ..." para añadir una.
- "eliminar fase: ..." para quitar una.
- "unir fases: ..." para combinar fases.
- "dividir fase: ..." para separar una fase.
```

Detente aquí y espera la respuesta del usuario.

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
7. Pregunta al usuario si valida la fase o quiere cambios.
8. Espera la respuesta del usuario.
9. Registra el feedback.
10. Continúa automáticamente con la siguiente fase si la respuesta permite avanzar.

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

### Pregunta interactiva

¿Validas esta fase o quieres añadir cambios al plan final?

Responde con una de estas opciones:
- "validado"
- "añadir cambio: ..."
- "cambiar prioridad: ..."
- "profundizar: ..."
- "marcar riesgo: ..."
- "volver a fase anterior"
- "terminar revisión y generar plan"
```

Detente aquí y espera la respuesta del usuario.

---

## Cómo actuar según la respuesta del usuario

### Si responde "validado"

Registra:

```markdown
### Feedback registrado — Fase X

- Estado validado por el usuario.
- Sin cambios solicitados.
```

Después continúa con la siguiente fase.

### Si responde "añadir cambio: ..."

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

Después pregunta brevemente:

```text
Cambio registrado. ¿Quieres añadir otro cambio a esta fase o avanzo a la siguiente?
```

Si el usuario indica avanzar, continúa con la siguiente fase.

### Si responde "cambiar prioridad: ..."

Actualiza el registro acumulado y continúa según indique el usuario.

### Si responde "profundizar: ..."

Haz una revisión más concreta solo sobre ese punto, con contexto mínimo, y vuelve a preguntar si valida o añade cambios.

### Si responde "marcar riesgo: ..."

Añade el riesgo al registro acumulado de esa fase y pregunta si avanza.

### Si responde "volver a fase anterior"

Vuelve a la fase anterior y muestra su resumen y feedback acumulado.

### Si responde "terminar revisión y generar plan"

Detén el recorrido de fases y genera el plan final.

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

La revisión debe sentirse como una conversación guiada.

No presentes todas las fases en detalle de una sola vez.

No generes el plan final hasta que:

* todas las fases hayan sido revisadas, o
* el usuario pida explícitamente terminar y generar plan.

Después de cada pregunta interactiva, espera respuesta.

Cuando el usuario responda, continúa desde el punto exacto donde se quedó.

---

## Prioridad máxima

Crear un proceso de revisión guiado, fase por fase, que permita al usuario validar, corregir o añadir cambios, y que al final produzca un plan estructurado sin haber modificado código.