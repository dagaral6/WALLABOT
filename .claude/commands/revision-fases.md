Trabaja en modo revisión estratégica por fases, con interacción obligatoria con el usuario.

Objetivo:
$ARGUMENTS

## Propósito del comando

Este comando sirve para revisar el estado actual del proyecto, detectar áreas de mejora y dividir el trabajo en fases ordenadas.

No implementes cambios directamente.

Tu misión es:

1. Auditar el estado actual del proyecto con contexto mínimo.
2. Identificar problemas, riesgos, deuda técnica y oportunidades de mejora.
3. Dividir el trabajo en fases lógicas y ordenadas.
4. Presentar una fase cada vez.
5. Esperar respuesta del usuario antes de avanzar a la siguiente fase o proponer implementación.

---

## Regla principal

Aunque la revisión sea global, no leas el repositorio completo.

Haz una revisión estratégica y eficiente:

* Usa `git status`.
* Usa `git diff --stat` si hay cambios pendientes.
* Usa `rg`, `git grep` o búsquedas dirigidas.
* Lee primero documentación corta si existe:

  * `CLAUDE.md`
  * `05_Docs/AI_BRIEF.md`
  * `05_Docs/AI_WORKFLOWS.md`
  * `05_Docs/AI_NO_READ_BY_DEFAULT.md`
* Lee `README.md` o `CONTEXT.md` solo si hace falta para entender arquitectura, instalación o decisiones históricas.
* No abras logs, backups, obsoletos, bases de datos, binarios ni archivos grandes salvo petición explícita.

---

## Restricciones

* No hagas commit.
* No hagas push.
* No cambies de rama.
* No edites archivos salvo que el usuario lo pida explícitamente después.
* No modifiques secretos, tokens, passwords ni credenciales.
* Si encuentras credenciales, avisa sin reproducirlas.
* No conviertas la revisión en una lectura masiva del repo.
* No propongas refactors grandes sin justificar impacto y prioridad.

---

## Fase 0 — Auditoría inicial

Antes de proponer fases, revisa el estado real del proyecto.

Ejecuta o inspecciona, si procede:

```powershell
git status
git diff --stat
git branch --show-current
```

Después localiza estructura y componentes relevantes con búsquedas dirigidas.

Determina:

* Qué partes principales tiene el proyecto.
* Qué áreas parecen críticas.
* Qué tests o diagnósticos existen.
* Qué documentación parece fuente de verdad.
* Qué zonas no deben tocarse por defecto.
* Si hay cambios pendientes sin commitear.
* Si hay riesgos visibles: secretos, archivos generados, logs, backups, obsoletos, estado versionado o workflows automáticos.

Entrega una auditoría breve de 5-12 líneas.

---

## Fase 1 — Mapa del proyecto

Crea un mapa breve del estado actual.

Formato:

```markdown
## Mapa actual del proyecto

### Componentes principales

- `ruta/`: función.

### Flujos importantes

- Flujo 1.
- Flujo 2.

### Tests / diagnósticos existentes

- `ruta/test`: qué cubre.

### Documentación relevante

- `ruta/documento`: para qué sirve.

### Riesgos visibles

- Riesgo 1.
- Riesgo 2.
```

No entres aún en soluciones detalladas.

---

## Fase 2 — Propuesta de fases

Divide el trabajo en fases ordenadas.

Cada fase debe ser concreta, revisable y accionable.

Formato:

```markdown
## Plan propuesto por fases

### Fase 1 — Nombre de la fase

**Objetivo:**  
Qué se quiere conseguir.

**Motivo:**  
Por qué esta fase va primero.

**Archivos o áreas probables:**  
- `ruta/archivo_o_carpeta`

**Cambios esperados:**  
- Cambio 1.
- Cambio 2.

**Validación:**  
- Tests, comandos o comprobaciones.

**Riesgos:**  
- Riesgo 1.

**Resultado esperado:**  
Qué debería quedar terminado al cerrar esta fase.
```

Ordena las fases por:

1. Seguridad y estado del repo.
2. Corrección de bugs críticos.
3. Estabilidad de tests.
4. Arquitectura base.
5. Funcionalidades nuevas.
6. Optimización.
7. Documentación.
8. Limpieza.

---

## Interacción obligatoria

Después de presentar el plan por fases, no sigas trabajando automáticamente.

Pregunta al usuario:

```text
¿Te parece bien este orden de fases?

Responde con una de estas opciones:
1. aprobar
2. cambiar orden
3. modificar una fase
4. añadir una fase
5. eliminar una fase
6. profundizar en una fase concreta
```

Espera respuesta.

---

## Trabajo fase por fase

Cuando el usuario apruebe el plan o una fase concreta, trabaja solo sobre esa fase.

Para cada fase:

1. Reexplica el objetivo de la fase.
2. Localiza archivos relevantes.
3. Propón microplan.
4. Pregunta si el usuario lo aprueba.
5. Solo implementa si el usuario lo pide explícitamente.
6. Valida.
7. Resume resultado.
8. Pregunta si avanzar a la siguiente fase.

Formato al cerrar cada fase:

```markdown
## Cierre de fase

### Fase completada

- Nombre de la fase.

### Qué se ha revisado

- Punto 1.
- Punto 2.

### Qué se ha cambiado

- Nada, si solo era revisión.
- O lista de cambios si el usuario pidió implementación.

### Validación

- Comandos ejecutados.
- Resultado.

### Riesgos pendientes

- Riesgo 1.

### Decisión necesaria

¿Avanzamos a la siguiente fase, ajustamos esta fase o paramos aquí?
```

---

## Modo de respuesta del usuario

Cuando preguntes al usuario, ofrece opciones claras:

```text
Puedes responder:
- "aprobar"
- "ajusta la fase X"
- "añade una fase para ..."
- "profundiza en la fase X"
- "implementa la fase X"
- "paramos aquí"
```

No avances a otra fase si el usuario no lo ha aprobado.

---

## Impacto en documentación

En cada fase, evalúa si hay documentación afectada.

Incluye siempre:

```markdown
## Impacto en documentación

- ¿Requiere actualizar documentación? Sí/No.
- Si sí, documentación afectada:
  - `ruta/documento`: motivo.
- Si no, motivo por el que no aplica.
```

---

## Formato final de la revisión inicial

La primera respuesta de este comando debe terminar con:

```markdown
## Siguiente decisión

¿Te parece bien este plan por fases?

Opciones:
1. aprobar
2. cambiar orden
3. modificar una fase
4. añadir una fase
5. eliminar una fase
6. profundizar en una fase concreta
```

---

## Regla de eficiencia

No intentes “entender todo el proyecto” leyendo todo.

Haz esto:

```text
mapear → detectar áreas → priorizar → dividir fases → pedir aprobación
```

No hagas esto:

```text
leer todo → resumir todo → proponer cambios enormes
```

---

## Prioridad máxima

Mantener una revisión ordenada, interactiva y eficiente en tokens, sin implementar nada hasta que el usuario apruebe una fase concreta.