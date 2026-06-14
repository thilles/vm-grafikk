"use strict";
// Avhengighetsfri force-directed nodegraf på canvas: ett landslag → gruppe + spillere.

const KG_TYPES = {
  team: { color: "#fbbf24", r: 16, label: "Landslag" },
  group: { color: "#60a5fa", r: 13, label: "Gruppe" },
  player: { color: "#4ade80", r: 6, label: "Spiller" },
};
const KG_LEGEND_ORDER = ["team", "group", "player"];

const WC = "http://example.org/wc2026/ontology#";
const Q_PREFIX =
  "PREFIX wc: <http://example.org/wc2026/ontology#>\n" +
  "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n" +
  "PREFIX foaf: <http://xmlns.com/foaf/0.1/>\n";

(function () {
  const canvas = document.getElementById("kg-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const statusEl = document.getElementById("kg-graph-status");
  const legendEl = document.getElementById("kg-legend");

  let nodes = [],
    links = [],
    byId = new Map();
  let width = 0,
    height = 520,
    dpr = 1;
  let alpha = 1;
  let dragNode = null,
    hoverNode = null,
    downAt = null,
    moved = false;
  let big = false,
    rScale = 1,
    hubs = []; // store-visning: skaler ned + hybrid layout
  // visningstransform for zoom/panorering (verden → skjerm: p = w*k + t)
  let k = 1,
    tx = 0,
    ty = 0;
  const pointers = new Map(); // aktive peker-id → skjermposisjon
  let pinch = null; // {dist, k} ved to-finger-zoom

  function toWorld(px, py) {
    return { x: (px - tx) / k, y: (py - ty) / k };
  }
  function clampK(v) {
    return Math.max(0.3, Math.min(8, v));
  }
  function resetView() {
    k = 1;
    tx = 0;
    ty = 0;
  }
  function zoomAt(px, py, factor) {
    const nk = clampK(k * factor);
    tx = px - ((px - tx) * nk) / k;
    ty = py - ((py - ty) * nk) / k;
    k = nk;
  }

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
    legendEl.innerHTML = KG_LEGEND_ORDER.filter((t) => present.has(t))
      .map(
        (t) =>
          `<span class="kg-leg"><i style="background:${KG_TYPES[t].color}"></i>${KG_TYPES[t].label}</span>`,
      )
      .join("");
  }

  function setData(graph) {
    byId = new Map();
    nodes = graph.nodes.map((n, i) => {
      const node = {
        ...n,
        index: i,
        x: width / 2 + (Math.random() - 0.5) * width * 0.85,
        y: height / 2 + (Math.random() - 0.5) * height * 0.85,
        vx: 0,
        vy: 0,
      };
      byId.set(n.id, node);
      return node;
    });
    links = graph.links
      .map((l) => ({
        source: byId.get(l.source),
        target: byId.get(l.target),
        rel: l.rel,
      }))
      .filter((l) => l.source && l.target);
    // skaler ned nodene når det er mange (hele turneringen ~1300 noder)
    big = nodes.length > 150;
    rScale = nodes.length > 600 ? 0.4 : nodes.length > 150 ? 0.6 : 1;
    hubs = nodes.filter((n) => n.type !== "player"); // lag/grupper = navnoder
    // nodestørrelse etter markedsverdi: spiller ~ egen verdi, lag ~ aggregert
    // lagverdi. sqrt → arealet (ikke radien) skalerer med verdien.
    const pMax = Math.max(
      1,
      ...nodes.filter((n) => n.type === "player").map((n) => n.value || 0),
    );
    const tMax = Math.max(
      1,
      ...nodes.filter((n) => n.type === "team").map((n) => n.value || 0),
    );
    const gMax = Math.max(
      1,
      ...nodes.filter((n) => n.type === "group").map((n) => n.value || 0),
    );
    for (const n of nodes) {
      if (n.type === "player") n.r = 2.5 + 8 * Math.sqrt((n.value || 0) / pMax);
      else if (n.type === "team")
        n.r = 9 + 15 * Math.sqrt((n.value || 0) / tMax);
      else if (n.type === "group")
        n.r = 9 + 12 * Math.sqrt((n.value || 0) / gMax);
      else n.r = (KG_TYPES[n.type] || KG_TYPES.player).r;
    }
    if (big) computeAnchors();
    alpha = 1;
    renderLegend();
  }

  // Forankret, hierarkisk layout for hele-turneringen-grafen: 12 grupper i et
  // rutenett, lagene fordelt rundt sin gruppe, spillerne klynget rundt sitt lag.
  // Mye stabilt enn ren kraftlayout på ~1300 noder (ingen hjørne-klumping).
  function computeAnchors() {
    const teamsByGroup = new Map(),
      teamOfPlayer = new Map();
    for (const l of links) {
      if (l.rel === "inGroup") {
        if (!teamsByGroup.has(l.target.id)) teamsByGroup.set(l.target.id, []);
        teamsByGroup.get(l.target.id).push(l.source);
      } else if (l.rel === "calledUp") {
        teamOfPlayer.set(l.target.id, l.source);
      }
    }
    const groups = nodes
      .filter((n) => n.type === "group")
      .sort((a, b) => a.label.localeCompare(b.label));
    const cols = Math.ceil(Math.sqrt((groups.length * width) / height)) || 4;
    const rows = Math.ceil(groups.length / cols);
    const mx = width * 0.07,
      my = height * 0.09;
    const cw = (width - 2 * mx) / cols,
      ch = (height - 2 * my) / rows;
    groups.forEach((g, i) => {
      g.ax = mx + ((i % cols) + 0.5) * cw;
      g.ay = my + (Math.floor(i / cols) + 0.5) * ch;
      g.x = g.ax;
      g.y = g.ay;
      const teams = (teamsByGroup.get(g.id) || []).sort((a, b) =>
        a.label.localeCompare(b.label),
      );
      const rad = Math.min(cw, ch) * 0.3;
      teams.forEach((t, ti) => {
        const ang =
          (ti / Math.max(1, teams.length)) * Math.PI * 2 - Math.PI / 2;
        t.ax = g.ax + Math.cos(ang) * rad;
        t.ay = g.ay + Math.sin(ang) * rad;
        t.x = t.ax;
        t.y = t.ay;
      });
    });
    for (const n of nodes) {
      if (n.type === "player") {
        const t = teamOfPlayer.get(n.id);
        const bx = t && t.ax != null ? t.ax : width / 2;
        const by = t && t.ay != null ? t.ay : height / 2;
        n.x = bx + (Math.random() - 0.5) * 24;
        n.y = by + (Math.random() - 0.5) * 24;
      }
    }
  }

  function _repel(a, b, strength) {
    let dx = a.x - b.x,
      dy = a.y - b.y;
    const d2 = dx * dx + dy * dy || 0.01;
    const d = Math.sqrt(d2),
      f = strength / d2,
      ux = dx / d,
      uy = dy / d;
    a.vx += ux * f;
    a.vy += uy * f;
    b.vx -= ux * f;
    b.vy -= uy * f;
  }

  function tick() {
    if (alpha < 0.01) return;
    const DAMP = 0.86;

    if (!big) {
      // små grafer: full O(n²)-frastøtning + sentergravitasjon (best layout)
      const cx = width / 2,
        cy = height / 2;
      for (const n of nodes) {
        n.vx += (cx - n.x) * 0.0015;
        n.vy += (cy - n.y) * 0.0015;
      }
      for (let i = 0; i < nodes.length; i++)
        for (let j = i + 1; j < nodes.length; j++)
          _repel(nodes[i], nodes[j], 1600);
      for (const l of links) {
        let dx = l.target.x - l.source.x,
          dy = l.target.y - l.source.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = 0.04 * (d - 64),
          ux = dx / d,
          uy = dy / d;
        l.source.vx += ux * f;
        l.source.vy += uy * f;
        l.target.vx -= ux * f;
        l.target.vy -= uy * f;
      }
    } else {
      // hele turneringen: trekk grupper/lag mot sine ankere; spillere fjærkobles
      // til sitt lag og spres lokalt via et romlig rutenett (O(n), ikke O(n²)).
      for (const n of nodes) {
        if (n.ax != null) {
          n.vx += (n.ax - n.x) * 0.1;
          n.vy += (n.ay - n.y) * 0.1;
        }
      }
      const cs = 30,
        grid = new Map();
      for (const n of nodes) {
        const k = Math.floor(n.x / cs) + ":" + Math.floor(n.y / cs);
        let a = grid.get(k);
        if (!a) {
          a = [];
          grid.set(k, a);
        }
        a.push(n);
      }
      for (const n of nodes) {
        const gx = Math.floor(n.x / cs),
          gy = Math.floor(n.y / cs);
        for (let dx = -1; dx <= 1; dx++)
          for (let dy = -1; dy <= 1; dy++) {
            const arr = grid.get(gx + dx + ":" + (gy + dy));
            if (!arr) continue;
            for (const m of arr) if (m.index > n.index) _repel(n, m, 110);
          }
      }
      for (const l of links) {
        // kun lag→spiller; ankerne holder lag↔gruppe
        if (l.rel !== "calledUp") continue;
        let dx = l.target.x - l.source.x,
          dy = l.target.y - l.source.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = 0.06 * (d - 16),
          ux = dx / d,
          uy = dy / d;
        l.source.vx += ux * f;
        l.source.vy += uy * f;
        l.target.vx -= ux * f;
        l.target.vy -= uy * f;
      }
    }

    for (const n of nodes) {
      if (n === dragNode) {
        n.vx = 0;
        n.vy = 0;
        continue;
      }
      n.vx *= DAMP;
      n.vy *= DAMP;
      n.x += n.vx * alpha;
      n.y += n.vy * alpha;
      n.x = Math.max(8, Math.min(width - 8, n.x));
      n.y = Math.max(8, Math.min(height - 8, n.y));
    }
    alpha *= 0.985;
  }

  function neighborSet(h) {
    const s = new Set([h]);
    for (const l of links) {
      if (l.source === h) s.add(l.target);
      else if (l.target === h) s.add(l.source);
    }
    return s;
  }

  function draw() {
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.translate(tx, ty);
    ctx.scale(k, k); // zoom/panorering
    const hl = hoverNode ? neighborSet(hoverNode) : null; // beregn naboer én gang
    ctx.lineWidth = 1 / k;
    for (const l of links) {
      const hot =
        hoverNode && (l.source === hoverNode || l.target === hoverNode);
      ctx.strokeStyle = hot ? "rgba(74,222,128,.6)" : "rgba(157,191,167,.15)";
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
    }
    ctx.font = "11px 'Segoe UI', system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const n of nodes) {
      const t = KG_TYPES[n.type] || KG_TYPES.player;
      const r = (n.r != null ? n.r : t.r) * rScale;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = t.color;
      ctx.globalAlpha = hl && !hl.has(n) ? 0.25 : 1;
      ctx.fill();
      if (n === hoverNode) {
        ctx.lineWidth = 2 / k;
        ctx.strokeStyle = "#eaf5ec";
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      // etiketter: små grafer = alle navnoder; store = bare grupper; alltid hover/dra
      const showLabel =
        n === hoverNode ||
        n === dragNode ||
        (big ? n.type === "group" : n.type !== "player");
      if (showLabel) {
        const label =
          n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
        const w = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(11,31,18,.78)";
        ctx.fillRect(n.x - w / 2 - 3, n.y + r + 2, w + 6, 14);
        ctx.fillStyle = "#eaf5ec";
        ctx.fillText(label, n.x, n.y + r + 9);
      }
    }
    ctx.restore();
  }

  function loop() {
    tick();
    draw();
    requestAnimationFrame(loop);
  }

  function nodeAt(x, y) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i],
        t = KG_TYPES[n.type] || KG_TYPES.player;
      const hit = (n.r != null ? n.r : t.r) * rScale + 4;
      const dx = x - n.x,
        dy = y - n.y;
      if (dx * dx + dy * dy <= hit * hit) return n;
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
      return (
        Q_PREFIX +
        "SELECT ?nr ?spiller ?klubb ?verdi WHERE {\n" +
        "  " +
        u +
        " wc:calledUp ?p . ?p foaf:name ?spiller .\n" +
        "  OPTIONAL { ?p wc:shirtNumber ?nr }\n" +
        "  OPTIONAL { ?p wc:playsAtClub ?c . ?c rdfs:label ?klubb }\n" +
        "  OPTIONAL { ?p wc:marketValueEUR ?verdi }\n" +
        "} ORDER BY DESC(?verdi)"
      );
    }
    if (n.type === "group") {
      return (
        Q_PREFIX +
        "SELECT ?landslag ?verdi WHERE {\n" +
        "  ?t wc:inGroup " +
        u +
        " ; rdfs:label ?landslag .\n" +
        "  OPTIONAL { ?t wc:totalMarketValueEUR ?verdi }\n" +
        "} ORDER BY DESC(?verdi)"
      );
    }
    // player (eller annet): alle fakta om noden (inkl. wc:marketValueEUR)
    return (
      Q_PREFIX +
      "SELECT ?egenskap ?verdi WHERE {\n  " +
      u +
      " ?egenskap ?verdi .\n}"
    );
  }

  function exploreNode(n) {
    const ta = document.getElementById("kg-query");
    if (ta) ta.value = queryForNode(n);
    if (typeof window.runQuery === "function") window.runQuery();
    if (ta) ta.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  let panning = false;

  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    const p = pos(e);
    pointers.set(e.pointerId, p);
    if (pointers.size === 2) {
      // start to-finger-zoom
      const [a, b] = [...pointers.values()];
      pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y) || 1, k };
      dragNode = null;
      panning = false;
      return;
    }
    const w = toWorld(p.x, p.y);
    dragNode = nodeAt(w.x, w.y);
    downAt = p;
    moved = false;
    panning = !dragNode; // tom bakgrunn → panorering
    if (dragNode) alpha = Math.max(alpha, 0.4);
  });

  canvas.addEventListener("pointermove", (e) => {
    const prev = pointers.get(e.pointerId);
    const p = pos(e);
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, p);

    if (pinch && pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const target = clampK(pinch.k * (dist / pinch.dist));
      zoomAt(mid.x, mid.y, target / k);
      return;
    }
    if (downAt && (Math.abs(p.x - downAt.x) > 4 || Math.abs(p.y - downAt.y) > 4))
      moved = true;
    if (dragNode) {
      const w = toWorld(p.x, p.y);
      dragNode.x = w.x;
      dragNode.y = w.y;
      alpha = Math.max(alpha, 0.3);
    } else if (panning && prev) {
      tx += p.x - prev.x;
      ty += p.y - prev.y;
    } else {
      const w = toWorld(p.x, p.y);
      const h = nodeAt(w.x, w.y);
      if (h !== hoverNode) hoverNode = h;
      canvas.style.cursor = h ? "pointer" : "grab";
    }
  });

  function endPointer(e) {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0) {
      const clicked = dragNode;
      dragNode = null;
      downAt = null;
      panning = false;
      if (clicked && !moved) exploreNode(clicked); // ekte klikk, ikke dra/panorer
    }
  }
  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("pointerleave", () => {
    hoverNode = null;
  });

  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const p = pos(e);
      zoomAt(p.x, p.y, Math.exp(-e.deltaY * 0.0015));
    },
    { passive: false },
  );
  canvas.addEventListener("dblclick", resetView);

  async function load() {
    statusEl.textContent = "Laster …";
    try {
      const r = await fetch("/api/kg/graph?view=all");
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.statusText);
      resize();
      resetView();
      setData(d);
      statusEl.textContent = `${d.nodes.length} noder · ${d.links.length} kanter`;
    } catch (e) {
      statusEl.textContent = "Feil: " + e.message;
    }
  }

  async function init() {
    resize();
    await load();
    loop();
  }

  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      resize();
      if (big) computeAnchors();
      alpha = Math.max(alpha, 0.3);
    }, 200);
  });
  init();
})();
