// NFL LABS : site public. Les pointages viennent d'ESPN directement dans le navigateur ;
// le reste vient des fichiers data/*.json que le robot GitHub met à jour.
(() => {
  const $ = (id) => document.getElementById(id);
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  const virg = (x, d = 1) => Number.isFinite(Number(x)) ? (Math.round(Number(x) * 10 ** d) / 10 ** d).toLocaleString("fr-CA") : "—";
  const cote = (x) => Number.isFinite(Number(x)) ? Number(x).toFixed(2).replace(".", ",") : "—";
  const pct = (x) => Math.round(Number(x) * 100) + " %";
  const ilya = (iso) => {
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if (!Number.isFinite(m)) return "?";
    return m < 1 ? "à l'instant" : m < 60 ? "il y a " + m + " min" : m < 1440 ? "il y a " + Math.round(m / 60) + " h" : "il y a " + Math.round(m / 1440) + " j";
  };
  const kick = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString("fr-CA", { weekday: "short", hour: "numeric", minute: "2-digit" }); };
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[.'’-]/g, " ").replace(/\s+/g, " ").trim();
  const decimal = (a) => { const o = Number(String(a ?? "").replace("+", "")); return !Number.isFinite(o) || o === 0 ? null : o > 0 ? 1 + o / 100 : 1 + 100 / -o; };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
  const INJ_FR = { Out: "Absent", Doubtful: "Douteux", Questionable: "Incertain", Suspension: "Suspendu", Suspended: "Suspendu", "Injured Reserve": "Liste des blessés", IR: "Liste des blessés" };
  const stTag = (s) => { const t = el("span", "st st-" + String(s).split(" ")[0], INJ_FR[s] || s); return t; };

  async function getJSON(path) {
    const r = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error(path + " " + r.status);
    return r.json();
  }

  // ---------- Pointages en direct (ESPN, CORS ouvert) ----------
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard";
  const darkHex = (h) => { const n = parseInt(String(h).slice(1), 16); return !Number.isFinite(n) || ((n >> 16) * 299 + ((n >> 8) & 255) * 587 + (n & 255) * 114) / 1000 < 40; };
  const downFr = (t) => String(t || "").replace(/\b1st\b/, "1er").replace(/\b(\d)(nd|rd|th)\b/, "$1e").replace("& Goal", "& but").replace(" at ", " à ");
  function parseScores(sb) {
    return (sb.events || []).map((e) => {
      const c = e.competitions[0], st = c.status, sit = c.situation || {};
      const side = {};
      for (const x of c.competitors) {
        const t = x.team || {};
        side[x.homeAway] = { t: t.abbreviation, nom: t.shortDisplayName, s: /^\d+$/.test(String(x.score ?? "")) ? Number(x.score) : null, c: "#" + (t.color || "8d9bb1"), rec: (x.records || [{}])[0]?.summary, id: t.id };
      }
      const inPlay = st.type.state === "in";
      return { away: side.away, home: side.home, state: st.type.state, detail: st.type.shortDetail, kickoff: e.date, period: st.period, clock: st.displayClock,
        poss: inPlay ? (side.away.id === sit.possession ? "away" : side.home.id === sit.possession ? "home" : null) : null,
        down: inPlay ? sit.downDistanceText : null, rz: inPlay && !!sit.isRedZone };
    });
  }
  function statusTxt(g) {
    if (g.state === "pre") return kick(g.kickoff);
    if (g.state === "post") return g.period > 4 ? "Final (prol.)" : "Final";
    if (/half/i.test(g.detail || "")) return "Mi-temps";
    if (/^end/i.test(g.detail || "")) return "Fin Q" + g.period;
    return (g.period > 4 ? "Prol." : "Q" + g.period) + " · " + (g.clock || "");
  }
  let scoresTimer = null, liveCount = 0;
  async function loadScores() {
    clearTimeout(scoresTimer);
    try {
      const r = await fetch(ESPN, { cache: "no-store" });
      const games = parseScores(await r.json());
      renderScores(games);
      liveCount = games.filter((g) => g.state === "in").length;
    } catch {
      if (!$("strip").querySelector(".game")) $("strip").replaceChildren(el("p", "empty-line", "Pointages indisponibles pour l'instant. On réessaie bientôt."));
    }
    setBadge();
    scoresTimer = setTimeout(loadScores, liveCount ? 30000 : 300000);
  }
  function renderScores(games) {
    const strip = $("strip");
    if (!games.length) { strip.replaceChildren(el("p", "empty-line", "Pas de match cette semaine.")); return; }
    const rank = { in: 0, pre: 1, post: 2 };
    const list = [...games].sort((a, b) => (rank[a.state] ?? 3) - (rank[b.state] ?? 3) || new Date(a.kickoff) - new Date(b.kickoff));
    strip.replaceChildren(...list.map((g) => {
      const card = el("article", "game");
      card.dataset.state = g.state; card.dataset.rz = String(!!g.rz);
      for (const k of ["away", "home"]) {
        const t = g[k] || {}, o = g[k === "away" ? "home" : "away"] || {};
        const row = el("div", "g-team" + (g.state === "post" && t.s < o.s ? " lose" : ""));
        const bar = el("i"); bar.style.background = darkHex(t.c) ? "var(--muted)" : t.c;
        const name = el("b", null, t.t || "?");
        if (t.rec) name.append(" ", el("small", null, t.rec));
        row.append(bar, name, el("span", "ball", g.poss === k ? "◀" : ""), el("span", "pts", g.state === "pre" ? "" : String(t.s ?? "")));
        row.title = t.nom || "";
        card.append(row);
      }
      card.append(el("div", "g-st", statusTxt(g)));
      if (g.state === "in" && g.down) card.append(el("div", "g-down", downFr(g.down)));
      card.setAttribute("aria-label", (g.away?.t || "") + " " + (g.away?.s ?? "") + ", " + (g.home?.t || "") + " " + (g.home?.s ?? "") + ", " + statusTxt(g));
      return card;
    }));
    const live = games.filter((g) => g.state === "in").length;
    $("scores-at").textContent = (live ? live + " match" + (live > 1 ? "s" : "") + " en cours · " : "") + "mis à jour " + new Date().toLocaleTimeString("fr-CA", { hour: "numeric", minute: "2-digit" });
  }
  function setBadge() {
    const b = $("live");
    if (liveCount) { b.dataset.state = "in"; $("live-text").textContent = liveCount + " match" + (liveCount > 1 ? "s" : "") + " en direct"; return; }
    if (maj?.at) { b.dataset.state = "ok"; $("live-text").textContent = "À jour · " + ilya(maj.at); return; }
    b.dataset.state = "wait"; $("live-text").textContent = "Chargement…";
  }

  // ---------- Données du robot ----------
  let paris = null, joueurs = null, fantasy = null, maj = null;
  const errs = {};

  // ---------- Onglets ----------
  const SUBS = { paris: ["bet365", "moj", "matchs", "blesses", "joueurs"], fantasy: ["matchs", "classement", "equipes", "agents"] };
  const state = { tab: "paris", sub: { paris: "bet365", fantasy: "matchs" } };
  function readHash() {
    const [t, s] = location.hash.slice(1).split("/");
    if (SUBS[t]) { state.tab = t; if (SUBS[t].includes(s)) state.sub[t] = s; return true; }
    return false;
  }
  if (!readHash()) {
    const saved = store.get("nfllabs.tab");
    if (saved && SUBS[saved.split("/")[0]]) { const [t, s] = saved.split("/"); state.tab = t; if (SUBS[t].includes(s)) state.sub[t] = s; }
  }
  function go(tab, sub) {
    state.tab = tab; if (sub) state.sub[tab] = sub;
    const h = "#" + tab + "/" + state.sub[tab];
    if (location.hash !== h) history.replaceState(null, "", h);
    store.set("nfllabs.tab", tab + "/" + state.sub[tab]);
    render();
  }
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
  document.querySelectorAll("#p-chips .chip").forEach((b) => b.addEventListener("click", () => go("paris", b.dataset.sub)));
  document.querySelectorAll("#f-chips .chip").forEach((b) => b.addEventListener("click", () => go("fantasy", b.dataset.sub)));
  addEventListener("hashchange", () => { if (readHash()) render(); });

  function render() {
    for (const t of ["paris", "fantasy"]) {
      $(t).hidden = state.tab !== t;
      $("tab-" + t).setAttribute("aria-selected", String(state.tab === t));
    }
    document.querySelectorAll("#p-chips .chip").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sub === state.sub.paris)));
    document.querySelectorAll("#f-chips .chip").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sub === state.sub.fantasy)));
    const body = state.tab === "paris" ? $("p-body") : $("f-body");
    try {
      body.replaceChildren(...(state.tab === "paris" ? PARIS[state.sub.paris]() : FANTASY[state.sub.fantasy]()));
    } catch (e) {
      console.error(e);
      body.replaceChildren(empty("Oups", "Cette section n'a pas pu s'afficher. Recharge la page dans un moment."));
    }
    renderFoot();
  }
  const empty = (title, text) => { const d = el("div", "empty"); d.append(el("b", null, title), el("span", null, text)); return d; };
  const loading = (what) => errs[what] ? empty("Pas encore de données", "Le robot n'a pas encore publié cette partie. Reviens dans quelques minutes.") : empty("Chargement…", "");

  // ---------- PARIS ----------
  function spark(hist, isHit, line) {
    const vals = [...hist].reverse();
    const top = Math.max(1, line || 0, ...vals) * 1.12;
    const box = el("div", "spark");
    box.setAttribute("aria-hidden", "true");
    for (const v of vals) {
      const s = el("span", isHit(v) ? "hit" : "");
      s.style.height = Math.max(4, (v / top) * 100) + "%";
      s.title = virg(v, 1);
      box.append(s);
    }
    if (line) { const l = el("i", "bar-line"); l.style.bottom = (line / top) * 100 + "%"; box.append(l); }
    return box;
  }
  function hitFn(p) {
    if (p.livre === "bet365") return [(v) => v >= p.palier, p.palier];
    if (p.mkey === "td") return [p.sens === "Oui" ? (v) => v >= 1 : (v) => v === 0, 1];
    return [p.sens === "Plus" ? (v) => v > p.ligne : (v) => v < p.ligne, p.ligne];
  }
  // Jour et heure du match d'un pari (« DAL @ PHI » → coup d'envoi), ou son état s'il est commencé
  function quand(match) {
    const g = (paris?.games || []).find((x) => x.away + " @ " + x.home === match);
    if (!g) return "";
    if (g.status === "STATUS_FINAL") return "Match terminé";
    if (g.status && g.status !== "STATUS_SCHEDULED") return "Match en cours";
    const d = new Date(g.kickoff);
    return isNaN(d) ? "" : d.toLocaleString("fr-CA", { weekday: "long", day: "numeric", month: "long", hour: "numeric", minute: "2-digit" });
  }
  function ticket(p) {
    const t = el("article", "ticket");
    const top = el("div", "t-top");
    const who = el("div", "t-who");
    who.append(el("b", null, p.joueur), el("small", null, p.pos + " · " + p.equipe + " · " + p.match));
    const price = el("div", "price" + (p.coteEstimee ? " est" : ""));
    price.append(el("b", null, (p.coteEstimee ? "≈ " : "") + cote(p.cote)), el("small", null, p.coteEstimee ? "Cote estimée" : "Cote"));
    top.append(who, price);
    t.append(top);
    const q = quand(p.match);
    if (q) t.append(el("div", "t-when", "🕐 " + q));
    t.append(el("div", "t-pick", p.choix));
    const [isHit, line] = hitFn(p);
    t.append(spark(p.hist || [], isHit, line));
    const hits = (p.hist || []).filter(isHit).length;
    t.append(el("span", "spark-cap", hits + " sur " + (p.hist || []).length + " derniers matchs (le plus récent à droite)"));
    t.append(el("p", "t-why", p.raison));
    const stub = el("div", "t-stub");
    const ch = el("span", "chance"); ch.append("Chance ", el("b", null, pct(p.probabilite)));
    const cf = el("span", "conf", "Confiance " + p.confiance); cf.dataset.c = p.confiance;
    stub.append(ch, cf);
    t.append(stub);
    return t;
  }
  function combos(list, picks) {
    const byId = Object.fromEntries(picks.map((p) => [p.id, p]));
    const box = el("div", "combos");
    for (const c of list) {
      const legs = c.ids.map((i) => byId[i]).filter(Boolean);
      if (!legs.length) continue;
      const d = el("article", "combo");
      d.append(el("h4", null, c.nom), el("p", "note", c.note));
      const ol = el("ol");
      for (const l of legs) { const li = el("li", null, l.joueur + " : " + l.choix + " "); li.append(el("small", null, "(" + (l.coteEstimee ? "≈ " : "") + cote(l.cote) + ")")); const q = quand(l.match); if (q) li.append(el("small", "leg-when", l.match + " · " + q)); ol.append(li); }
      d.append(ol);
      const nums = el("div", "nums");
      for (const [k, v] of [["Mise", c.mise + " $"], ["Cote", (legs.some((l) => l.coteEstimee) ? "≈ " : "") + cote(c.cote)], ["Gain", virg(c.gain, 2) + " $"]]) {
        const x = el("div"); x.append(el("small", null, k), el("b", null, v)); nums.append(x);
      }
      d.append(nums, el("span", "note", "Chance que tout passe : " + pct(c.probabilite)));
      box.append(d);
    }
    return box;
  }
  function propsView(key, titre, intro) {
    if (!paris) return [loading("paris")];
    const P = paris.propositions?.[key];
    const out = [el("h2", "sec", titre + (paris.week ? " · semaine " + paris.week : ""))];
    out.push(el("p", "note", intro + (paris.propositionsAt ? " Calculées " + ilya(paris.propositionsAt) + "." : "")));
    if (!P?.picks?.length) { out.push(empty("Rien à proposer pour l'instant", "Aucun pari ne bat la cote en ce moment, ou les lignes de la prochaine semaine ne sont pas encore sorties (souvent mardi ou mercredi).")); return out; }
    out.push(el("h3", "sub-h", "Paris simples"));
    const g = el("div", "tickets"); P.picks.forEach((p) => g.append(ticket(p))); out.push(g);
    if (P.combines?.length) { out.push(el("h3", "sub-h", "Combinés")); out.push(combos(P.combines, P.picks)); }
    return out;
  }
  function matchsView() {
    if (!paris?.games) return [loading("paris")];
    const out = [el("h2", "sec", "Matchs et cotes · semaine " + (paris.week ?? "?")), el("p", "note", "Cotes DraftKings converties en cotes décimales (comme sur bet365). Elles peuvent différer un peu chez bet365 et Mise-O-Jeu. Mis à jour " + ilya(paris.oddsAt) + ".")];
    const wrap = el("div", "tbl-wrap"), t = el("table");
    const head = el("tr");
    for (const [h, n] of [["Match"], ["Quand"], ["Écart", 1], ["Total", 1], ["Visiteur gagne", 1], ["Local gagne", 1]]) head.append(el("th", n ? "num" : "", h));
    t.append(head);
    const rows = [...paris.games].sort((a, b) => new Date(a.kickoff) - new Date(b.kickoff));
    for (const g of rows) {
      const tr = el("tr");
      const sp = Number(String(g.spreadHome ?? "").replace("+", ""));
      const fav = Number.isFinite(sp) && g.spreadHome != null ? (sp < 0 ? g.home + " " + virg(sp) : sp > 0 ? g.away + " " + virg(-sp) : "Égal") : "—";
      const done = g.status !== "STATUS_SCHEDULED";
      tr.append(el("td", null, g.away + " @ " + g.home), el("td", "muted", done ? (g.status === "STATUS_FINAL" ? "Terminé" : "En cours") : kick(g.kickoff)),
        el("td", "num", fav), el("td", "num", g.total != null ? virg(g.total) : "—"),
        el("td", "num", cote(decimal(g.mlAway))), el("td", "num", cote(decimal(g.mlHome))));
      if (done) tr.classList.add("muted");
      t.append(tr);
    }
    wrap.append(t); out.push(wrap);
    return out;
  }
  let injTeam = "";
  function blessesView() {
    if (!paris?.injuries) return [loading("paris")];
    const out = [el("h2", "sec", "Blessés · QB, RB, WR, TE"), el("p", "note", "Rapport des blessures d'ESPN, mis à jour " + ilya(paris.oddsAt) + ".")];
    const sel = el("select", "search"); sel.setAttribute("aria-label", "Équipe");
    sel.append(new Option("Toutes les équipes", ""));
    const teams = Object.keys(paris.injuries).filter((t) => paris.injuries[t].length).sort();
    teams.forEach((t) => sel.append(new Option(t, t)));
    sel.value = injTeam;
    const row = el("div", "row"); row.append(sel); out.push(row);
    const box = el("div");
    const draw = () => {
      const wrap = el("div", "tbl-wrap"), t = el("table");
      const head = el("tr"); ["Joueur", "Équipe", "Poste", "Statut", "Détail"].forEach((h) => head.append(el("th", null, h))); t.append(head);
      const order = { Out: 0, "Injured Reserve": 1, Suspension: 1, Doubtful: 2, Questionable: 3 };
      const list = (injTeam ? [injTeam] : teams).flatMap((tm) => paris.injuries[tm].map((x) => ({ ...x, tm }))).sort((a, b) => (order[a.s] ?? 9) - (order[b.s] ?? 9) || a.tm.localeCompare(b.tm));
      for (const x of list) {
        const tr = el("tr"), st = el("td"); st.append(stTag(x.s));
        const c = el("td", "muted", x.c || ""); c.style.whiteSpace = "normal"; c.style.minWidth = "240px";
        tr.append(el("td", null, x.n), el("td", null, x.tm), el("td", null, x.pos), st, c); t.append(tr);
      }
      wrap.append(t); box.replaceChildren(list.length ? wrap : empty("Personne", "Aucun blessé signalé."));
    };
    sel.onchange = () => { injTeam = sel.value; draw(); };
    draw(); out.push(box);
    return out;
  }
  // Colonnes d'une ligne de match : semaine, adv, cmp, att, vp, tdp, int, courses, vs, tds, rec, cibles, vr, tdr, domicile
  const POS_COLS = {
    QB: [["Passes", (g) => g[2] + "/" + g[3]], ["Verges passe", (g) => g[4]], ["TD", (g) => g[5]], ["INT", (g) => g[6]], ["Verges sol", (g) => g[8]]],
    RB: [["Courses", (g) => g[7]], ["Verges sol", (g) => g[8]], ["TD sol", (g) => g[9]], ["Récept.", (g) => g[10]], ["Verges réc.", (g) => g[12]]],
    WR: [["Cibles", (g) => g[11]], ["Récept.", (g) => g[10]], ["Verges réc.", (g) => g[12]], ["TD", (g) => g[13]]],
  };
  POS_COLS.TE = POS_COLS.WR;
  const MAIN = { QB: (g) => g[4], RB: (g) => g[8] + g[12], WR: (g) => g[12], TE: (g) => g[12] };
  let pq = "", pSel = null;
  function joueursView() {
    if (!joueurs?.teams) return [loading("joueurs")];
    const all = Object.entries(joueurs.teams).flatMap(([team, t]) => t.players.map((p) => ({ ...p, team, next: t.next })));
    const out = [el("h2", "sec", "Joueurs"), el("p", "note", "Les 10 derniers matchs de chaque joueur (stats nflverse jusqu'à la semaine " + joueurs.lastWeek + ").")];
    const inp = el("input", "search"); inp.type = "search"; inp.placeholder = "Chercher un joueur (ex. Lamar, Chase…)"; inp.value = pq; inp.setAttribute("aria-label", "Chercher un joueur");
    const row = el("div", "row"); row.append(inp); out.push(row);
    const res = el("div", "res"); out.push(res);
    const draw = () => {
      const q = norm(pq);
      if (pSel) { res.replaceChildren(playerCard(pSel)); return; }
      if (q.length < 2) { res.replaceChildren(el("p", "note", "Tape au moins 2 lettres.")); return; }
      const hits = all.filter((p) => norm(p.name).includes(q) || p.team.toLowerCase() === q).slice(0, 12);
      res.replaceChildren(...(hits.length ? hits.map((p) => {
        const b = el("button", "pick-btn"); b.type = "button";
        b.append(el("b", null, p.name + " "), el("small", null, p.pos + " · " + p.team));
        b.onclick = () => { pSel = p; draw(); };
        return b;
      }) : [el("p", "note", "Aucun joueur trouvé.")]));
    };
    inp.oninput = () => { pq = inp.value; pSel = null; draw(); };
    draw();
    return out;
  }
  function playerCard(p) {
    const c = el("div", "pcard");
    const back = el("button", "chip", "← Retour"); back.type = "button"; back.onclick = () => { pSel = null; render(); };
    c.append(back, el("h4", null, p.name));
    const nx = p.next ? (p.next.home ? "vs " : "@ ") + p.next.opp : "pas de match prévu";
    c.append(el("span", "note", p.pos + " · " + p.team + " · prochain match : " + nx));
    const inj = (paris?.injuries?.[p.team] || []).find((x) => norm(x.n) === norm(p.name));
    if (inj) { const s = el("p", "note"); s.append(stTag(inj.s), " " + (inj.c || "")); c.append(s); }
    const main = MAIN[p.pos];
    if (main && p.g.length) {
      const vals = p.g.map(main), avg = vals.reduce((a, b) => a + b, 0) / vals.length;
      c.append(spark(vals, (v) => v >= avg, avg), el("span", "spark-cap", (p.pos === "QB" ? "Verges par la passe" : p.pos === "RB" ? "Verges au sol + réception" : "Verges sur réception") + " · moyenne " + virg(avg) + " (ligne pointillée)"));
    }
    const wrap = el("div", "tbl-wrap"), t = el("table");
    const cols = POS_COLS[p.pos] || POS_COLS.WR;
    const head = el("tr"); head.append(el("th", null, "Sem."), el("th", null, "Adv.")); cols.forEach(([h]) => head.append(el("th", "num", h))); t.append(head);
    for (const g of p.g) {
      const tr = el("tr"); tr.append(el("td", null, String(g[0])), el("td", null, (g[14] ? "vs " : "@ ") + g[1]));
      cols.forEach(([, f]) => tr.append(el("td", "num", String(f(g))))); t.append(tr);
    }
    wrap.append(t); c.append(wrap);
    return c;
  }
  const PARIS = {
    bet365: () => propsView("bet365", "Propositions bet365", "Paliers « X+ » comme sur bet365 (verges par tranches de 10, Plus seulement). Les cotes sont estimées (≈) : vérifie la vraie cote sur bet365 avant de miser."),
    moj: () => propsView("miseojeu", "Propositions Mise-O-Jeu", "Vraies cotes de Mise-O-Jeu. Les paris sur les joueurs ne se jouent pas seuls sur Mise-O-Jeu : mets-les dans un combiné."),
    matchs: matchsView, blesses: blessesView, joueurs: joueursView,
  };

  // ---------- FANTASY ----------
  const GROUPS = ["QB", "RB", "WR", "TE", "PK", "DL", "LB", "DB"];
  let fTeam = null;
  function fMatchs() {
    if (!fantasy) return [loading("fantasy")];
    const out = [el("h2", "sec", "Semaine " + fantasy.semaine + " · " + (fantasy.ligue || "QFF")), el("p", "note", "Pointage en cours de MFL et projection de chaque alignement. Mis à jour " + ilya(fantasy.updatedAt) + ".")];
    const box = el("div", "duels");
    for (const m of fantasy.matchs || []) {
      if (m.length < 2) continue;
      const started = m.some((s) => (s.score || 0) > 0);
      const val = (s) => started ? s.score || 0 : s.proj || 0;
      const d = el("article", "duel" + (m.some((s) => s.id === fantasy.moi) ? " me" : ""));
      const lead = val(m[0]) >= val(m[1]) ? 0 : 1;
      m.forEach((s, i) => {
        const r = el("div", "d-row" + (i === lead ? " lead" : ""));
        const n = el("div"); n.append(el("b", null, s.nom), el("br"), el("small", null, (fantasy.equipes?.[s.id]?.fiche || "") + " · proj. " + virg(s.proj)));
        r.append(n, el("span", "sc", started ? virg(s.score, 0) : "—"));
        d.append(r);
      });
      const a = val(m[0]), b = val(m[1]), tot = a + b || 1;
      const tug = el("div", "tug"), x = el("span"), y = el("span");
      x.style.width = (a / tot) * 100 + "%"; y.style.width = (b / tot) * 100 + "%"; tug.append(x, y);
      d.append(tug, el("span", "note", started ? "En cours ou terminé" : "Pas encore commencé : barre selon la projection"));
      box.append(d);
    }
    out.push(box);
    return out;
  }
  function fClassement() {
    if (!fantasy) return [loading("fantasy")];
    const out = [el("h2", "sec", "Classement"), el("p", "note", "Saison régulière jusqu'à la semaine " + fantasy.finSaisonReg + ".")];
    const wrap = el("div", "tbl-wrap"), t = el("table"), head = el("tr");
    [["#"], ["Équipe"], ["Fiche"], ["Pts pour", 1], ["Pts contre", 1], ["Moy.", 1], ["Série"]].forEach(([h, n]) => head.append(el("th", n ? "num" : "", h)));
    t.append(head);
    fantasy.classement.forEach((r, i) => {
      const tr = el("tr", r.id === fantasy.moi ? "me" : "");
      tr.append(el("td", "num", String(i + 1)), el("td", null, r.nom), el("td", null, r.fiche), el("td", "num", virg(r.pf, 0)), el("td", "num", virg(r.pa, 0)), el("td", "num", virg(r.moyPF)), el("td", "muted", r.serie || ""));
      tr.style.cursor = "pointer"; tr.onclick = () => { fTeam = r.id; go("fantasy", "equipes"); };
      t.append(tr);
    });
    wrap.append(t); out.push(wrap);
    const bowl = fantasy.bowl;
    if (bowl?.equipes?.length) {
      out.push(el("h3", "sub-h", "Course au QFF Bowl · " + bowl.conference), el("p", "note", "Le plus de points aux semaines " + (bowl.semaines || []).join(", ") + " dans la conférence. Chances calculées avec 4000 saisons simulées."));
      const w2 = el("div", "tbl-wrap"), t2 = el("table"), h2 = el("tr");
      [["Équipe"], ["Projection", 1], ["Chance", 1]].forEach(([h, n]) => h2.append(el("th", n ? "num" : "", h))); t2.append(h2);
      for (const e of bowl.equipes) { const tr = el("tr", e.id === fantasy.moi ? "me" : ""); tr.append(el("td", null, e.nom), el("td", "num", virg(e.proj, 0)), el("td", "num", pct(e.prob))); t2.append(tr); }
      w2.append(t2); out.push(w2);
    }
    return out;
  }
  function rosterTable(js, withStart) {
    const wrap = el("div", "tbl-wrap"), t = el("table"), head = el("tr");
    const cols = [["Joueur"], ["Poste"], ["NFL"], ["Adv."], ["Moy.", 1], ["Proj.", 1], ["Statut"]];
    if (withStart) cols.push(["Partant"]);
    cols.forEach(([h, n]) => head.append(el("th", n ? "num" : "", h))); t.append(head);
    const order = (p) => GROUPS.indexOf(p.grp);
    for (const p of [...js].sort((a, b) => order(a) - order(b) || (b.proj || 0) - (a.proj || 0))) {
      const tr = el("tr"), st = el("td");
      if (p.ir) st.append(stTag("IR")); else if (p.bless) st.append(stTag(p.bless));
      tr.append(el("td", null, p.nom), el("td", null, p.pos), el("td", null, p.nfl || ""), el("td", "muted", p.adv || ""), el("td", "num", virg(p.moy)), el("td", "num", virg(p.proj)), st);
      if (withStart) tr.append(el("td", null, p.aligne ? "✓" : ""));
      t.append(tr);
    }
    wrap.append(t);
    return wrap;
  }
  function fEquipes() {
    if (!fantasy) return [loading("fantasy")];
    const ids = Object.keys(fantasy.equipes).sort((a, b) => fantasy.equipes[a].nom.localeCompare(fantasy.equipes[b].nom));
    if (!fTeam || !fantasy.equipes[fTeam]) fTeam = fantasy.moi;
    const out = [el("h2", "sec", "Équipes")];
    const sel = el("select", "search"); sel.setAttribute("aria-label", "Équipe");
    ids.forEach((id) => sel.append(new Option(fantasy.equipes[id].nom, id)));
    sel.value = fTeam; sel.onchange = () => { fTeam = sel.value; render(); };
    const row = el("div", "row"); row.append(sel); out.push(row);
    const e = fantasy.equipes[fTeam];
    const k = el("div", "kpis");
    for (const [l, v] of [["Fiche", e.fiche || "—"], ["Projection semaine", virg(e.proj)], ["Alignement", e.alignementSoumis ? "Soumis" : "Pas encore"]]) { const d = el("div", "kpi"); d.append(el("small", null, l), el("b", null, v)); k.append(d); }
    out.push(k, el("h3", "sub-h", "Joueurs"), rosterTable(e.joueurs, true));
    return out;
  }
  function fAgents() {
    if (!fantasy?.agentsLibres) return [loading("fantasy")];
    const out = [el("h2", "sec", "Meilleurs agents libres"), el("p", "note", "Les 6 meilleurs joueurs libres par poste selon la projection de la semaine. Ramassage premier arrivé, premier servi dans MFL.")];
    for (const g of GROUPS) {
      const js = fantasy.agentsLibres[g];
      if (!js?.length) continue;
      out.push(el("h3", "sub-h", g), rosterTable(js, false));
    }
    return out;
  }
  const FANTASY = { matchs: fMatchs, classement: fClassement, equipes: fEquipes, agents: fAgents };

  function renderFoot() {
    if (paris?.propositions?.methode) $("p-methode").textContent = "Comment c'est calculé : " + paris.propositions.methode;
    if (!maj?.at) return;
    const bad = Object.entries(maj.etapes || {}).filter(([, v]) => !v.ok).map(([k]) => k);
    $("maj").textContent = "Données mises à jour " + ilya(maj.at) + " par le robot." + (bad.length ? " En retard : " + bad.join(", ") + " (on réessaie au prochain passage)." : "");
  }

  async function loadData() {
    const jobs = [["paris", "data/paris.json", (d) => (paris = d)], ["joueurs", "data/joueurs.json", (d) => (joueurs = d)],
      ["fantasy", "data/fantasy.json", (d) => (fantasy = d)], ["maj", "data/maj.json", (d) => (maj = d)]];
    await Promise.all(jobs.map(([k, url, set]) => getJSON(url).then((d) => { set(d); delete errs[k]; }).catch(() => { errs[k] = true; })));
    setBadge();
    // Ne pas effacer la recherche en cours pendant qu'on tape
    if (!(document.activeElement?.tagName === "INPUT")) render();
  }

  render();
  loadScores();
  loadData();
  setInterval(loadData, 5 * 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { loadScores(); loadData(); } });
})();
