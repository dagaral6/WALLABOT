import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "01_Core"))
import classifier as c

cases = [
    ("Catan edicion base", "Juego de mesa en buen estado, completo.", False),
    ("Catan joc de taula", "Venc aquest joc en molt bon estat, complet.", False),
    ("Catan board game", "Great condition, complete, all pieces included.", False),
    ("Catan jeu de société", "Très bon état, vendu avec toutes les pièces.", True),
    ("Catan Brettspiel", "Sehr guter Zustand, komplett, gebraucht verkaufe.", True),
    ("Catan gioco da tavolo", "Usato in ottime condizioni, completo.", True),
    ("Catan jogo de tabuleiro", "Muito bom estado, perfeito, completo.", True),
]

ok = True
for title, desc, expected in cases:
    got = c.looks_foreign_language(title, desc)
    status = "OK" if got == expected else "FAIL"
    if got != expected:
        ok = False
    print(f"{status}  esperado={expected} obtenido={got}  '{title}' / '{desc}'")

sys.exit(0 if ok else 1)
