# Wallapop Alerts — instrucciones para agentes

## Regla principal

Trabaja siempre con mínimo contexto.

No leas el repositorio completo salvo petición explícita. Antes de abrir archivos, localiza lo relevante usando `rg`, `git grep`, `find` o búsquedas dirigidas.

Haz cambios pequeños, seguros y verificables. Evita exploración amplia, refactors innecesarios y lectura de carpetas grandes.

---

## Idioma y estilo

* Responde en español.
* Sé directo, técnico y práctico.
* Antes de editar, explica brevemente qué archivos crees que tocarás y por qué.
* Si hay varias opciones, recomienda una y justifica brevemente.
* No pegues archivos completos en la conversación salvo petición explícita.

---

## Documentación auxiliar

Usa estos archivos solo cuando aporten valor a la tarea:

* `05_Docs/AI_BRIEF.md`: resumen del proyecto, estructura general y componentes principales.
* `05_Docs/AI_WORKFLOWS.md`: flujo recomendado según tipo de cambio.
* `05_Docs/AI_NO_READ_BY_DEFAULT.md`: archivos y carpetas que no deben leerse salvo petición explícita.

No leas `README.md`, `CONTEXT.md` ni documentación larga completa como primer paso salvo que la tarea lo requiera.

---

## Flujo de trabajo

Para cualquier cambio:

1. Entiende el objetivo exacto.
2. Localiza archivos relevantes con `rg` o `git grep`.
3. Lee solo los archivos mínimos necesarios.
4. Propón un plan breve antes de editar.
5. Aplica el cambio mínimo.
6. Ejecuta validaciones relevantes si procede.
7. Revisa `git diff`.
8. Resume lo hecho.

No hagas cambios amplios, reestructuraciones o refactors grandes salvo petición explícita.

---

## Reglas de edición

* No reescribas archivos completos si basta con un patch pequeño.
* No cambies formato global, indentación masiva o estilo de archivos no relacionados.
* No renombres funciones, clases o archivos salvo necesidad clara.
* No introduzcas dependencias nuevas sin explicar por qué.
* No ejecutes comandos destructivos.
* No borres datos, bases de datos, logs ni configuraciones sin confirmación explícita.
* No abras logs, backups, obsoletos, bases de datos o archivos grandes salvo petición explícita.
* No modifiques secretos, tokens, passwords ni credenciales.

---

## Seguridad y secretos

Nunca muestres, copies, muevas, modifiques ni hardcodees credenciales.

Si detectas credenciales en archivos del repo:

1. Avisa sin reproducirlas.
2. Recomienda moverlas a GitHub Secrets, variables de entorno o mecanismo seguro equivalente.
3. No hagas cambios automáticos sobre ellas salvo petición explícita.

---

## Reglas sobre Git

* El usuario revisa, commitea y sincroniza con GitHub Desktop.
* No hagas commit salvo petición explícita.
* No hagas push.
* No cambies de rama salvo petición explícita.
* Antes de terminar, muestra `git status` y, si procede, `git diff --stat`.

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

## Prioridad máxima

Reducir consumo de contexto, evitar exploración innecesaria y aplicar cambios mínimos, seguros y revisables.