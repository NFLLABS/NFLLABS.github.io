"""Propositions de paris par règles (sans IA) pour le site NFL LABS.

usage: python -I propositions.py <joueurs_dir> <meta.json> <live.json> <props_dk.json> <miseojeu.json|-> <out.json>

bet365 : paliers « X+ » (verges par 10, Plus seulement) choisis sous la ligne DraftKings.
Chance = moitié historique du joueur (8 derniers matchs), moitié marché (ligne DK ≈ 50 %), ajustée selon la
défense adverse. La cote bet365 est estimée comme dans le module PARIS (marge de 7 %).
Mise-O-Jeu : vraies cotes ; chance = moitié historique, moitié cote sans marge, même ajustement de défense.
"""
import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dk_props import COL as DK_COL, norm_name  # noqa: E402

YARDS = {"pass_yds": 0.25, "rush_yds": 0.5, "rec_yds": 0.6, "rush_rec_yds": 0.45}
MARCHE = {"pass_yds": "verges par la passe", "rush_yds": "verges au sol", "rec_yds": "verges sur réception",
          "rush_rec_yds": "verges au sol + réception", "receptions": "réceptions", "pass_cmp": "passes complétées",
          "carries": "courses", "pass_td": "passes de touché", "td": "touché marqué"}
DEF_KEY = {"pass_yds": "QB_pass", "pass_cmp": "QB_pass", "pass_td": "QB_pass", "rush_yds": "RB_rush", "carries": "RB_rush",
           "rush_rec_yds": "RB_rush"}
MOJ_COL = {"pass_yds": lambda g: g[4], "rush_yds": lambda g: g[8], "rec_yds": lambda g: g[12], "td": lambda g: g[9] + g[13]}
SKIP = {"Out", "Doubtful", "Suspension", "Injured Reserve"}
FR_INJ = {"Questionable": "questionnable"}


def load(p):
    if not p or p == "-" or not Path(p).is_file():
        return None
    d = json.loads(Path(p).read_text(encoding="utf-8"))
    return d.get("data", d) if isinstance(d.get("data"), dict) else d


def ncdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def palier_de(mkey, ligne):
    return max(10, math.floor(ligne / 10) * 10) if mkey in YARDS else max(1, math.ceil(ligne))


def p_marche(mkey, X, ligne):
    """P(stat >= X) si la ligne DraftKings vaut 50 % (même modèle que la page PARIS)."""
    sd = max(8, YARDS[mkey] * ligne) if mkey in YARDS else max(1, math.sqrt(ligne))
    return min(0.97, max(0.03, 1 - ncdf((X - 0.5 - ligne) / sd)))


def cote_bet365(p):
    return max(1.05, round(100 / (p * 1.07)) / 100)


def adj_def(rank):
    # rang 1 = défense qui accorde le plus = meilleur match : jusqu'à +4 points de %, rang 32 : -4
    return 0.0 if not rank else (16.5 - rank) / 15.5 * 0.04


def virg(x):
    return f"{x:g}".replace(".", ",")


def fr_rank(rank, k):
    quoi = {"QB_pass": "contre la passe", "RB_rush": "contre la course", "RB_rec": "contre les passes aux RB",
            "WR_rec": "contre les receveurs", "TE_rec": "contre les ailiers rapprochés"}[k]
    if rank <= 8:
        return f"défense {rank}e plus généreuse {quoi}"
    if rank >= 25:
        return f"défense {33 - rank}e plus dure {quoi}"
    return None


def confiance(p, edge):
    return "élevée" if p >= 0.7 and edge >= 0.06 else "moyenne" if p >= 0.6 and edge >= 0.02 else "faible"


def roster_of(joueurs_dir):
    roster = {}
    for f in Path(joueurs_dir).glob("*.json"):
        t = load(f)
        for p in t.get("players", []):
            roster[(t["team"], norm_name(p["name"]))] = {**p, "team": t["team"], "next": t.get("next")}
    return roster


def bet365_picks(dk, roster, defense, inj):
    out = []
    for x in (dk or {}).get("props", {}).values():
        mkey, ligne = x["mkey"], x["ligne"]
        p = roster.get((x["equipe"], norm_name(x["joueur"])))
        if not p or mkey not in DK_COL or mkey == "pass_td":
            continue
        statut = inj.get((x["equipe"], norm_name(x["joueur"])))
        if statut in SKIP:
            continue
        hist = [DK_COL[mkey](g) for g in p["g"][:8]]
        if len(hist) < 4:
            continue
        X = palier_de(mkey, ligne)
        hits = sum(v >= X for v in hist)
        rate = (hits + 1) / (len(hist) + 2)
        pm = p_marche(mkey, X, ligne)
        opp = (p.get("next") or {}).get("opp")
        k = DEF_KEY.get(mkey) or (p["pos"] + "_rec")
        rank = (defense.get(opp) or {}).get(k + "_rank")
        prob = 0.5 * rate + 0.5 * pm + adj_def(rank) - (0.06 if statut == "Questionable" else 0)
        prob = round(min(0.95, max(0.05, prob)), 3)
        cote = cote_bet365(pm)
        edge = prob * cote - 1
        if rate < 0.55 or edge <= 0:
            continue
        raisons = [f"{X}+ atteint dans {hits} de ses {len(hist)} derniers matchs (moyenne {virg(round(sum(hist) / len(hist), 1))})",
                   f"ligne DraftKings {virg(ligne)}"]
        if rank and fr_rank(rank, k):
            raisons.append(f"{opp} : {fr_rank(rank, k)}")
        if statut:
            raisons.append(f"⚠️ {FR_INJ.get(statut, statut)} sur le rapport des blessures")
        out.append({"livre": "bet365", "match": x["match"], "joueur": x["joueur"], "equipe": x["equipe"], "pos": p["pos"],
                    "mkey": mkey, "palier": X, "choix": f"{X}+ {MARCHE[mkey]}", "ligneDK": ligne, "cote": cote,
                    "coteEstimee": True, "probabilite": prob, "valeur": round(edge, 3), "confiance": confiance(prob, edge),
                    "hist": hist, "adversaire": opp, "rangDef": rank, "blessure": statut, "raison": " · ".join(raisons) + "."})
    return out


def moj_picks(moj, roster, defense, inj):
    out = []
    for mk in (moj or {}).get("markets", []):
        key = mk.get("mkey")
        if key not in MOJ_COL or not mk.get("joueur"):
            continue
        p = roster.get((mk["equipe"], norm_name(mk["joueur"])))
        statut = inj.get((mk["equipe"], norm_name(mk["joueur"])))
        if not p or statut in SKIP:
            continue
        hist = [MOJ_COL[key](g) for g in p["g"][:8]]
        if len(hist) < 4:
            continue
        opp = (p.get("next") or {}).get("opp")
        k = {"pass_yds": "QB_pass", "rush_yds": "RB_rush"}.get(key) or (p["pos"] + "_rec")
        rank = (defense.get(opp) or {}).get(k + "_rank")
        vig = sum(1 / c["cote"] for c in mk["choix"] if c.get("cote"))
        for c in mk["choix"]:
            if not c.get("cote"):
                continue
            if key == "td":
                if c["d"] not in ("Oui", "Non"):
                    continue
                choix, sens, ligne = ("Marque un touché" if c["d"] == "Oui" else "Ne marque pas de touché"), c["d"], None
                hit = [(v >= 1) == (c["d"] == "Oui") for v in hist]
                sign = 1 if c["d"] == "Oui" else -1
            elif c.get("sens"):
                sens, ligne = c["sens"], c["ligne"]
                choix = f"{sens} de {virg(ligne)} {MARCHE[key]}"
                hit = [(v > ligne) if sens == "Plus" else (v < ligne) for v in hist]
                sign = 1 if sens == "Plus" else -1
            else:
                continue
            rate = (sum(hit) + 1) / (len(hit) + 2)
            fair = (1 / c["cote"]) / vig
            prob = 0.5 * rate + 0.5 * fair + sign * adj_def(rank) - (0.06 if statut == "Questionable" and sign > 0 else 0)
            prob = round(min(0.95, max(0.05, prob)), 3)
            edge = prob * c["cote"] - 1
            if rate < 0.55 or edge <= 0:
                continue
            raisons = [f"réussi dans {sum(hit)} de ses {len(hit)} derniers matchs (moyenne {virg(round(sum(hist) / len(hist), 1))})"]
            if rank and fr_rank(rank, k):
                raisons.append(f"{opp} : {fr_rank(rank, k)}")
            if statut:
                raisons.append(f"⚠️ {FR_INJ.get(statut, statut)} sur le rapport des blessures")
            out.append({"livre": "Mise-O-Jeu", "match": mk["match"], "joueur": mk["joueur"], "equipe": mk["equipe"],
                        "pos": p["pos"], "mkey": key, "choix": choix, "sens": sens, "ligne": ligne, "cote": c["cote"],
                        "coteEstimee": False, "simple": bool(mk.get("simple")), "probabilite": prob,
                        "valeur": round(edge, 3), "confiance": confiance(prob, edge), "hist": hist, "adversaire": opp,
                        "rangDef": rank, "blessure": statut, "raison": " · ".join(raisons) + "."})
    return out


def best(picks, n, per_game=2):
    """Les meilleures selon la valeur, un pari par joueur, au plus `per_game` par match."""
    picked, seen, games = [], set(), {}
    for p in sorted(picks, key=lambda p: (-p["valeur"], -p["probabilite"])):
        if p["joueur"] in seen or games.get(p["match"], 0) >= per_game:
            continue
        seen.add(p["joueur"]); games[p["match"]] = games.get(p["match"], 0) + 1
        picked.append(p)
        if len(picked) >= n:
            break
    for i, p in enumerate(picked, 1):
        p["id"] = f"{p['livre'][:3].lower()}{i}"
    return picked


def combine(nom, legs, mise, note):
    cote = math.prod(l["cote"] for l in legs)
    prob = math.prod(l["probabilite"] for l in legs)
    return {"nom": nom, "ids": [l["id"] for l in legs], "mise": mise, "cote": round(cote, 2), "probabilite": round(prob, 3),
            "gain": round(mise * cote, 2), "note": note}


def combines(picks, livre):
    out = []
    sure = sorted(picks, key=lambda p: -p["probabilite"])

    def spread(n):
        legs, games = [], set()
        for p in sure:
            if p["match"] not in games:
                legs.append(p); games.add(p["match"])
            if len(legs) == n:
                return legs
        return None

    for nom, n, mise, note in (("Le prudent", 2, 10, "Les 2 paris les plus sûrs, dans 2 matchs différents."),
                               ("Le classique", 3, 5, "3 paris solides, chacun dans un match différent."),
                               ("Le payant", 5, 5, "Plus risqué, mais ça paie gros. 5 matchs différents.")):
        legs = spread(n) or (spread(4) if n == 5 else None)
        if legs:
            out.append(combine(nom, legs, mise, note))
    # Même match : un QB par la passe + un de ses receveurs, ou deux joueurs de la même attaque
    by_game = {}
    for p in sure:
        by_game.setdefault(p["match"], []).append(p)
    duo = None
    for g, ps in by_game.items():
        qb = next((p for p in ps if p["mkey"] == "pass_yds"), None)
        rec = next((p for p in ps if qb and p["equipe"] == qb["equipe"] and p["mkey"] in ("rec_yds", "receptions")), None)
        if qb and rec:
            cand = [qb, rec]
        elif len(ps) >= 2:
            cand = ps[:2]
        else:
            continue
        if not duo or math.prod(x["probabilite"] for x in cand) > math.prod(x["probabilite"] for x in duo):
            duo = cand
    if duo:
        note = "2 paris du même match" + (" : le QB et son receveur montent ensemble." if duo[0]["equipe"] == duo[1]["equipe"] else ".")
        out.append(combine("Le même match", duo, 5, note + (" Sur bet365 : « Créer un pari »." if livre == "bet365" else "")))
    return out


def main(joueurs_dir, meta_p, live_p, dk_p, moj_p, out_p):
    meta, live, dk, moj = load(meta_p), load(live_p), load(dk_p), load(moj_p)
    roster = roster_of(joueurs_dir)
    defense = (meta or {}).get("defense", {})
    inj = {(t, norm_name(x["n"])): x["s"] for t, rows in (live or {}).get("injuries", {}).items() for x in rows}
    b = best(bet365_picks(dk, roster, defense, inj), 10)
    # Mise-O-Jeu : les props joueurs ne se jouent pas seules, on donne aussi des combinés
    m = best(moj_picks(moj, roster, defense, inj), 10)
    doc = {"bet365": {"picks": b, "combines": combines(b, "bet365")},
           "miseojeu": {"picks": m, "combines": combines(m, "Mise-O-Jeu")},
           "methode": "Chance = moitié l'historique du joueur (8 derniers matchs), moitié le marché, ajustée selon la défense adverse. "
                      "Un pari est proposé seulement si cette chance bat la cote. Cotes bet365 estimées (≈) à partir de la ligne DraftKings."}
    Path(out_p).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("propositions bet365", len(b), "mise-o-jeu", len(m))


if __name__ == "__main__":
    main(*sys.argv[1:7])
