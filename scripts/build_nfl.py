"""Build compact JSON documents for the Analyste NFL artifact db from nflverse CSVs.

Usage: python -I build_nfl.py <data_dir> <out_dir>
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

data_dir, out_dir = sys.argv[1], sys.argv[2]
os.makedirs(out_dir, exist_ok=True)

SEASON = 2026
POS = {"QB", "RB", "WR", "TE"}
# Column order of each game row stored in the db (keep in sync with the page)
COLS = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds"]


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(f) if f.is_integer() else round(f, 1)


rows = []
with open(os.path.join(data_dir, "week.csv"), newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["season"] == str(SEASON) and r["season_type"] in ("REG", "POST") and r["position"] in POS:
            rows.append(r)

last_week = max(int(r["week"]) for r in rows)

# Schedule: next week's games and each team's next opponent
games = []
with open(os.path.join(data_dir, "games.csv"), newline="", encoding="utf-8") as f:
    for g in csv.DictReader(f):
        if g["season"] == str(SEASON):
            games.append(g)
upcoming = [g for g in games if g["home_score"] == "" and g["game_type"] == "REG"]
next_week = min((int(g["week"]) for g in upcoming), default=None)
next_games = [g for g in upcoming if next_week is not None and int(g["week"]) == next_week]
next_opp = {}
for g in next_games:
    next_opp[g["away_team"]] = {"opp": g["home_team"], "home": False}
    next_opp[g["home_team"]] = {"opp": g["away_team"], "home": True}

# Home flag per game row (last column): 1 = the player's team was at home
home_of = {g["game_id"]: g["home_team"] for g in games}

# Players by team (current team = team of most recent game)
players = {}
for r in sorted(rows, key=lambda r: int(r["week"])):
    p = players.setdefault(r["player_id"], {"id": r["player_id"], "name": r["player_display_name"] or r["player_name"],
                                             "pos": r["position"], "g": []})
    p["team"] = r["team"]
    home = home_of.get(r["game_id"]) or r["game_id"].split("_")[-1]
    p["g"].append([int(r["week"]), r["opponent_team"]] + [num(r[c]) for c in COLS] + [1 if home == r["team"] else 0])

by_team = defaultdict(list)
for p in players.values():
    g = p["g"]
    usage = sum(x[3] + x[7] + x[11] for x in g)  # attempts + carries + targets
    if usage < 3:
        continue
    p["g"] = list(reversed(g))[:10]  # most recent first
    by_team[p["team"]].append(p)

for team, ps in by_team.items():
    ps.sort(key=lambda p: -sum(x[3] + x[7] + x[11] for x in p["g"]))
    doc = {"team": team, "next": next_opp.get(team), "players": [{k: p[k] for k in ("id", "name", "pos", "g")} for p in ps]}
    with open(os.path.join(out_dir, f"team_{team}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

# Defense vs position: yards allowed per game by each defense, ranked (1 = allows the most = best matchup)
allowed = defaultdict(lambda: defaultdict(float))
dgames = defaultdict(set)
for r in rows:
    d, pos = r["opponent_team"], r["position"]
    dgames[d].add(r["game_id"])
    if pos == "QB":
        allowed[d]["QB_pass"] += num(r["passing_yards"])
    if pos == "RB":
        allowed[d]["RB_rush"] += num(r["rushing_yards"])
    allowed[d][pos + "_rec"] += num(r["receiving_yards"])
    allowed[d]["TD"] += num(r["passing_tds"]) if pos == "QB" else 0
keys = ["QB_pass", "RB_rush", "RB_rec", "WR_rec", "TE_rec"]
defense = {}
for d in allowed:
    n = len(dgames[d]) or 1
    defense[d] = {k: round(allowed[d][k] / n, 1) for k in keys}
for k in keys:
    for rank, d in enumerate(sorted(defense, key=lambda d: -defense[d][k]), 1):
        defense[d][k + "_rank"] = rank

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
meta = {
    "season": SEASON, "lastWeek": last_week, "nextWeek": next_week, "updatedAt": now,
    "source": "nflverse", "cols": ["week", "opp"] + COLS + ["home"], "teams": sorted(by_team),
    "games": [{"away": g["away_team"], "home": g["home_team"], "day": g["gameday"], "time": g["gametime"],
               "spread": num(g["spread_line"]) if g["spread_line"] else None,
               "total": num(g["total_line"]) if g["total_line"] else None} for g in next_games],
    "defense": defense,
}
with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))

sizes = sorted((os.path.getsize(os.path.join(out_dir, x)), x) for x in os.listdir(out_dir))
print("last_week", last_week, "next_week", next_week, "games", len(next_games), "teams", len(by_team),
      "players", sum(len(v) for v in by_team.values()))
print("largest", sizes[-3:], "total", sum(s for s, _ in sizes))
