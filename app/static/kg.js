"use strict";

const PREFIXES = {
  "http://example.org/wc2026/ontology#": "wc:",
  "http://example.org/wc2026/resource/": "wcr:",
  "http://xmlns.com/foaf/0.1/": "foaf:",
  "https://schema.org/": "schema:",
  "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
  "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
  "http://www.w3.org/2001/XMLSchema#": "xsd:",
};

const EXAMPLES = [
  {
    label: "Klubber med flest spillere",
    q: `PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?klubb (COUNT(?spiller) AS ?antall) WHERE {
  ?spiller wc:playsAtClub ?c . ?c rdfs:label ?klubb .
} GROUP BY ?klubb ORDER BY DESC(?antall) ?klubb LIMIT 15`,
  },
  {
    label: "Norges spillere",
    q: `PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?nr ?navn ?klubb WHERE {
  ?lag rdfs:label "Norway"@en ; wc:calledUp ?p .
  ?p foaf:name ?navn .
  OPTIONAL { ?p wc:shirtNumber ?nr }
  OPTIONAL { ?p wc:playsAtClub ?c . ?c rdfs:label ?klubb }
} ORDER BY ?nr`,
  },
  {
    label: "Mest verdifulle per lag",
    q: `PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT ?lag ?navn ?verdi WHERE {
  { SELECT ?t (MAX(?v) AS ?verdi) WHERE {
      ?t wc:calledUp ?pp . ?pp wc:marketValueEUR ?v .
    } GROUP BY ?t }
  ?t rdfs:label ?lag ; wc:calledUp ?p .
  ?p wc:marketValueEUR ?verdi ; foaf:name ?navn .
} ORDER BY DESC(?verdi)`,
  },
  {
    label: "Eldste spillere",
    q: `PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?navn ?født ?lag WHERE {
  ?p a wc:Player ; foaf:name ?navn ; wc:dateOfBirth ?født ;
     wc:playsForNationalTeam ?t .
  ?t rdfs:label ?lag .
} ORDER BY ?født LIMIT 15`,
  },
  {
    label: "Spillere i Premier League",
    q: `PREFIX wc: <http://example.org/wc2026/ontology#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?navn ?klubb WHERE {
  ?l rdfs:label "Premier League"@en .
  ?c wc:clubInLeague ?l ; rdfs:label ?klubb .
  ?p wc:playsAtClub ?c ; foaf:name ?navn .
} ORDER BY ?klubb ?navn`,
  },
  {
    label: "Klasser i ontologien",
    q: `PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?klasse ?navn WHERE {
  ?klasse a owl:Class . OPTIONAL { ?klasse rdfs:label ?navn }
} ORDER BY ?klasse`,
  },
];

const $ = (id) => document.getElementById(id);

function shorten(uri) {
  for (const [full, pre] of Object.entries(PREFIXES)) {
    if (uri.startsWith(full)) return pre + uri.slice(full.length);
  }
  return uri;
}

function cellHtml(binding) {
  if (!binding) return "";
  if (binding.type === "uri") {
    const short = shorten(binding.value);
    return `<a href="${binding.value}" target="_blank" rel="noopener" title="${binding.value}">${short}</a>`;
  }
  let txt = binding.value;
  if (binding.datatype && binding.datatype.includes("decimal") && /^\d+(\.0)?$/.test(txt)) {
    txt = Number(parseFloat(txt)).toLocaleString("no-NO");
  }
  return `<span>${escapeHtml(txt)}</span>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function loadInfo() {
  try {
    const r = await fetch("/api/kg/info");
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "ukjent feil");
    const cls = Object.entries(d.classes)
      .map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ");
    $("kg-meta").innerHTML =
      `Grafen inneholder <b>${d.triples.toLocaleString("no-NO")}</b> triples — ${cls}.`;
    if (d.ask) $("kg-ask").hidden = false;  // vis spør-boksen kun når Claude er konfigurert
  } catch (e) {
    $("kg-meta").textContent = "Klarte ikke å laste graf-info: " + e.message;
  }
}

function renderExamples() {
  const box = $("kg-examples");
  EXAMPLES.forEach((ex) => {
    const b = document.createElement("button");
    b.className = "kg-chip";
    b.textContent = ex.label;
    b.onclick = () => { $("kg-query").value = ex.q; runQuery(); };
    box.appendChild(b);
  });
}

function renderSelect(data) {
  const vars = data.head.vars || [];
  const rows = data.results.bindings || [];
  if (!rows.length) return `<p class="hint">Ingen treff.</p>`;
  const head = vars.map((v) => `<th>${escapeHtml(v)}</th>`).join("");
  const body = rows.map((row) =>
    "<tr>" + vars.map((v) => `<td>${cellHtml(row[v])}</td>`).join("") + "</tr>"
  ).join("");
  return `<div class="kg-table-wrap"><table class="kg-table">
      <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

async function runQuery() {
  const query = $("kg-query").value;
  const limit = $("kg-limit").value || 200;
  const status = $("kg-status");
  const out = $("kg-result");
  status.textContent = "Kjører …";
  const t0 = performance.now();
  try {
    const r = await fetch("/api/kg/sparql?limit=" + encodeURIComponent(limit), {
      method: "POST",
      headers: { "Content-Type": "application/sparql-query" },
      body: query,
    });
    const ct = r.headers.get("content-type") || "";
    const ms = Math.round(performance.now() - t0);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: r.statusText }));
      out.innerHTML = `<p class="kg-error">⚠ ${escapeHtml(err.error || "Feil")}</p>`;
      status.textContent = `Feil (${r.status})`;
      return;
    }
    if (ct.includes("sparql-results+json")) {
      const data = await r.json();
      if ("boolean" in data) {
        out.innerHTML = `<p class="kg-bool">${data.boolean ? "✅ true" : "❌ false"}</p>`;
      } else {
        const n = (data.results.bindings || []).length;
        const trunc = r.headers.get("X-Truncated") === "1";
        out.innerHTML = renderSelect(data);
        status.textContent = `${n} rad(er)${trunc ? " (avkortet)" : ""} · ${ms} ms`;
        return;
      }
    } else {
      const text = await r.text();
      out.innerHTML = `<pre class="kg-turtle">${escapeHtml(text)}</pre>`;
    }
    status.textContent = `Ferdig · ${ms} ms`;
  } catch (e) {
    out.innerHTML = `<p class="kg-error">⚠ ${escapeHtml(e.message)}</p>`;
    status.textContent = "Feil";
  }
}

// Naturlig språk → SPARQL via Claude (/api/kg/ask)
async function askQuestion() {
  const q = $("kg-ask-input").value.trim();
  if (!q) return;
  const status = $("kg-ask-status");
  const answer = $("kg-ask-answer");
  const btn = $("kg-ask-btn");
  const out = $("kg-result");
  status.textContent = "Tenker … (oversetter til SPARQL og kjører)";
  answer.hidden = true;
  btn.disabled = true;
  try {
    const r = await fetch("/api/kg/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ "spørsmål": q }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (d.sparql) $("kg-query").value = d.sparql;  // vis spørringen som feilet
      status.textContent = "⚠ " + (d.error || `Feil (${r.status})`);
      return;
    }
    $("kg-query").value = d.sparql || "";  // synlig og redigerbar i SPARQL-feltet
    if (d.results && "boolean" in d.results) {
      out.innerHTML = `<p class="kg-bool">${d.results.boolean ? "✅ true" : "❌ false"}</p>`;
      $("kg-status").textContent = `Ferdig · ${d.ms} ms`;
    } else if (d.results) {
      const n = (d.results.results.bindings || []).length;
      out.innerHTML = renderSelect(d.results);
      $("kg-status").textContent = `${n} rad(er)${d.truncated ? " (avkortet)" : ""} · ${d.ms} ms`;
    } else if (d.turtle != null) {
      out.innerHTML = `<pre class="kg-turtle">${escapeHtml(d.turtle)}</pre>`;
      $("kg-status").textContent = `Ferdig · ${d.ms} ms`;
    }
    if (d.svar) { answer.textContent = d.svar; answer.hidden = false; }
    status.textContent = "Ferdig.";
  } catch (e) {
    status.textContent = "⚠ " + e.message;
  } finally {
    btn.disabled = false;
  }
}

// Ctrl/Cmd+Enter kjører spørringen
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); runQuery(); }
});

$("kg-ask-btn").onclick = askQuestion;
$("kg-ask-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); askQuestion(); }
});
$("kg-run").onclick = runQuery;
renderExamples();
$("kg-query").value = EXAMPLES[0].q;
loadInfo();
runQuery();
