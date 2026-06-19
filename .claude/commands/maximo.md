Trabaja en modo desarrollo grande, pero con control estricto de contexto.

Objetivo:
$ARGUMENTS

## Modo de trabajo

Esta tarea puede requerir varios archivos, varias fases y cierto trabajo autónomo. Aun así, debes evitar leer el repositorio completo o abrir documentación innecesaria.

Actúa como agente de desarrollo senior: localiza, planifica, implementa por bloques pequeños, valida y resume.

No trabajes como explorador general del repo. Trabaja como cirujano: busca, abre solo lo necesario, modifica lo mínimo viable y valida.

---

## Reglas principales

* No leas el repositorio completo.
* No abras carpetas grandes salvo necesidad clara.
* No abras `04_Logs/`, `06_Backups/`, `99_Obsoletos/`, bases de datos, binarios o archivos generados salvo petición explícita.
* No leas documentación larga completa salvo que sea imprescindible.
* Usa primero `rg`, `git grep`, búsqueda por nombre de archivo o búsqueda por símbolo.
* Lee primero `CLAUDE.md`.
* Lee `05_Docs/AI_BRIEF.md` solo si necesitas contexto general.
* Lee `05_Docs/AI_WORKFLOWS.md` solo si necesitas decidir el flujo por tipo de tarea.
* Lee `05_Docs/AI_NO_READ_BY_DEFAULT.md` antes de explorar zonas grandes o dudosas.
* No hagas commit.
* No hagas push.
* No cambies de rama.
* No modifiques secretos, tokens, passwords ni credenciales.
* Si encuentras credenciales, avisa sin reproducirlas.

---

## Presupuesto de contexto

Antes de abrir muchos archivos, haz una fase de localización.

Presupuesto inicial recomendado:

* Máximo 12 archivos leídos antes del primer plan.
* Máximo 3 documentos de contexto.
* Máximo 3 comandos exploratorios amplios.
* No pegues archivos completos en la conversación.
* Resume lo leído en vez de acumular contenido.

Puedes ampliar el presupuesto solo si justificas brevemente por qué hace falta.

Formato de justificación:

```text
Necesito ampliar contexto porque:
- Motivo:
- Archivos adicionales previstos:
- Riesgo de no leerlos:
```

---

## Fase 1 — Localización

Primero localiza los puntos relevantes.

Usa comandos como:

```powershell
git status
rg "texto_o_simbolo_relevante"
git grep "texto_o_simbolo_relevante"
```

Determina:

* Qué parte del proyecto afecta: backend, HTML, configs, usuarios, clasificador, GitHub Actions, documentación u otra.
* Qué archivos parecen realmente relevantes.
* Qué archivos NO vas a abrir.
* Qué validaciones serán necesarias.

No edites todavía.

---

## Fase 2 — Plan de implementación

Antes de modificar archivos, genera un plan breve.

Debe incluir:

```markdown
## Plan

### Objetivo técnico
- Qué se va a conseguir.

### Archivos candidatos
- `ruta/archivo`: por qué puede tocarse.

### Cambios previstos
- Cambio 1.
- Cambio 2.
- Cambio 3.

### Validación prevista
- Comandos o pruebas a ejecutar.

### Riesgos
- Riesgo 1.
- Riesgo 2.
```

Si el objetivo es claro y no hay riesgo destructivo, continúa implementando sin esperar confirmación.

Pide confirmación solo si:

* Hay que borrar datos.
* Hay que tocar credenciales.
* Hay que hacer cambios irreversibles.
* Hay ambigüedad funcional importante.
* Hay varias arquitecturas posibles con impacto alto.

---

## Fase 3 — Implementación por bloques

Implementa en bloques pequeños.

Cada bloque debe cumplir:

* Tocar pocos archivos.
* Mantener compatibilidad con lo existente.
* Evitar refactors no solicitados.
* No cambiar estilo global.
* No reescribir archivos completos si basta con un patch localizado.
* Mantener nombres y estructura salvo necesidad clara.
* Evitar dependencias nuevas salvo justificación.

Después de cada bloque importante, actualiza internamente el estado:

```text
Hecho:
- ...

Pendiente:
- ...

Riesgos detectados:
- ...
```

No hace falta mostrar todo el razonamiento, pero sí mantener el avance organizado.

---

## Fase 4 — Validación

Ejecuta las validaciones razonables según el tipo de cambio.

Prioridad:

1. Tests específicos del área modificada.
2. Diagnósticos existentes.
3. Comandos de dry-run.
4. `git diff --stat`.
5. Revisión manual del diff.

Si no puedes ejecutar una validación, explica el motivo.

No ejecutes comandos potencialmente destructivos.

No ejecutes `main.py` si puede interferir con GitHub Actions o producción, salvo que sea necesario y seguro.

---

## Fase 5 — Revisión del diff

Antes de terminar, revisa:

```powershell
git status
git diff --stat
```

Si el diff es razonable, resume los cambios.

Si el diff es demasiado grande o toca archivos inesperados, detente y avisa.

Comprueba especialmente:

* Archivos modificados por accidente.
* Cambios de formato masivos.
* Secretos o credenciales.
* Archivos generados.
* Logs, backups u obsoletos tocados por error.
* Cambios en `alerts.db` o `configs/` no esperados.

---

## Formato final obligatorio

Termina siempre con:

```markdown
## Resumen

- Qué se ha hecho.
- Qué problema resuelve.

## Archivos modificados

- `ruta/archivo`: descripción breve del cambio.

## Comandos ejecutados

- `comando`: resultado breve.

## Validación

- Qué se ha comprobado.
- Qué no se ha podido comprobar y por qué.

## Diff

- Resumen del diff.
- Archivos tocados.
- Cambios inesperados, si los hay.

## Riesgos

- Riesgos técnicos o funcionales pendientes.

## Siguiente paso recomendado

- Qué debería revisar o probar el usuario antes de hacer commit.
```

---

## Regla de eficiencia

Aunque esta sea una tarea grande, no conviertas el desarrollo en una lectura masiva del repo.

La estrategia correcta es:

```text
buscar → leer poco → planificar → implementar por bloques → validar → revisar diff
```

No hagas:

```text
leer todo → entender todo → cambiar mucho → validar al final
```

---

## Regla de autonomía

Trabaja de forma autónoma mientras el objetivo esté claro y los cambios sean seguros.

No pidas permiso para cada pequeño paso.

Detente y pregunta solo ante decisiones de alto impacto, riesgo destructivo, credenciales, borrado de datos o ambigüedad funcional real.

## Impacto en documentación

- ¿Este cambio requiere actualizar documentación? Sí/No.
- Si sí, archivos actualizados:
  - `ruta/archivo`: motivo.
- Si no, motivo por el que no aplica.