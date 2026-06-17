"""Diagnostico puntual: busca en el buzon (todos los correos, no solo
UNSEEN) los que tengan 'WALLAPOP' en el asunto, e imprime asunto + flags
+ remitente. No imprime credenciales ni cuerpos."""
import sys
import os
import imaplib
import email
from email.header import decode_header, make_header

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "01_Core"))
import config_inbox as ci

settings = ci.load_settings()
if not settings:
    print("No se pudo cargar bot_settings.yaml")
    sys.exit(1)

im = settings.get("imap") or {}
M = imaplib.IMAP4_SSL(im.get("host", "imap.gmail.com"), int(im.get("port", 993)))
M.login(im["user"], im["app_password"])
M.select("INBOX")

typ, data = M.search(None, '(SUBJECT "WALLAPOP")')
nums = data[0].split() if typ == "OK" and data and data[0] else []
print("Mensajes con 'WALLAPOP' en asunto (cualquier estado):", len(nums))

for num in nums[-10:]:
    typ, fdata = M.fetch(num, "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
    raw = fdata[0][1]
    msg = email.message_from_bytes(raw)
    subject = str(make_header(decode_header(msg.get("Subject") or "")))
    sender = msg.get("From") or ""
    flags = fdata[0][0] if isinstance(fdata[0], tuple) else b""
    seen = b"\\Seen" in (fdata[0][0] if isinstance(fdata[0], (list, tuple)) else b"")
    print("---")
    print("num:", num.decode())
    print("from:", sender)
    print("subject:", repr(subject))
    print("flags raw:", fdata[0])

M.logout()
