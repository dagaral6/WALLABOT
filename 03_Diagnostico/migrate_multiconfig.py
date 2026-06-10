"""
migrate_multiconfig.py  (one-shot, idempotente)
-----------------------------------------------
Migra el proyecto al modo multi-config:
  1) Copia 01_Core/config.yaml -> 01_Core/configs/dario.yaml
  2) Retira el config.yaml original a 06_Backups/config_pre_multiconfig.yaml
  3) Renombra en alerts.db las filas existentes a 'dario/<alerta>' para
     conservar el historial de vistos (evita re-notificarlo todo).

Ejecutar UNA vez, con el bot parado:
    python migrate_multiconfig.py
"""

import os
import shutil
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
BACKUPS = os.path.normpath(os.path.join(BASE, "..", "06_Backups"))
USER_ID = "dario"


def main():
    old_cfg = os.path.join(CORE, "config.yaml")
    cfg_dir = os.path.join(CORE, "configs")
    target = os.path.join(cfg_dir, USER_ID + ".yaml")
    os.makedirs(cfg_dir, exist_ok=True)

    if os.path.exists(old_cfg) and not os.path.exists(target):
        shutil.copy2(old_cfg, target)
        print("config.yaml copiado a", target)
    elif os.path.exists(target):
        print("Ya existe", target, "- no se copia nada.")

    if os.path.exists(old_cfg):
        os.makedirs(BACKUPS, exist_ok=True)
        dest = os.path.join(BACKUPS, "config_pre_multiconfig.yaml")
        shutil.move(old_cfg, dest)
        print("config.yaml retirado a", dest)

    db = os.path.join(CORE, "alerts.db")
    if os.path.exists(db):
        con = sqlite3.connect(db)
        cur = con.execute(
            "UPDATE seen_items SET alert_name = ? || '/' || alert_name "
            "WHERE instr(alert_name, '/') = 0", (USER_ID,))
        con.commit()
        print("Filas de la BD renombradas a '%s/...':" % USER_ID, cur.rowcount)
        con.close()
    else:
        print("Sin alerts.db: nada que migrar en BD.")

    print("Migracion completada.")


if __name__ == "__main__":
    main()
