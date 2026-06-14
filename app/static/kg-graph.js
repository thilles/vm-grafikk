"use strict";
// Avhengighetsfri force-directed nodegraf på canvas.
// Visninger: ett landslag (lag→gruppe, spiller→liga), alle grupper, alle landslag.

const KG_TYPES = {
  team:          { color: "#fbbf24", r: 16, label: "Landslag" },
  confederation: { color: "#f97316", r: 15, label: "Konføderasjon" },
  group:         { color: "#60a5fa", r: 13, label: "Gruppe" },
  league:        { color: "#c084fc", r: 11, label: "Liga" },
  player:        { color: "#4ade80", r: 6,  label: "Spiller" },
};
const KG_LEGEND_ORDER = ["team", "confederation", "group", "league", "player"];

const WC = "http://example.org/wc2026/ontology#";
const Q_PREFIX =
  "PREFIX wc: <http://example.org/wc2026/ontology#>\n" +
  "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" +
  "PREFIX foaf: <http://xmlns.com/foaf/0.1/>\n";

(function () {
  const canvas = document.getElementById("kg-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const sel = document.getElementById("kg-team");
  const viewSel = document.getElementById("kg-view");
  const teamWrap = document.getElementById("kg-team-wrap");
  const statusEl = document.getElementById("kg-graph-status");
  const legendEl = document.getElementById("kg-legend");

  let nodes = [], links = [], byId = new Map();
  let width = 0, height = 520, dpr = 1;
  let alpha = 1;
  let dragNode = null, hoverNode = null, downAt = null, moved = false;

  function resize() {
    dpr = window.devicePixelRatio || 1;
    width = canvas.clientWidth || canvas.parentElement.clientWidth;
    height = Math.max(380, Math.min(640, Math.round(width * 0.62)));
    canvas.style.height = height + "px";
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function renderLegend() {
    const present = new Set(nodes.map((n) => n.type));
    legendEl.innerHTML = KG_LEGEND_ORDER.filter((t) => present.has(t)).map((t) =>
      `<span class="kg-leg"><i style="background:${KG_TYPES[t].color}"></i>${KG_TYPES[t].label}</span>`
    ).join("");
  }

  function setData(graph) {
    byId = new Map();
    nodes = graph.nodes.map((n) => {
      const node = {
        ...n,
        x: width / 2 + (Math.random() - 0.5) * width * 0.6,
        y: height / 2 + (Math.random() - 0.5) * height * 0.6,
        vx: 0, vy: 0,
      };
      byId.set(n.id, node);
      return node;
    });
    links = graph.links
      .map((l) => ({ source: byId.get(l.source), target: byId.get(l.target), rel: l.rel }))
      .filter((l) => l.source && l.target);
    alpha = 1;
    renderLegend();
  }

  function tick() {
    if (alpha < 0.01) return;
    const cx = width / 2, cy = height / 2;
    const REP = 1600, GRAV = 0.0015, SPRING = 0.04, REST = 64, DAMP = 0.86;
    for (const n of nodes) { n.vx += (cx - n.x) * GRAV; n.vy += (cy - n.y) * GRAV; }
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2), f = REP / d2;
        const ux = dx / d, uy = dy / d;
        a.vx += ux * f; a.vy += uy * f;
        b.vx -= ux * f; b.vy -= uy * f;
      }
    }
    for (const l of links) {
      let dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = SPRING * (d - REST), ux = dx / d, uy = dy / d;
      l.source.vx += ux * f; l.source.vy += uy * f;
      l.target.vx -= ux * f; l.target.vy -= uy * f;
    }
    for (const n of nodes) {
      if (n === dragNode) { n.vx = 0; n.vy = 0; continue; }
      n.vx *= DAMP; n.vy *= DAMP;
      n.x += n.vx * alpha; n.y += n.vy * alpha;
      n.x = Math.max(14, Math.min(width - 14, n.x));
      n.y = Math.max(14, Math.min(height - 14, n.y));
    }
    alpha *= 0.985;
  }

  function isNeighbor(n, h) {
    for (const l of links)
      if ((l.source === h && l.target === n) || (l.target === h && l.source === n)) return true;
    return false;
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    ctx.lineWidth = 1;
    for (const l of links) {
      const hot = hoverNode && (l.source === hoverNode || l.target === hoverNode);
      ctx.strokeStyle = hot ? "rgba(74,222,128,.55)" : "rgba(157,191,167,.18)";
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
    }
    ctx.font = "11px 'Segoe UI', system-ui, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (const n of nodes) {
      const t = KG_TYPES[n.type] || KG_TYPES.player;
      ctx.beginPath();
      ctx.arc(n.x, n.y, t.r, 0, Math.PI * 2);
      ctx.fillStyle = t.color;
      ctx.globalAlpha = hoverNode && hoverNode !== n && !isNeighbor(n, hoverNode) ? 0.3 : 1;
      ctx.fill();
      if (n === hoverNode) { ctx.lineWidth = 2; ctx.strokeStyle = "#eaf5ec"; ctx.stroke(); }
      ctx.globalAlpha = 1;
      if (n.type !== "player" || n === hoverNode || n === dragNode) {
        const label = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
        const w = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(11,31,18,.75)";
        ctx.fillRect(n.x - w / 2 - 3, n.y + t.r + 2, w + 6, 14);
        ctx.fillStyle = "#eaf5ec";
        ctx.fillText(label, n.x, n.y + t.r + 9);
      }
    }
  }

  function loop() { tick(); draw(); requestAnimationFrame(loop); }

  function nodeAt(x, y) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i], t = KG_TYPES[n.type] || KG_TYPES.player;
      const dx = x - n.x, dy = y - n.y;
      if (dx * dx + dy * dy <= (t.r + 4) * (t.r + 4)) return n;
    }
    return null;
  }
  function pos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  // ── trykk på node → bygg SPARQL-spørring nedenfor ──
  function queryForNode(n) {
    const u = "<" + n.id + ">";
    if (n.type === "team") {
      return Q_PREFIX + "SELECT ?nr ?spiller ?klubb WHERE {\n" +
        "  " + u + " wc:calledUp ?p . ?p foaf:name ?spiller .\n" +
        "  OPTIONAL { ?p wc:shirtNumber ?nr }\n" +
        "  OPTIONAL { ?p wc:playsAtClub ?c . ?c rdfs:label ?klubb }\n} ORDER BY ?nr";
    }
    if (n.type === "group") {
      return Q_PREFIX + "SELECT ?landslag WHERE {\n" +
        "  ?t wc:inGroup " + u + " ; rdfs:label ?landslag .\n} ORDER BY ?landslag";
    }
    if (n.type === "league") {
      return Q_PREFIX + "SELECT ?spiller ?klubb WHERE {\n" +
        "  ?c wc:clubInLeague " + u + " ; rdfs:label ?klubb .\n" +
        "  ?p wc:playsAtClub ?c ; foaf:name ?spiller .\n} ORDER BY ?klubb ?spiller";
    }
    if (n.type === "confederation") {
      return Q_PREFIX + "SELECT ?landslag WHERE {\n" +
        "  ?t wc:affiliatedTo " + u + " ; rdfs:label ?landslag .\n} ORDER BY ?landslag";
    }
    // player (eller annet): alle fakta om noden
    return Q_PREFIX + "SELECT ?egenskap ?verdi WHERE {\n  " + u + " ?egenskap ?verdi .\n}";
  }

  function exploreNode(n) {
    const ta = document.getElementById("kg-query");
    if (ta) ta.value = queryForNode(n);
    if (typeof window.runQuery === "function") window.runQuery();
    if (ta) ta.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  canvas.addEventListener("pointerdown", (e) => {
    const p = pos(e);
    dragNode = nodeAt(p.x, p.y);
    downAt = p; moved = false;
    if (dragNode) { canvas.setPointerCapture(e.pointerId); alpha = Math.max(alpha, 0.4); }
  });
  canvas.addEventListener("pointermove", (e) => {
    const p = pos(e);
    if (downAt && (Math.abs(p.x - downAt.x) > 4 || Math.abs(p.y - downAt.y) > 4)) moved = true;
    if (dragNode) { dragNode.x = p.x; dragNode.y = p.y; alpha = Math.max(alpha, 0.3); }
    else {
      const h = nodeAt(p.x, p.y);
      if (h !== hoverNode) hoverNode = h;
      canvas.style.cursor = h ? "pointer" : "default";
    }
  });
  canvas.addEventListener("pointerup", (e) => {
    const clicked = dragNode;
    dragNode = null; downAt = null;
    if (clicked && !moved) exploreNode(clicked);  // ekte klikk, ikke dra
  });
  canvas.addEventListener("pointerleave", () => { hoverNode = null; });

  async function load() {
    const view = viewSel ? viewSel.value : "team";
    teamWrap.style.display = view === "team" ? "" : "none";
    const url = view === "team"
      ? "/api/kg/graph?view=team&team=" + encodeURIComponent(sel.value || "Norway")
      : "/api/kg/graph?view=" + encodeURIComponent(view);
    statusEl.textContent = "Laster …";
    try {
      const r = await fetch(url);
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.statusText);
      resize();
      setData(d);
      statusEl.textContent = `${d.nodes.length} noder · ${d.links.length} kanter`;
    } catch (e) {
      statusEl.textContent = "Feil: " + e.message;
    }
  }

  async function init() {
    resize();
    try {
      const r = await fetch("/api/kg/teams");
      const d = await r.json();
      const teams = d.teams || [];
      sel.innerHTML = teams.map((t) => `<option${t === "Norway" ? " selected" : ""}>${t}</option>`).join("");
      sel.onchange = load;
      if (viewSel) viewSel.onchange = load;
      await load();
    } catch (e) {
      statusEl.textContent = "Klarte ikke å laste landslag: " + e.message;
    }
    loop();
  }

  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => { resize(); alpha = Math.max(alpha, 0.3); }, 200);
  });
  init();
})();
