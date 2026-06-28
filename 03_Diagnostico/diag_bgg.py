"""
diag_bgg.py
-----------
DIAGNÓSTICO del 401 de BGG (no toca producción). Prueba varias combinaciones de
dominio y cabeceras contra la búsqueda real de BGG e imprime, por cada una, el
código HTTP, si responde Cloudflare (cabecera CF-RAY/Server) y el inicio del
cuerpo. Sirve para saber si el 401 es por el dominio, por las cabeceras o por la
IP (bloqueo de Cloudflare).

    py 03_Diagnostico/diag_bgg.py
"""

import sys
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PARAMS = {"query": "catan", "type": "boardgame"}

UA_NAV = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
H_MIN = {"User-Agent": UA_NAV, "Accept": "application/xml, text/xml, */*"}
H_FULL = {                          # set "de navegador real" completo
    "User-Agent": UA_NAV,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

VARIANTS = [
    ("boardgamegeek.com + UA navegador (actual)",
     "https://boardgamegeek.com/xmlapi2/search", H_MIN),
    ("api.geekdo.com + UA navegador",
     "https://api.geekdo.com/xmlapi2/search", H_MIN),
    ("www.boardgamegeek.com + UA navegador",
     "https://www.boardgamegeek.com/xmlapi2/search", H_MIN),
    ("boardgamegeek.com + headers navegador COMPLETOS",
     "https://boardgamegeek.com/xmlapi2/search", H_FULL),
    ("boardgamegeek.com SIN cabeceras",
     "https://boardgamegeek.com/xmlapi2/search", {}),
]


def main():
    print("Probando BGG /search?query=catan ...\n")
    ok = []
    for name, url, headers in VARIANTS:
        try:
            r = requests.get(url, params=PARAMS, headers=headers, timeout=15,
                             allow_redirects=True)
            body = r.text[:160].replace("\n", " ").replace("\r", " ")
            cf = r.headers.get("CF-RAY")
            srv = r.headers.get("Server")
            print(f"[{r.status_code}] {name}")
            print(f"      server={srv!r}  cf-ray={'sí' if cf else 'no'}  "
                  f"url_final={r.url[:60]}")
            print(f"      body: {body!r}\n")
            if r.status_code == 200:
                ok.append(name)
        except Exception as e:
            print(f"[ERR] {name}\n      {type(e).__name__}: {str(e)[:120]}\n")

    print("=" * 60)
    if ok:
        print("FUNCIONAN (HTTP 200):")
        for n in ok:
            print("  -", n)
    else:
        print("NINGUNA variante devolvió 200: el bloqueo es por IP/Cloudflare")
        print("(probar desde otra red/hotspot lo confirmaría).")


if __name__ == "__main__":
    main()
