# Alta y modificación de usuarios

Guía corta y operativa para dar de alta a alguien nuevo en wallabot, modificar
un alta existente y darlo de baja. Es el procedimiento completo: lo que hay que
tocar y en qué orden.

> **Idea clave:** el cuello de botella es la **lista blanca** de
> `01_Core/bot_settings.yaml` (`allowed_senders`). Un correo que no esté ahí se
> ignora: el bot lo marca como leído, lo deja en el log y no aplica nada. Todo
> lo demás (config, base de datos) se crea solo en cuanto esa persona envía su
> primer formulario desde un correo autorizado.

---

## Conceptos: nombre normalizado y user_id

- **Correo**: el remitente real desde el que esa persona enviará el formulario.
  Es lo que identifica al usuario (no el nombre que escriba en el formulario).
- **user_id**: identificador corto y normalizado. Decide:
  - el archivo de config: `01_Core/configs/<user_id>.yaml`
  - el prefijo en la base de datos `alerts.db`
  - qué config sustituye cada correo nuevo de ese remitente

**Reglas del user_id**: solo letras, números, `_` o `-` (sin espacios, sin
tildes, sin Ñ). Minúsculas por convención. Ejemplos válidos: `dario`, `marc`,
`ana_lopez`, `user-3`.

> El **nombre** que la persona escribe en el formulario (p. ej. "Marcos") da
> igual a efectos de identidad: el bot usa el **correo** para saber quién es y
> qué config sustituir. Marc puede poner "Marc" o "Marcos" sin duplicar nada.

---

## Dar de alta a un usuario nuevo (paso a paso)

Hay que tocar **tres sitios**. Solo el primero (la lista blanca) es obligatorio
para que el bot lo acepte; los otros dos son para que el formulario le ofrezca
su nombre y para dejarlo documentado.

### 1. Lista blanca del bot (OBLIGATORIO)

Desde `01_Core`:

```powershell
python3 manage.py add-user correo.de.la.persona@gmail.com user_id
```

Esto añade la entrada `correo: user_id` en `allowed_senders` de
`bot_settings.yaml`, preservando los comentarios y dejando un backup en
`06_Backups/configs/`. No hace falta reiniciar el bot: `bot_settings.yaml` se
relee en cada pasada.

Comprobar que ha quedado bien:

```powershell
python3 manage.py list
```

> Alternativa manual (si no quieres usar `manage.py`): edita
> `01_Core/bot_settings.yaml` y añade bajo `allowed_senders:` una línea
> `  correo.de.la.persona@gmail.com: user_id`. Respeta los dos espacios de
> indentación.

### 2. Formulario HTML (recomendado)

Para que esa persona pueda elegir su nombre en el desplegable del formulario,
edita `02_Herramienta/wallapop_config_v18.html` (la última versión) en **dos
puntos**:

- El array `USERS` (busca `const USERS = [`):

  ```javascript
  const USERS = [
    { id: "dario", name: "Darío", email: "dariogarciaalvarez01@gmail.com" },
    { id: "marc",  name: "Marc",  email: "marcferrando01@gmail.com" },
    { id: "user_id", name: "Nombre a mostrar", email: "correo.de.la.persona@gmail.com" },
  ];
  ```

- El desplegable `<select id="who">` (busca `<select id="who">`), añade una
  opción con el **mismo `id`** que en `USERS`:

  ```html
  <option value="user_id">Nombre a mostrar</option>
  ```

> El `id` del `USERS` y el `value` del `<option>` **deben coincidir** con el
> `user_id` de la lista blanca. El campo `email` del formulario es solo el valor
> por defecto: dentro del formulario se puede editar y se recuerda en esa copia
> del HTML (pero el cambio bueno hay que hacerlo aquí, en el código).

### 3. Que la persona envíe su primer formulario

1. Abre el HTML, elige su nombre en el desplegable, define sus alertas y pulsa
   **Enviar a wallabot**.
2. El correo debe salir **desde el correo autorizado** (el de la lista blanca).
3. El bot lo detecta en ≤ 5 minutos (`inbox_check_minutes`), valida, crea
   `01_Core/configs/<user_id>.yaml` y responde "Configuración aplicada ✓" con la
   lista de alertas activas.

A partir de ahí ya recibe avisos. No hay que crear la config ni la base de datos
a mano: se generan solas con ese primer correo.

---

## Modificar un alta existente

Según lo que quieras cambiar:

### Cambiar el correo de un usuario (mismo user_id)

El correo es la clave de identidad, así que es **baja del correo viejo + alta
del nuevo** apuntando al mismo `user_id`. Desde `01_Core`:

```powershell
python3 manage.py remove-user correo.viejo@gmail.com
python3 manage.py add-user  correo.nuevo@gmail.com  user_id
```

La config (`configs/<user_id>.yaml`) y la base de datos se conservan: solo
cambia desde qué correo puede enviar formularios. Actualiza también el `email`
de ese usuario en el array `USERS` del HTML.

### Cambiar el nombre que se muestra (no afecta a la identidad)

Solo en el HTML: cambia el `name` en `USERS` y el texto del `<option>`. No toques
la lista blanca ni el `user_id`.

### Cambiar a dónde llegan los avisos (destinatario)

El destinatario sale del campo `email` de ese usuario en el HTML (lo que se
escribe como `recipient` en el YAML). Cámbialo en `USERS` (o, puntualmente,
editándolo en el propio formulario antes de enviar) y reenvía el formulario: la
config nueva sustituye a la anterior.

### Cambiar el user_id (rara vez necesario)

Es lo más aparatoso porque arrastra el nombre del archivo de config y el prefijo
en la BD. Lo práctico:

1. `manage.py add-user <correo> nuevo_id` y `manage.py remove-user <correo>`
   para dejar la lista blanca apuntando al `nuevo_id`.
2. Renombra `configs/viejo_id.yaml` a `configs/nuevo_id.yaml` (o que reenvíe el
   formulario para regenerarla).
3. Actualiza el `id` en `USERS` y el `value` del `<option>` en el HTML.
4. Las filas con el prefijo viejo en `alerts.db` quedan huérfanas pero son
   inofensivas (ya no se consultan).

---

## Dar de baja a un usuario

Desde `01_Core`:

```powershell
python3 manage.py remove-user user_id
# o por correo:
python3 manage.py remove-user correo.de.la.persona@gmail.com
```

Quita sus entradas de la lista blanca (con backup). **No** borra su
`configs/<user_id>.yaml` ni sus filas en la BD: simplemente deja de aceptar
correos suyos y de mandarle avisos. Si quieres, borra también su `.yaml` a mano.
Conviene quitar su entrada del array `USERS` y su `<option>` en el HTML para que
no aparezca en el desplegable.

---

## Eliminar una alerta concreta (no es una baja de usuario)

Una "alerta" es una entrada de la lista `alerts:` dentro del config del usuario.
Para quitar alguna sin dar de baja al usuario, tienes tres vías:

- **Desde el formulario** (lo más cómodo): pestaña **Eliminar alertas**, pega la
  lista de alertas activas que llega en los correos de confirmación, marca las
  que sobran y envía. El bot las quita y responde con las que quedan.
- **A mano**: edita `01_Core/configs/<user_id>.yaml` y borra ese bloque
  `- name: ...`.
- **Regenerando**: vuelve a generar la config en el formulario sin esa alerta y
  reenvíala (la del buzón sustituye a la anterior).

Lo que esa alerta dejó en `alerts.db` queda huérfano pero es inofensivo.

---

## Checklist rápido de alta

- [ ] `manage.py add-user <correo> <user_id>` (lista blanca)
- [ ] `manage.py list` para verificar
- [ ] Añadir el usuario a `USERS` en `wallapop_config_v18.html`
- [ ] Añadir su `<option>` al `<select id="who">`
- [ ] La persona envía su primer formulario **desde el correo autorizado**
- [ ] Llega "Configuración aplicada ✓" → alta completada
