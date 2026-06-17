# -*- coding: utf-8 -*-
"""Throwaway: por que ciertos anuncios de Risk salen como lote / base."""
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "01_Core")
sys.path.insert(0, CORE)
import scraper
import classifier

NEEDLES = ["risk everything", "figuras de risk caballeria", "miniaturas de plastico verde",
           "nintendo switch", "snowboard chorus", "botas de seguridad lavoro no risk"]

res = scraper.search(keywords="risk", latitude=39.4699, longitude=-0.3763,
                     min_price=None, max_price=None)
for it in res:
    title = it.get("title", "")
    nt = classifier._normalize(title)
    if not any(n in nt for n in NEEDLES):
        continue
    desc = it.get("description", "") or ""
    stripped = classifier.strip_tag_spam(desc)
    full = classifier._normalize(title + " " + stripped)
    m = classifier._LOTE_VOCAB_RE.search(full)
    print("\n" + "=" * 60)
    print("TITULO:", title)
    print("PRECIO:", it.get("price"))
    print("lote_vocab termino:", repr(m.group(0)) if m else None)
    print("DESC:", " ".join(desc.split())[:240])
print("\nFIN.")
