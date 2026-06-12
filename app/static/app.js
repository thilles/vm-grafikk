/* Frontend for tippekonkurranse-scoreboardet. Leser alt fra /api/state. */

const $ = (id) => document.getElementById(id);

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

function goalLabel(g) {
  const extra = g.type === "penalty" ? " (str)" : g.type === "own" ? " (selvmål)" : "";
  return `<li>⚽ ${g.minute}' ${g.flag} ${g.player}${extra}</li>`;
}

function cardLabel(c) {
  return `<li>${c.card === "RED" ? "🟥" : "🟨"} ${c.minute}' ${c.flag} ${c.player}</li>`;
}

function highlightsBlock(h) {
  if (!h || (!h.goals.length && !h.cards.length)) return "";
  const goals = h.goals.length
    ? `<div class="hl-col"><h4>⚽ Mål</h4><ul>${h.goals.map(goalLabel).join("")}</ul></div>`
    : "";
  const cards = h.cards.length
    ? `<div class="hl-col"><h4>🟨 Kort</h4><ul>${h.cards.map(cardLabel).join("")}</ul></div>`
    : "";
  return `<div class="match-details">${goals}${cards}</div>`;
}

function matchCard(m, live) {
  const played = m.goals_home !== null && m.goals_home !== undefined;
  const score = played
    ? `${m.goals_home}–${m.goals_away}`
    : new Date(m.date).toLocaleTimeString("no-NO", { hour: "2-digit", minute: "2-digit" });
  const details = highlightsBlock(m.highlights);
  const clickable = details
    ? ' clickable" onclick="this.classList.toggle(\'open\')"'
    : '"';
  return `
    <div class="match ${live ? "live" : ""}${clickable}>
      <div class="team"><span>${m.home_flag}</span><span class="name">${m.home}</span></div>
      <div class="score">${score}</div>
      <div class="team away"><span class="name">${m.away}</span><span>${m.away_flag}</span></div>
      <div class="when">${fmtDate(m.date)} · ${stageBadge(m)}${m.pens ? " · " + m.pens : ""}${live ? " · PÅGÅR" : ""}${details ? " · 👆 detaljer" : ""}</div>
      ${details}
    </div>`;
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
    $("live-matches").innerHTML = s.matches.live.map((m) => matchCard(m, true)).join("");
    $("finished-matches").innerHTML =
      s.matches.finished.map((m) => matchCard(m, false)).join("") ||
      '<p style="color:var(--muted)">Ingen spilte kamper ennå.</p>';
    $("upcoming-matches").innerHTML = s.matches.upcoming.map((m) => matchCard(m, false)).join("");

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
