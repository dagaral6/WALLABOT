"""
main.py
-------
Carga la config, comprueba cada alerta y envía emails ante novedades o bajas.

Flujo por ciclo (eficiente con el LLM):
  1) Pide a Wallapop los resultados (sin filtro de precio, para no perder lotes).
  2) Clasifica SOLO los anuncios nuevos (los ya vistos no se reclasifican).
  3) Aplica categoría deseada + precio (con bypass para lotes).
  4) Detecta BAJADAS DE PRECIO en lo ya notificado y recupera anuncios que se
     habían descartado por caros y ahora entran en presupuesto.
  5) Detecta bajas: items que notificamos y ya no aparecen.

Uso:
    python main.py            # bucle multi-config (cada usuario a su ritmo)
    python main.py --once     # una pasada de todos los configs
    python main.py --seed     # registra lo actual SIN avisar (todos)
    python main.py --force    # ignora la ventana de sueño (1-7h) en esta ejecución

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
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:          # Python <3.9 o sin tzdata instalado
    ZoneInfo = None

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


# Categoría(s) NATIVA(s) de Wallapop a las que se restringe la búsqueda
# (juegos de mesa). Se rellena en main() desde bot_settings.yaml (search.
# category_ids) vía configure_search(). Vacío = sin filtro (comportamiento de
# siempre). Lista de IDs como str.
_SEARCH_CATEGORY_IDS = []


def configure_search(settings):
    """Lee search.category_ids de bot_settings.yaml y fija el filtro global de
    categoría. Tolerante: si falta la sección o el valor no es válido, deja el
    filtro vacío (sin filtrar). Las env-vars no aplican aquí (ajuste global)."""
    global _SEARCH_CATEGORY_IDS
    ids = []
    try:
        raw = ((settings or {}).get("search") or {}).get("category_ids") or []
        if isinstance(raw, (str, int)):
            raw = [raw]
        ids = [str(c).strip() for c in raw if str(c).strip()]
    except Exception as e:
        log.warning("search.category_ids inválido (%s); sin filtro de categoría.", e)
        ids = []
    _SEARCH_CATEGORY_IDS = ids
    if ids:
        log.info("Filtro de categoría Wallapop activo: category_ids=%s",
                 ",".join(ids))


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


def _use_ai(cfg):
    """¿Usar IA (cascada de LLM) para clasificar? Lee el campo simplificado
    'use_ai'; si no está, cae al antiguo 'classifier.use_llm' (compat). Por
    defecto, sí."""
    if "use_ai" in cfg:
        return bool(cfg.get("use_ai"))
    return bool((cfg.get("classifier") or {}).get("use_llm", True))


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


def evaluate(item, alert, cfg, cat_cache=None):
    """
    Decide sobre un anuncio NUEVO. Devuelve (decision, category) con
    decision in {'keep', 'reject'}.

    cat_cache (opcional): dict {item_id: categoria} precalculado POR LOTES en
    process_alert. Si el anuncio está ahí, se usa esa categoría en vez de
    llamar al LLM uno a uno. Sin cat_cache el comportamiento es el de siempre
    (clasificación por anuncio), para no romper llamadas directas ni tests.

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

    title = item.get("title", "")
    desc = item.get("description", "")
    if classifier.looks_foreign_language(title, desc):
        return "reject", "foreign_language"

    use_llm = _use_ai(cfg)
    model = classifier.get_ollama_model()
    target = alert["keywords"]
    want = alert.get("want") or ["base", "lote"]
    bypass = cfg.get("lote_bypass_price", True)

    # ----- RAMA 1: el título coincide -> el juego es correcto -----
    if classifier.title_matches(target, title):
        if cat_cache is not None and item.get("id") in cat_cache:
            category = cat_cache[item["id"]]      # precalculado por lotes
        else:
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
        category_ids=_SEARCH_CATEGORY_IDS or None,   # categoría nativa (juegos de mesa)
    )
    raw_by_id = {it["id"]: it for it in results}
    raw_ids = set(raw_by_id)

    known = database.get_known_ids(db_key)         # ya clasificados antes
    kept_rows = database.get_kept_rows(db_key)     # los que notificamos en su día
    rejected_rows = database.get_rejected_rows(db_key)  # descartados (para recuperar)
    want = alert.get("want") or ["base", "lote"]

    # --- 1) NUEVOS: solo clasificamos los anuncios que no habíamos visto -----
    candidates = [it for it in results if it["id"] not in known]
    # Filtro por CATEGORÍA nativa de Wallapop (red de seguridad al filtro
    # server-side): descarta lo que no es juego de mesa antes de gastar LLM.
    # Solo se cae un anuncio si TIENE category_id y NO está en la lista; si no
    # trae category_id (campo ausente en el payload), no se descarta (no perder
    # anuncios; se confía en el filtro server-side de scraper.search).
    n_descartados_categoria = 0
    if _SEARCH_CATEGORY_IDS:
        allowed = set(_SEARCH_CATEGORY_IDS)
        n_pre_cat = len(candidates)
        candidates = [it for it in candidates
                      if it.get("category_id") is None
                      or str(it.get("category_id")) in allowed]
        n_descartados_categoria = n_pre_cat - len(candidates)
    # Filtro de entrega (radio / envío) ANTES de clasificar: así no gastamos
    # LLM en anuncios que el usuario no podría recibir según su config.
    n_candidates = len(candidates)
    candidates = [it for it in candidates if _delivery_ok(it, config)]
    n_descartados_entrega = n_candidates - len(candidates)

    # Pre-clasificación POR LOTES (Tarea 1): los anuncios cuyo título coincide
    # se clasifican agrupados (1 llamada LLM por lote, no por anuncio). Esto
    # recorta drásticamente las peticiones/minuto en pasadas grandes y evita
    # disparar 429 en todos los proveedores a la vez. El resto de evaluate()
    # (idioma, precio, want, rama de lotes) no cambia. Como process_alert se
    # ejecuta por (usuario, alerta), el lote es siempre de un único usuario.
    target = alert["keywords"]
    use_llm = _use_ai(config)
    model = classifier.get_ollama_model()
    match_items = [it for it in candidates
                   if classifier.title_matches(target, it.get("title", ""))]
    cats = classifier.classify_categories_batch(
        [(it.get("title", ""), it.get("description", "")) for it in match_items],
        use_llm, model)
    cat_cache = {it["id"]: c for it, c in zip(match_items, cats)}

    decided, new_kept = [], []
    for it in candidates:
        decision, category = evaluate(it, alert, config, cat_cache)
        # Idioma detectado (es/ca/en/otro) para TODAS las filas. La descripción
        # ya viene en `it` desde el scraper; database.add_items la guarda solo en
        # 'keep'. detect_language reutiliza el gate looks_foreign_language, así
        # que es consistente con category == 'foreign_language' (-> 'otro').
        it["language"] = classifier.detect_language(
            it.get("title", ""), it.get("description", ""))
        decided.append((it, category, decision))
        if decision == "keep":
            it["category"] = category
            new_kept.append(it)

    # --- 2) BAJADAS DE PRECIO en anuncios que YA notificamos y siguen vivos --
    # "Cualquier bajada" respecto al último precio visto. Si sube, refrescamos
    # la referencia (sin avisar) para comparar futuras bajadas con el último.
    price_drops, price_updates = [], []   # price_updates: (id, nuevo_precio)
    for iid, row in kept_rows.items():
        it = raw_by_id.get(iid)
        if it is None:
            continue                       # desaparecido -> se trata como baja
        old, new = row.get("price"), it.get("price")
        if old is None or new is None:
            continue
        if new < old:
            drop = dict(it)
            drop["old_price"], drop["category"] = old, row.get("category")
            price_drops.append(drop)
            price_updates.append((iid, new))
        elif new != old:
            price_updates.append((iid, new))

    # --- 3) RECUPERADOS: rechazados por precio que ahora entran (han bajado) --
    resurrected, promoted = [], []         # promoted: (id, nuevo_precio) -> keep
    for iid, row in rejected_rows.items():
        it = raw_by_id.get(iid)
        if it is None:
            continue
        cat = row.get("category")
        # Solo categorías que el usuario quiere y que son producto real.
        if cat not in want or cat in ("excluded", "no_title_match", "not_game"):
            continue
        old, new = row.get("price"), it.get("price")
        if new is None:
            continue
        # Tiene que entrar ahora en el filtro de precio Y haber bajado.
        if _price_ok(it, alert) and (old is None or new < old):
            res = dict(it)
            res["old_price"], res["category"] = old, cat
            res["recovered"] = True   # bajó hasta entrar en tu presupuesto
            resurrected.append(res)
            promoted.append((iid, new))

    # Bajas: items que notificamos y cuyo listing ya no aparece.
    sold_ids = set(kept_rows) - raw_ids
    sold_items = [kept_rows[i] for i in sold_ids]

    # Housekeeping: rechazados que desaparecen, fuera de la BD.
    rejected_ids = known - set(kept_rows)
    rejected_gone = rejected_ids - raw_ids

    log.info("  -> [%s] %d resultados | %d fuera por categoría | %d nuevos | "
             "%d fuera por entrega | %d aceptados | %d bajadas | %d recuperados "
             "| %d retirados",
             user_id, len(results), n_descartados_categoria, n_candidates,
             n_descartados_entrega, len(new_kept), len(price_drops),
             len(resurrected), len(sold_items))

    database.add_items(db_key, decided)
    database.update_prices(db_key, price_updates)
    database.promote_to_keep(db_key, promoted)
    database.delete_items(db_key, sold_ids | rejected_gone)

    # Para el email, los recuperados son también "bajada de precio".
    all_drops = price_drops + resurrected

    if notify_enabled:
        notifier.notify(config, name, new_kept, sold_items, all_drops)
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
    if not any(_use_ai(c) for c in configs.values()):
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


# ---------------------------------------------------------------------------
#  VENTANA DE SUEÑO (no buscar de madrugada)
# ---------------------------------------------------------------------------

def _sleep_config():
    """Lee la ventana de sueño de bot_settings.yaml. Devuelve dict o None.

    Estructura esperada:
        sleep_hours:
          enabled: true
          start: 1            # hora (en 'timezone') a la que empieza a dormir
          end: 7              # hora a la que despierta (NO incluida)
          timezone: "Europe/Madrid"

    Override por entorno: SLEEP_HOURS_ENABLED=0/1.
    """
    settings = config_inbox.load_settings() or {}
    sh = dict(settings.get("sleep_hours") or {})
    env = os.getenv("SLEEP_HOURS_ENABLED")
    if env is not None:
        sh["enabled"] = env.strip().lower() in ("1", "true", "yes", "si", "sí", "on")
    if not sh.get("enabled"):
        return None
    try:
        return {
            "start": int(sh.get("start", 1)),
            "end": int(sh.get("end", 7)),
            "tz": str(sh.get("timezone") or "Europe/Madrid"),
        }
    except (TypeError, ValueError):
        log.warning("sleep_hours mal configurado: %s (se ignora).", sh)
        return None


def _now_hour(tz_name):
    """Hora (0-23) actual en la zona indicada. Si zoneinfo no está disponible
    (Windows sin tzdata), cae a la hora local del sistema: para una máquina en
    España y para GitHub Actions (TZ=Europe/Madrid) ya es la hora correcta."""
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name)).hour
        except Exception:
            pass
    return datetime.now().hour


def _is_sleeping(force=False, cfg=None):
    """¿Toca dormir ahora? Las ejecuciones manuales (--force o el botón
    'Run workflow' de GitHub, que define GITHUB_EVENT_NAME=workflow_dispatch)
    ignoran el horario de sueño."""
    if force or os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return False
    cfg = cfg if cfg is not None else _sleep_config()
    if not cfg:
        return False
    h = _now_hour(cfg["tz"])
    s, e = cfg["start"], cfg["end"]
    if s == e:
        return False
    if s < e:
        return s <= h < e
    return h >= s or h < e        # ventana que cruza medianoche (p.ej. 23->7)


def main():
    args = sys.argv[1:]
    force = "--force" in args
    _bootstrap_data_dir()
    database.init_db()
    # Configura la cascada de LLM (orden, modelos, claves) desde bot_settings.yaml;
    # las variables de entorno (Secrets en CI) siguen teniendo prioridad.
    _settings = config_inbox.load_settings()
    classifier.configure_from_settings(_settings)
    configure_search(_settings)   # filtro de categoría nativa (search.category_ids)
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
        if _is_sleeping(force):
            log.info("Horario de sueño: no se hace nada en esta pasada.")
            return
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
    sleeping = False
    try:
        while True:
            if _is_sleeping(force):
                if not sleeping:
                    cfg_s = _sleep_config()
                    if cfg_s:
                        log.info("Entrando en horario de sueño "
                                 "(%02d:00-%02d:00 %s): sin búsquedas ni buzón "
                                 "hasta despertar.",
                                 cfg_s["start"], cfg_s["end"], cfg_s["tz"])
                    sleeping = True
                time.sleep(60)
                continue
            if sleeping:
                log.info("Fin del horario de sueño: reanudando.")
                sleeping = False
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
