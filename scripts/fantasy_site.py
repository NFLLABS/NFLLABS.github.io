"""Données publiques de la ligue QFF pour le site NFL LABS, à partir de la sortie de build_fantasy.py.

usage: python -I fantasy_site.py <dossier_sortie_build_fantasy> <fantasy.json>
Ajoute les matchs de la semaine de toute la ligue (pointage en cours de MFL) et les projections de chaque équipe.
Les conseils privés (changements à faire, échanges) ne sont pas publiés.
"""
import json, sys, urllib.request
from pathlib import Path

HOST = "https://www49.myfantasyleague.com"
KEEP = ("id", "nom", "pos", "grp", "nfl", "moy", "med", "der3", "proj", "pts", "bless", "ir", "bye", "adv", "aligne", "start")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-labs/1.0"}), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


as_list = lambda x: x if isinstance(x, list) else ([x] if x else [])


def main(src, out):
    src = Path(src)
    ld = lambda n: json.loads((src / f"{n}.json").read_text(encoding="utf-8"))
    meta, ligue, equipe, waivers = ld("meta"), ld("ligue"), ld("equipe"), ld("waivers")
    yr, lid, week = meta["saison"], meta["lien"].rstrip("/").split("/")[-1], meta["semaine"]

    teams = {t["id"]: t for t in ligue["equipes"]}
    mine = next(r for r in meta["classement"] if r["id"] == meta["moi"])
    teams[meta["moi"]] = {**mine, "force": equipe["force"], "joueurs": equipe["joueurs"]}
    equipes = {}
    for fid, t in teams.items():
        js = [{k: p.get(k) for k in KEEP if k in p} for p in t["joueurs"]]
        aligne = [p for p in js if p.get("aligne")]
        base = aligne or [p for p in js if p.get("start")]
        equipes[fid] = {"nom": t["nom"], "abbr": t.get("abbr"), "fiche": t.get("fiche"), "force": t.get("force"),
                        "proj": round(sum(p.get("proj") or 0 for p in base), 1), "alignementSoumis": bool(aligne),
                        "joueurs": js}

    # Matchs de la semaine : calendrier + pointage en direct de MFL
    sched = get(f"{HOST}/{yr}/export?L={lid}&JSON=1&TYPE=schedule&W={week}")["schedule"]["weeklySchedule"]
    live = {}
    try:
        for m in as_list(get(f"{HOST}/{yr}/export?L={lid}&JSON=1&TYPE=liveScoring&W={week}")["liveScoring"].get("matchup")):
            for f in as_list(m.get("franchise")):
                left = sum(int(p.get("gameSecondsRemaining") or 0) for p in as_list((f.get("players") or {}).get("player"))
                           if p.get("status") == "starter")
                live[f["id"]] = {"score": float(f.get("score") or 0), "reste": left}
    except Exception as e:
        print("liveScoring indisponible :", e)
    matchs = []
    for m in as_list((sched[0] if isinstance(sched, list) else sched).get("matchup")):
        side = []
        for f in as_list(m.get("franchise")):
            e = equipes.get(f["id"], {})
            side.append({"id": f["id"], "nom": e.get("nom", f["id"]), "abbr": e.get("abbr"), "proj": e.get("proj"),
                         "score": live.get(f["id"], {}).get("score"), "reste": live.get(f["id"], {}).get("reste"),
                         "domicile": f.get("isHome") == "1"})
        matchs.append(side)

    agents = {g: [{k: p.get(k) for k in KEEP if k in p} for p in rows[:6]] for g, rows in waivers["parGroupe"].items()}
    doc = {"updatedAt": meta["majAt"], "saison": yr, "semaine": week, "ligue": meta["ligue"], "lien": meta["lien"],
           "finSaisonReg": meta["finSaisonReg"], "moi": meta["moi"], "classement": meta["classement"],
           "bowl": (meta.get("projSaison") or {}).get("bowl"), "matchs": matchs, "equipes": equipes,
           "agentsLibres": agents, "alignement": meta.get("alignement"), "pointage": meta.get("pointage")}
    Path(out).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("fantasy", len(equipes), "équipes,", len(matchs), "matchs, semaine", week)


if __name__ == "__main__":
    main(*sys.argv[1:3])
