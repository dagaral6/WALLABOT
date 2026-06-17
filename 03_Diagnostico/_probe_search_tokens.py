import sys
import os
import imaplib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "01_Core"))
import config_inbox as ci

settings = ci.load_settings()
im = settings["imap"]
M = imaplib.IMAP4_SSL(im.get("host", "imap.gmail.com"), int(im.get("port", 993)))
M.login(im["user"], im["app_password"])
M.select("INBOX")

for tok in ["ADIR", "ADIR WALLAPOP", "WALLAPOP", "AÑADIR", "ANADIR", "AÑADIR WALLAPOP"]:
    typ, data = M.search(None, '(UNSEEN SUBJECT "%s")' % tok)
    nums = data[0].split() if typ == "OK" and data and data[0] else []
    print(repr(tok), "->", typ, len(nums), nums)

M.logout()
