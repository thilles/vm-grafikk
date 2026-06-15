"use strict";
// «Kamp i kampen»: liten, avhengighetsfri force-directed nodegraf pr kampkort.
// Spillere fra de to landslagene som deler klubblag, knyttet gjennom en klubb-hub.
// Fler-instans: window.mountKik(canvas, duell, homeFlag, awayFlag) → { stop() }.

(function () {
  const COL = { club: "#60a5fa", home: "#fbbf24", away: "#4ade80" };

  function buildGraph(duell, homeFlag, awayFlag) {
    const nodes = [];
    const links = [];
    let i = 0;
    for (const c of duell) {
      const hub = { id: "c" + i++, type: "club", label: c.club };
      nodes.push(hub);
      const addSide = (players, side, flag) => {
        for (const p of players) {
          const n = { id: "p" + i++, type: side, label: p.name, flag };
          nodes.push(n);
          links.push({ s: hub, t: n });
        }
      };
      addSide(c.home, "home", homeFlag);
      addSide(c.away, "away", awayFlag);
    }
    return { nodes, links };
  }

  // Enkel fysikk: frastøtning mellom alle noder + fjær langs lenker + sentrering.
  function step(nodes, links, w, h) {
    for (let a = 0; a < nodes.length; a++) {
      for (let b = a + 1; b < nodes.length; b++) {
        const na = nodes[a], nb = nodes[b];
        let dx = na.x - nb.x, dy = na.y - nb.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2), f = 1400 / d2;
        const ux = dx / d, uy = dy / d;
        na.vx += ux * f; na.vy += uy * f;
        nb.vx -= ux * f; nb.vy -= uy * f;
      }
    }
    for (const l of links) {
      let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - 78) * 0.012, ux = dx / d, uy = dy / d;
      l.s.vx += ux * f; l.s.vy += uy * f;
      l.t.vx -= ux * f; l.t.vy -= uy * f;
    }
    for (const n of nodes) {
      n.vx += (w / 2 - n.x) * 0.012;
      n.vy += (h / 2 - n.y) * 0.012;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(46, Math.min(w - 46, n.x));
      n.y = Math.max(22, Math.min(h - 16, n.y));
    }
  }

  function mountKik(canvas, duell, homeFlag, awayFlag) {
    const { nodes, links } = buildGraph(duell, homeFlag, awayFlag);
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 260;
    const h = Math.max(150, 56 + nodes.length * 13);
    canvas.style.height = h + "px";
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    nodes.forEach((n, idx) => {
      const a = (idx / nodes.length) * Math.PI * 2;
      n.x = w / 2 + Math.cos(a) * 52;
      n.y = h / 2 + Math.sin(a) * 38;
      n.vx = 0; n.vy = 0;
    });

    let running = true, frame = 0;
    function draw() {
      if (!running) return;
      step(nodes, links, w, h);
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth = 1.2;
      for (const l of links) {
        ctx.beginPath();
        ctx.moveTo(l.s.x, l.s.y);
        ctx.lineTo(l.t.x, l.t.y);
        ctx.stroke();
      }
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const n of nodes) {
        const r = n.type === "club" ? 7 : 5;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fillStyle = COL[n.type];
        ctx.fill();
        ctx.font = n.type === "club" ? "600 12px system-ui" : "11px system-ui";
        ctx.fillStyle = "#e8f0e8";
        const txt =
          n.type === "club" ? n.label : (n.flag ? n.flag + " " : "") + n.label;
        ctx.fillText(txt, n.x, n.y - r - 7);
      }
      if (++frame < 600) requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
    return { stop() { running = false; } };
  }

  window.mountKik = mountKik;
})();
