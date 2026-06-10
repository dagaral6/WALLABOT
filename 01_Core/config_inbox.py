"""
config_inbox.py
---------------
Extraccion automatica de configs desde el buzon de wallabot01@gmail.com.

El formulario HTML envia un correo con:
    Asunto: "ALERTA WALLAPOP <NOMBRE>"
    Cuerpo: resumen legible
            ----- config_<nombre>.yaml -----
            <YAML completo>

Este modulo, por cada correo NO LEIDO con ese asunto:
  1) Valida el remitente contra la lista blanca de bot_settings.yaml.
  2) Extrae el YAML tras la linea marcador (reconstruye lineas partidas
     por Gmail y recorta firmas/citas que vengan despues).
  3) Valida el schema minimo (email, location, alerts).
  4) Hace backup del config anterior del usuario en 06_Backups/configs/
     y escribe configs/<user_id>.yaml de forma atomica.
  5) Marca el correo como leido y responde con una confirmacion.

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

def _process_message(M, num, settings, applied, dry_run):
    typ, data = M.fetch(num, "(BODY.PEEK[])")
    if typ != "OK" or not data or data[0] is None:
        log.warning("No se pudo descargar el mensaje %s", num)
        return
    msg = email.message_from_bytes(data[0][1])
    subject = str(make_header(decode_header(msg.get("Subject") or "")))
    sender = parseaddr(msg.get("From") or "")[1].strip().lower()
    form_name = subject.upper().replace(SUBJECT_TOKEN, "").strip().title() or None

    user_id = settings["allowed_senders"].get(sender)
    if not user_id:
        log.warning("Remitente NO autorizado: %s (asunto: '%s'). Ignorado.",
                    sender, subject)
        _mark_seen(M, num, dry_run)
        return

    parsed_data, parsed_text = None, None
    for body in _body_candidates(msg):
        body = body.replace("\r\n", "\n").replace("\r", "\n")
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
    names = ", ".join(str(a.get("name", "?")) for a in alerts)
    _reply(settings, sender, "Re: " + subject,
           "<div style='font-family:Arial'>Configuracion aplicada &#10003;"
           "<br>%d juego(s) vigilado(s): %s"
           "<br>Avisos a: %s</div>"
           % (len(alerts), names, parsed_data["email"]["recipient"]),
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
        typ, data = M.search(None, '(UNSEEN SUBJECT "%s")' % SUBJECT_TOKEN)
        nums = data[0].split() if typ == "OK" and data and data[0] else []
        if nums:
            log.info("Buzon: %d correo(s) de config sin leer.", len(nums))
        for num in nums:          # orden ascendente: el mas reciente gana
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
