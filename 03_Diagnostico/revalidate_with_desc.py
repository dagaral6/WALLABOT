"""
revalidate_with_desc.py
-----------------------
Revalidacion con DESCRIPCION (decision del usuario). Scrapea en vivo las
keywords reales y clasifica cada anuncio con las MISMAS reglas usando:
  (a) solo el titulo
  (b) titulo + descripcion

Mide el VALOR INCREMENTAL de la descripcion: anuncios que con el titulo se
enviarian (base/lote) pero con la descripcion se detectan como no-juego
(not_game/components). Lista esos casos con su descripcion para revision manual
(confirmar que son aciertos y que no se marca por error ningun juego real).

Reutiliza el clasificador de reglas de tune_rules_only.py.

Esta maquina tiene fallo SSL local; en Actions el scraping va con verificacion
normal. Aqui (solo diagnostico, datos publicos) saltamos la verificacion SSL.

    py revalidate_with_desc.py
"""

import os
import sys
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(BASE, "..", "01_Core"))
sys.path.insert(0, CORE)
sys.path.insert(0, BASE)

import scraper                # noqa: E402
import tune_rules_only as tr  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass

LAT, LON = 39.4699, -0.3763
SEND = tr.WANT_SENT          # {"base", "lote"} -> se enviaria al usuario


def search_no_ssl(kw, pages=3):
    items, seen, token, page = [], set(), None, 0
    while page < pages:
        page += 1
        params = ({"next_page": token} if token else
                  {"source": "search_box", "keywords": kw,
                   "latitude": LAT, "longitude": LON})
        try:
            resp = requests.get(scraper.SEARCH_URL, params=params,
                                headers=scraper.HEADERS, timeout=25,
                                verify=False)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            print(f"  error scrape '{kw}': {e}")
            break
        raw = scraper._extract_items(payload)
        for r in raw:
            it = scraper._normalize_item(r)
            if it["id"] and it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
        token = scraper._extract_next_page(payload)
        if not raw or not token:
            break
    return items


def main():
    keywords = sorted(set(tr.ALERT_KEYWORDS.values()))
    tot = send_title = send_full = 0
    rescued = []   # titulo->enviar, desc->no enviar (valor de la descripcion)

    for kw in keywords:
        items = search_no_ssl(kw)
        print(f"'{kw}': {len(items)} anuncios")
        for it in items:
            title = it.get("title") or ""
            desc = it.get("description") or ""
            pred_t = tr.classify(title, kw, desc="")
            pred_f = tr.classify(title, kw, desc=desc)
            tot += 1
            st = pred_t in SEND
            sf = pred_f in SEND
            send_title += int(st)
            send_full += int(sf)
            if st and not sf:
                rescued.append((kw, title, desc, pred_f))

    print(f"\n--- {tot} anuncios scrapeados ---")
    print(f"Se enviarian SOLO con titulo:        {send_title}")
    print(f"Se enviarian con titulo+descripcion: {send_full}")
    print(f"RUIDO que QUITA la descripcion:       {send_title - send_full} "
          f"({len(rescued)} casos)")

    print(f"\n=== Casos detectados gracias a la DESCRIPCION (revision manual) ===")
    for kw, title, desc, pred in rescued[:40]:
        d = desc.replace("\n", " ")[:110]
        print(f"  [{kw}] -> {pred}")
        print(f"     titulo: {title[:60]}")
        print(f"     desc:   {d}")
    if len(rescued) > 40:
        print(f"  ... y {len(rescued) - 40} mas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
