"""
config_inbox.py
---------------
Extraccion automatica de configs desde el buzon de wallabot01@gmail.com.

El formulario HTML envia dos tipos de correo:

  APLICAR (crear/editar alertas):
    Asunto: "ALERTA WALLAPOP <NOMBRE>"
    Cuerpo: resumen legible
            ----- config_<nombre>.yaml -----
            <YAML completo>
    -> backup del config anterior y escritura atomica de configs/<user_id>.yaml.

  BORRAR (eliminar alertas):
    Asunto: "BORRAR WALLAPOP <NOMBRE>"
    Cuerpo: ----- ALERTAS A ELIMINAR -----
            <un nombre de alerta por linea, o "TODAS">
    -> quita esas alertas del config del usuario (backup + escritura atomica).
       "TODAS" deja el config con la lista vacia (en pausa), sin borrar el archivo.

  AGREGAR (sumar alertas nuevas sin tocar el resto):
    Asunto: "AÑADIR WALLAPOP <NOMBRE>"
    Cuerpo: ----- config_<nombre>.yaml -----
            alerts:
              - <solo las alertas nuevas>
    -> anyade esas alertas a las que ya tiene el usuario (backup + escritura
       atomica), saltando las que ya existan con el mismo nombre.

En ambos casos valida el remitente contra la lista blanca de bot_settings.yaml,
marca el correo como leido y responde una confirmacion que SIEMPRE incluye la
lista de alertas activas que quedan (copiable para usarla luego en la pestaña
"Eliminar alertas" del formulario).

Uso suelto:
    python config_inbox.py            # una pasada real
    python config_inbox.py --dry-run  # simula: no escribe, no marca, no responde
"""

import os
import re
import sys
import html
import time
import email
import shutil
import imaplib
import logging
from email.header import decode_header, make_header
from email.utils import parseaddr

import yaml

import notifier

log = logging.getLogger("inbox")

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR")          # definido en despliegues cloud
CONFIGS_DIR = os.path.join(DATA_DIR or CORE_DIR, "configs")
SETTINGS_PATH = os.path.join(CORE_DIR, "bot_settings.yaml")
BACKUPS_DIR = (os.path.join(DATA_DIR, "backups", "configs") if DATA_DIR
               else os.path.normpath(
                   os.path.join(CORE_DIR, "..", "06_Backups", "configs")))

SUBJECT_TOKEN = "ALERTA WALLAPOP"
MARKER_RE = re.compile(
    r"^[ \t]*-{2,}\s*(?P<fname>\S+\.ya?ml)\s*-{2,}[ \t]*$", re.M)

# --- borrado de alertas ---
DELETE_TOKEN = "BORRAR WALLAPOP"
DELETE_MARKER_RE = re.compile(
    r"^[ \t]*-{2,}\s*ALERTAS A ELIMINAR\s*-{2,}[ \t]*$", re.M | re.I)
_ALL_TOKENS = {"todas", "todos", "all", "todas las alertas",
               "borrar todas", "*"}

# --- agregar alertas (incremental) ---
ADD_TOKEN = "AÑADIR WALLAPOP"
# La busqueda IMAP de Gmail indexa por palabras completas (como su buscador
# web), no por subcadena del header crudo: "ADIR" nunca casa con "AÑADIR"
# por mucho que sea substring, asi que no sirve como token de busqueda.
# Verificado en vivo: SUBJECT "ADIR" -> 0 resultados aunque haya correos
# "AÑADIR WALLAPOP" sin leer; SUBJECT "WALLAPOP" -> los encuentra siempre,
# porque es una palabra completa presente en los tres asuntos.


# ---------------------------------------------------------------- settings --

def load_settings(path=SETTINGS_PATH):
    """Lee bot_settings.yaml. Devuelve None si no existe o no se puede leer."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = yaml.safe_load(f) or {}
    except Exception as e:
        log.error("bot_settings.yaml ilegible: %s", e)
        return None
    senders = {}
    for k, v in (s.get("allowed_senders") or {}).items():
        if k and v:
            senders[str(k).strip().lower()] = str(v).strip()

    # Overrides por variables de entorno (despliegue cloud / Railway).
    env_pwd = os.getenv("GMAIL_APP_PASSWORD")
    if env_pwd:
        s.setdefault("imap", {})["app_password"] = env_pwd
    env_senders = os.getenv("ALLOWED_SENDERS")   # "correo:uid,correo:uid"
    if env_senders:
        for pair in env_senders.split(","):
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            if k.strip() and v.strip():
                senders[k.strip().lower()] = v.strip()
    env_every = os.getenv("INBOX_CHECK_MINUTES")
    if env_every:
        try:
            s["inbox_check_minutes"] = float(env_every)
        except ValueError:
            log.warning("INBOX_CHECK_MINUTES invalido: %s", env_every)

    s["allowed_senders"] = senders
    return s


# ------------------------------------------------------- cuerpo del correo --

def _decode_part(payload, charset):
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _html_to_text(h):
    """Pasa el HTML de Gmail a texto preservando los saltos de linea."""
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</(div|p|tr|li|h[1-6])>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", "", h)
    return html.unescape(h)


def _unflow(text):
    """Deshace el format=flowed (RFC 3676): una linea acabada en espacio es
    un salto blando que hay que unir con la siguiente."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        while line.endswith(" ") and line.strip() != "--" and i + 1 < len(lines):
            i += 1
            nxt = lines[i]
            if nxt.startswith(" "):          # space-stuffing del RFC
                nxt = nxt[1:]
            line = line + nxt
        out.append(line.rstrip())
        i += 1
    return "\n".join(out)


def _body_candidates(msg):
    """Devuelve los cuerpos posibles del mensaje, HTML primero: la parte HTML
    conserva mejor las lineas largas que Gmail parte en la version texto."""
    htmls, plains = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        if disp.startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = _decode_part(payload, part.get_content_charset())
        ctype = part.get_content_type()
        if ctype == "text/html":
            htmls.append(_html_to_text(text))
        elif ctype == "text/plain":
            if (part.get_param("format") or "").lower() == "flowed":
                text = _unflow(text)
            plains.append(text)
    return htmls + plains


# ----------------------------------------------------- extraccion del YAML --

def _extract_yaml_block(body):
    """Todo lo que hay despues de la linea '----- config_x.yaml -----'."""
    m = MARKER_RE.search(body)
    if not m:
        return None
    return body[m.end():].lstrip("\n")


def _extract_delete_names(body):
    """Nombres de alerta a eliminar, tomados tras '----- ALERTAS A ELIMINAR -----'
    (uno por linea). Devuelve la cadena "ALL" si pide borrarlas todas, una lista
    de nombres, o None si no encuentra el marcador."""
    m = DELETE_MARKER_RE.search(body)
    if not m:
        return None
    names = []
    for raw in body[m.end():].split("\n"):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s == "--" or re.match(r"^-{2,}\s*$", s):   # firma / separador -> fin
            break
        s = re.sub(r"^[-*\u2022]\s+", "", s)           # quita viñeta "- ", "* "
        s = s.strip().strip('"').strip("'").strip()
        if not s:
            continue
        if s.lower() in _ALL_TOKENS:
            return "ALL"
        names.append(s)
    return names


def _schema_problems(d):
    """Validacion minima para no escribir configs que rompan main.py."""
    p = []
    if not isinstance(d, dict):
        return ["estructura"]
    em = d.get("email") or {}
    if not isinstance(em, dict) or not str(em.get("recipient") or "").strip():
        p.append("email.recipient")
    if not (em.get("sender") and em.get("app_password")):
        p.append("email.sender/app_password")
    loc = d.get("location") or {}
    if not isinstance(loc, dict) or loc.get("latitude") is None \
            or loc.get("longitude") is None:
        p.append("location.latitude/longitude")
    alerts = d.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        p.append("alerts")
    else:
        for i, a in enumerate(alerts):
            if not isinstance(a, dict) or not a.get("name") or not a.get("keywords"):
                p.append("alerts[%d].name/keywords" % i)
    return p


def _parse_trimming(text, max_drop=200):
    """Intenta parsear el YAML; si falla, recorta lineas finales (firmas,
    citas o pies que el correo anyade despues del YAML) y reintenta."""
    lines = text.split("\n")
    for _ in range(max_drop + 1):
        chunk = "\n".join(lines).strip()
        if chunk:
            try:
                data = yaml.safe_load(chunk)
            except yaml.YAMLError:
                data = None
            if isinstance(data, dict) and not _schema_problems(data):
                return data, chunk
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        lines.pop()
    return None, None


# ------------------------------------------------------------- aplicacion --

def _apply(user_id, sender, form_name, yaml_text, dry_run=False):
    """Backup del config anterior del usuario y escritura atomica del nuevo."""
    os.makedirs(CONFIGS_DIR, exist_ok=True)
    target = os.path.join(CONFIGS_DIR, user_id + ".yaml")
    if os.path.exists(target):
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(BACKUPS_DIR, "%s_%s.yaml" % (user_id, stamp))
        if not dry_run:
            shutil.copy2(target, backup)
        log.info("Backup de la config anterior de '%s' -> %s", user_id, backup)
    header = (
        "# Config de '%s' aplicada automaticamente desde el buzon.\n"
        "# Remitente: %s | Nombre en el formulario: %s\n"
        "# Aplicada: %s\n\n"
        % (user_id, sender, form_name or "-",
           time.strftime("%Y-%m-%d %H:%M:%S"))
    )
    if dry_run:
        log.info("[dry-run] Se escribiria %s (%d caracteres de YAML)",
                 target, len(yaml_text))
        return target
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + yaml_text.rstrip() + "\n")
    os.replace(tmp, target)
    return target


def _active_alerts_html(alerts):
    """Bloque HTML con las alertas activas + lista copiable (un nombre por
    linea) para pegar en la pestaña 'Eliminar alertas' del formulario."""
    names = [str(a.get("name", "?")) for a in (alerts or []) if a.get("name")]
    if not names:
        return "<p style='color:#666'>No tienes alertas activas ahora mismo.</p>"
    items = "".join("<li>%s</li>" % html.escape(n) for n in names)
    pre = html.escape("\n".join(names))
    return (
        "<p>Tus alertas activas (%d):</p><ul>%s</ul>"
        "<p style='color:#666;font-size:13px'>Para borrar alguna, copia esta "
        "lista y pégala en la pestaña <b>Eliminar alertas</b> del formulario:</p>"
        "<pre style='background:#f4f4f4;border:1px solid #ddd;border-radius:6px;"
        "padding:10px;white-space:pre-wrap;font-size:13px'>%s</pre>"
        % (len(names), items, pre)
    )


def _apply_delete(user_id, names, dry_run=False):
    """Elimina alertas del config de un usuario. 'names' es "ALL" o lista de
    nombres. Devuelve (removed, remaining, not_found). Si no hay config,
    removed/remaining son None."""
    target = os.path.join(CONFIGS_DIR, user_id + ".yaml")
    if not os.path.exists(target):
        return None, None, []
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        log.error("No se pudo leer el config de '%s' para borrar: %s", user_id, e)
        return None, None, []

    current = data.get("alerts") or []
    if names == "ALL":
        removed = [str(a.get("name", "?")) for a in current]
        remaining, not_found = [], []
    else:
        targets = {n.strip().lower() for n in names}
        remaining = [a for a in current
                     if str(a.get("name", "")).strip().lower() not in targets]
        removed = [str(a.get("name", "?")) for a in current
                   if str(a.get("name", "")).strip().lower() in targets]
        have = {str(a.get("name", "")).strip().lower() for a in current}
        not_found = [n for n in names if n.strip().lower() not in have]

    if not removed:                       # nada que borrar: no tocamos el archivo
        return [], [str(a.get("name", "?")) for a in current], not_found

    data["alerts"] = remaining

    if dry_run:
        log.info("[dry-run] Se eliminarian de '%s': %s", user_id, removed)
        return removed, [str(a.get("name", "?")) for a in remaining], not_found

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUPS_DIR, "%s_%s.yaml" % (user_id, stamp))
    shutil.copy2(target, backup)
    log.info("Backup antes de borrar alertas de '%s' -> %s", user_id, backup)

    header = (
        "# Config de '%s' actualizada automaticamente (borrado de alertas).\n"
        "# %s | Eliminadas: %s\n\n"
        % (user_id, time.strftime("%Y-%m-%d %H:%M:%S"), ", ".join(removed))
    )
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + body)
    os.replace(tmp, target)
    return removed, [str(a.get("name", "?")) for a in remaining], not_found


def _reply(settings, to_addr, subject, body_html, dry_run=False):
    if not settings.get("reply_confirmation", True):
        return
    if dry_run:
        log.info("[dry-run] Respuesta a %s: %s", to_addr, subject)
        return
    im = settings.get("imap") or {}
    cfg = {"email": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "sender": im.get("user"),
        "app_password": im.get("app_password"),
        "recipient": to_addr,
    }}
    notifier.send_email(cfg, subject, body_html)


def _mark_seen(M, num, dry_run=False):
    if dry_run:
        return
    try:
        M.store(num, "+FLAGS", "\\Seen")
    except Exception as e:
        log.warning("No se pudo marcar como leido el mensaje %s: %s", num, e)


# ------------------------------------------------------------------ bucle --

def _process_delete(M, num, settings, applied, dry_run,
                    user_id, sender, subject, bodies):
    """Maneja un correo 'BORRAR WALLAPOP': quita alertas del config del usuario."""
    names = None
    for body in bodies:
        names = _extract_delete_names(body)
        if names:                       # "ALL" o lista no vacia
            break
    _mark_seen(M, num, dry_run)

    if not names:
        log.error("Borrado de %s sin lista de alertas (asunto: '%s').",
                  sender, subject)
        _reply(settings, sender, "Re: " + subject,
               "<div style='font-family:Arial'>No pude leer qué alertas borrar. "
               "Usa la pestaña <b>Eliminar alertas</b> del formulario y vuelve a "
               "enviarlo sin editar el cuerpo.</div>", dry_run)
        return

    removed, remaining, not_found = _apply_delete(user_id, names, dry_run)
    if removed is None:
        _reply(settings, sender, "Re: " + subject,
               "<div style='font-family:Arial'>No encuentro tu configuración, "
               "así que no hay alertas que borrar.</div>", dry_run)
        return

    if removed:
        head = ("Eliminada(s) %d alerta(s): %s."
                % (len(removed), html.escape(", ".join(removed))))
    else:
        head = "No borré ninguna alerta (ningún nombre coincidía con las tuyas)."
    nf = ("<p style='color:#b00;font-size:13px'>No encontré (no borré): %s</p>"
          % html.escape(", ".join(not_found))) if not_found else ""
    body_html = ("<div style='font-family:Arial'>%s%s<br><br>%s</div>"
                 % (head, nf,
                    _active_alerts_html([{"name": n} for n in remaining])))
    _reply(settings, sender, "Re: " + subject, body_html, dry_run)

    if user_id in applied:
        applied.remove(user_id)
    applied.append(user_id)
    log.info("Borrado de alertas de '%s' desde %s: %s",
             user_id, sender, removed or "ninguna")


def _extract_added_alerts(body):
    """De un correo AÑADIR, saca la lista de alertas del bloque YAML (que solo
    contiene 'alerts:'). Recorta lineas finales (firmas) hasta que parsea.
    Devuelve la lista o None."""
    block = _extract_yaml_block(body)
    if not block:
        return None
    lines = block.split("\n")
    for _ in range(300):
        chunk = "\n".join(lines).strip()
        if chunk:
            try:
                data = yaml.safe_load(chunk)
            except yaml.YAMLError:
                data = None
            if (isinstance(data, dict) and isinstance(data.get("alerts"), list)
                    and data["alerts"]):
                return data["alerts"]
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        lines.pop()
    return None


def _apply_add(user_id, new_alerts, dry_run=False):
    """Agrega alertas al config del usuario SIN tocar el resto. Devuelve
    (added, skipped, all_names). Si no existe el config -> (None, [], None)."""
    target = os.path.join(CONFIGS_DIR, user_id + ".yaml")
    if not os.path.exists(target):
        return None, [], None
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        log.error("No se pudo leer el config de '%s': %s", user_id, e)
        return None, [], None

    current = data.get("alerts") or []
    have = {str(a.get("name", "")).strip().lower() for a in current
            if isinstance(a, dict)}
    added, skipped = [], []
    for a in new_alerts:
        if not isinstance(a, dict):
            continue
        nm = str(a.get("name", "")).strip()
        if not nm or not str(a.get("keywords", "")).strip():
            continue
        if nm.lower() in have:
            skipped.append(nm)
            continue
        current.append(a)
        have.add(nm.lower())
        added.append(nm)

    all_names = [str(a.get("name", "?")) for a in current if isinstance(a, dict)]
    if not added:
        return [], skipped, all_names

    data["alerts"] = current
    if dry_run:
        log.info("[dry-run] Se agregarian a '%s': %s", user_id, added)
        return added, skipped, all_names

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUPS_DIR, "%s_%s.yaml" % (user_id, stamp))
    shutil.copy2(target, backup)
    log.info("Backup antes de agregar alertas de '%s' -> %s", user_id, backup)

    header = (
        "# Config de '%s' actualizada automaticamente (alertas agregadas).\n"
        "# %s | Nuevas: %s\n\n"
        % (user_id, time.strftime("%Y-%m-%d %H:%M:%S"), ", ".join(added))
    )
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + text)
    os.replace(tmp, target)
    return added, skipped, all_names


def _process_add(M, num, settings, applied, dry_run,
                 user_id, sender, subject, bodies):
    """Maneja 'AÑADIR WALLAPOP': suma alertas al config del usuario."""
    new_alerts = None
    for body in bodies:
        new_alerts = _extract_added_alerts(body)
        if new_alerts:
            break
    _mark_seen(M, num, dry_run)

    if not new_alerts:
        log.error("AGREGAR de %s sin alertas validas (asunto: '%s').",
                  sender, subject)
        _reply(settings, sender, "Re: " + subject,
               "<div style='font-family:Arial'>No pude leer ninguna alerta que "
               "añadir. Vuelve a generarlo desde la pestaña <b>Añadir alertas</b> "
               "del formulario y envíalo sin editar el cuerpo.</div>", dry_run)
        return

    added, skipped, all_names = _apply_add(user_id, new_alerts, dry_run)
    if added is None:
        _reply(settings, sender, "Re: " + subject,
               "<div style='font-family:Arial'>No encuentro tu configuración. "
               "Crea primero una con la pestaña <b>Crear / editar</b> y luego ya "
               "podrás añadir alertas.</div>", dry_run)
        return

    if added:
        head = ("Añadida(s) %d alerta(s): %s."
                % (len(added), html.escape(", ".join(added))))
    else:
        head = "No añadí ninguna alerta nueva."
    sk = ("<p style='color:#b00;font-size:13px'>Ya las tenías (no las duplico): "
          "%s</p>" % html.escape(", ".join(skipped))) if skipped else ""
    body_html = ("<div style='font-family:Arial'>%s%s<br><br>%s</div>"
                 % (head, sk,
                    _active_alerts_html([{"name": n} for n in all_names])))
    _reply(settings, sender, "Re: " + subject, body_html, dry_run)

    if user_id in applied:
        applied.remove(user_id)
    applied.append(user_id)
    log.info("Alertas agregadas a '%s' desde %s: %s",
             user_id, sender, added or "ninguna")


def _process_message(M, num, settings, applied, dry_run):
    typ, data = M.fetch(num, "(BODY.PEEK[])")
    if typ != "OK" or not data or data[0] is None:
        log.warning("No se pudo descargar el mensaje %s", num)
        return
    msg = email.message_from_bytes(data[0][1])
    subject = str(make_header(decode_header(msg.get("Subject") or "")))
    sender = parseaddr(msg.get("From") or "")[1].strip().lower()
    subj_up = subject.upper()
    is_delete = DELETE_TOKEN in subj_up
    is_add = (ADD_TOKEN in subj_up) or ("ANADIR WALLAPOP" in subj_up)
    token = DELETE_TOKEN if is_delete else (ADD_TOKEN if is_add else SUBJECT_TOKEN)
    form_name = subj_up.replace(token, "").strip().title() or None

    user_id = settings["allowed_senders"].get(sender)
    if not user_id:
        log.warning("Remitente NO autorizado: %s (asunto: '%s'). Ignorado.",
                    sender, subject)
        _mark_seen(M, num, dry_run)
        return

    bodies = [b.replace("\r\n", "\n").replace("\r", "\n")
              for b in _body_candidates(msg)]

    if is_delete:
        _process_delete(M, num, settings, applied, dry_run,
                        user_id, sender, subject, bodies)
        return

    if is_add:
        _process_add(M, num, settings, applied, dry_run,
                     user_id, sender, subject, bodies)
        return

    # ---- APLICAR (crear / editar alertas) ----
    parsed_data, parsed_text = None, None
    for body in bodies:
        block = _extract_yaml_block(body)
        if not block:
            continue
        parsed_data, parsed_text = _parse_trimming(block)
        if parsed_data:
            break

    if not parsed_data:
        log.error("Correo de %s sin YAML valido (asunto: '%s').", sender, subject)
        _mark_seen(M, num, dry_run)
        _reply(settings, sender, "Re: " + subject,
               "<div style='font-family:Arial'>No se pudo aplicar tu "
               "configuracion: el contenido del correo no es un YAML valido. "
               "Vuelve a generarlo desde el formulario y envialo sin editar "
               "el cuerpo.</div>", dry_run)
        return

    target = _apply(user_id, sender, form_name, parsed_text, dry_run)
    _mark_seen(M, num, dry_run)

    alerts = parsed_data.get("alerts") or []
    _reply(settings, sender, "Re: " + subject,
           "<div style='font-family:Arial'>Configuración aplicada &#10003;<br>"
           "Avisos a: %s<br><br>%s</div>"
           % (html.escape(str(parsed_data["email"]["recipient"])),
              _active_alerts_html(alerts)),
           dry_run)

    if user_id in applied:
        applied.remove(user_id)
    applied.append(user_id)
    log.info("Config de '%s' aplicada desde %s -> %s", user_id, sender, target)


def check_and_apply(settings=None, dry_run=False):
    """Una pasada por el buzon. Devuelve la lista de user_id aplicados."""
    settings = settings or load_settings()
    if not settings:
        log.warning("Sin bot_settings.yaml: extraccion de buzon desactivada.")
        return []
    im = settings.get("imap") or {}
    user, pwd = im.get("user"), im.get("app_password")
    if not (user and pwd):
        log.error("Faltan imap.user / imap.app_password en bot_settings.yaml")
        return []
    applied = []
    try:
        M = imaplib.IMAP4_SSL(im.get("host", "imap.gmail.com"),
                              int(im.get("port", 993)))
    except Exception as e:
        log.warning("Sin conexion IMAP: %s", e)
        return []
    try:
        M.login(user, pwd)
        M.select("INBOX")
        # Una sola busqueda por la palabra comun a los 3 asuntos (ALERTA/
        # BORRAR/AÑADIR WALLAPOP). Gmail indexa por palabra completa, no por
        # subcadena, asi que un token parcial de "AÑADIR" nunca funciona.
        # Se excluyen los correos del propio buzon del bot (sus avisos de
        # novedades "[Wallapop] ..." tambien contienen esa palabra).
        typ, data = M.search(
            None, '(UNSEEN SUBJECT "WALLAPOP" NOT FROM "%s")' % user)
        nums = data[0].split() if typ == "OK" and data and data[0] else []
        # Sin duplicados y en orden ascendente (el correo mas reciente gana).
        nums = sorted(set(nums), key=lambda b: int(b))
        if nums:
            log.info("Buzon: %d correo(s) de config/borrado sin leer.", len(nums))
        for num in nums:
            try:
                _process_message(M, num, settings, applied, dry_run)
            except Exception:
                log.exception("Error procesando el mensaje %s", num)
                _mark_seen(M, num, dry_run)
    except imaplib.IMAP4.error as e:
        log.error("Error IMAP: %s", e)
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return applied


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    dry = "--dry-run" in sys.argv
    if dry:
        log.info("== DRY RUN: no se escribe, no se marca, no se responde ==")
    result = check_and_apply(dry_run=dry)
    print("Configs aplicadas:", ", ".join(result) if result else "ninguna")
