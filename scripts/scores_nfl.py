"""Pointages NFL en direct pour NFL LABS.

python3 -I scores_nfl.py sb.json out.json [prev.json]
  sb.json   : https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  out.json  : doc nfl/scores du hub
  prev.json : doc actuel (facultatif) ; affiche CHANGED ou SAME pour savoir s'il faut écrire
"""
import json, sys
from datetime import datetime, timezone


def team(c):
    t = c.get("team", {})
    rec = (c.get("records") or [{}])[0].get("summary")
    return {"t": t.get("abbreviation"), "nom": t.get("shortDisplayName"), "s": int(c["score"]) if str(c.get("score", "")).isdigit() else None,
            "c": "#" + (t.get("color") or "8d9bb1"), "rec": rec, "id": t.get("id")}


def build(sb):
    games = []
    for e in sb.get("events", []):
        c = e["competitions"][0]
        st = c["status"]
        side = {x["homeAway"]: team(x) for x in c["competitors"]}
        sit = c.get("situation") or {}
        poss = next((k for k, v in side.items() if sit.get("possession") and v["id"] == sit.get("possession")), None)
        g = {"id": e["id"], "away": side["away"], "home": side["home"], "state": st["type"]["state"],
             "detail": st["type"].get("shortDetail"), "kickoff": e.get("date"), "period": st.get("period"),
             "clock": st.get("displayClock"), "poss": poss if st["type"]["state"] == "in" else None,
             "down": sit.get("downDistanceText") if st["type"]["state"] == "in" else None,
             "rz": bool(sit.get("isRedZone")) if st["type"]["state"] == "in" else False,
             "last": ((sit.get("lastPlay") or {}).get("text") or "")[:140] or None}
        for k in ("away", "home"):
            g[k].pop("id", None)
        games.append(g)
    return {"week": (sb.get("week") or {}).get("number"), "games": games}


def main():
    sb = json.load(open(sys.argv[1], encoding="utf-8"))
    doc = build(sb)
    same = False
    if len(sys.argv) > 3:
        try:
            prev = json.load(open(sys.argv[3], encoding="utf-8"))
            prev = prev.get("data", prev)
            same = {k: prev.get(k) for k in ("week", "games")} == doc
        except (OSError, ValueError):
            pass
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(doc, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    live = sum(g["state"] == "in" for g in doc["games"])
    print("SAME" if same else "CHANGED", "live=%d" % live, "games=%d" % len(doc["games"]))


if __name__ == "__main__":
    main()
