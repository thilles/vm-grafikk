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
  const label =
    `${eventIcon(e)} ${e.minute}' ${e.flag} ${e.player}${eventSuffix(e)}` +
    (playable ? ' <span class="hl-play">▶</span>' : "");
  const cell = playable
    ? `<button class="hl-event hl-clip" data-clip="${e.video}" data-title="${e.player} ${e.minute}'" onclick="event.stopPropagation()">${label}</button>`
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
