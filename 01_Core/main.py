"""
main.py
-------
Carga la config, comprueba cada alerta y envía emails ante novedades o bajas.

Flujo por ciclo (eficiente con el LLM):
  1) Pide a Wallapop los resultados (sin filtro de precio, para no perder lotes).
  2) Clasifica SOLO los anuncios nuevos (los ya vistos no se reclasifican).
  3) Aplica categoría deseada + precio (con bypass para lotes).
  4) Detecta bajas: items que notificamos y ya no aparecen.

Uso:
    python main.py            # bucle multi-config (cada usuario a su ritmo)
    python main.py --once     # una pasada de todos los configs
    python main.py --seed     # registra lo actual SIN avisar (todos)

Multi-config: hay un YAML por usuario en 01_Core/configs/<user_id>.yaml.
Llegan solos por correo (config_inbox.py + lista blanca en bot_settings.yaml)
y en la BD cada usuario va con el prefijo '<user_id>/' en alert_name.
"""

import sys
import os
import time
import math
import shutil
import logging

import yaml

import scraper
import database
import notifier
import classifier
import config_inbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def load_config(path=None):
    """Carga un config concreto. Sin 'path': usa el config.yaml legacy si
    existe; si no, el primer YAML de configs/ (compat para los scripts de
    03_Diagnostico, que operan sobre un solo usuario)."""
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "config.yaml")
        if not os.path.exists(path) and os.path.isdir(CONFIGS_DIR):
            yamls = sorted(f for f in os.listdir(CONFIGS_DIR)
                           if f.lower().endswith((".yaml", ".yml")))
            if yamls:
                path = os.path.join(CONFIGS_DIR, yamls[0])
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# En despliegues cloud (Railway), DATA_DIR apunta al volumen persistente:
# los configs y la BD viven ahi para sobrevivir a los redeploys.
CONFIGS_DIR = os.path.join(
    os.getenv("DATA_DIR") or os.path.dirname(os.path.abspath(__file__)),
    "configs")


def load_all_configs():
    """Lee todos los configs de usuario de 01_Core/configs/*.yaml.
    Devuelve {user_id: config}; user_id = nombre del archivo sin extension."""
    out = {}
    if not os.path.isdir(CONFIGS_DIR):
        return out
    for fn in sorted(os.listdir(CONFIGS_DIR)):
        if not fn.lower().endswith((".yaml", ".yml")):
            continue
        user_id = os.path.splitext(fn)[0]
        try:
            cfg = load_config(os.path.join(CONFIGS_DIR, fn))
        except Exception as e:
            log.error("Config invalido '%s': %s (se ignora)", fn, e)
            continue
        if cfg and cfg.get("alerts"):
            out[user_id] = cfg
        else:
            log.warning("Config '%s' sin alertas: se ignora.", fn)
    return out


def _hard_excluded(item, alert):
    """Exclusión manual OPCIONAL por variantes (p.ej. 'junior'). Vacía por defecto."""
    title = (item.get("title") or "").lower()
    return any(w.lower() in title for w in (alert.get("exclude") or []))


def _price_ok(item, alert):
    price = item.get("price")
    mn, mx = alert.get("min_price"), alert.get("max_price")
    if mx is not None and price is not None and price > mx:
        return False
    if mn is not None and price is not None and price < mn:
        return False
    return True


def _haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos (lat/lon en grados)."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _delivery_ok(item, config):
    """
    Filtro de entrega según config (radio + tipo). Se aplica ANTES de
    clasificar, para no gastar LLM en anuncios que no cumplen la entrega.

    Lógica (confirmada con el usuario):
      - delivery.in_person -> el anuncio vale si está a <= radius_km del centro
                              (entrega en mano dentro del radio).
      - delivery.shipping  -> el anuncio vale si admite envío (distancia
                              IGNORADA: un envío llega estés donde estés).
      - ambas / ninguna    -> sin filtro: vale cualquier anuncio (unión).

    Ante la duda, dejar pasar: si faltan datos (sin coordenadas, radio no
    definido, etc.) no descartamos el anuncio.
    """
    delivery = config.get("delivery") or {}
    in_person = bool(delivery.get("in_person"))
    shipping = bool(delivery.get("shipping"))

    # Nada marcado = ambas activas (sin filtro).
    if not in_person and not shipping:
        return True
    if in_person and shipping:
        return True

    loc = config.get("location") or {}
    radius_km = loc.get("radius_km")

    # Vía ENVÍO: si el anuncio admite envío, vale (sin mirar distancia).
    if shipping and item.get("is_shippable"):
        return True

    # Vía EN PERSONA: dentro del radio.
    if in_person:
        # Sin radio definido -> no filtramos por distancia (dejar pasar).
        if radius_km is None:
            return True
        dist = _haversine_km(
            loc.get("latitude"), loc.get("longitude"),
            item.get("lat"), item.get("lon"),
        )
        # Sin coordenadas del anuncio -> ante la duda, dejar pasar.
        if dist is None:
            return True
        return dist <= float(radius_km)

    # Solo 'shipping' marcado y el anuncio NO admite envío -> fuera.
    return False


def evaluate(item, alert, cfg):
    """
    Decide sobre un anuncio NUEVO. Devuelve (decision, category) con
    decision in {'keep', 'reject'}.

    Árbol de decisión:
      ¿El TÍTULO contiene alguna palabra del juego buscado?
       ├─ SÍ  -> el juego es correcto. Clasificar el producto por descripción:
       │         base / expansion / components / lote.
       │         - categoría no deseada (want)  -> reject
       │         - lote                          -> keep (precio ignorado)
       │         - resto                         -> keep si el precio encaja
       └─ NO  -> única vía: que sea un LOTE que incluya el juego buscado
                 (el LLM lo confirma ignorando los tags).
                 - lote relevante y 'lote' en want -> keep (precio ignorado)
                 - en caso contrario               -> reject
    """
    if _hard_excluded(item, alert):
        return "reject", "excluded"

    cls = cfg.get("classifier", {})
    use_llm = cls.get("use_llm", True)
    model = cls.get("model", "qwen2.5:3b")
    target = alert["keywords"]
    title = item.get("title", "")
    desc = item.get("description", "")
    want = alert.get("want") or ["base", "lote"]
    bypass = cfg.get("lote_bypass_price", True)

    # ----- RAMA 1: el título coincide -> el juego es correcto -----
    if classifier.title_matches(target, title):
        category = classifier.classify_category(title, desc, use_llm, model)

        # Si el LLM no decide (o está apagado): aceptar como base, según
        # tu preferencia de no perder anuncios cuyo título sí coincide.
        if category == "unknown":
            category = "base"

        if category not in want:
            return "reject", category

        if category == "lote" and bypass:
            return "keep", category

        return ("keep", category) if _price_ok(item, alert) else \
               ("reject", category)

    # ----- RAMA 2: el título NO coincide -> solo vale un lote relevante -----
    if "lote" not in want:
        return "reject", "no_title_match"

    # Prefiltro barato: solo preguntamos al LLM si el texto parece un lote.
    # Evita una llamada al modelo por cada anuncio que no es del juego buscado.
    if not classifier.looks_like_lote(title, desc):
        return "reject", "no_title_match"

    lote = classifier.check_lote(target, title, desc, use_llm, model)
    if lote["is_lote"] and lote["includes_target"]:
        return "keep", "lote"   # precio ignorado en lotes
    return "reject", "no_title_match"


def process_alert(user_id, config, alert, notify_enabled=True):
    name = alert["name"]
    db_key = f"{user_id}/{name}"   # separa lo visto por cada usuario en la BD
    log.info("[%s] Comprobando alerta: %s", user_id, name)

    results = scraper.search(
        keywords=alert["keywords"],
        latitude=config["location"]["latitude"],
        longitude=config["location"]["longitude"],
        min_price=None, max_price=None,   # filtramos nosotros (bypass de lotes)
    )
    raw_ids = {it["id"] for it in results}

    known = database.get_known_ids(db_key)     # ya clasificados antes
    kept_rows = database.get_kept_rows(db_key)  # los que notificamos en su día

    # Solo clasificamos los anuncios NUEVOS.
    candidates = [it for it in results if it["id"] not in known]

    # Filtro de entrega (radio / envío) ANTES de clasificar: así no gastamos
    # LLM en anuncios que el usuario no podría recibir según su config.
    n_candidates = len(candidates)
    candidates = [it for it in candidates if _delivery_ok(it, config)]
    n_descartados_entrega = n_candidates - len(candidates)

    decided, new_kept = [], []
    for it in candidates:
        decision, category = evaluate(it, alert, config)
        decided.append((it, category, decision))
        if decision == "keep":
            it["category"] = category
            new_kept.append(it)

    # Bajas: items que notificamos y cuyo listing ya no aparece.
    sold_ids = set(kept_rows) - raw_ids
    sold_items = [kept_rows[i] for i in sold_ids]

    # Housekeeping: rechazados que desaparecen, fuera de la BD.
    rejected_ids = known - set(kept_rows)
    rejected_gone = rejected_ids - raw_ids

    log.info("  -> [%s] %d resultados | %d nuevos | %d fuera por entrega | "
             "%d clasificados | %d aceptados | %d retirados",
             user_id, len(results), n_candidates, n_descartados_entrega,
             len(candidates), len(new_kept), len(sold_items))

    database.add_items(db_key, decided)
    database.delete_items(db_key, sold_ids | rejected_gone)

    if notify_enabled:
        notifier.notify(config, name, new_kept, sold_items)
    else:
        log.info("  (modo seed: registrado sin enviar email)")


def run_cycle(user_id, config, notify_enabled=True):
    for alert in config.get("alerts") or []:
        try:
            process_alert(user_id, config, alert, notify_enabled)
        except Exception as e:
            log.exception("[%s] Error en alerta '%s': %s",
                          user_id, alert.get("name"), e)
        time.sleep(2)


def _bootstrap_data_dir():
    """Solo en cloud (DATA_DIR definido): crea la estructura en el volumen
    y, la primera vez (volumen vacio), lo siembra con los configs del repo."""
    data_dir = os.getenv("DATA_DIR")
    if not data_dir:
        return
    log.info("Modo cloud: datos persistentes en %s", data_dir)
    os.makedirs(CONFIGS_DIR, exist_ok=True)
    repo_configs = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "configs")
    if not os.path.isdir(repo_configs):
        return
    existing = [f for f in os.listdir(CONFIGS_DIR)
                if f.lower().endswith((".yaml", ".yml"))]
    if existing:
        return
    seeded = []
    for fn in sorted(os.listdir(repo_configs)):
        if fn.lower().endswith((".yaml", ".yml")):
            shutil.copy2(os.path.join(repo_configs, fn),
                         os.path.join(CONFIGS_DIR, fn))
            seeded.append(fn)
    if seeded:
        log.info("Volumen sembrado con los configs del repo: %s",
                 ", ".join(seeded))


def _llm_banner(configs):
    if not any((c.get("classifier") or {}).get("use_llm", True)
               for c in configs.values()):
        return
    ok, desc = classifier.llm_available()
    if ok:
        log.info("LLM activo: %s", desc)
    else:
        log.warning("LLM NO disponible (%s). Se seguira con la red de "
                    "seguridad (menos precisa).", desc)


def _check_inbox(last_ts):
    """Comprueba el buzon si toca. Devuelve (nuevo_last_ts, aplicados)."""
    settings = config_inbox.load_settings()
    if not settings:
        return last_ts, []
    every = float(settings.get("inbox_check_minutes", 5)) * 60
    now = time.monotonic()
    if last_ts is not None and now - last_ts < every:
        return last_ts, []
    try:
        applied = config_inbox.check_and_apply(settings)
    except Exception:
        log.exception("Fallo comprobando el buzon")
        applied = []
    return now, applied


def main():
    args = sys.argv[1:]
    _bootstrap_data_dir()
    database.init_db()
    configs = load_all_configs()

    if not configs:
        log.warning("No hay configs en %s. El bot esperara a que llegue "
                    "alguna por correo (o crea una a mano).", CONFIGS_DIR)
    else:
        log.info("Configs cargadas: %s", ", ".join(configs))
    if not os.path.exists(config_inbox.SETTINGS_PATH):
        log.warning("Sin bot_settings.yaml: la extraccion automatica del "
                    "buzon queda desactivada.")
    _llm_banner(configs)

    if "--seed" in args:
        log.info("== SEED: registrando estado actual sin enviar emails ==")
        for user_id, cfg in configs.items():
            run_cycle(user_id, cfg, notify_enabled=False)
        log.info("Seed completado. A partir de ahora, solo novedades.")
        return

    if "--once" in args:
        _, applied = _check_inbox(None)
        if applied:
            configs = load_all_configs()
        for user_id, cfg in configs.items():
            run_cycle(user_id, cfg, notify_enabled=True)
        return

    log.info("Iniciado en modo multi-config. Tick de 60 s; cada usuario "
             "corre segun su check_interval_minutes. Ctrl+C para parar.")
    last_run = {}        # user_id -> time.monotonic() de su ultimo ciclo
    last_inbox = None
    try:
        while True:
            last_inbox, applied = _check_inbox(last_inbox)
            if applied:
                log.info("Configs aplicadas desde el buzon: %s",
                         ", ".join(applied))
                configs = load_all_configs()
                for user_id in applied:
                    last_run.pop(user_id, None)  # ciclo inmediato con la nueva
            for user_id, cfg in list(configs.items()):
                interval = float(cfg.get("check_interval_minutes") or 30) * 60
                prev = last_run.get(user_id)
                if prev is None or time.monotonic() - prev >= interval:
                    run_cycle(user_id, cfg, notify_enabled=True)
                    last_run[user_id] = time.monotonic()
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Detenido por el usuario.")


if __name__ == "__main__":
    main()
