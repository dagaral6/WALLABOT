"""
test_railway_paths.py
---------------------
Simula el entorno de Railway en local: define DATA_DIR (el "volumen"),
GMAIL_APP_PASSWORD, ALLOWED_SENDERS y OLLAMA_HOST ANTES de importar los
modulos, y comprueba que todo se resuelve dentro del volumen y que los
overrides de entorno aplican. No usa red.

    python test_railway_paths.py
"""

import os
import sys
import shutil
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)

SIM = os.path.join(tempfile.gettempdir(), "wallabot_railway_sim")
shutil.rmtree(SIM, ignore_errors=True)
os.makedirs(SIM)

os.environ["DATA_DIR"] = SIM
os.environ["GMAIL_APP_PASSWORD"] = "pwd-de-prueba"
os.environ["ALLOWED_SENDERS"] = "amigo@test.com:amigo"
os.environ["OLLAMA_HOST"] = "http://ollama-remoto:11434"

import database          # noqa: E402
import classifier        # noqa: E402
import config_inbox      # noqa: E402
import main              # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("[OK ] " if cond else "[FAIL] ") + name +
          ((" -> " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


check("database.DB_PATH dentro del volumen",
      database.DB_PATH == os.path.join(SIM, "alerts.db"), database.DB_PATH)
check("main.CONFIGS_DIR dentro del volumen",
      main.CONFIGS_DIR == os.path.join(SIM, "configs"), main.CONFIGS_DIR)
check("config_inbox.CONFIGS_DIR dentro del volumen",
      config_inbox.CONFIGS_DIR == os.path.join(SIM, "configs"))
check("config_inbox.BACKUPS_DIR dentro del volumen",
      config_inbox.BACKUPS_DIR == os.path.join(SIM, "backups", "configs"))
check("classifier usa OLLAMA_HOST",
      classifier.OLLAMA_CHAT == "http://ollama-remoto:11434/api/chat",
      classifier.OLLAMA_CHAT)

main._bootstrap_data_dir()
seeded = sorted(os.listdir(main.CONFIGS_DIR))
check("bootstrap siembra los configs del repo", "dario.yaml" in seeded, seeded)

database.init_db()
check("alerts.db creada en el volumen",
      os.path.exists(os.path.join(SIM, "alerts.db")))

s = config_inbox.load_settings()
check("env GMAIL_APP_PASSWORD aplica",
      s["imap"]["app_password"] == "pwd-de-prueba")
check("env ALLOWED_SENDERS se suma a la lista blanca",
      s["allowed_senders"].get("amigo@test.com") == "amigo")
check("lista blanca del YAML se conserva",
      s["allowed_senders"].get("wallabot01@gmail.com") == "dario")

cfgs = main.load_all_configs()
check("load_all_configs lee del volumen", "dario" in cfgs, list(cfgs))

print()
print("RESULTADO:", "TODO OK" if not fails else "FALLAN: " + ", ".join(fails))
sys.exit(1 if fails else 0)
