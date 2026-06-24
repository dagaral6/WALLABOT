import os, sys, sqlite3, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import build_review_html as b

db = os.path.join(tempfile.gettempdir(), "_wallabot_tmp.db")
if os.path.exists(db):
    os.remove(db)
con = sqlite3.connect(db)
con.execute("""CREATE TABLE seen_items (
    alert_name TEXT, item_id TEXT, title TEXT, price REAL, url TEXT,
    category TEXT, decision TEXT, description TEXT, language TEXT,
    category_id TEXT, first_seen TEXT, PRIMARY KEY(alert_name,item_id))""")
rows = [
 ("dario/Cities","1","Cities juego de Devir",30,"http://x","base","keep","Negociacion completo","es","12579"),
 ("dario/Cities","2","Lost Cities de Knizia",15,"http://x","no_title_match","reject",None,"en","12579"),
 ("dario/Cities","3","Underwater Cities",40,"http://x","no_title_match","reject",None,None,None),
 ("dario/Catan","4","Catan base",35,"http://x","base","keep","Como nuevo","es","12461"),
 ("dario/Catan","5","Catan en italiano",20,"http://x","foreign_language","reject",None,"otro",None),
 ("dario/Risk","6","Risk Legacy",50,"http://x","base","keep","Precintado","es","12579"),
]
con.executemany(
    "INSERT INTO seen_items (alert_name,item_id,title,price,url,category,"
    "decision,description,language,category_id) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
con.commit()
con.close()

data, has_desc, has_lang = b.load_rows(db)
print("filas:", len(data),
      "| keep:", sum(1 for d in data if d["decision"] == "keep"),
      "| reject:", sum(1 for d in data if d["decision"] == "reject"))
html = b.build_html(data)
out = os.path.join(tempfile.gettempdir(), "_wallabot_tmp.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

checks = {
    "fAlert select": 'id="fAlert"' in html,
    "fDecision select": 'id="fDecision"' in html,
    "populateFilters()": "populateFilters" in html,
    "css .badge.keep": ".badge.keep" in html,
    "dato 'Lost Cities'": "Lost Cities" in html,
    "motivo reject 'no_title_match'": "no_title_match" in html,
    "6 filas embebidas": html.count('"item_id"') == 6,
}
for k, v in checks.items():
    print(("[OK ] " if v else "[FAIL] ") + k)
os.remove(db)
os.remove(out)
print("RESULTADO:", "TODO OK" if all(checks.values()) else "FALLOS")
