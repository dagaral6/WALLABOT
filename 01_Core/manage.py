"""
manage.py
---------
Administracion del bot SIN editar los YAML a mano.

  python manage.py list
      Lista los usuarios de la lista blanca, si tienen config, sus alertas y
      cuantas filas tienen en la base de datos. Avisa de desajustes (config
      sin lista blanca, o lista blanca sin config).

  python manage.py add-user <correo> <user_id>
      Da de alta un remitente en la lista blanca de bot_settings.yaml
      (preservando comentarios; con backup). A partir de ahi ese correo ya
      puede enviar su configuracion desde el formulario y se aplica sola.

  python manage.py remove-user <correo|user_id>
      Quita de la lista blanca las entradas que coincidan (con backup).
      NO borra el config ni la base de datos del usuario.

Para BORRAR UNA ALERTA concreta: edita configs/<user_id>.yaml y quita ese
bloque (o regenera la config desde el formulario sin esa alerta). Las filas
viejas de la BD quedan huerfanas pero son inofensivas: ya no se consultan.
"""

import os
import re
import sys
import time
import shutil
import sqlite3

import yaml

import database

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(CORE_DIR, "bot_settings.yaml")
CONFIGS_DIR = os.path.join(CORE_DIR, "configs")
BACKUPS_DIR = os.path.normpath(
    os.path.join(CORE_DIR, "..", "06_Backups", "configs"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ------------------------------------------------------------- utilidades --

def _backup(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUPS_DIR, "%s_%s" % (os.path.basename(path), stamp))
    shutil.copy2(path, dst)
    return dst


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def _load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _find_block(lines, key="allowed_senders:"):
    """(start, end) de las lineas indentadas bajo 'key:'. start es la linea
    siguiente a 'key:'; end es exclusivo (primera linea a nivel 0)."""
    head = None
    for i, ln in enumerate(lines):
        if ln.strip() == key:
            head = i
            break
    if head is None:
        return None, None
    j = head + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "" or ln[:1] in (" ", "\t"):
            j += 1
            continue
        break
    return head + 1, j


def _parse_mapping(line):
    """De '  correo: uid   # comentario' saca (correo_lower, uid). None si es
    comentario, linea en blanco o no es un mapeo."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    s = s.split("#", 1)[0].strip()
    if ":" not in s:
        return None
    k, v = s.split(":", 1)
    k, v = k.strip(), v.strip()
    if not k or not v:
        return None
    return k.lower(), v

# --------------------------------------------------------------- add-user --

def cmd_add_user(email, user_id):
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        print("Correo no valido:", email)
        return 1
    if not _UID_RE.match(user_id):
        print("user_id no valido (usa letras, numeros, _ o -):", user_id)
        return 1
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = raw.split("\n")
    s, e = _find_block(lines)
    if s is None:
        print("No encuentro 'allowed_senders:' en bot_settings.yaml.")
        return 1
    for ln in lines[s:e]:
        m = _parse_mapping(ln)
        if m and m[0] == email:
            print("Ese correo ya esta en la lista blanca (-> %s). Sin cambios."
                  % m[1])
            return 0
    new_line = "  %s: %s        # alta: %s" % (
        email, user_id, time.strftime("%Y-%m-%d"))
    lines.insert(s, new_line)
    bk = _backup(SETTINGS_PATH)
    _atomic_write(SETTINGS_PATH, "\n".join(lines))
    print("Alta OK:  %s  ->  %s" % (email, user_id))
    if bk:
        print("Backup de bot_settings.yaml:", bk)
    print("Siguiente paso: que '%s' genere su config en el formulario y la "
          "envie a wallabot01@gmail.com DESDE ese correo." % user_id)
    return 0


# ------------------------------------------------------------ remove-user --

def cmd_remove_user(target):
    target = target.strip().lower()
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = raw.split("\n")
    s, e = _find_block(lines)
    if s is None:
        print("No encuentro 'allowed_senders:' en bot_settings.yaml.")
        return 1
    keep, removed = [], []
    for idx, ln in enumerate(lines):
        if s <= idx < e:
            m = _parse_mapping(ln)
            if m and (m[0] == target or m[1].lower() == target):
                removed.append(ln.strip())
                continue
        keep.append(ln)
    if not removed:
        print("No hay entradas activas que coincidan con:", target)
        return 0
    bk = _backup(SETTINGS_PATH)
    _atomic_write(SETTINGS_PATH, "\n".join(keep))
    print("Quitada(s) %d entrada(s):" % len(removed))
    for r in removed:
        print("  -", r)
    if bk:
        print("Backup de bot_settings.yaml:", bk)
    print("Nota: no se ha tocado configs/ ni la base de datos.")
    return 0

# ----------------------------------------------------------------- list ----

def _db_counts():
    """{user_id: (aceptadas, vistas)} a partir de los prefijos 'user/...'."""
    out = {}
    if not os.path.exists(database.DB_PATH):
        return out
    try:
        con = sqlite3.connect(database.DB_PATH)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT alert_name, decision FROM seen_items").fetchall()
        con.close()
    except sqlite3.Error as ex:
        print("(aviso) no pude leer la BD:", ex)
        return out
    for r in rows:
        an = r["alert_name"] or ""
        uid = an.split("/", 1)[0] if "/" in an else "(sin prefijo)"
        kept, total = out.get(uid, (0, 0))
        total += 1
        if r["decision"] == "keep":
            kept += 1
        out[uid] = (kept, total)
    return out


def _configs():
    out = {}
    if not os.path.isdir(CONFIGS_DIR):
        return out
    for fn in sorted(os.listdir(CONFIGS_DIR)):
        if not fn.lower().endswith((".yaml", ".yml")):
            continue
        uid = os.path.splitext(fn)[0]
        try:
            with open(os.path.join(CONFIGS_DIR, fn), "r", encoding="utf-8") as f:
                out[uid] = yaml.safe_load(f) or {}
        except Exception as ex:
            out[uid] = {"__error__": str(ex)}
    return out

def cmd_list():
    settings = _load_settings()
    senders = settings.get("allowed_senders") or {}
    uid_emails = {}
    for email, uid in senders.items():
        uid_emails.setdefault(str(uid), []).append(str(email))
    configs = _configs()
    counts = _db_counts()

    all_uids = sorted(set(uid_emails) | set(configs))
    print("=" * 64)
    print(" USUARIOS DE WALLABOT")
    print("=" * 64)
    if not all_uids:
        print("(no hay usuarios todavia)")
    for uid in all_uids:
        emails = uid_emails.get(uid, [])
        cfg = configs.get(uid)
        kept, total = counts.get(uid, (0, 0))
        print("\n- %s" % uid)
        print("    correos lista blanca: %s"
              % (", ".join(emails) or "NINGUNO (no podra enviar config)"))
        if cfg is None:
            print("    config: NO existe configs/%s.yaml" % uid)
        elif "__error__" in cfg:
            print("    config: ILEGIBLE (%s)" % cfg["__error__"])
        else:
            alerts = cfg.get("alerts") or []
            names = [str(a.get("name", "?")) for a in alerts]
            rcpt = ((cfg.get("email") or {}).get("recipient")) or "?"
            print("    config: OK  | avisos a: %s" % rcpt)
            print("    alertas (%d): %s"
                  % (len(alerts), ", ".join(names) or "ninguna"))
        print("    BD: %d aceptadas / %d vistas" % (kept, total))

    wl_no_cfg = [u for u in uid_emails if u not in configs]
    cfg_no_wl = [u for u in configs if u not in uid_emails]
    if wl_no_cfg or cfg_no_wl:
        print("\n" + "-" * 64)
        if wl_no_cfg:
            print(" En lista blanca pero SIN config (esperando su correo): %s"
                  % ", ".join(wl_no_cfg))
        if cfg_no_wl:
            print(" Con config pero SIN lista blanca (sus correos nuevos se "
                  "ignorarian): %s" % ", ".join(cfg_no_wl))
    return 0


# ------------------------------------------------------------------ main ---

def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0].lower()
    if cmd == "list":
        return cmd_list()
    if cmd == "add-user":
        if len(argv) != 3:
            print("Uso: python manage.py add-user <correo> <user_id>")
            return 1
        return cmd_add_user(argv[1], argv[2])
    if cmd == "remove-user":
        if len(argv) != 2:
            print("Uso: python manage.py remove-user <correo|user_id>")
            return 1
        return cmd_remove_user(argv[1])
    print("Comando desconocido:", cmd)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
