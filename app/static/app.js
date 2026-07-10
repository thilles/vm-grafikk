/* Frontend for tippekonkurranse-scoreboardet. Leser alt fra /api/state. */

const $ = (id) => document.getElementById(id);

// «Kamp i kampen»: payload pr kamp-id (kortene re-rendres hvert 60 s, så vi
// holder duell-dataene utenfor DOM-en) + aktive sim-håndtak pr kort-element.
const DUELL = new Map();
const _kikHandles = new WeakMap();

function toggleMatch(card) {
  const open = card.classList.toggle("open");
  const canvas = card.querySelector(".kik-canvas");
  if (!canvas) return;
  if (open) {
    const d = DUELL.get(card.dataset.mid);
    if (d && !_kikHandles.has(card)) {
      _kikHandles.set(card, window.mountKik(canvas, d.duell, d.homeFlag, d.awayFlag));
    }
  } else {
    const h = _kikHandles.get(card);
    if (h) { h.stop(); _kikHandles.delete(card); }
  }
}
window.toggleMatch = toggleMatch;

// Sett et kamp-containers innhold på nytt uten å miste hvilke kort som er åpne.
// Kortene re-rendres hvert minutt; her bevares «open»-tilstand og evt. kjørende
// kamp-i-kampen-animasjon stoppes rent før DOM-en byttes ut (ingen foreldreløs rAF).
function setMatchHTML(container, html) {
  const openIds = [...container.querySelectorAll(".match.open")].map((c) => c.dataset.mid);
  container.querySelectorAll(".match.open").forEach((c) => {
    const h = _kikHandles.get(c);
    if (h) { h.stop(); _kikHandles.delete(c); }
  });
  container.innerHTML = html;
  openIds.forEach((id) => {
    if (!id) return;
    const c = container.querySelector(`.match[data-mid="${CSS.escape(id)}"]`);
    if (c) toggleMatch(c); // gjenåpner kortet og re-monterer grafen
  });
}

// Escaper tekst fra eksterne kilder (NRK) før den settes inn som innerHTML.
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("no-NO", {
    weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit",
  });
}

const STAGE_LABEL = {
  GROUP: "Gruppe", R32: "16-delsfinale", R16: "8-delsfinale",
  QF: "Kvartfinale", SF: "Semifinale", THIRD: "Bronsefinale", FINAL: "FINALE",
};

function stageBadge(m) {
  if (m.stage === "GROUP") return m.group ? `Gruppe ${m.group}` : "Gruppespill";
  return STAGE_LABEL[m.stage] || m.stage;
}

function eventIcon(e) {
  if (e.kind === "goal") return "⚽";
  return e.card === "RED" ? "🟥" : "🟨";
}

function eventSuffix(e) {
  if (e.kind !== "goal") return "";
  return e.type === "penalty" ? " (str)" : e.type === "own" ? " (selvmål)" : "";
}

function timelineRow(e) {
  const playable = e.kind === "goal" && e.video;
  const player = esc(e.player); // spillernavn kommer fra NRK/NIFS – escapes
  // Minutt + ikon (f.eks. 15'🟨). Flagget droppes – siden av tidslinjen viser
  // allerede hvilket lag hendelsen tilhører.
  const label =
    `${e.minute}'${eventIcon(e)} ${player}${eventSuffix(e)}` +
    (playable ? ' <span class="hl-play">▶</span>' : "");
  const cell = playable
    ? `<button class="hl-event hl-clip" data-clip="${e.video}" data-title="${player} ${e.minute}'" onclick="event.stopPropagation();openClip(this.dataset.clip,this.dataset.title)">${label}</button>`
    : `<span class="hl-event">${label}</span>`;
  return `<div class="hl-row hl-${e.side}"><div class="hl-cell">${cell}</div></div>`;
}

function highlightsBlock(h) {
  if (!h || !h.events || !h.events.length) return "";
  const rows = h.events.map(timelineRow).join("");
  return `<div class="hl-timeline">
      <div class="hl-cap">Start</div>
      ${rows}
      <div class="hl-cap">Slutt</div>
    </div>`;
}

function reportBlock(url) {
  if (!url) return "";
  // Lenke til NRKs kampside (høydepunkter + rapport). stopPropagation så klikk
  // på lenka ikke lukker kampkortet.
  return `<a class="match-report" href="${url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">
      📺 Se høydepunkter og rapport hos NRK →
    </a>`;
}

function kikBlock(m) {
  if (!m.duell || !m.duell.length) return "";
  return `<div class="kik"><h4>🔗 Kamp i kampen</h4><canvas class="kik-canvas"></canvas></div>`;
}

function matchCard(m, live) {
  const played = m.goals_home !== null && m.goals_home !== undefined;
  const score = played
    ? `${m.goals_home}–${m.goals_away}`
    : new Date(m.date).toLocaleTimeString("no-NO", { hour: "2-digit", minute: "2-digit" });
  const inner = highlightsBlock(m.highlights) + reportBlock(m.report_url) + kikBlock(m);
  const expandable = inner.length > 0;
  if (m.duell && m.duell.length) {
    DUELL.set(m.id, { duell: m.duell, homeFlag: m.home_flag, awayFlag: m.away_flag });
  }
  const cls = `match ${live ? "live" : ""}${expandable ? " clickable" : ""}`;
  const onclick = expandable ? ' onclick="toggleMatch(this)"' : "";
  return `
    <div class="${cls}"${onclick} data-mid="${m.id}">
      <div class="team"><span>${m.home_flag}</span><span class="name">${m.home}</span></div>
      <div class="score">${score}</div>
      <div class="team away"><span class="name">${m.away}</span><span>${m.away_flag}</span></div>
      <div class="when">${fmtDate(m.date)} · ${stageBadge(m)}${m.pens ? " · " + m.pens : ""}${live ? " · PÅGÅR" : ""}${expandable ? " · 👆 detaljer" : ""}</div>
      ${inner}
    </div>`;
}

/* ── Tidslinje: vei gjennom mesterskapet ─────────────────────────────────── */
// Stage-starter for VM 2026 (faste datoer). Brukes til progresjons-indikatoren.
const STAGES_TL = [
  { key: "GROUP", label: "Gruppespill",   start: "2026-06-11" },
  { key: "R32",   label: "16-delsfinale", start: "2026-06-28" },
  { key: "R16",   label: "8-delsfinale",  start: "2026-07-04" },
  { key: "QF",    label: "Kvartfinale",   start: "2026-07-09" },
  { key: "SF",    label: "Semifinale",    start: "2026-07-14" },
  { key: "FINAL", label: "Finale",        start: "2026-07-19" },
];
// Tidsaksen går fra første kamp til finalen. Stage-prikkene plasseres
// proporsjonalt med antall dager inn i perioden, slik at det lange gruppespillet
// får mer plass enn de tette sluttrundene. Marker-prikken («vi er her») står på
// samme datoskala, så avstanden den har flyttet seg speiler faktisk forløp.
function stageStarts() {
  return STAGES_TL.map((s) => new Date(s.start + "T00:00:00Z"));
}

function tournamentProgress(now) {
  const starts = stageStarts();
  const span = starts[starts.length - 1] - starts[0]; // første kamp → finale
  let idx = 0;
  for (let i = 0; i < starts.length; i++) if (now >= starts[i]) idx = i;
  const pct = Math.min(100, Math.max(0, ((now - starts[0]) / span) * 100));
  return { idx, pct };
}

function renderStageProgress(now) {
  const { idx, pct } = tournamentProgress(now);
  const starts = stageStarts();
  const span = starts[starts.length - 1] - starts[0];
  const stages = STAGES_TL.map((s, i) => {
    const state = i < idx ? "done" : i === idx ? "active" : "future";
    const left = ((starts[i] - starts[0]) / span) * 100;
    // Etikettene veksler over/under linja så de tette sluttrundene ikke kolliderer.
    const side = i % 2 === 0 ? "down" : "up";
    return `<div class="sp-stage ${state} ${side}" style="left:${left}%">
        <span class="sp-dot"></span><span class="sp-name">${s.label}</span>
      </div>`;
  }).join("");
  $("stage-progress").innerHTML = `
    <div class="sp">
      <div class="sp-line"></div>
      <div class="sp-line-fill" style="width:${pct}%"></div>
      <div class="sp-now" style="left:${pct}%" title="Vi er her"></div>
      ${stages}
    </div>`;
}

function renderTimelineStrip(matches) {
  // Siste resultater + pågående + neste kamper, samlet og sortert kronologisk,
  // med en «NÅ»-skillelinje mellom det som er spilt og det som kommer.
  const past = [...matches.finished, ...matches.live];
  const next = [...matches.upcoming];
  const byDate = (a, b) => new Date(a.date) - new Date(b.date);
  past.sort(byDate);
  next.sort(byDate);
  const liveSet = new Set(matches.live);
  const chips = [
    ...past.map((m) => matchCard(m, liveSet.has(m))),
    past.length && next.length ? '<div class="tl-now">Nå</div>' : "",
    ...next.map((m) => matchCard(m, false)),
  ].join("");
  const strip = $("timeline-strip");
  setMatchHTML(strip, chips || '<p style="color:var(--muted)">Ingen kamper å vise ennå.</p>');
  // Rull stripa slik at «Nå»-skillet er synlig (grensen mellom spilt og kommende).
  const nowEl = strip.querySelector(".tl-now");
  if (nowEl) strip.scrollLeft = Math.max(0, nowEl.offsetLeft - strip.clientWidth / 2);
}

function renderPodium(board) {
  // Topp 3, men tegnet i rekkefølgen 2 – 1 – 3 slik en ekte pall ser ut
  const top = board.slice(0, 3);
  if (top.length < 3) { $("podium").innerHTML = ""; return; }
  const order = [top[1], top[0], top[2]];
  const place = [2, 1, 3];
  const medal = { 1: "🥇", 2: "🥈", 3: "🥉" };
  $("podium").innerHTML = order.map((b, i) => {
    const p = place[i];
    return `
      <div class="podium-spot p${p}">
        <div class="podium-medal">${medal[p]}</div>
        <div class="podium-name">${b.name}</div>
        <div class="podium-pts">${b.total}<span>p</span></div>
        <div class="podium-block">${p}</div>
      </div>`;
  }).join("");
}

function renderConsensus(polls) {
  $("consensus").innerHTML = (polls || []).map((poll) => {
    const bars = poll.options.map((o) => `
      <div class="poll-row">
        <div class="poll-label">${o.flag ? o.flag + " " : ""}${o.label}</div>
        <div class="poll-track"><div class="poll-fill" style="width:${o.pct}%"></div></div>
        <div class="poll-count">${o.count} · ${o.pct}%</div>
      </div>`).join("");
    return `
      <div class="poll">
        <div class="poll-title">${poll.icon} ${poll.title}</div>
        ${bars}
      </div>`;
  }).join("");
}

// Plasseringene ved forrige besøk – sammenlikningsgrunnlag for ▲/▼ gjennom hele økta.
const RANK_SNAPSHOT_KEY = "vm_rank_snapshot";
let prevRanks = (() => {
  try { return JSON.parse(localStorage.getItem(RANK_SNAPSHOT_KEY)) || null; }
  catch { return null; }
})();

function rankDelta(name, rank) {
  if (!prevRanks || prevRanks[name] == null) return "";
  const d = prevRanks[name] - rank; // positiv = klatret oppover
  if (d === 0) return `<span class="lb-delta same" title="uendret siden sist">–</span>`;
  const up = d > 0;
  return `<span class="lb-delta ${up ? "up" : "down"}" title="${up ? "+" : "-"}${Math.abs(d)} siden sist">${up ? "▲" : "▼"}${Math.abs(d)}</span>`;
}

function renderLeaderboard(board) {
  const maxTotal = Math.max(1, ...board.map((b) => b.total));
  $("leaderboard").innerHTML = board.map((b) => {
    const medal = b.rank === 1 ? "🥇" : b.rank === 2 ? "🥈" : b.rank === 3 ? "🥉" : b.rank + ".";
    const securePct = (100 * b.secure) / maxTotal;
    const provPct = (100 * Math.max(0, b.total - b.secure)) / maxTotal;
    const rows = b.breakdown
      .filter((i) => i.status !== "pending" || i.points > 0)
      .map((i) => {
        const cls = i.status === "provisional" ? "prov" : i.points > 0 ? "got" : "";
        const star = i.status === "provisional" ? " *" : "";
        return `<tr><td>${i.label}</td><td class="pts ${cls}">${i.points}/${i.max}${star}</td></tr>`;
      }).join("");
    return `
      <div class="lb-row" onclick="this.classList.toggle('open')">
        <div class="lb-rank r${b.rank}">${medal}</div>
        <div>
          <div class="lb-name">${b.name}${rankDelta(b.name, b.rank)}</div>
          <div class="lb-sub">${b.secure} sikre poeng · tippet 🏆 ${b.vinner ?? "?"}</div>
        </div>
        <div class="lb-points">${b.total}</div>
        <div class="lb-bar" title="${b.secure} sikre + ${Math.max(0, b.total - b.secure)} foreløpige poeng">
          <div class="lb-bar-secure" style="width:${securePct}%"></div>
          <div class="lb-bar-prov" style="width:${provPct}%"></div>
        </div>
        <div class="lb-details">
          <table>${rows || "<tr><td>Ingen avgjorte spørsmål ennå</td></tr>"}</table>
          <p style="color:var(--muted)">* = foreløpig fasit · klikk for å lukke</p>
        </div>
      </div>`;
  }).join("");

  // Lagre dagens plasseringer slik at neste besøk kan vise endringen.
  try {
    const snap = {};
    board.forEach((b) => { snap[b.name] = b.rank; });
    localStorage.setItem(RANK_SNAPSHOT_KEY, JSON.stringify(snap));
  } catch { /* localStorage utilgjengelig – hopp over endringspiler */ }
}

function renderGroups(groups) {
  $("groups").innerHTML = Object.keys(groups).sort().map((letter) => {
    const rows = groups[letter].map((r) => `
      <tr class="${r.pos <= 2 ? "q" : ""}">
        <td class="team-cell">${r.flag} ${r.team}</td>
        <td>${r.played}</td><td>${r.gd > 0 ? "+" + r.gd : r.gd}</td><td class="pts">${r.pts}</td>
      </tr>`).join("");
    return `
      <div class="group-card">
        <h3>Gruppe ${letter}</h3>
        <table>
          <tr><th>Lag</th><th>K</th><th>+/-</th><th>P</th></tr>
          ${rows}
        </table>
      </div>`;
  }).join("");
}

function renderFacts(facts) {
  $("facts").innerHTML = facts.map((f) => `
    <div class="fact">
      <div class="fact-title">${f.icon} ${f.title}</div>
      <div class="fact-text">${f.text}</div>
    </div>`).join("");
}

function renderScorers(scorers) {
  const withGoals = (scorers || []).filter((s) => s.goals > 0);
  $("scorers-heading").hidden = withGoals.length === 0;
  $("scorers").innerHTML = withGoals.map((s) => `
    <div class="scorer-row">
      <span>${s.flag} ${s.player} <span class="badge">${s.team}</span></span>
      <span class="goals">${s.goals}</span>
    </div>`).join("");
}

function renderNews(news) {
  const link = $("news-link");
  if (link && news && news.url) link.href = news.url;
  const items = (news && news.items) || [];
  $("news").innerHTML = items.length
    ? items.map((n) => {
        const hasSummary = !!n.summary;
        const caret = hasSummary ? '<span class="news-caret">▾</span>' : "";
        const cls = hasSummary ? "news-item has-summary" : "news-item";
        const toggle = hasSummary ? ' onclick="this.classList.toggle(\'open\')"' : "";
        return `
        <article class="${cls}"${toggle}>
          <div class="news-time">${fmtDate(n.published)}</div>
          <div class="news-title"><span>${esc(n.title)}</span>${caret}</div>
          ${hasSummary ? `<div class="news-summary">${esc(n.summary)}</div>` : ""}
        </article>`;
      }).join("")
    : '<p style="color:var(--muted)">Ingen nyheter akkurat nå.</p>';
}

/* ── Treertabell ──────────────────────────────────────────────────────────── */
function renderThirds(thirds) {
  const sec = $("thirds-section");
  const el = $("thirds-table");
  if (!thirds || !thirds.length) { sec.hidden = true; return; }
  sec.hidden = false;

  const hasAnyPlayed = thirds.some((t) => t.played > 0);
  $("thirds-note").textContent = hasAnyPlayed
    ? "Topp 8 (grønt) går videre til 16-delsfinalen. Rangering etter FIFAs kriterier: poeng → målforskjell → scorede mål."
    : "Treertabellen fylles etter hvert som grupper fullføres. De 8 beste av 12 går videre til 16-delsfinalen.";

  const rows = thirds.map((t) => `
    <tr class="${t.advances ? "third-adv" : "third-out"}">
      <td class="td-rank">${t.rank}</td>
      <td class="td-team">${t.flag}&nbsp;${t.team}</td>
      <td class="td-center">${t.group}</td>
      <td class="td-center">${t.played}</td>
      <td class="td-center td-wdl">${t.w}–${t.d}–${t.l}</td>
      <td class="td-center">${t.gf}:${t.ga}</td>
      <td class="td-center">${t.gd > 0 ? "+" + t.gd : t.gd}</td>
      <td class="td-center pts">${t.pts}</td>
    </tr>`).join("");

  el.innerHTML = `
    <div class="table-scroll">
      <table class="thirds-tbl">
        <thead>
          <tr>
            <th>#</th>
            <th class="th-left">Lag</th>
            <th>Gr</th>
            <th>K</th>
            <th>S–U–T</th>
            <th>Mål</th>
            <th>+/−</th>
            <th>P</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* ── Bracket-tre ──────────────────────────────────────────────────────────── */

// Holder bracket-data for sunburst (fylles av renderBracket, leses av setBracketView)
let _bracketData = null;

function setBracketView(mode) {
  $("bracket-view").hidden = mode !== "bracket";
  $("sunburst-view").hidden = mode !== "sunburst";
  $("btn-bracket").classList.toggle("brac-active", mode === "bracket");
  $("btn-sunburst").classList.toggle("brac-active", mode === "sunburst");
  if (mode === "sunburst" && _bracketData) renderSunburst(_bracketData);
}
window.setBracketView = setBracketView;

const ROUND_LABELS = {
  R32: "16-delsfinale", R16: "8-delsfinale", QF: "Kvartfinale",
  SF: "Semifinale", THIRD: "Bronsefinale", FINAL: "FINALE",
};

function bracketNode(m) {
  if (!m) return `<div class="bn bn-tbd"><div class="bn-t"><span class="bn-f">?</span><span class="bn-n">TBD</span></div><div class="bn-t"><span class="bn-f">?</span><span class="bn-n">TBD</span></div></div>`;
  const played = m.status === "FINISHED";
  const homeWon = played && m.winner === "HOME_TEAM";
  const awayWon = played && m.winner === "AWAY_TEAM";
  const dt = m.date
    ? new Date(m.date).toLocaleDateString("no-NO", { day: "numeric", month: "short" })
    : "";
  return `
    <div class="bn${played ? " bn-done" : ""}">
      <div class="bn-t${homeWon ? " bn-win" : awayWon ? " bn-lose" : ""}">
        <span class="bn-f">${m.home_flag}</span><span class="bn-n">${m.home}</span>
        ${played ? `<span class="bn-sc">${m.goals_home}</span>` : ""}
      </div>
      <div class="bn-t${awayWon ? " bn-win" : homeWon ? " bn-lose" : ""}">
        <span class="bn-f">${m.away_flag}</span><span class="bn-n">${m.away}</span>
        ${played ? `<span class="bn-sc">${m.goals_away}</span>` : ""}
      </div>
      ${dt ? `<div class="bn-meta">${dt}</div>` : ""}
    </div>`;
}

function renderBracket(bracket) {
  const sec = $("bracket-section");
  const el = $("bracket-view");
  sec.hidden = false;
  _bracketData = bracket;

  // ── Web-layout: venstre halvdel → finale → høyre halvdel (møtes i midten)
  // Runder fra venstre til høyre: R32-L | R16-L | QF-L | SF-L | FINAL | SF-R | QF-R | R16-R | R32-R
  // «Halvdel» er de første / siste halvdelene av hvert rundes match-liste (sortert etter dato).
  function half(stage, side) {
    const ms = bracket[stage] || [];
    const n = Math.ceil(ms.length / 2);
    return side === "L" ? ms.slice(0, n) : ms.slice(n);
  }

  const TBD_NODE = bracketNode(null);

  function col(stage, side, label) {
    const ms = side ? half(stage, side) : (bracket[stage] || []);
    if (!ms.length && side) {
      // Fyll opp med TBD-noder for å beholde høydestrukturen
      const expected = { R32: 8, R16: 4, QF: 2, SF: 1 }[stage] || 1;
      return `<div class="brac-col" data-stage="${stage}">
        <div class="brac-lbl">${label}</div>
        <div class="brac-ms">${TBD_NODE.repeat(expected)}</div>
      </div>`;
    }
    return `<div class="brac-col" data-stage="${stage}">
      <div class="brac-lbl">${label}</div>
      <div class="brac-ms">${ms.map(bracketNode).join("")}</div>
    </div>`;
  }

  const finalMs = bracket["FINAL"] || [];
  const thirdMs = bracket["THIRD"] || [];
  const finalNode = finalMs.length ? bracketNode(finalMs[0]) : bracketNode(null);
  const thirdNode = thirdMs.length ? bracketNode(thirdMs[0]) : bracketNode(null);
  const centerCol = `<div class="brac-col brac-center">
    <div class="brac-lbl">⚽ FINALE</div>
    <div class="brac-ms brac-ms-final">${finalNode}</div>
    <div class="brac-lbl brac-lbl-bronze">🥉 Bronse</div>
    <div class="brac-ms">${thirdNode}</div>
  </div>`;

  // ── Mobilvisning: runde-for-runde seksjoner (stables vertikalt)
  const mobileRounds = ["R32", "R16", "QF", "SF", "FINAL", "THIRD"].map((stage) => {
    const ms = bracket[stage] || [];
    if (!ms.length) return "";
    return `<div class="brac-mobile-round">
      <div class="brac-mobile-lbl">${ROUND_LABELS[stage]}</div>
      <div class="brac-mobile-ms">${ms.map(bracketNode).join("")}</div>
    </div>`;
  }).join("");

  el.innerHTML = `
    <div class="brac-web">
      <div class="brac-grid">
        ${col("R32", "L", "16-df")}
        ${col("R16", "L", "8-df")}
        ${col("QF", "L", "KF")}
        ${col("SF", "L", "SF")}
        ${centerCol}
        ${col("SF", "R", "SF")}
        ${col("QF", "R", "KF")}
        ${col("R16", "R", "8-df")}
        ${col("R32", "R", "16-df")}
      </div>
    </div>
    <div class="brac-mobile">${mobileRounds}</div>`;
}

/* ── Sunburst-visning ─────────────────────────────────────────────────────── */
// Hvert oppgjør opptar en fast, lik andel av ringen: R32 = 1/16, R16 = 1/8,
// QF = 1/4, SF = 1/2 av 360°. Innenfor hvert oppgjørs slice deles vinkelen
// mellom de to lagene etter lagets totale Transfermarkt-verdi (home_mv / away_mv).
// Resultatet påvirker ikke skaleringen. Ringene nøstes etter bracket-treet:
// den innerste ringen setter rekkefølgen, og hver ring utenfor legger et oppgjørs
// to «barn» (kampene laga kom fra) rett under det – så oppgjørene flukter radialt
// og et lag kan følges innover. Alle segmenter har samme farge (konføderasjons-
// fargene ble for mye visuell støy).
const SUNBURST_BASE = 1;
const SUNBURST_FILL = "var(--accent)";

function arcPath(cx, cy, r1, r2, startDeg, endDeg) {
  // SVG-bue: r1 = indre radius, r2 = ytre; 0° = topp, medsols
  const rad = (d) => ((d - 90) * Math.PI) / 180;
  const px = (r, d) => cx + r * Math.cos(rad(d));
  const py = (r, d) => cy + r * Math.sin(rad(d));
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return [
    `M ${px(r2, startDeg).toFixed(2)} ${py(r2, startDeg).toFixed(2)}`,
    `A ${r2} ${r2} 0 ${large} 1 ${px(r2, endDeg).toFixed(2)} ${py(r2, endDeg).toFixed(2)}`,
    `L ${px(r1, endDeg).toFixed(2)} ${py(r1, endDeg).toFixed(2)}`,
    `A ${r1} ${r1} 0 ${large} 0 ${px(r1, startDeg).toFixed(2)} ${py(r1, startDeg).toFixed(2)}`,
    "Z",
  ].join(" ");
}

function renderSunburst(bracket) {
  const svg = $("sunburst-svg");
  if (!svg) return;
  const cx = 300, cy = 300;

  // Ringer fra ytterst til innerst: R32 → R16 → QF → SF → senterprikk (FINAL-vinner)
  const RING_DEFS = [
    { stage: "R32",   r1: 246, r2: 292 },
    { stage: "R16",   r1: 186, r2: 240 },
    { stage: "QF",    r1: 131, r2: 180 },
    { stage: "SF",    r1: 76,  r2: 125 },
  ];

  const parts = [];

  // Bygg rekkefølgen ring for ring ut fra bracket-treet, fra innerst til ytterst.
  // Den innerste ringen beholder gitt rekkefølge; hver ring utenfor ekspanderer
  // hvert oppgjør til sine to «barn» – kampene de to laga vant i ringen utenfor,
  // funnet via lagnavn. Da flukter et oppgjør nøyaktig med sine to barnekamper.
  const stageOrder = {};
  const inToOut = RING_DEFS.filter((r) => (bracket[r.stage] || []).length).reverse();
  inToOut.forEach((ring, idx) => {
    const ms = bracket[ring.stage] || [];
    if (idx === 0) {
      stageOrder[ring.stage] = ms.slice();
      return;
    }
    // Koble hvert lag til kampen det kom fra i denne (ytre) ringen.
    const byTeam = {};
    for (const m of ms) {
      if (byTeam[m.home] == null) byTeam[m.home] = m;
      if (byTeam[m.away] == null) byTeam[m.away] = m;
    }
    const used = new Set();
    const order = [];
    const take = (team) => {
      const m = byTeam[team];
      if (m && !used.has(m)) { used.add(m); order.push(m); }
    };
    // For hvert oppgjør i ringen innenfor: legg hjemmelagets barn, så bortelagets.
    for (const parent of stageOrder[inToOut[idx - 1].stage]) {
      take(parent.home);
      take(parent.away);
    }
    // Ta med kamper som ikke ble koblet (ukjente/TBD-lag) til slutt.
    for (const m of ms) if (!used.has(m)) order.push(m);
    stageOrder[ring.stage] = order;
  });

  for (const ring of RING_DEFS) {
    const ms = stageOrder[ring.stage];
    if (!ms || !ms.length) continue;

    // Hvert oppgjør opptar en fast, lik andel av ringen (1/antall kamper). Siden
    // rekkefølgen følger bracket-treet og alle ringer starter på 0°, flukter et
    // oppgjørs slice nøyaktig med de to barnekampene i ringen utenfor.
    const matchSpan = 360 / ms.length;
    let angle = 0;

    for (const m of ms) {
      const played = m.status === "FINISHED";
      const homeWon = played && m.winner === "HOME_TEAM";
      const awayWon = played && m.winner === "AWAY_TEAM";
      // Vektingen baseres alltid på lagets totale Transfermarkt-verdi – resultatet
      // påvirker ikke skaleringen. Fallback til SUNBURST_BASE om verdien mangler.
      const homeWeight = m.home_mv ? m.home_mv : SUNBURST_BASE;
      const awayWeight = m.away_mv ? m.away_mv : SUNBURST_BASE;

      // Del oppgjørets faste slice mellom hjemme og borte etter vektforhold.
      // Hjemme først, borte sist – samme rekkefølge som barnekampene legges i.
      const wSum = homeWeight + awayWeight || 1;
      const segs = [
        {
          name: m.home, flag: m.home_flag,
          span: matchSpan * (homeWeight / wSum),
          winner: homeWon,
        },
        {
          name: m.away, flag: m.away_flag,
          span: matchSpan * (awayWeight / wSum),
          winner: awayWon,
        },
      ];

      for (const seg of segs) {
        const opac = seg.winner ? "0.9" : "0.4";

        // Litt mellomrom mellom segmenter (0.6°)
        const path = arcPath(cx, cy, ring.r1, ring.r2, angle, angle + seg.span - 0.6);
        parts.push(`<path d="${path}" fill="${SUNBURST_FILL}" opacity="${opac}" stroke="var(--bg)" stroke-width="1">
          <title>${seg.flag} ${seg.name}${seg.winner ? " ✓" : ""}</title>
        </path>`);

        // Flagg-label der det er plass (> 12°)
        if (seg.span > 12) {
          const mid = angle + seg.span / 2;
          const rm = (ring.r1 + ring.r2) / 2;
          const rad = ((mid - 90) * Math.PI) / 180;
          const lx = (cx + rm * Math.cos(rad)).toFixed(1);
          const ly = (cy + rm * Math.sin(rad)).toFixed(1);
          parts.push(`<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle"
            font-size="${seg.span > 22 ? 11 : 8}" pointer-events="none">${seg.flag}</text>`);
        }
        angle += seg.span;
      }
    }
  }

  // Senterprikk: vinner av finalen (eller 🏆 om ukjent)
  const finalMs = bracket["FINAL"] || [];
  const finalPlayed = finalMs.length && finalMs[0].status === "FINISHED";
  if (finalPlayed) {
    const wFlag = finalMs[0].winner === "HOME_TEAM" ? finalMs[0].home_flag : finalMs[0].away_flag;
    const wName = (finalMs[0].winner === "HOME_TEAM" ? finalMs[0].home : finalMs[0].away).split(" ")[0].slice(0, 10);
    parts.push(`<circle cx="${cx}" cy="${cy}" r="70" fill="${SUNBURST_FILL}" opacity="0.9">
      <title>🏆 ${wName}</title>
    </circle>`);
    parts.push(`<text x="${cx}" y="${cy - 10}" text-anchor="middle" dominant-baseline="middle" font-size="26">${wFlag}</text>`);
    parts.push(`<text x="${cx}" y="${cy + 18}" text-anchor="middle" dominant-baseline="middle" font-size="9" fill="var(--bg2)" font-weight="700">${wName}</text>`);
  } else {
    parts.push(`<circle cx="${cx}" cy="${cy}" r="70" fill="var(--panel2)" stroke="var(--line)" stroke-width="2"/>`);
    parts.push(`<text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle" font-size="30">🏆</text>`);
  }

  svg.innerHTML = parts.join("");

  // Konføderasjons-legenden er fjernet – segmentene er nå ensfargede.
  const legendEl = $("sunburst-legend");
  if (legendEl) legendEl.innerHTML = "";
}

async function refresh() {
  try {
    const res = await fetch("/api/state");
    const s = await res.json();
    if (!s.ready) {
      $("loading").textContent = s.error
        ? "Klarte ikke hente data: " + s.error
        : "Laster scoreboard …";
      return;
    }
    $("loading").hidden = true;
    $("content").hidden = false;

    $("meta").innerHTML =
      `Oppdatert ${fmtDate(s.updated)}<br>Kilde: ${s.source}` +
      (s.demo ? ' · <b style="color:var(--gold)">DEMODATA</b>' : "");

    $("live-section").hidden = s.matches.live.length === 0;
    setMatchHTML($("live-matches"), s.matches.live.map((m) => matchCard(m, true)).join(""));

    const anyMatches =
      s.matches.live.length + s.matches.finished.length + s.matches.upcoming.length > 0;
    $("timeline-section").hidden = !anyMatches;
    if (anyMatches) {
      renderStageProgress(new Date());
      renderTimelineStrip(s.matches);
    }

    renderNews(s.news);
    renderPodium(s.leaderboard);
    renderLeaderboard(s.leaderboard);
    renderConsensus(s.consensus);
    renderThirds(s.thirds || []);
    renderBracket(s.bracket || {});
    renderGroups(s.groups);
    renderFacts(s.facts);
    renderScorers(s.scorers);
    $("footer-source").textContent =
      `Tippesvar: ${s.predictions_source} · Kampdata: ${s.source} · Oppdateres automatisk`;
  } catch (e) {
    console.error(e);
  }
}

refresh();
setInterval(refresh, 60_000);

// ---- Video-modal for NRK-høydepunktklipp ----
// Klippene er geoblokkert til Norge, og NRKs psapi gir bare manifestet til norske
// IP-er + whitelistede nrk.no-origins. Render-serveren står utenfor Norge, så et
// server-side oppslag ble alltid 404. Vi bygger derfor inn NRKs egen spiller
// (iframe mot nrk.no), som laster fra nrk.no: den resolver geo og spiller av i
// brukerens egen nettleser (som er i Norge) og håndterer HLS på iOS/Android/desktop
// selv. Da slipper vi både geoblokk-problemet og egen hls.js/nativ-avspilling.
function closeClip() {
  const modal = document.getElementById("clip-modal");
  const frame = modal.querySelector(".clip-frame");
  frame.removeAttribute("src"); // stopp avspillingen
  modal.hidden = true;
}

function openClip(uuid, title) {
  const modal = document.getElementById("clip-modal");
  const frame = modal.querySelector(".clip-frame");
  modal.querySelector(".clip-title").textContent = title || "Høydepunkt";
  frame.src = `https://www.nrk.no/video/embed/${encodeURIComponent(uuid)}`;
  modal.hidden = false;
}
