"""Mise-O-Jeu (Loto-Québec) NFL odds -> compact JSON for the Analyste NFL db (doc nfl/miseojeu).

usage: python -I moj_nfl.py --fetch <out.json>      (downloads the page itself)
       python -I moj_nfl.py <page.html> <out.json>
       python -I moj_nfl.py --candidats <miseojeu.json> <joueurs_dir> <meta.json> <live.json> <out.json>
page.html = https://miseojeu.lotoquebec.com/fr/offre-de-paris/football/nfl/matchs (latin-1)
--candidats lists every Mise-O-Jeu player prop with the player's real history (nflverse),
how often he beat the line, the probability implied by the odds and the opposing defense rank.
"""
import html, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

TEAMS = {
    "Arizona": "ARI", "Atlanta": "ATL", "Baltimore": "BAL", "Buffalo": "BUF", "Caroline": "CAR",
    "Chicago": "CHI", "Cincinnati": "CIN", "Cleveland": "CLE", "Dallas": "DAL", "Denver": "DEN",
    "Detroit": "DET", "Green Bay": "GB", "Houston": "HOU", "Indianapolis": "IND", "Jacksonville": "JAX",
    "Kansas City": "KC", "Los Angeles-R": "LA", "Los Angeles-C": "LAC", "Las Vegas": "LV", "Miami": "MIA",
    "Minnesota": "MIN", "Nouvelle-Angleterre": "NE", "Nouvelle-Orléans": "NO", "New York-G": "NYG",
    "New York-J": "NYJ", "Philadelphie": "PHI", "Pittsburgh": "PIT", "Seattle": "SEA", "San Francisco": "SF",
    "Tampa Bay": "TB", "Tennessee": "TEN", "Washington": "WAS",
}
# Mise-O-Jeu player suffixes that differ from nflverse codes
PCODES = {"N.O": "NO", "N.E": "NE", "G.B": "GB", "K.C": "KC", "L.V": "LV", "S.F": "SF", "T.B": "TB",
          "LAR": "LA", "WSH": "WAS", "JAC": "JAX", "NYG": "NYG", "NYJ": "NYJ"}

TOKEN = re.compile(
    r'<h3>(?P<h3>[^<]+)</h3>'
    r'|class="titreDate">\s*(?P<date>[\d-]+)'
    r'|class="titreEvenement">(?P<ev>[^<]+)<'
    r'|class="titreQuestion"\s*>(?P<q>[^<]+)<'
    r'|class="colonneHeure(?:AvecIcones)?"\s*>\s*<span>\s*(?P<heure>\d\d:\d\d)'
    r'|class="imgSingle"(?P<single>)'
    r'|descActivite="(?P<desc>[^"]*)"[^>]*>.*?class="souligne">.*?<br>\s*(?P<cote>\d+,\d+)'
    r'|matchs\?idEve=(?P<eve>\d+)',
    re.S)


def clean(s):
    # the page mixes latin-1 headers with UTF-8 body text
    try:
        s = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def team_code(name):
    return TEAMS.get(name.split(",")[0].strip())


def player(text):
    """'Total de verges au sol pour Derrick Henry-BAL (B)' -> ('Derrick Henry', 'BAL')"""
    m = re.search(r"(?:pour|Est-ce que) (.+?)-([A-Z.]{2,4})\b", text)
    if not m:
        return None, None
    return m.group(1).strip(), PCODES.get(m.group(2), m.group(2))


def num(s):
    return float(s.replace(",", "."))


def parse(page):
    games, markets, by_eve = {}, [], {}
    marche = date = ev = question = heure = None
    single = False
    cur = None
    for m in TOKEN.finditer(page):
        if m.group("eve"):
            if cur is not None:
                cur["eve"] = m.group("eve")
                if cur["match"] and " @ " in cur["match"]:
                    by_eve[cur["eve"]] = cur["match"]
            continue
        if m.group("h3"):
            marche = re.sub(r"\s*\(\d+\)$", "", clean(m.group("h3")))
            ev = question = None
        elif m.group("date"):
            date = m.group("date")
        elif m.group("ev"):
            ev = clean(m.group("ev"))
            question = None
        elif m.group("q"):
            question = clean(m.group("q"))
        elif m.group("heure"):
            heure, single, cur = m.group("heure"), False, None
        elif m.group("single") is not None:
            single = True
        elif m.group("desc") is not None:
            if cur is None:
                away, _, home = (ev or "").partition(" c. ")
                a, h = team_code(away), team_code(home)
                match = f"{a} @ {h}" if a and h else ev
                if a and h:
                    games.setdefault(match, {"away": a, "home": h, "date": date, "heure": heure})
                cur = {"marche": marche, "match": match, "q": question, "simple": single, "choix": []}
                j, t = player(question or "")
                if j:
                    cur["joueur"], cur["equipe"] = j, t
                markets.append(cur)
            cur["choix"].append({"d": clean(m.group("desc")), "cote": num(m.group("cote"))})
    # the main-line sections have no event header: recover the game from the row's idEve link
    for mk in markets:
        if not mk["match"]:
            mk["match"] = by_eve.get(mk.get("eve"))
    return games, markets


def mkey(mk):
    q = (mk.get("q") or "").lower()
    if "verges par la passe" in q and "pour" in q:
        return "pass_yds"
    if "verges au sol" in q and "pour" in q:
        return "rush_yds"
    if "verges sur réception" in q and "pour" in q:
        return "rec_yds"
    if "marquera au moins un touché" in q:
        return "td"
    m = (mk.get("marche") or "").lower()
    if m.startswith("gagnant du match avec écart"):
        return "spread"
    if m.startswith("gagnant du match"):
        return "ml"
    if m.startswith("total de points") and "équipes" not in m:
        return "total"
    return None


def build(page):
    games, markets = parse(page)
    for mk in markets:
        key = mkey(mk)
        if key:
            mk["mkey"] = key
        # "Plus de 60,5" -> ligne 60.5 for over/under markets
        for c in mk["choix"]:
            lm = re.match(r"(Plus|Moins) de (\d+,\d+)$", c["d"])
            if lm:
                c["sens"], c["ligne"] = lm.group(1), num(lm.group(2))
            # "Pittsburgh -3,5 pt(s)" -> equipe PIT, ligne -3.5 ; "Pittsburgh" (gagnant) -> equipe PIT
            sp = re.match(r"(.+?) ([+-]\d+(?:,\d+)?) pt", c["d"])
            if key == "spread" and sp and team_code(sp.group(1)):
                c["equipe"], c["ligne"] = team_code(sp.group(1)), num(sp.group(2))
            elif key == "ml" and team_code(c["d"]):
                c["equipe"] = team_code(c["d"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"updatedAt": now, "source": "Mise-O-Jeu (Loto-Québec), cotes décimales",
            "games": games, "markets": markets}


# columns of a game row in joueurs/<TEAM>.players[].g (newest game first)
COL = {"pass_yds": lambda g: g[4], "rush_yds": lambda g: g[8], "rec_yds": lambda g: g[12], "td": lambda g: g[9] + g[13]}
DEF = {"pass_yds": lambda pos: "QB_pass", "rush_yds": lambda pos: "RB_rush", "rec_yds": lambda pos: pos + "_rec", "td": None}


def norm_name(n):
    import unicodedata
    n = unicodedata.normalize("NFD", n.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[.'’-]", " ", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def candidates(moj, joueurs_dir, meta, live):
    roster = {}
    for f in Path(joueurs_dir).glob("*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        t = t.get("data", t) if isinstance(t.get("data"), dict) else t
        for p in t.get("players", []):
            roster[(t["team"], norm_name(p["name"]))] = {**p, "team": t["team"], "next": t.get("next")}
    inj = {(t, norm_name(x["n"])): x["s"] for t, rows in (live or {}).get("injuries", {}).items() for x in rows}
    defense = (meta or {}).get("defense", {})
    out = []
    for mk in moj["markets"]:
        key = mk.get("mkey")
        if key not in COL or not mk.get("joueur"):
            continue
        p = roster.get((mk["equipe"], norm_name(mk["joueur"])))
        hist = [COL[key](g) for g in p["g"][:8]] if p else []
        opp = (p or {}).get("next", {}) or {}
        rank = None
        if p and DEF[key] and opp.get("opp") in defense:
            rank = defense[opp["opp"]].get(DEF[key](p["pos"]) + "_rank")
        c = mk["choix"]
        vig = sum(1 / x["cote"] for x in c)
        for x in c:
            if key == "td":
                hit = [v >= 1 for v in hist] if x["d"] == "Oui" else [v == 0 for v in hist]
                side = "Oui" if x["d"] == "Oui" else "Non"
                ligne = None
            elif x.get("sens"):
                hit = [(v > x["ligne"]) if x["sens"] == "Plus" else (v < x["ligne"]) for v in hist]
                side, ligne = x["sens"], x["ligne"]
            else:
                continue
            n = len(hit)
            rate = (sum(hit) + 1) / (n + 2) if n else None
            implied = 1 / x["cote"]
            out.append({
                "match": mk["match"], "joueur": mk["joueur"], "equipe": mk["equipe"], "pos": (p or {}).get("pos"),
                "mkey": key, "marche": mk["marche"], "choix": side, "ligne": ligne, "cote": x["cote"],
                "simple": mk["simple"], "hist": hist, "reussites": f"{sum(hit)}/{n}" if n else None,
                "taux_lisse": round(rate, 3) if rate is not None else None,
                "prob_cote": round(implied, 3), "prob_sans_marge": round(implied / vig, 3),
                "ecart": round(rate - implied, 3) if rate is not None else None,
                "rang_defense_adverse": rank, "blessure": inj.get((mk["equipe"], norm_name(mk["joueur"]))),
            })
    out.sort(key=lambda r: -(r["ecart"] if r["ecart"] is not None else -9))
    return out


BASE = "https://miseojeu.lotoquebec.com/fr/offre-de-paris/football/nfl/matchs"


def fetch():
    """The bare NFL page shows no bets: follow each nfl/matchs?idAct=N link and keep the richest one."""
    import urllib.request
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("latin-1")
    home = get(BASE)
    best = build(home)
    for act in dict.fromkeys(re.findall(r"nfl/matchs\?idAct=(\d+)", home)):
        doc = build(get(BASE + "?idAct=" + act))
        if len(doc["markets"]) > len(best["markets"]):
            best = doc
    return best


if __name__ == "__main__":
    if sys.argv[1] == "--fetch":
        doc = fetch()
        if not doc["markets"]:
            sys.exit("Mise-O-Jeu : aucun pari trouvé")
        Path(sys.argv[2]).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(len(doc["games"]), "matchs,", len(doc["markets"]), "paris,", sum(1 for m in doc["markets"] if m.get("joueur")), "props joueurs")
        sys.exit()
    if sys.argv[1] == "--candidats":
        load = lambda f: (lambda d: d.get("data", d) if isinstance(d.get("data"), dict) else d)(json.loads(Path(f).read_text(encoding="utf-8")))
        rows = candidates(load(sys.argv[2]), sys.argv[3], load(sys.argv[4]), load(sys.argv[5]))
        Path(sys.argv[6]).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(len(rows), "candidats,", sum(1 for r in rows if r["hist"]), "avec historique")
        sys.exit()
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    doc = build(src.read_bytes().decode("latin-1"))
    if not doc["markets"]:
        sys.exit("Mise-O-Jeu : aucun pari trouvé")
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    props = sum(1 for m in doc["markets"] if m.get("joueur"))
    print(len(doc["games"]), "matchs,", len(doc["markets"]), "paris,", props, "props joueurs")
