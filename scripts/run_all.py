"""Mise à jour complète du site NFL LABS (roule dans GitHub Actions, ou sur le PC pour tester).

usage: python -I scripts/run_all.py [--sans-fantasy] [--sans-paris]
Écrit data/paris.json, data/joueurs.json, data/fantasy.json et data/maj.json. Garde l'état du suivi Fantasy dans state/.
Une étape qui plante garde le fichier précédent et est notée dans data/maj.json.
"""
import json, os, shutil, subprocess, sys, tempfile, traceback, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "scripts"
DATA, STATE = ROOT / "data", ROOT / "state"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv"
GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
SEASON = 2026
SKILL = {"QB", "RB", "WR", "TE"}

now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
etapes = {}


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NFL LABS)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        Path(dest).write_bytes(r.read())


def py(*args):
    # -X utf8 : sous Windows, la sortie des scripts serait sinon en cp1252
    r = subprocess.run([sys.executable, "-I", "-X", "utf8", *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    msg = (r.stderr or r.stdout or "").strip()
    if r.returncode:
        raise RuntimeError(msg.splitlines()[-1] if msg else "erreur")
    print((r.stdout or "").strip())


def etape(nom):
    def deco(fn):
        def run(*a):
            try:
                out = fn(*a)
                etapes[nom] = {"ok": True, "at": now()}
                return out
            except Exception as e:
                traceback.print_exc()
                etapes[nom] = {"ok": False, "at": now(), "erreur": str(e)[:200]}
        return run
    return deco


def load(p):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save(name, doc):
    (DATA / name).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


@etape("cotes")
def live(tmp):
    download(ESPN + "scoreboard", tmp / "sb.json")
    download(ESPN + "injuries", tmp / "inj.json")
    py(S / "live_nfl.py", tmp, tmp / "live.json")
    return load(tmp / "live.json")


@etape("stats")
def stats(tmp):
    src = tmp / "nflverse"
    src.mkdir()
    download(NFLVERSE.format(y=SEASON), src / "week.csv")
    download(GAMES, src / "games.csv")
    py(S / "build_nfl.py", src, tmp / "joueurs")
    meta = load(tmp / "joueurs" / "meta.json")
    teams = {}
    for f in (tmp / "joueurs").glob("team_*.json"):
        t = load(f)
        teams[t["team"]] = {"next": t["next"], "players": t["players"]}
    save("joueurs.json", {"updatedAt": meta["updatedAt"], "season": meta["season"], "lastWeek": meta["lastWeek"],
                          "nextWeek": meta["nextWeek"], "cols": meta["cols"], "defense": meta["defense"], "teams": teams})
    return tmp / "joueurs"


def joueurs_from_site(tmp):
    """Si nflverse ne répond pas, on reprend les stats déjà publiées."""
    j = load(DATA / "joueurs.json")
    if not j:
        return None
    d = tmp / "joueurs"
    d.mkdir(exist_ok=True)
    for team, t in j["teams"].items():
        (d / f"team_{team}.json").write_text(json.dumps({"team": team, **t}, ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({k: j[k] for k in ("season", "lastWeek", "nextWeek", "defense")}), encoding="utf-8")
    return d


@etape("lignes DraftKings")
def dk(tmp):
    py(S / "dk_props.py", tmp / "live.json", tmp / "props_dk.json")


@etape("Mise-O-Jeu")
def moj(tmp):
    py(S / "moj_nfl.py", "--fetch", tmp / "miseojeu.json")


@etape("propositions")
def props(tmp, jdir):
    moj_f = tmp / "miseojeu.json"
    py(S / "propositions.py", jdir, jdir / "meta.json", tmp / "live.json", tmp / "props_dk.json",
       moj_f if moj_f.is_file() else "-", tmp / "propositions.json")
    return load(tmp / "propositions.json")


def paris(live_doc, props_doc, tmp):
    prev = load(DATA / "paris.json") or {}
    doc = dict(prev)
    if live_doc:
        doc.update({"week": live_doc["week"], "season": live_doc["season"], "oddsAt": live_doc["oddsAt"],
                    "games": live_doc["games"],
                    "injuries": {t: [x for x in rows if x["pos"] in SKILL] for t, rows in live_doc["injuries"].items()}})
    if props_doc:
        doc.update({"propositions": props_doc, "propositionsAt": now()})
    dkp = load(tmp / "props_dk.json")
    if dkp:
        doc["lignesDK"] = len(dkp["props"])
    doc["updatedAt"] = now()
    save("paris.json", doc)


@etape("fantasy")
def fantasy(tmp):
    out = tmp / "fantasy"
    STATE.mkdir(exist_ok=True)
    prev = STATE / "suivi.json"
    py(S / "build_fantasy.py", out, prev if prev.is_file() else "")
    shutil.copy(out / "suivi.json", prev)
    py(S / "fantasy_site.py", out, DATA / "fantasy.json")
    alertes = load(out / "alertes.json") or []
    topic = os.environ.get("NTFY_TOPIC")
    try:
        hour = datetime.now(ZoneInfo("America/Toronto")).hour
    except Exception:  # Windows sans tzdata : heure de l'Est approximative
        hour = (datetime.now(timezone.utc).hour - 4) % 24
    if alertes and topic and 8 <= hour < 20:
        for a in alertes[:5]:
            req = urllib.request.Request("https://ntfy.sh/" + topic, data=a["texte"].encode("utf-8"),
                                         headers={"Title": "Fantasy QFF", "Content-Type": "text/plain; charset=utf-8"})
            urllib.request.urlopen(req, timeout=15)
        print(len(alertes), "alertes envoyées")


def main():
    DATA.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        if "--sans-paris" not in sys.argv:
            live_doc = live(tmp)
            jdir = stats(tmp) or joueurs_from_site(tmp)
            props_doc = None
            if live_doc:
                dk(tmp)
                moj(tmp)
                if jdir and (tmp / "props_dk.json").is_file():
                    props_doc = props(tmp, jdir)
            paris(live_doc, props_doc, tmp)
        if "--sans-fantasy" not in sys.argv:
            fantasy(tmp)
    maj = load(DATA / "maj.json") or {}
    maj.setdefault("etapes", {}).update(etapes)
    maj["at"] = now()
    save("maj.json", maj)
    print(json.dumps(etapes, ensure_ascii=False))


if __name__ == "__main__":
    main()
