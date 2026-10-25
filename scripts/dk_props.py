"""DraftKings player-prop lines (via ESPN's free API) -> doc nfl/props_dk for the Analyste NFL db.

usage: python -I dk_props.py <live.json> <out.json>
       python -I dk_props.py --candidats <props_dk.json> <joueurs_dir> <meta.json> <live.json> <out.json>
live.json = the nfl/live doc (games with ESPN event ids). Downloads, for every scheduled game,
the DraftKings prop lines and the two teams' rosters (to turn athlete ids into names).
ESPN gives the line only, never the odds: the page assumes a typical 1,87.
"""
import json, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{e}/competitions/{e}/odds/100/propBets?lang=en&region=us&limit=1000&page={p}"
ROSTER = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{t}/roster"
# ESPN market name -> mkey used by the page (main over/under lines only)
TYPES = {
    "Total Passing Yards (incl. overtime)": "pass_yds",
    "Total Pass Completions (incl. overtime)": "pass_cmp",
    "Total Passing Touchdowns (incl. overtime)": "pass_td",
    "Total Rushing Yards (incl. overtime)": "rush_yds",
    "Total Carries (incl. overtime)": "carries",
    "Total Receiving Yards (incl. overtime)": "rec_yds",
    "Total Receptions (incl. overtime)": "receptions",
    "Total Rushing Plus Receiving Yards (incl. overtime)": "rush_rec_yds",
}
ESPN_TEAM = {"LA": "LAR", "WAS": "WSH"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def roster(team):
    d = get(ROSTER.format(t=ESPN_TEAM.get(team, team)))
    return {a["id"]: (a["fullName"], team) for g in d.get("athletes", []) for a in g.get("items", [])}


def game_props(g):
    items, page = [], 1
    while True:
        d = get(CORE.format(e=g["id"], p=page))
        items += d.get("items", [])
        if page >= d.get("pageCount", 1):
            return g, items
        page += 1


def build(live):
    games = [g for g in live.get("games", []) if g.get("status") == "STATUS_SCHEDULED"]
    teams = sorted({t for g in games for t in (g["away"], g["home"])})
    with ThreadPoolExecutor(8) as ex:
        names = {}
        for r in ex.map(roster, teams):
            names.update(r)
        results = list(ex.map(game_props, games))
    props = {}
    for g, items in results:
        for x in items:
            key = TYPES.get((x.get("type") or {}).get("name"))
            line = ((x.get("current") or {}).get("target") or {}).get("value")
            if not key or line is None:
                continue
            aid = (x.get("athlete") or {}).get("$ref", "").split("/athletes/")[-1].split("?")[0]
            if aid not in names:
                continue
            name, team = names[aid]
            opn = ((x.get("open") or {}).get("target") or {}).get("value")
            props[name + "|" + key] = {"joueur": name, "equipe": team, "mkey": key, "ligne": line, "ouverture": opn,
                                       "match": g["away"] + " @ " + g["home"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {"updatedAt": now, "source": "DraftKings via ESPN (lignes seulement)", "props": props}


# columns of a game row in joueurs/<TEAM>.players[].g (newest game first)
COL = {"pass_yds": lambda g: g[4], "pass_cmp": lambda g: g[2], "pass_td": lambda g: g[5], "rush_yds": lambda g: g[8],
       "carries": lambda g: g[7], "rec_yds": lambda g: g[12], "receptions": lambda g: g[10], "rush_rec_yds": lambda g: g[8] + g[12]}
DEF = {"pass_yds": "QB_pass", "pass_cmp": "QB_pass", "pass_td": "QB_pass", "rush_yds": "RB_rush", "carries": "RB_rush", "rush_rec_yds": "RB_rush"}
TYPICAL = 1.87  # DraftKings/bet365 usually price a main player line around -115


def norm_name(n):
    import re, unicodedata
    n = unicodedata.normalize("NFD", n.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[.'’-]", " ", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def candidates(dk, joueurs_dir, meta, live):
    """Every DraftKings line, both sides, with how often the player would have won it."""
    roster = {}
    for f in Path(joueurs_dir).glob("*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        t = t.get("data", t) if isinstance(t.get("data"), dict) else t
        for p in t.get("players", []):
            roster[(t["team"], norm_name(p["name"]))] = {**p, "team": t["team"], "next": t.get("next")}
    inj = {(t, norm_name(x["n"])): x["s"] for t, rows in (live or {}).get("injuries", {}).items() for x in rows}
    defense = (meta or {}).get("defense", {})
    out = []
    for x in dk["props"].values():
        p = roster.get((x["equipe"], norm_name(x["joueur"])))
        if not p:
            continue
        hist = [COL[x["mkey"]](g) for g in p["g"][:8]]
        opp = (p.get("next") or {}).get("opp")
        k = DEF.get(x["mkey"]) or (p["pos"] + "_rec")
        rank = defense.get(opp, {}).get(k + "_rank")
        for side in ("Plus", "Moins"):
            hit = [(v > x["ligne"]) if side == "Plus" else (v < x["ligne"]) for v in hist]
            rate = (sum(hit) + 1) / (len(hit) + 2)
            out.append({**x, "pos": p["pos"], "choix": side, "hist": hist, "reussites": f"{sum(hit)}/{len(hit)}",
                        "taux_lisse": round(rate, 3), "ecart": round(rate - 1 / TYPICAL, 3),
                        "moyenne": round(sum(hist) / len(hist), 1) if hist else None,
                        "rang_defense_adverse": rank, "blessure": inj.get((x["equipe"], norm_name(x["joueur"])))})
    out.sort(key=lambda r: -r["ecart"])
    return out


if __name__ == "__main__":
    load = lambda f: (lambda d: d.get("data", d) if isinstance(d.get("data"), dict) else d)(json.loads(Path(f).read_text(encoding="utf-8")))
    if sys.argv[1] == "--candidats":
        # dk_props.py --candidats <props_dk.json> <joueurs_dir> <meta.json> <live.json> <out.json>
        rows = candidates(load(sys.argv[2]), sys.argv[3], load(sys.argv[4]), load(sys.argv[5]))
        Path(sys.argv[6]).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(len(rows), "candidats")
        sys.exit()
    doc = build(load(sys.argv[1]))
    if not doc["props"]:
        sys.exit("DraftKings : aucune ligne de joueur")
    Path(sys.argv[2]).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(len(doc["props"]), "lignes de joueurs DraftKings")
