# -*- coding: utf-8 -*-
"""
probe_clasificacion.py
----------------------
Saca TODOS los resultados de la alerta activa (o la indicada) y muestra como se
clasifica cada anuncio con la logica actual de classifier.py, tras el rediseno
de jun 2026 (recorte estructural de tags + regla dura de lote).

Dos partes:
  A) Comprobaciones deterministas (SIN red) sobre los casos problematicos
     conocidos (Fantasy Realms / Cryptid / Everdell / Miniaturas Root).
  B) En vivo: pide a Wallapop los resultados de la alerta y clasifica cada uno.

Por defecto clasifica con REGLAS (sin LLM): es lo que aislan los cambios y es
rapido y determinista. Con --llm usa la cascada real (groq/gemini/...).

Uso (desde 03_Diagnostico):
    python probe_clasificacion.py            # alerta activa de dario.yaml
    python probe_clasificacion.py "catan"    # fuerza otras keywords
    python probe_clasificacion.py --llm      # usa la cascada LLM real
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Verificacion TLS con el almacen de certificados del SISTEMA (Windows). En
# local, requests/certifi a veces no encuentra la CA (antivirus que inspecciona
# HTTPS) y da "unable to get local issuer certificate"; truststore usa el store
# del SO y lo resuelve SIN desactivar la verificacion. Solo afecta a este test;
# scraper.py (produccion/Actions) no se toca. Best-effort: si no esta, no pasa.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "01_Core")
sys.path.insert(0, CORE)

import yaml
import scraper
import classifier


def _load_active_alert():
    """Devuelve (config, alert): la 1a alerta de dario.yaml."""
    cfg_path = os.path.join(CORE, "configs", "dario.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    alerts = cfg.get("alerts") or []
    if not alerts:
        raise SystemExit("dario.yaml no tiene alertas.")
    return cfg, alerts[0]


def _price_ok(item, alert):
    p = item.get("price")
    if p is None:
        return True
    mn, mx = alert.get("min_price"), alert.get("max_price")
    if mn is not None and p < mn:
        return False
    if mx is not None and p > mx:
        return False
    return True


def _excluded(item, alert):
    ex = alert.get("exclude") or []
    if not ex:
        return False
    t = classifier._normalize(item.get("title", ""))
    return any(classifier._normalize(x) in t for x in ex)


def decide(item, alert, want, bypass, use_llm, model):
    """Replica fiel del arbol de main.evaluate(), con use_llm controlable."""
    title = item.get("title", "")
    desc = item.get("description", "")
    target = alert["keywords"]
    if _excluded(item, alert):
        return "reject", "excluded"
    if classifier.title_matches(target, title):
        cat = classifier.classify_category(title, desc, use_llm, model)
        if cat == "unknown":
            cat = "base"
        if cat not in want:
            return "reject", cat
        if cat == "lote" and bypass:
            return "keep", cat
        return ("keep", cat) if _price_ok(item, alert) else ("reject", cat)
    if "lote" not in want:
        return "reject", "no_title_match"
    if not classifier.looks_like_lote(title, desc):
        return "reject", "no_title_match"
    lote = classifier.check_lote(target, title, desc, use_llm, model)
    if lote["is_lote"] and lote["includes_target"]:
        return "keep", "lote"
    return "reject", "no_title_match"


def _short(s, n=70):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "..."


def _money(p):
    if p is None:
        return "-"
    try:
        return ("%d EUR" % int(p)) if float(p).is_integer() else ("%.2f EUR" % p)
    except (TypeError, ValueError):
        return str(p)


_SPAM_TAIL = ("Barrage, Underwater Cities, Gran Austria Hotel, SETI, Revive, "
              "Cascadia, Juegos de mesa, Sabika, Ark nova, Lacrimosa, "
              "viticulture, Bitoku, bgg, scythe, azul, Arnak, covenant, "
              "galactic cruise, everdell, eurogame, Gloomhaven, Root, devir, "
              "Maldito Games, labsk, Terraforming Mars, Praga, coimbra, catan, "
              "juego de mesa, juegos, LABSK, Brass, wargame, Wingspan, dune, "
              "Arkham Horror, Mansiones Locura, Spirit Island, Marvel, "
              "Lacerda, Earth")

_BASE_DESC = ("Juego en muy buen estado y como nuevo. Se vende por falta de "
              "espacio. ")

_CASES = [
    ("Fantasy Realms Mitos Griegos. Juego de mesa", _BASE_DESC + _SPAM_TAIL, "root"),
    ("Juego de mesa Cryptid", _BASE_DESC + _SPAM_TAIL, "root"),
    ("Everdell Juego de Mesa", _BASE_DESC + _SPAM_TAIL, "root"),
    ("Miniaturas Root (141uds) resina 4k",
     "Pack Completo de 141 minis para el Juego de Mesa Root: Juego Base y "
     "Expansiones Los Riberenos, Los Subterraneos, Merodeadores. Fabricados en "
     "resina 4k a color. Incluye los 9 vagabundos adicionales.", "root"),
]


def part_a():
    print("=" * 72)
    print("PARTE A - Casos problematicos conocidos (sin red, reglas)")
    print("=" * 72)
    for title, desc, target in _CASES:
        stripped = classifier.strip_tag_spam(desc)
        cut = stripped != desc
        cat = classifier.classify_category(title, desc, use_llm=False)
        print("\nTITULO:", title)
        print("  alerta buscada    :", target)
        print("  title_matches     :", classifier.title_matches(target, title))
        print("  recorto tags      :", cut,
              ("(-%d chars)" % (len(desc) - len(stripped))) if cut else "")
        print("  desc (limpia)     :", _short(stripped, 110))
        print("  has_lote_vocab    :",
              classifier._has_lote_vocab(title + " " + stripped))
        print("  looks_like_lote   :", classifier.looks_like_lote(title, desc))
        print("  categoria (reglas):", cat)


def part_b(keywords_override, use_llm):
    cfg, alert = _load_active_alert()
    if keywords_override:
        alert = dict(alert)
        alert["keywords"] = keywords_override
        alert.setdefault("name", keywords_override)
    want = alert.get("want") or ["base", "lote"]
    bypass = cfg.get("lote_bypass_price", True)
    model = classifier.get_ollama_model()
    loc = cfg["location"]

    print("\n" + "=" * 72)
    print("PARTE B - En vivo: alerta '%s' (keywords=%r)"
          % (alert.get("name"), alert["keywords"]))
    ok, casc = classifier.llm_available()
    print("  cascada LLM       :", casc, "(disp.)" if ok else "(NO disp.)")
    print("  modo              :", "LLM (cascada)" if use_llm else "REGLAS (sin LLM)")
    print("  want=%s bypass_lote=%s min=%s max=%s"
          % (want, bypass, alert.get("min_price"), alert.get("max_price")))
    print("=" * 72)

    results = scraper.search(
        keywords=alert["keywords"],
        latitude=loc["latitude"], longitude=loc["longitude"],
        min_price=None, max_price=None,
    )
    print("Wallapop devolvio %d anuncios.\n" % len(results))

    cats, dec_count, n_stripped = {}, {"keep": 0, "reject": 0}, 0
    for i, it in enumerate(results, 1):
        title = it.get("title", "")
        desc = it.get("description", "") or ""
        stripped = classifier.strip_tag_spam(desc)
        if stripped != desc:
            n_stripped += 1
        decision, cat = decide(it, alert, want, bypass, use_llm, model)
        cats[cat] = cats.get(cat, 0) + 1
        dec_count[decision] = dec_count.get(decision, 0) + 1
        flag = "KEEP" if decision == "keep" else "rej."
        print("%3d. [%-4s] %9s | %s" % (i, flag, _money(it.get("price")),
                                        _short(title, 64)))
        print("      cat=%-11s match=%s lote_voc=%s%s"
              % (cat, classifier.title_matches(alert["keywords"], title),
                 classifier._has_lote_vocab(title + " " + stripped),
                 "  [tags recortados]" if stripped != desc else ""))

    print("\n" + "-" * 72)
    print("RESUMEN: %d anuncios | KEEP=%d REJECT=%d | tags recortados en %d"
          % (len(results), dec_count.get("keep", 0), dec_count.get("reject", 0),
             n_stripped))
    print("  por categoria:",
          ", ".join("%s=%d" % (k, v) for k, v in sorted(cats.items())))


if __name__ == "__main__":
    argv = sys.argv[1:]
    use_llm = "--llm" in argv
    rest = [a for a in argv if a != "--llm"]
    kw = rest[0] if rest else None
    part_a()
    part_b(kw, use_llm)
