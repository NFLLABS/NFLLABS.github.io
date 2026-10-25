"""Construit les données du module Fantasy (M-002) depuis l'API publique de MyFantasyLeague.

Usage : python -I build_fantasy.py <out_dir> [suivi_precedent.json] [conseils.json]
Écrit dans out_dir : meta.json, equipe.json, waivers.json, ligue.json, suivi.json (un fichier par doc db `fantasy/<nom>`).
`suivi` garde les conseils de chaque semaine (figés au début de chaque match), les compare aux vrais points une fois
la semaine finie, et choisit par poste la méthode de projection la plus juste sur les semaines passées.
"""
import csv, io, json, math, random, sys, time, unicodedata, urllib.request
from pathlib import Path

YEAR = 2026
LEAGUE = "49625"
HOST = "https://www49.myfantasyleague.com"
MINE = "0013"
LEAGUE_URL = f"{HOST}/{YEAR}/home/{LEAGUE}"

# Groupes de postes de la ligue (IDP) : DT+DE, LB, CB+S
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "PK": "PK",
         "DT": "DL", "DE": "DL", "LB": "LB", "CB": "DB", "S": "DB"}
# Partants : minimum et maximum par groupe, 14 au total
START_MIN = {"QB": 1, "RB": 1, "WR": 1, "TE": 1, "PK": 1, "DL": 1, "LB": 1, "DB": 1}
START_MAX = {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "PK": 1, "DL": 3, "LB": 3, "DB": 3}
N_START = 14
# 7 partants en attaque (PK inclus) et 7 en défense
SIDE = {"QB": "O", "RB": "O", "WR": "O", "TE": "O", "PK": "O", "DL": "D", "LB": "D", "DB": "D"}
N_SIDE = {"O": 7, "D": 7}
INJ_FACTOR = {"Out": 0.0, "IR": 0.0, "Doubtful": 0.25, "Questionable": 0.85, "Suspended": 0.0}
# Méthodes de projection comparées sur les semaines passées ; la plus juste par poste est retenue
METHODS = {
    "mixte": "moitié moyenne récente (3 derniers matchs comptés double), moitié médiane",
    "moyenne": "moyenne de la saison",
    "mediane": "médiane de la saison",
    "recent": "moyenne des 3 derniers matchs",
}
MIN_BACKTEST = 30  # matchs minimum pour changer de méthode ou corriger un biais
BACKTEST_FROM = 4  # il faut au moins 3 semaines d'historique pour projeter
# Saisons passées (même pointage de ligue depuis 2025) : la moyenne d'une saison passée vaut PRIOR_K matchs de cette saison
PRIOR_YEARS = (YEAR - 1, YEAR - 2)
PRIOR_K = 3
# Stats d'équipe et de joueurs nflverse : style de l'attaque adverse (sacs accordés, passes, courses, interceptions)
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
# Code MFL -> code nflverse
CODES = {"LAR": "LA", "JAC": "JAX", "GBP": "GB", "KCC": "KC", "NOS": "NO", "NEP": "NE", "SFO": "SF", "TBB": "TB", "LVR": "LV"}
# Statuts de blessure qui déclenchent une alerte sur le téléphone
ALERT = {"Out": "absent", "Questionable": "questionnable", "Doubtful": "douteux", "Suspended": "suspendu", "IR": "sur la liste des blessés"}
# Cotes Vegas : points prévus de l'équipe / moyenne, à cette puissance. Testé sur la saison 2025 de la ligue
# (le meilleur exposant par poste, arrondi vers le bas) : aide un peu QB, RB, TE et PK, rien pour WR et les défensifs.
VEGAS_EXP = {"QB": 0.3, "RB": 0.4, "TE": 0.5, "PK": 0.5}
IMP_MOY = 22.5
# Vent de 15 mi/h ou plus au coup d'envoi (2025 : QB -25 %, TE -30 %, WR -13 %, PK -10 %, RB +19 %), réduit de moitié par prudence
WIND_MULT = {"QB": 0.88, "WR": 0.93, "TE": 0.87, "PK": 0.95, "RB": 1.08}
WIND_MIN = 15
# Code ESPN -> code MFL
ESPN2MFL = {"KC": "KCC", "GB": "GBP", "JAX": "JAC", "NE": "NEP", "NO": "NOS", "SF": "SFO", "TB": "TBB", "LV": "LVR", "WSH": "WAS"}
# Stade de chaque équipe (code MFL) : ville et coordonnées, pour la météo des stades extérieurs
STADES = {"ARI": ("Glendale", 33.528, -112.263), "ATL": ("Atlanta", 33.755, -84.401), "BAL": ("Baltimore", 39.278, -76.623),
          "BUF": ("Orchard Park", 42.774, -78.787), "CAR": ("Charlotte", 35.226, -80.853), "CHI": ("Chicago", 41.862, -87.617),
          "CIN": ("Cincinnati", 39.095, -84.516), "CLE": ("Cleveland", 41.506, -81.700), "DAL": ("Arlington", 32.748, -97.093),
          "DEN": ("Denver", 39.744, -105.020), "DET": ("Detroit", 42.340, -83.046), "GBP": ("Green Bay", 44.501, -88.062),
          "HOU": ("Houston", 29.685, -95.411), "IND": ("Indianapolis", 39.760, -86.164), "JAC": ("Jacksonville", 30.324, -81.637),
          "KCC": ("Kansas City", 39.049, -94.484), "LVR": ("Las Vegas", 36.091, -115.184), "LAC": ("Inglewood", 33.953, -118.339),
          "LAR": ("Inglewood", 33.953, -118.339), "MIA": ("Miami Gardens", 25.958, -80.239), "MIN": ("Minneapolis", 44.974, -93.258),
          "NEP": ("Foxborough", 42.091, -71.264), "NOS": ("New Orleans", 29.951, -90.081), "NYG": ("East Rutherford", 40.814, -74.074),
          "NYJ": ("East Rutherford", 40.814, -74.074), "PHI": ("Philadelphia", 39.901, -75.168), "PIT": ("Pittsburgh", 40.447, -80.016),
          "SFO": ("Santa Clara", 37.403, -121.970), "SEA": ("Seattle", 47.595, -122.332), "TBB": ("Tampa", 27.976, -82.503),
          "TEN": ("Nashville", 36.166, -86.771), "WAS": ("Landover", 38.908, -76.864)}
# Keepers : âge où chaque poste commence à décliner, et baisse par année au-delà
PEAK = {"QB": 32, "RB": 26, "WR": 28, "TE": 29, "PK": 36, "DL": 29, "LB": 28, "DB": 28}
DECLINE = {"QB": 0.05, "RB": 0.12, "WR": 0.07, "TE": 0.07, "PK": 0.02, "DL": 0.07, "LB": 0.07, "DB": 0.07}


def median(xs):
    s = sorted(xs)
    return (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2) if s else 0.0


def base_proj(games, method):
    if not games:
        return 0.0
    last = games[-3:]
    if method == "moyenne":
        return sum(games) / len(games)
    if method == "mediane":
        return median(games)
    if method == "recent":
        return sum(last) / len(last)
    wmean = (sum(games) + sum(last)) / (len(games) + len(last))
    return (wmean + median(games)) / 2


def opp_mult(grp, o):
    if not o:
        return 0.0  # bye ou pas de match
    rank = o["rushDef"] if grp == "RB" else o["passDef"] if grp in ("QB", "WR", "TE") else 16
    return 1.0 + (rank - 16.5) / 16.5 * 0.15  # 32e défense = +15 %, 1re = -15 %


def with_prior(games, method, prior):
    """Projection de la saison, tirée vers la moyenne de la saison passée (qui vaut PRIOR_K matchs)."""
    if prior is None:
        return base_proj(games, method)
    n = len(games)
    return (n * base_proj(games, method) + PRIOR_K * prior) / (n + PRIOR_K) if n else prior


def fr1(x):
    return f"{x:.1f}".replace(".", ",")


def pct(m):
    return f"{'+' if m >= 1 else '−'}{abs(round((m - 1) * 100))} %"


def fnum(x):
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def pname(s):
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    for ch in ".'-":
        s = s.replace(ch, " ")
    return " ".join(w for w in s.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def get_csv(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-labs/1.0"}), timeout=120) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))


OFF_KEYS = ("att", "car", "sacs", "int", "jeux")


def team_offense(rows, week):
    """Par attaque, moyennes par match avant `week` : passes, courses, sacs accordés, interceptions, jeux. Rang 1 = en donne le plus."""
    acc = {}
    for r in rows:
        if r.get("season_type") != "REG" or int(r["week"]) >= week:
            continue
        a = acc.setdefault(r["team"], {"g": 0, "att": 0.0, "car": 0.0, "sacs": 0.0, "int": 0.0})
        a["g"] += 1
        a["att"] += fnum(r["attempts"]); a["car"] += fnum(r["carries"])
        a["sacs"] += fnum(r["sacks_suffered"]); a["int"] += fnum(r["passing_interceptions"])
    off = {t: {k: a[k] / a["g"] for k in ("att", "car", "sacs", "int")} for t, a in acc.items() if a["g"]}
    for o in off.values():
        o["jeux"] = o["att"] + o["car"] + o["sacs"]
    for k in OFF_KEYS:
        for i, t in enumerate(sorted(off, key=lambda t: -off[t][k])):
            off[t][k + "Rang"] = i + 1
    avg = {k: sum(o[k] for o in off.values()) / len(off) for k in OFF_KEYS} if off else {}
    return off, avg


def idp_profiles(rows, week):
    """Par défensif (nom, équipe), moyennes par match avant `week` : plaqués solo, sacs, passes défendues, interceptions."""
    acc = {}
    for r in rows:
        if r.get("season_type") != "REG" or int(r["week"]) >= week:
            continue
        vals = {k: fnum(r[c]) for k, c in (("solo", "def_tackles_solo"), ("ast", "def_tackle_assists"), ("sacs", "def_sacks"),
                                             ("pd", "def_pass_defended"), ("int", "def_interceptions"))}
        if not any(vals.values()):
            continue
        a = acc.setdefault((pname(r["player_display_name"]), r["team"]), {"g": 0, "solo": 0.0, "sacs": 0.0, "pd": 0.0, "int": 0.0})
        a["g"] += 1
        for k in ("solo", "sacs", "pd", "int"):
            a[k] += vals[k]
    profs = {k: {"g": a["g"], **{x: a[x] / a["g"] for x in ("solo", "sacs", "pd", "int")}} for k, a in acc.items()}
    by_name = {}
    for (n, t), p in profs.items():
        if n not in by_name or p["g"] > by_name[n]["g"]:
            by_name[n] = p
    return profs, by_name


def idp_mult(grp, prof, o, avg):
    """IDP selon l'attaque adverse : un QB souvent sacké aide les rusheurs, beaucoup de jeux donne plus de plaqués,
    beaucoup de passes aide les DB. Le poids des sacs dépend du rythme de sacs du joueur. Borné à ±20 %."""
    if not o or not avg:
        return 1.0
    r = lambda k: o[k] / avg[k] if avg.get(k) else 1.0
    sacs = (prof or {}).get("sacs", 0.0)
    if grp == "DL":
        ws = min(0.6, 0.25 + sacs)
        raw = ws * r("sacs") + (1 - ws) * r("car")
    elif grp == "LB":
        ws = min(0.5, sacs)
        raw = ws * r("sacs") + (1 - ws) * r("jeux")
    else:
        raw = 0.5 * r("att") + 0.2 * r("int") + 0.3 * r("jeux")
    return 1.0 + max(-0.2, min(0.2, (raw - 1) * 0.6))


def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-labs/1.0"}), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == 2:
                raise
            time.sleep(2)


def get_once(url, timeout=10):
    """Source facultative : un seul essai, court (si le site est bloqué, on s'en passe vite)."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-labs/1.0"}), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def lg(t, **kw):
    q = "".join(f"&{k}={v}" for k, v in kw.items())
    return get(f"{HOST}/{YEAR}/export?L={LEAGUE}&JSON=1&TYPE={t}{q}")


def api(t, **kw):
    q = "".join(f"&{k}={v}" for k, v in kw.items())
    return get(f"https://api.myfantasyleague.com/{YEAR}/export?JSON=1&TYPE={t}{q}")


def as_list(x):
    return x if isinstance(x, list) else ([x] if x else [])


def nfl_opp(w):
    opp = {}
    for m in as_list(api("nflSchedule", W=w)["nflSchedule"].get("matchup")):
        a, b = m["team"]
        for t, o in ((a, b), (b, a)):
            opp[t["id"]] = {"opp": o["id"], "home": t.get("isHome") == "1", "kick": int(m.get("kickoff", 0)),
                            "passDef": int(o.get("passDefenseRank") or 16), "rushDef": int(o.get("rushDefenseRank") or 16)}
    return opp


def vegas_lines():
    """Cotes du tableau ESPN (DraftKings) : points prévus de chaque équipe (code MFL), stade couvert ou non, ville."""
    lines = {}
    for ev in get_once("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard", 20).get("events", []):
        c = ev["competitions"][0]
        teams = {x["homeAway"]: ESPN2MFL.get(x["team"]["abbreviation"], x["team"]["abbreviation"]) for x in c["competitors"]}
        venue = c.get("venue") or {}
        info = {"dome": bool(venue.get("indoor")), "ville": (venue.get("address") or {}).get("city", ""), "domicile": teams.get("home")}
        o = (c.get("odds") or [{}])[0]
        total, spread = o.get("overUnder"), o.get("spread")
        for side, t in teams.items():
            lines[t] = dict(info)
        if total is None or spread is None:
            continue
        # spread = écart du point de vue de l'équipe locale (négatif = locale favorite)
        s = -float(spread)
        imp = {"home": (float(total) + s) / 2, "away": (float(total) - s) / 2}
        for side, t in teams.items():
            other = "away" if side == "home" else "home"
            lines[t].update({"imp": round(imp[side], 1), "impAdv": round(imp[other], 1), "total": float(total)})
    return lines


def weather(lines, opp):
    """Vent (mi/h), pluie/neige (mm) et température (°C) à l'heure du coup d'envoi, stades extérieurs seulement (Open-Meteo)."""
    out, cache = {}, {}
    blocked = False
    for t, l in lines.items():
        home = l.get("domicile")
        o = opp.get(t)
        if l.get("dome") or not o or home not in STADES or STADES[home][0].lower() != str(l.get("ville", "")).lower():
            continue
        if home not in cache and blocked:
            continue
        if home not in cache:
            _, lat, lon = STADES[home]
            hour = time.strftime("%Y-%m-%dT%H:00", time.gmtime(o["kick"]))
            try:
                d = get_once(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,precipitation,temperature_2m"
                        f"&wind_speed_unit=mph&timezone=GMT&forecast_days=8")["hourly"]
                i = d["time"].index(hour)
                cache[home] = {"vent": round(d["wind_speed_10m"][i]), "precip": d["precipitation"][i], "temp": round(d["temperature_2m"][i])}
            except ValueError:
                cache[home] = None  # heure du match hors des prévisions
            except Exception as e:
                print("météo indisponible :", e)
                cache[home], blocked = None, True
        if cache[home]:
            out[t] = cache[home]
    return out


def usage(snap_rows, player_rows, week):
    """Par joueur (nom, équipe nflverse) : % des jeux joués chaque semaine, part des cibles et courses des 3 derniers matchs."""
    snaps, use = {}, {}
    for r in snap_rows:
        if r.get("game_type") != "REG" or int(r["week"]) >= week:
            continue
        pct = max(fnum(r["offense_pct"]), fnum(r["defense_pct"]))
        if pct > 0:
            snaps.setdefault((pname(r["player"]), r["team"]), {})[int(r["week"])] = round(pct * 100)
    for r in player_rows:
        if r.get("season_type") != "REG" or int(r["week"]) >= week:
            continue
        use.setdefault((pname(r["player_display_name"]), r["team"]), {})[int(r["week"])] = (fnum(r["target_share"]), fnum(r["carries"]))
    return snaps, use


def sleeper_trending():
    """Joueurs les plus ajoutés sur Sleeper dans les dernières 24 h : {nom normalisé: nombre d'ajouts}."""
    try:
        top = get_once("https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=24&limit=200")
        allp = get_once("https://api.sleeper.app/v1/players/nfl", 60)
    except Exception as e:
        print("Sleeper indisponible :", e)
        return {}
    return {pname(allp[x["player_id"]].get("full_name", "")): x["count"] for x in top if x["player_id"] in allp}


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else default
    except (OSError, ValueError):
        return default


def main(out, prev_suivi=None, prev_conseils=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    suivi = load(prev_suivi, {}) or {}
    conseils = load(prev_conseils, {}) or {}
    now_s = int(time.time())

    league = lg("league")["league"]
    names = {f["id"]: f["name"] for f in league["franchises"]["franchise"]}
    abbrev = {f["id"]: f.get("abbrev", "") for f in league["franchises"]["franchise"]}
    # Positions propres à la ligue (ex. plusieurs DE y sont classés LB)
    players = {p["id"]: p for p in lg("players")["players"]["player"]}
    byes = {t["id"]: int(t["bye_week"]) for t in as_list(api("nflByeWeeks")["nflByeWeeks"]["team"])}
    inj = {i["id"]: i for i in as_list(api("injuries")["injuries"].get("injury"))}

    # Semaine courante = première semaine du calendrier H2H sans résultat
    sched = lg("schedule")["schedule"]["weeklySchedule"]
    week = next((int(w["week"]) for w in sched
                 if any(f.get("score") in (None, "") for m in as_list(w.get("matchup")) for f in m["franchise"])),
                int(league.get("endWeek", 18)))
    done = list(range(1, week))

    # Points par semaine, dans le pointage de la ligue
    pts = {}
    for w in done:
        for s in as_list(lg("playerScores", W=w)["playerScores"].get("playerScore")):
            if s.get("id") and s.get("score") not in (None, ""):
                pts.setdefault(s["id"], {})[w] = float(s["score"])

    # Saisons passées, même pointage : moyenne par match (la plus récente saison où le joueur a joué)
    prior_avg = {}
    for y in PRIOR_YEARS:
        try:
            rows = as_list(get(f"{HOST}/{y}/export?L={LEAGUE}&JSON=1&TYPE=playerScores&W=AVG")["playerScores"].get("playerScore"))
        except Exception:
            continue
        for s in rows:
            if s.get("id") and s.get("score") not in (None, ""):
                prior_avg.setdefault(s["id"], {})[y] = float(s["score"])
    prior = lambda pid: next((prior_avg[pid][y] for y in PRIOR_YEARS if y in prior_avg.get(pid, {})), None)

    # nflverse : style des attaques (pour les défensifs) et rythme de sacs/plaqués de chaque défensif
    try:
        team_rows = get_csv(f"{NFLVERSE}/stats_team/stats_team_week_{YEAR}.csv")
        player_rows = get_csv(f"{NFLVERSE}/stats_player/stats_player_week_{YEAR}.csv")
    except Exception as e:
        print("nflverse indisponible :", e)
        team_rows, player_rows = [], []
    try:
        snap_rows = get_csv(f"{NFLVERSE}/snap_counts/snap_counts_{YEAR}.csv")
    except Exception as e:
        print("temps de jeu indisponible :", e)
        snap_rows = []
    nv = lambda t: CODES.get(t, t)
    snaps, use = usage(snap_rows, player_rows, week)
    pkey = lambda p: (pname(" ".join(reversed(p.get("name", "").split(", ", 1)))), nv(p.get("team", "")))

    def prof_of(pid, profs):
        p = players.get(pid, {})
        n = pname(" ".join(reversed(p.get("name", "").split(", ", 1))))
        return profs[0].get((n, nv(p.get("team", "")))) or profs[1].get(n)

    # Matchs NFL de la semaine : adversaire et classements défensifs
    opp = nfl_opp(week)
    off_now, off_avg = team_offense(team_rows, week)
    profs_now = idp_profiles(player_rows, week)
    rosters = {f["id"]: f for f in as_list(lg("rosters")["rosters"]["franchise"])}
    try:
        lines = vegas_lines()
    except Exception as e:
        print("cotes ESPN indisponibles :", e)
        lines = {}
    meteo = weather(lines, opp)
    trending = sleeper_trending()
    # Semaines à venir jusqu'à la fin de la saison NFL : adversaires (calendrier, valeur d'échange, semaines de congé)
    last_reg = int(league.get("lastRegularSeasonWeek", 14))
    fut_weeks = list(range(week, 18))
    fut_opp = {w: (opp if w == week else nfl_opp(w)) for w in fut_weeks}
    # Date de naissance (keepers) des joueurs sur un roster
    rostered = [r["id"] for f in rosters.values() for r in as_list(f.get("player"))]
    born = {}
    for i in range(0, len(rostered), 150):
        for p in as_list(api("players", DETAILS=1, PLAYERS=",".join(rostered[i:i + 150]))["players"].get("player")):
            if p.get("birthdate"):
                born[p["id"]] = int(p["birthdate"])

    def history(pid, upto):
        team = players.get(pid, {}).get("team", "")
        wk = pts.get(pid, {})
        return [wk[w] for w in range(1, upto) if w in wk and byes.get(team) != w]

    # Rétro-test : pour chaque semaine passée, chaque méthode projette avec les seules semaines d'avant,
    # puis on compare aux vrais points. On prend tous les joueurs qui valaient un partant AVANT la semaine
    # (projection d'au moins 8), pas seulement ceux sur un roster aujourd'hui : ceux-là ont souvent été
    # ramassés après de bonnes semaines, ce qui ferait croire que les projections sont trop basses.
    # Chaque méthode est aussi essayée « + saison passée » ; le défensif tient compte du style de l'attaque adverse
    bt = {}
    for w in range(BACKTEST_FROM, week):
        ow = nfl_opp(w)
        off_w, avg_w = team_offense(team_rows, w)
        profs_w = idp_profiles(player_rows, w)
        for pid in pts:
            actual = pts[pid].get(w)
            past = history(pid, w)
            p = players.get(pid, {})
            grp = GROUP.get(p.get("position"), None)
            o = ow.get(p.get("team", ""))
            if actual is None or len(past) < 2 or not grp or not o or base_proj(past, "mixte") < 8:
                continue
            mult = opp_mult(grp, o)
            if SIDE.get(grp) == "D":
                mult = idp_mult(grp, prof_of(pid, profs_w), off_w.get(nv(o["opp"])), avg_w)
            for m in METHODS:
                for key, pr in ((m, base_proj(past, m)), (m + "+passe", with_prior(past, m, prior(pid)))):
                    e = bt.setdefault(grp, {}).setdefault(key, {"n": 0, "abs": 0.0, "proj": 0.0, "reel": 0.0})
                    pr *= mult
                    e["n"] += 1; e["abs"] += abs(actual - pr); e["proj"] += pr; e["reel"] += actual
    modele = {}
    for g in START_MAX:
        res = {m: {"mae": round(e["abs"] / e["n"], 1), "n": e["n"], "ratio": round(e["reel"] / e["proj"], 3) if e["proj"] else 1.0}
               for m, e in bt.get(g, {}).items() if e["n"]}
        n = res.get("mixte", {}).get("n", 0)
        best = min(res, key=lambda m: res[m]["mae"]) if n >= MIN_BACKTEST else "mixte"
        # Correction du biais (projette trop haut ou trop bas), bornée à ±15 %
        ratio = min(1.15, max(0.85, res[best]["ratio"])) if n >= MIN_BACKTEST else 1.0
        desc = METHODS[best.split("+")[0]] + (", tirée vers la moyenne de la saison passée" if best.endswith("+passe") else "")
        modele[g] = {"methode": best, "description": desc, "correction": round(ratio, 3), "n": n,
                     "erreur": res.get(best, {}).get("mae"), "erreurMixte": res.get("mixte", {}).get("mae"), "parMethode": res}

    def player(pid):
        p = players.get(pid, {})
        pos = p.get("position", "?")
        grp = GROUP.get(pos, pos)
        team = p.get("team", "")
        wk = pts.get(pid, {})
        games = [wk[w] for w in done if w in wk and byes.get(team) != w]
        last = games[-3:]
        avg = sum(games) / len(games) if games else 0.0
        med = median(games)
        # Méthode retenue par le rétro-test pour ce poste, corrigée de son biais
        mod = modele.get(grp, {"methode": "mixte", "correction": 1.0})
        meth = mod["methode"].split("+")[0]
        base = (with_prior(games, meth, prior(pid)) if mod["methode"].endswith("+passe") else base_proj(games, meth)) * mod["correction"]
        o = opp.get(team)
        i = inj.get(pid)
        status = i["status"] if i else ""
        # Adversaire : défense adverse pour l'attaque, style de l'attaque adverse pour les défensifs
        notes = []
        if o and grp in ("QB", "RB", "WR", "TE"):
            rk = o["rushDef"] if grp == "RB" else o["passDef"]
            notes.append(f"Défense de {o['opp']} contre {'la course' if grp == 'RB' else 'la passe'} : {rk}e sur 32 (32e = celle qui donne le plus)")
        mo = opp_mult(grp, o)
        if o and SIDE.get(grp) == "D":
            prof = prof_of(pid, profs_now)
            oo = off_now.get(nv(o["opp"]))
            mo = idp_mult(grp, prof, oo, off_avg)
            fr = lambda x: f"{x:.1f}".replace(".", ",")
            if oo:
                if grp in ("DL", "LB"):
                    notes.append(f"{o['opp']} accorde {fr(oo['sacs'])} sacs par match ({oo['sacsRang']}e sur 32 pour en accorder)")
                notes.append(f"{o['opp']} joue {round(oo['jeux'])} jeux par match ({oo['jeuxRang']}e)" if grp != "DB"
                             else f"{o['opp']} lance {round(oo['att'])} passes par match ({oo['attRang']}e), {fr(oo['int'])} interception par match")
            if prof:
                notes.append(f"Lui : {fr(prof['sacs'])} sac, {fr(prof['solo'])} plaqués solo, {fr(prof['pd'])} passe défendue par match")
        # Cotes Vegas (points prévus de l'équipe) et vent au stade
        l, wx = lines.get(team) or {}, meteo.get(team)
        mv = 1.0
        if o and l.get("imp") and grp in VEGAS_EXP:
            mv = (l["imp"] / IMP_MOY) ** VEGAS_EXP[grp]
            notes.append(f"Vegas : {team} devrait marquer {fr1(l['imp'])} points (moyenne {fr1(IMP_MOY)}), effet {pct(mv)}")
        if o and wx and wx["vent"] >= WIND_MIN and grp in WIND_MULT:
            mv *= WIND_MULT[grp]
            notes.append(f"Vent de {wx['vent']} mi/h prévu au match : {pct(WIND_MULT[grp])} pour un {grp}")
        mult = mo * mv * INJ_FACTOR.get(status, 1.0)
        # Écart-type de ses semaines : sert aux chances de gagner et au plafond / plancher
        sd = (sum((g - avg) ** 2 for g in games) / (len(games) - 1)) ** 0.5 if len(games) >= 3 else 0.5 * base
        # Temps de jeu (% des jeux) et, en attaque, part des cibles et courses
        k = pkey(p)
        sn = snaps.get(k, {})
        weeks_sn = sorted(sn)[-4:]
        tend = None
        if len(weeks_sn) >= 3:
            a2, b2 = weeks_sn[-2:], weeks_sn[:-2]
            dlt = sum(sn[w] for w in a2) / len(a2) - sum(sn[w] for w in b2) / len(b2)
            tend = "hausse" if dlt >= 10 else "baisse" if dlt <= -10 else "stable"
        us = use.get(k, {})
        u3 = [us[w] for w in sorted(us)[-3:]]
        # Calendrier : adversaire et difficulté (1 facile, 5 difficile) de chaque semaine à venir, projection de la semaine
        cal, fut = [], []
        for w in fut_weeks:
            ow = fut_opp[w].get(team)
            if not ow:
                cal.append({"w": w, "adv": "BYE", "diff": None}); fut.append(0.0)
                continue
            if SIDE.get(grp) == "D":
                oo = off_now.get(nv(ow["opp"]))
                rang = (oo["jeuxRang"] if grp == "LB" else oo["attRang"] if grp == "DB" else (oo["sacsRang"] + oo["carRang"]) / 2) if oo else 16.5
                dif = 1 + round((rang - 1) / 31 * 4)
                m_w = idp_mult(grp, prof_of(pid, profs_now), oo, off_avg)
            elif grp in ("QB", "RB", "WR", "TE"):
                rank = ow["rushDef"] if grp == "RB" else ow["passDef"]
                dif = 5 - round((rank - 1) / 31 * 4)
                m_w = opp_mult(grp, ow)
            else:
                dif, m_w = 3, 1.0
            cal.append({"w": w, "adv": ("vs " if ow["home"] else "@ ") + ow["opp"], "diff": dif})
            fut.append(base * m_w)
        if fut:
            fut[0] = base * mult  # cette semaine : avec blessure, Vegas et météo
        if status == "IR":
            fut = [0.0 if i < 4 else x for i, x in enumerate(fut)]
        b = born.get(pid)
        age = round((time.mktime((YEAR, 9, 1, 0, 0, 0, 0, 0, -1)) - b) / 31557600, 1) if b else None
        n = p.get("name", pid)
        if ", " in n:
            last_n, first_n = n.split(", ", 1)
            n = f"{first_n} {last_n}"
        return {
            "id": pid, "nom": n, "pos": pos, "grp": grp, "nfl": team,
            "bye": byes.get(team), "pts": [wk.get(w) for w in done],
            "moy": round(avg, 1), "der3": round(sum(last) / len(last), 1) if last else 0.0,
            "mj": len(games), "med": round(med, 1), "zeros": sum(1 for g in games if g == 0),
            "max": max(games) if games else 0, "proj": round(base * mult, 1),
            "adv": (("vs " if o["home"] else "@ ") + o["opp"]) if o else "BYE",
            "rangDef": (o["rushDef"] if grp == "RB" else o["passDef"]) if o and grp in ("QB", "RB", "WR", "TE") else None,
            "effetAdv": round((mo - 1) * 100) if o else None, "notesAdv": notes,
            "saisonsPassees": {str(y): prior_avg[pid][y] for y in PRIOR_YEARS if y in prior_avg.get(pid, {})},
            "kick": o["kick"] if o else None,
            "bless": status, "blessInfo": (i.get("details") or "") if i else "",
            "retour": (i.get("exp_return") or "") if i else "",
            "sd": round(sd, 1), "plafond": round(base * mult + 1.28 * sd, 1) if base * mult else 0.0,
            "plancher": round(max(0.0, base * mult - 1.28 * sd), 1) if base * mult else 0.0,
            "vegas": {"imp": l.get("imp"), "impAdv": l.get("impAdv")} if l.get("imp") else None,
            "meteo": ({"dome": True} if l.get("dome") else wx) if o else None,
            "snaps": [{"w": w, "pct": sn[w]} for w in weeks_sn], "tendance": tend,
            "cibles": round(sum(x[0] for x in u3) / len(u3) * 100) if u3 and grp in ("RB", "WR", "TE") else None,
            "courses": round(sum(x[1] for x in u3) / len(u3), 1) if u3 and grp in ("RB", "QB") else None,
            "cal": cal, "_fut": fut, "_base": base, "age": age,
            "sleeper": trending.get(pname(n)) if grp in START_MAX else None,
        }

    def best_lineup(roster):
        pool = sorted([p for p in roster if p["grp"] in START_MAX], key=lambda p: -p["proj"])
        chosen, count = [], {}
        for g, n in START_MIN.items():
            for p in [p for p in pool if p["grp"] == g][:n]:
                chosen.append(p); count[g] = count.get(g, 0) + 1
        side = lambda c: sum(1 for x in chosen if SIDE[x["grp"]] == c)
        for p in pool:
            if len(chosen) >= N_START:
                break
            if (p not in chosen and count.get(p["grp"], 0) < START_MAX[p["grp"]]
                    and side(SIDE[p["grp"]]) < N_SIDE[SIDE[p["grp"]]]):
                chosen.append(p); count[p["grp"]] = count.get(p["grp"], 0) + 1
        return {p["id"] for p in chosen}

    # Alignements réellement soumis dans MFL pour la semaine
    lineups = {}
    for m in as_list(lg("weeklyResults", W=week)["weeklyResults"].get("matchup")):
        for f in as_list(m.get("franchise")):
            lineups[f["id"]] = {x["id"] for x in as_list(f.get("player")) if x.get("status") == "starter"}
    teams = {}
    for fid, f in rosters.items():
        roster = []
        for r in as_list(f.get("player")):
            p = player(r["id"])
            p["ir"] = r.get("status") == "INJURED_RESERVE"
            roster.append(p)
        starters = best_lineup([p for p in roster if not p["ir"]])
        for p in roster:
            p["start"] = p["id"] in starters
            p["aligne"] = p["id"] in lineups.get(fid, set())
        teams[fid] = roster

    # Points projetés de l'alignement idéal + force par groupe (somme des partants idéaux)
    def strength(roster):
        # Alignement idéal selon la moyenne de saison (ignore le bye de cette semaine)
        healthy = [dict(p, proj=p["moy"]) for p in roster if not p["ir"]]
        best = best_lineup(healthy)
        s = {}
        for p in roster:
            if p["id"] in best:
                s[p["grp"]] = round(s.get(p["grp"], 0) + p["moy"], 1)
        return s

    standings = {s["id"]: s for s in as_list(lg("standings")["leagueStandings"]["franchise"])}

    # Matchup de la semaine
    match = None
    for m in as_list(next(w for w in sched if int(w["week"]) == week).get("matchup")):
        ids = [x["id"] for x in m["franchise"]]
        if MINE in ids:
            other = ids[1] if ids[0] == MINE else ids[0]
            match = {"adv": other, "advNom": names.get(other, other),
                     "projMoi": round(sum(p["proj"] for p in teams[MINE] if p["start"]), 1),
                     "projAdv": round(sum(p["proj"] for p in teams.get(other, []) if p["start"]), 1)}

    # Joueurs libres : les meilleurs par groupe
    fa_ids = [p["id"] for p in as_list(lg("freeAgents")["freeAgents"]["leagueUnit"].get("player"))]
    fa = [player(i) for i in fa_ids if players.get(i, {}).get("position") in GROUP]
    fa = [p for p in fa if p["mj"] > 0 and p["bless"] not in ("IR", "Out", "Suspended")]
    waivers = {}
    for g in START_MAX:
        waivers[g] = sorted([p for p in fa if p["grp"] == g], key=lambda p: -p["proj"] if p["proj"] else -(p["med"] + p["moy"]) / 2)[:12]

    # Valeur d'échange : points au-dessus d'un joueur de remplacement (moyenne des 3 meilleurs joueurs libres du poste),
    # semaine par semaine jusqu'à la semaine 17, selon le calendrier. Keeper : même idée pour l'an prochain, selon l'âge.
    repl = {g: (sum(sorted((p["_base"] for p in fa if p["grp"] == g), reverse=True)[:3]) / 3) for g in START_MAX}
    # Keepers : l'an prochain, le repêchage donne accès à tous les joueurs non gardés. Le remplaçant = le joueur
    # au rang « dernier partant de la ligue » à ce poste (16 équipes x partants habituels), pas un joueur libre d'aujourd'hui.
    every = [p for r in teams.values() for p in r] + fa
    typ = {"QB": 1, "RB": 1.5, "WR": 2.5, "TE": 1.5, "PK": 1, "DL": 2, "LB": 2.5, "DB": 2.5}
    repl_k = {}
    for g in START_MAX:
        bases = sorted((p["_base"] for p in every if p["grp"] == g), reverse=True)
        repl_k[g] = bases[min(len(bases) - 1, int(len(names) * typ[g]))] if bases else 0.0
    # Coût d'un keeper : la ronde où il a été repêché (un joueur des vrais Ravens coûte 1 ronde plus tard).
    # Valeur typique d'un choix de chaque ronde = moyenne (base - remplaçant) des joueurs repêchés à cette ronde cette année.
    try:
        picks = as_list(lg("draftResults")["draftResults"]["draftUnit"].get("draftPick"))
    except Exception:
        picks = []
    drafted = {x["player"]: int(x["round"]) for x in picks if x.get("player", "----") != "----"}
    n_rounds = max([int(x["round"]) for x in picks] or [22])
    by_id = {p["id"]: p for p in every}
    rv = {}
    for pid, r in drafted.items():
        q = by_id.get(pid)
        if q and q["grp"] in START_MAX:
            rv.setdefault(r, []).append(q["_base"] - repl_k[q["grp"]])
    round_val = {}
    for r in range(1, n_rounds + 1):
        xs = [x for k in (r - 1, r, r + 1) for x in rv.get(k, [])]
        round_val[r] = sum(xs) / len(xs) if xs else 0.0
    weeks_po = [i for i, w in enumerate(fut_weeks) if last_reg < w <= 17]
    for p in every:
        rp = repl.get(p["grp"], 0.0)
        p["val"] = round(sum(max(0.0, x - rp) for x in p["_fut"]), 1)
        p["valSeries"] = round(sum(max(0.0, p["_fut"][i] - rp) for i in weeks_po), 1)
        r = drafted.get(p["id"])
        p["cout"] = (min(n_rounds, r + 1) if p["nfl"] == "BAL" else r) if r else None
        if p["grp"] in START_MAX and p["age"]:
            f = 1 - DECLINE[p["grp"]] * max(0.0, p["age"] + 1 - PEAK[p["grp"]])
            p["keeper"] = round(max(-9.9, p["_base"] * f - repl_k[p["grp"]]), 1)
        else:
            p["keeper"] = None
        # Surplus : ce qu'il vaut de plus qu'un joueur repêché normalement à la ronde qu'il coûte
        p["surplus"] = round(p["keeper"] - round_val.get(p["cout"], 0.0), 1) if p["keeper"] is not None and p["cout"] else None

    # Chances de gagner : chaque joueur varie selon l'écart-type de ses semaines ; loi normale sur la différence
    def win_prob(mine_ids, adv_ids, roster_m, roster_a):
        sm = [p for p in roster_m if p["id"] in mine_ids]
        sa = [p for p in roster_a if p["id"] in adv_ids]
        diff = sum(p["proj"] for p in sm) - sum(p["proj"] for p in sa)
        var = sum((p["sd"] if p["proj"] else 0) ** 2 for p in sm + sa) or 1.0
        return round(0.5 * (1 + math.erf(diff / math.sqrt(2 * var))), 3)

    if match:
        adv_r = teams.get(match["adv"], [])
        mine_r = teams[MINE]
        start_a = {p["id"] for p in adv_r if p["start"]}
        match["probConseil"] = win_prob({p["id"] for p in mine_r if p["start"]}, start_a, mine_r, adv_r)
        match["probActuel"] = win_prob({p["id"] for p in mine_r if p["aligne"]}, start_a, mine_r, adv_r)
        # Analyse de l'adversaire : ses partants probables, ses blessés, sa force par poste contre la mienne
        match["advPartants"] = [{k: p[k] for k in ("nom", "pos", "grp", "nfl", "proj", "adv", "bless", "aligne")}
                                for p in sorted(adv_r, key=lambda p: -p["proj"]) if p["start"]]
        match["advBlesses"] = [{k: p[k] for k in ("nom", "pos", "nfl", "bless", "moy")} for p in adv_r
                               if p["bless"] and not p["ir"] and p["moy"] >= 8]
        match["parPoste"] = {g: {"moi": round(sum(p["proj"] for p in mine_r if p["start"] and p["grp"] == g), 1),
                                 "adv": round(sum(p["proj"] for p in adv_r if p["start"] and p["grp"] == g), 1)} for g in START_MAX}
        pc = match["probConseil"]
        match["strategie"] = ("negligé" if pc < 0.4 else "favori" if pc > 0.65 else "serré")

    # Fin de saison simulée : chaque équipe marque selon sa moyenne et l'écart-type de la ligue
    scores = {}
    for wsch in sched:
        if int(wsch["week"]) >= week:
            continue
        for m in as_list(wsch.get("matchup")):
            for f in m["franchise"]:
                if f.get("score") not in (None, ""):
                    scores.setdefault(f["id"], []).append(float(f["score"]))
    mu = {f: sum(v) / len(v) for f, v in scores.items() if v}
    resid = [x - mu[f] for f, v in scores.items() for x in v]
    sd_l = (sum(r * r for r in resid) / max(1, len(resid) - 1)) ** 0.5 if resid else 40.0
    proj_now = {f: sum(p["proj"] for p in r if p["start"]) for f, r in teams.items()}
    rest = []
    for wsch in sched:
        w = int(wsch["week"])
        if week <= w <= last_reg:
            for m in as_list(wsch.get("matchup")):
                ids = [x["id"] for x in m["franchise"]]
                if len(ids) == 2:
                    rest.append((w, ids[0], ids[1]))
    wins0 = {f: int(standings.get(f, {}).get("h2hw") or 0) for f in names}
    pf0 = {f: float(standings.get(f, {}).get("pf") or 0) for f in names}
    rng = random.Random(week)
    N = 4000
    rank_ct = {r: 0 for r in range(1, len(names) + 1)}
    wins_tot = 0
    for _ in range(N):
        wn, pf = dict(wins0), dict(pf0)
        for w, a, b in rest:
            ma = proj_now.get(a, 0) if w == week else mu.get(a, 0)
            mb = proj_now.get(b, 0) if w == week else mu.get(b, 0)
            sa, sb = rng.gauss(ma, sd_l), rng.gauss(mb, sd_l)
            pf[a] += sa; pf[b] += sb
            wn[a if sa > sb else b] += 1
        order = sorted(names, key=lambda f: (-wn[f], -pf[f]))
        rank_ct[order.index(MINE) + 1] += 1
        wins_tot += wn[MINE]
    restants = [{"w": w, "adv": (b if a == MINE else a), "advNom": names.get(b if a == MINE else a),
                 "prob": (match["probConseil"] if w == week and match else
                          round(0.5 * (1 + math.erf((mu.get(MINE, 0) - mu.get(b if a == MINE else a, 0)) / (2 * sd_l))), 3))}
                for w, a, b in rest if MINE in (a, b)]
    # QFF Bowl : l'équipe avec le plus de points au total des semaines 15, 16 et 17 dans chaque conférence
    # (bris d'égalité : victoires de conférence). Projection de chaque équipe = son meilleur alignement chaque semaine.
    div_conf = {d["id"]: d.get("conference") for d in as_list((league.get("divisions") or {}).get("division"))}
    conf_names = {c["id"]: c["name"] for c in as_list((league.get("conferences") or {}).get("conference"))}
    conf_of = {f["id"]: div_conf.get(f.get("division")) for f in league["franchises"]["franchise"]}
    my_conf = conf_of.get(MINE)
    po_proj = {}
    for fid, r in teams.items():
        if conf_of.get(fid) != my_conf:
            continue
        tot = 0.0
        for i in weeks_po:
            wk = [dict(p, proj=p["_fut"][i]) for p in r if not p["ir"]]
            ids = best_lineup(wk)
            tot += sum(p["proj"] for p in wk if p["id"] in ids)
        po_proj[fid] = tot
    bowl = None
    if po_proj and weeks_po:
        sd3 = sd_l * math.sqrt(len(weeks_po))
        win_ct = {f: 0 for f in po_proj}
        for _ in range(N):
            sc = {f: rng.gauss(m, sd3) for f, m in po_proj.items()}
            win_ct[max(sc, key=sc.get)] += 1
        bowl = {"conference": conf_names.get(my_conf, my_conf), "semaines": [fut_weeks[i] for i in weeks_po],
                "prob": round(win_ct[MINE] / N, 3), "victoiresConf": standings.get(MINE, {}).get("confwlt", ""),
                "equipes": sorted([{"id": f, "nom": names.get(f, f), "proj": round(m, 1), "prob": round(win_ct[f] / N, 3)}
                                   for f, m in po_proj.items()], key=lambda x: -x["proj"])}
    projSaison = {"bowl": bowl, "victoiresMoy": round(wins_tot / N, 1), "victoiresAct": wins0.get(MINE, 0), "matchs": last_reg,
                  "rangs": {str(r): round(c / N, 3) for r, c in rank_ct.items()}, "restants": restants,
                  "moyEquipes": {f: round(v, 1) for f, v in mu.items()}, "ecartTypeLigue": round(sd_l, 1)}

    def rec(fid):
        s = standings.get(fid, {})
        return {"id": fid, "nom": names.get(fid, fid), "abbr": abbrev.get(fid, ""),
                "fiche": s.get("h2hwlt", ""), "pf": float(s.get("pf") or 0), "pa": float(s.get("pa") or 0),
                "moyPF": float(s.get("avgpf") or 0), "serie": s.get("strk", "")}

    classement = sorted((rec(f) for f in names), key=lambda r: (-int((r["fiche"] or "0-0-0").split("-")[0]), -r["pf"]))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    meta = {"saison": YEAR, "semaine": week, "faites": done, "moi": MINE, "monNom": names[MINE],
            "ligue": league.get("name", ""), "lien": LEAGUE_URL, "equipes": len(names),
            "finSaisonReg": int(league.get("lastRegularSeasonWeek", 14)), "match": match,
            "classement": classement, "majAt": now, "projSaison": projSaison,
            "alignement": "7 en attaque (QB 1, RB 1-2, WR 1-3, TE 1-2, PK 1) et 7 en défense (DL DT+DE 1-3, LB 1-3, DB CB+S 1-3) = 14 partants. On ne peut jamais remplacer un attaquant par un défensif dans l'alignement.",
            "pointage": "Paliers de verges et de TD (pas de point par réception). IDP : 5 pts par plaqué solo, sacs/INT/passes défendues par paliers."}
    mine = teams[MINE]
    ins = sorted([p for p in mine if p["start"] and not p["aligne"]], key=lambda p: -p["proj"])
    outs = sorted([p for p in mine if p["aligne"] and not p["start"]], key=lambda p: p["proj"])
    # Jumeler d'abord poste pour poste (QB contre QB), puis le reste
    pairs = []
    for o in list(outs):
        i = next((i for i in ins if i["grp"] == o["grp"]), None)
        if i:
            pairs.append((o, i)); outs.remove(o); ins.remove(i)
    pairs += list(zip(outs, ins))
    changements = [{"sort": o["nom"], "sortPos": o["pos"], "sortProj": o["proj"], "entre": i["nom"], "entrePos": i["pos"], "entreProj": i["proj"]}
                   for o, i in pairs]
    equipe = {"semaine": week, "joueurs": mine, "changements": changements,
              "projActuel": round(sum(p["proj"] for p in mine if p["aligne"]), 1),
              "projConseil": round(sum(p["proj"] for p in mine if p["start"]), 1), "force": strength(teams[MINE]), "majAt": now,
              "forceMoyLigue": {g: round(sum(strength(r).get(g, 0) for f, r in teams.items() if f != MINE) / (len(teams) - 1), 1) for g in START_MAX}}
    # Semaines de congé à venir : mes joueurs absents et les postes où il manquerait un partant
    conges = []
    core = sorted([p for p in mine if not p["ir"]], key=lambda p: -p["_base"])[:N_START]
    for i, w in enumerate(fut_weeks):
        if w > last_reg:
            break
        off = [p for p in core if p["cal"][i]["adv"] == "BYE"]
        if not off:
            continue
        dispo = lambda g: sum(1 for p in mine if not p["ir"] and p["grp"] == g and p["cal"][i]["adv"] != "BYE"
                              and not (w == week and p["bless"] in ("Out", "Suspended")))
        trous = [{"grp": g, "dispo": dispo(g), "besoin": START_MIN[g]} for g in START_MAX if dispo(g) < START_MIN[g]]
        conges.append({"w": w, "absents": [{"nom": p["nom"], "pos": p["pos"]} for p in off], "trous": trous})
    equipe["conges"] = conges
    equipe["semainesCal"] = fut_weeks
    equipe["remplacement"] = {g: round(v, 1) for g, v in repl.items()}
    equipe["remplacementKeeper"] = {g: round(v, 1) for g, v in repl_k.items()}
    for p in every:
        p.pop("_fut", None); p.pop("_base", None)
    keep = ("id", "nom", "pos", "grp", "nfl", "moy", "der3", "proj", "start", "aligne", "bless", "bye", "ir", "sd", "val", "valSeries", "keeper", "age")
    ligue = {"semaine": week, "majAt": now, "equipes": [
        {**rec(fid), "force": strength(r), "joueurs": [{k: p[k] for k in keep} for p in r]}
        for fid, r in teams.items() if fid != MINE]}
    wv = {"semaine": week, "majAt": now, "parGroupe": waivers}

    # Suivi : figer les conseils de la semaine, joueur par joueur, au début de son match
    def full_name(pid):
        n = players.get(pid, {}).get("name", pid)
        return " ".join(reversed(n.split(", ", 1))) if ", " in n else n
    by_name = {full_name(pid).lower(): pid for pid in players}
    semaines = suivi.get("semaines") or {}
    snap = semaines.get(str(week)) or {"semaine": week, "joueurs": {}}
    on_team = {p["id"] for p in mine}
    for pid in list(snap["joueurs"]):
        if pid not in on_team and (snap["joueurs"][pid].get("kick") or 0) > now_s:
            del snap["joueurs"][pid]  # lâché avant son match
    for p in mine:
        if p["ir"] or p["kick"] is None:
            continue
        if p["kick"] > now_s or p["id"] not in snap["joueurs"]:
            snap["joueurs"][p["id"]] = {"nom": p["nom"], "grp": p["grp"], "proj": p["proj"], "aligne": p["aligne"],
                                         "start": p["start"], "kick": p["kick"]}
    if conseils.get("semaine") == week:
        snap["waivers"] = [{"nom": w.get("nom"), "pos": w.get("pos"), "pid": by_name.get(str(w.get("nom", "")).lower()),
                            "remplace": next((by_name[n.lower()] for n in (x["nom"] for x in mine) if n.lower() in str(w.get("lacher", "")).lower()), None)}
                           for w in conseils.get("waivers") or []]
    snap["majAt"] = now
    semaines[str(week)] = snap

    # Bilan des semaines terminées (tous les matchs NFL commencés depuis plus de 5 h)
    for key, s in semaines.items():
        w = int(key)
        if w >= week or s.get("resultat"):
            continue
        ow = nfl_opp(w)
        if not ow or max(o["kick"] for o in ow.values()) + 5 * 3600 > now_s:
            continue
        act = lambda pid: pts.get(pid, {}).get(w) or 0.0
        js = s["joueurs"]
        reel = sum(act(pid) for pid, j in js.items() if j["aligne"])
        conseil = sum(act(pid) for pid, j in js.items() if j["start"])
        # Meilleur alignement possible avec les vrais points (le maximum atteignable)
        maxi_ids = best_lineup([{"id": pid, "grp": j["grp"], "proj": act(pid)} for pid, j in js.items()])
        ins = [pid for pid, j in js.items() if j["start"] and not j["aligne"]]
        outs = [pid for pid, j in js.items() if j["aligne"] and not j["start"]]
        chg = []
        for o in list(outs):
            i = next((i for i in ins if js[i]["grp"] == js[o]["grp"]), None)
            if i:
                chg.append((o, i)); outs.remove(o); ins.remove(i)
        chg += list(zip(outs, ins))
        changements = [{"sort": js[o]["nom"], "sortPts": act(o), "entre": js[i]["nom"], "entrePts": act(i),
                        "verdict": "bon" if act(i) > act(o) else "egal" if act(i) == act(o) else "mauvais"} for o, i in chg]
        proj_err = {}
        for pid, j in js.items():
            if j["proj"] <= 0 and act(pid) == 0:
                continue
            e = proj_err.setdefault(j["grp"], {"n": 0, "proj": 0.0, "reel": 0.0, "abs": 0.0})
            e["n"] += 1; e["proj"] += j["proj"]; e["reel"] += act(pid); e["abs"] += abs(act(pid) - j["proj"])
        wv_res = [{"nom": x["nom"], "pos": x.get("pos"), "pts": act(x["pid"]) if x.get("pid") else None,
                   "remplace": js.get(x.get("remplace"), {}).get("nom"), "remplacePts": act(x["remplace"]) if x.get("remplace") else None,
                   "ramasse": x.get("pid") in on_team}
                  for x in s.get("waivers") or []]
        s["resultat"] = {"reel": round(reel, 1), "conseil": round(conseil, 1), "maximum": round(sum(act(pid) for pid in maxi_ids), 1),
                         "suivi": not chg, "changements": changements, "waivers": wv_res,
                         "projections": {g: {"n": e["n"], "proj": round(e["proj"], 1), "reel": round(e["reel"], 1), "erreur": round(e["abs"] / e["n"], 1)} for g, e in proj_err.items()},
                         "evalueAt": now}

    done_s = [s["resultat"] for s in semaines.values() if s.get("resultat")]
    all_chg = [c for r in done_s for c in r["changements"]]
    all_wv = [x for r in done_s for x in r["waivers"] if x["pts"] is not None]
    bilan = {"semaines": len(done_s),
             "changementsBons": sum(1 for c in all_chg if c["verdict"] == "bon"),
             "changementsMauvais": sum(1 for c in all_chg if c["verdict"] == "mauvais"),
             "changementsTotal": len(all_chg),
             "ptsGagnesSiSuivi": round(sum(r["conseil"] - r["reel"] for r in done_s), 1),
             "ptsLaissesSurLeBanc": round(sum(r["maximum"] - r["conseil"] for r in done_s), 1),
             "waiversBons": sum(1 for x in all_wv if x["remplacePts"] is None or x["pts"] > x["remplacePts"]),
             "waiversTotal": len(all_wv)}
    # Alertes téléphone : un joueur de mon équipe devient absent, douteux, questionnable ou suspendu
    # (premier passage : on note les statuts sans alerter)
    prev_st = suivi.get("statuts")
    statuts = {p["id"]: p["bless"] for p in mine if p["bless"]}
    alertes = []
    if prev_st is not None:
        for p in mine:
            s = p["bless"]
            if p["ir"] or s not in ALERT or prev_st.get(p["id"]) == s:
                continue
            role = "partant" if p["aligne"] else "au banc"
            alertes.append({"id": p["id"], "statut": s, "role": role,
                            "texte": f"{p['nom']} ({p['pos']}, {p['nfl']}, {role}) est maintenant {ALERT[s]}"
                                     + (f" : {p['blessInfo']}" if p["blessInfo"] else "") + "."})
    (out / "alertes.json").write_text(json.dumps(alertes, ensure_ascii=False), encoding="utf-8")
    print("alertes", len(alertes))
    suivi_doc = {"majAt": now, "semaine": week, "modele": modele, "bilan": bilan, "semaines": semaines,
                 "lecons": suivi.get("lecons") or [], "statuts": statuts}

    for name, doc in (("meta", meta), ("equipe", equipe), ("ligue", ligue), ("waivers", wv), ("suivi", suivi_doc)):
        (out / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(name, (out / f"{name}.json").stat().st_size, "octets")


if __name__ == "__main__":
    main(*sys.argv[1:4])
