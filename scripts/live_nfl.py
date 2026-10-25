"""Cotes DraftKings + blessures (flux publics ESPN) -> document nfl/live pour l'Analyste NFL.

Usage : python -I live_nfl.py <dossier avec sb.json et inj.json> <fichier live.json en sortie>
  sb.json  = https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  inj.json = https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries
La page fait la même conversion en JavaScript (bouton « Actualiser en direct »).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ESPN -> codes nflverse utilisés dans joueurs/<TEAM>
CODES = {"LAR": "LA", "WSH": "WAS"}
KEEP = {"Out", "Doubtful", "Questionable", "Suspension"}
SKILL = {"QB", "RB", "WR", "TE"}


def code(abbr):
    return CODES.get(abbr, abbr)


def side(o, market, team, key="close"):
    m = (o.get(market) or {}).get(team) or {}
    return (m.get(key) or {})


def build(sb, inj):
    names = {}
    games = []
    for t in (sb.get("week") or {}).get("teamsOnBye") or []:
        names[t["displayName"]] = code(t["abbreviation"])
    for e in sb.get("events", []):
        c = e["competitions"][0]
        teams = {x["homeAway"]: x["team"] for x in c["competitors"]}
        for t in teams.values():
            names[t["displayName"]] = code(t["abbreviation"])
        o = (c.get("odds") or [{}])[0]
        g = {
            "id": e["id"],
            "away": code(teams["away"]["abbreviation"]),
            "home": code(teams["home"]["abbreviation"]),
            "kickoff": e["date"],
            "status": c["status"]["type"]["name"],
        }
        if o.get("details"):
            g.update({
                "book": (o.get("provider") or {}).get("name"),
                "spreadHome": side(o, "pointSpread", "home").get("line"),
                "spreadHomeOdds": side(o, "pointSpread", "home").get("odds"),
                "spreadAwayOdds": side(o, "pointSpread", "away").get("odds"),
                "spreadHomeOpen": side(o, "pointSpread", "home", "open").get("line"),
                "total": o.get("overUnder"),
                "overOdds": side(o, "total", "over").get("odds"),
                "underOdds": side(o, "total", "under").get("odds"),
                "totalOpen": (side(o, "total", "over", "open").get("line") or "").lstrip("o") or None,
                "mlHome": side(o, "moneyline", "home").get("odds"),
                "mlAway": side(o, "moneyline", "away").get("odds"),
                "mlHomeOpen": side(o, "moneyline", "home", "open").get("odds"),
                "mlAwayOpen": side(o, "moneyline", "away", "open").get("odds"),
            })
        games.append(g)
    injuries = {}
    for t in inj.get("injuries", []):
        team = names.get(t.get("displayName"))
        if not team:
            continue
        rows = []
        for x in t.get("injuries", []):
            a = x.get("athlete") or {}
            pos = (a.get("position") or {}).get("abbreviation")
            # Blessé à long terme : on le garde seulement pour les positions qui comptent pour les paris
            if x.get("status") not in KEEP and not (x.get("status") == "Injured Reserve" and pos in SKILL):
                continue
            rows.append({
                "n": a.get("displayName"),
                "pos": pos,
                "s": x["status"],
                "c": (x.get("shortComment") or "")[:160],
            })
        injuries[team] = rows
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "updatedAt": now,
        "oddsAt": now,
        "injuriesAt": now,
        "source": "ESPN · cotes DraftKings",
        "season": (sb.get("season") or {}).get("year"),
        "week": (sb.get("week") or {}).get("number"),
        "games": games,
        "injuries": injuries,
    }


FR = {"Out": "absent", "Doubtful": "douteux", "Questionable": "questionnable", "Suspension": "suspendu", "Injured Reserve": "sur la liste des blessés"}


def fr(x, sign=False):
    return (f"{x:+g}" if sign else f"{x:g}").replace(".", ",")


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def alerts(doc, prev, props, morning):
    """Messages de notification (moins de 200 caractères chacun), du plus important au moins important."""
    out = []
    old_inj = {(t, x["n"]): x["s"] for t, r in (prev or {}).get("injuries", {}).items() for x in r}
    new_inj = {(t, x["n"]): x["s"] for t, r in doc["injuries"].items() for x in r}
    picks = (props or {}).get("picks") or []
    mine = {(p.get("equipe"), p.get("joueur")) for p in picks if p.get("joueur")}
    teams = {p.get("equipe") for p in picks}
    if prev:
        # Blessures : un de mes joueurs proposés, ou un quart, dont le statut change
        for (t, n), s in new_inj.items():
            before = old_inj.get((t, n))
            if before == s:
                continue
            pos = next((x["pos"] for x in doc["injuries"][t] if x["n"] == n), "")
            if (t, n) in mine:
                out.append(f"⚠️ {n} ({t}), dans tes propositions, est maintenant {FR.get(s, s)}. Revois ce leg.")
            elif pos == "QB" or (pos in SKILL and t in teams and s in ("Out", "Doubtful")):
                out.append(f"Blessure : {n} ({pos}, {t}) est maintenant {FR.get(s, s)}.")
        for (t, n), before in old_inj.items():
            if (t, n) in mine and (t, n) not in new_inj:
                out.append(f"✅ {n} ({t}), dans tes propositions, n'est plus sur le rapport des blessures.")
        # Lignes : écart qui bouge d'au moins 1,5 point ou total d'au moins 2 points depuis la dernière fois
        old_g = {g["id"]: g for g in prev.get("games", [])}
        for g in doc["games"]:
            o = old_g.get(g["id"])
            if not o or g["status"] != "STATUS_SCHEDULED":
                continue
            a, b = num(o.get("spreadHome")), num(g.get("spreadHome"))
            if a is not None and b is not None and abs(a - b) >= 1.5:
                out.append(f"Ligne qui bouge : {g['away']} @ {g['home']}, {g['home']} {fr(a, True)} → {fr(b, True)}.")
            a, b = num(o.get("total")), num(g.get("total"))
            if a is not None and b is not None and abs(a - b) >= 2:
                out.append(f"Total qui bouge : {g['away']} @ {g['home']}, {fr(a)} → {fr(b)}.")
    if morning:
        left = sum(g["status"] == "STATUS_SCHEDULED" for g in doc["games"])
        best = picks[0] if picks else None
        msg = f"Semaine {doc['week']} : {left} matchs à venir."
        if best:
            msg += f" Ma préférée : {best.get('joueur') or best.get('selection')} {best.get('choix', '')} {str(best.get('ligneMax', '')).replace('.', ',')}."
        n_c = len((props or {}).get("combines") or [])
        if n_c:
            msg += f" {n_c} combinés prêts dans ton module."
        out.insert(0, msg)
    return [m[:199] for m in out]


if __name__ == "__main__":
    # Usage : live_nfl.py <dossier> <live.json> [ancien_live.json] [propositions.json] [--matin]
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    extra = [a for a in sys.argv[3:] if not a.startswith("--")]
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if p and Path(p).is_file() else None
    unwrap = lambda d: (d.get("data") if isinstance(d, dict) and isinstance(d.get("data"), dict) else d)
    sb = json.loads((src / "sb.json").read_text(encoding="utf-8"))
    inj = json.loads((src / "inj.json").read_text(encoding="utf-8"))
    doc = build(sb, inj)
    if not doc["games"]:
        sys.exit("ESPN : aucun match")
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    prev = unwrap(load(extra[0] if extra else None))
    props = unwrap(load(extra[1] if len(extra) > 1 else None))
    msgs = alerts(doc, prev, props, "--matin" in sys.argv)
    (out.parent / "alerts.json").write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
    print(doc["week"], len(doc["games"]), "matchs,", sum(map(len, doc["injuries"].values())), "blessés,", len(msgs), "alertes")
