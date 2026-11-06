// InvoiceFlow UI: no framework, three views, live run over Server-Sent Events.
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const inr = (x) => (x == null ? "—" : "₹" + Number(x).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const when = (iso) => new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const api = async (url, opts) => { const r = await fetch(url, opts); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); };
const toast = (msg) => { const t = Object.assign(document.createElement("div"), { className: "toast", textContent: msg }); document.body.append(t); setTimeout(() => t.remove(), 2600); };

let META = null;
const SAMPLE_INFO = {
  "01": ["happy", "Clean invoice, PO matches", "Apex · paper & toner"],
  "02": ["edge", "Duplicate in disguise", "Apex · re-formatted invoice no."],
  "03": ["edge", "Split PO goes over budget", "BlueLine · 2nd part-bill"],
  "04": ["edge", "Scanned, no PO number", "Delta · OCR + PO inference"],
  "05": ["edge", "Tax ID & bank changed", "Cobalt · impersonation risk"],
  "06": ["extra", "Slightly over PO", "Cobalt · inside tolerance"],
  "07": ["extra", "Blocked vendor", "Evergreen · failed KYC"],
  "08": ["extra", "Missing number, wrong GST", "BlueLine · vendor must fix"],
};

// ---------- routing ----------
function show() {
  const view = (location.hash.match(/#\/(\w+)/) || [, "process"])[1];
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== "view-" + view));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === view));
  const runId = (location.hash.match(/#\/process\/(\w+)/) || [])[1];
  if (view === "dashboard") loadDashboard();
  if (view === "reference") loadReference();
  if (view === "process" && runId) openRun(runId);
}
window.addEventListener("hashchange", show);

// ---------- intake ----------
async function init() {
  META = await api("/api/meta");
  $("#engine").textContent = "Extractor: " + META.extractor;
  $("#sample-list").innerHTML = META.samples.map((name) => {
    const [kind, title, sub] = SAMPLE_INFO[name.slice(0, 2)] || ["extra", name, ""];
    return `<button class="sample" data-name="${esc(name)}"><b><span class="tag ${kind}">${kind === "happy" ? "happy path" : kind}</span>${esc(title)}</b><span>${esc(sub)}</span></button>`;
  }).join("");
  $("#sample-list").onclick = (e) => { const b = e.target.closest(".sample"); if (b) start(api("/api/runs/sample/" + encodeURIComponent(b.dataset.name), { method: "POST" }), b.dataset.name); };
  const drop = $("#drop"), file = $("#file");
  file.onchange = () => file.files[0] && upload(file.files[0]);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  $("#new-run").onclick = () => { location.hash = "#/process"; $("#run").hidden = true; $("#intake").hidden = false; };
  $("#reset").onclick = async () => { if (!confirm("Reset demo data? This clears run history and restores the starting ledger.")) return; await api("/api/reset", { method: "POST" }); toast("Demo data reset"); show(); };
  $("#filters").onclick = (e) => { const c = e.target.closest(".chip"); if (!c) return; document.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === c)); renderRuns(); };
  $("#search").oninput = renderRuns;
  show();
}

function upload(f) {
  const fd = new FormData(); fd.append("file", f);
  start(api("/api/runs", { method: "POST", body: fd }), f.name);
}

// ---------- live run ----------
function stageShell() {
  $("#timeline").innerHTML = META.stages.map((s, i) => `
    <li class="stage pending" id="st-${s.key}">
      <div class="stage-row"><div class="dot"><span>${i + 1}</span></div>
        <div class="stage-title"><b>${esc(s.title)}</b><small>${esc(s.hint)}</small></div><span class="ms mono"></span></div>
      <div class="stage-body"></div>
    </li>`).join("");
  $("#timeline").onclick = (e) => { const st = e.target.closest(".stage-row"); if (st) st.parentElement.classList.toggle("open"); };
}

async function start(promise, filename) {
  $("#intake").hidden = true; $("#run").hidden = false; $("#decision").hidden = true;
  $("#run-file").textContent = filename; $("#run-title").textContent = "Processing…"; $("#run-time").textContent = "";
  stageShell();
  let id;
  try { ({ id } = await promise); } catch (e) { toast(e.message); $("#run").hidden = true; $("#intake").hidden = false; return; }
  history.replaceState(null, "", "#/process/" + id);
  $("#preview").src = `/api/runs/${id}/file`; $("#open-file").href = `/api/runs/${id}/file`;
  // The backend is fast; pace the events so each stage is visible as it happens.
  const queue = []; let busy = false;
  const pump = async () => { if (busy) return; busy = true; while (queue.length) { const ev = queue.shift(); applyEvent(ev); await new Promise((r) => setTimeout(r, ev.type === "stage" && ev.status === "running" ? 320 : 120)); } busy = false; };
  const es = new EventSource(`/api/runs/${id}/events`);
  es.onmessage = (m) => { const ev = JSON.parse(m.data); queue.push(ev); if (ev.type === "done") es.close(); pump(); };
  es.onerror = () => es.close();
}

function applyEvent(ev) {
  if (ev.type === "stage") return renderStage(ev.stage, ev);
  if (ev.type === "done") renderDone(ev.run);
}

function renderStage(key, s) {
  const el = $("#st-" + key); if (!el) return;
  el.className = "stage " + (s.status === "done" ? "pass" : s.status) + (el.classList.contains("open") ? " open" : "");
  const dot = $(".dot", el);
  dot.innerHTML = { pass: "✓", done: "✓", warn: "!", fail: "✕", error: "✕", skipped: "–" }[s.status] || `<span>${META.stages.findIndex((x) => x.key === key) + 1}</span>`;
  $(".stage-title small", el).textContent = s.summary || META.stages.find((x) => x.key === key).hint;
  $(".ms", el).textContent = s.ms != null ? s.ms + " ms" : "";
  if (s.data) $(".stage-body", el).innerHTML = stageBody(key, s.data);
  if (["warn", "fail"].includes(s.status) && key !== "decide") el.classList.add("open");
}

function stageBody(key, d) {
  if (key === "read") return `<dl class="kv"><dt>Method</dt><dd>${d.method === "ocr" ? "OCR on scanned image" : "PDF text layer"}</dd><dt>Pages</dt><dd>${d.pages}</dd>
      ${d.ocr_confidence != null ? `<dt>OCR confidence</dt><dd>${Math.round(d.ocr_confidence * 100)}%</dd>` : ""}</dl>
      ${(d.notes || []).map((n) => `<div class="note">${esc(n)}</div>`).join("")}<pre class="raw">${esc(d.text)}</pre>`;
  if (key === "extract") {
    const f = d.fields, val = (v, fmt) => (v == null || v === "" ? '<span class="missing">not on invoice</span>' : esc(fmt ? fmt(v) : v));
    return `<dl class="kv"><dt>Extractor</dt><dd>${esc(d.extractor)}</dd><dt>Vendor</dt><dd>${val(f.vendor_name)}</dd><dt>GSTIN</dt><dd class="mono">${val(f.vendor_gstin)}</dd>
      <dt>Invoice no.</dt><dd>${val(f.invoice_number)}</dd><dt>Date</dt><dd>${val(f.invoice_date)}</dd><dt>PO reference</dt><dd>${val(f.po_reference)}</dd>
      <dt>Subtotal</dt><dd>${val(f.subtotal, inr)}</dd><dt>Tax</dt><dd>${val(f.tax_amount, inr)}</dd><dt>Total</dt><dd><b>${val(f.total, inr)}</b></dd>
      <dt>Bank a/c (last 4)</dt><dd>${val(f.bank_account_last4)}</dd></dl>
      ${f.line_items.length ? `<table class="lines"><tr><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr>${f.line_items.map((l) => `<tr><td>${esc(l.description)}</td><td class="r">${l.quantity ?? ""}</td><td class="r">${inr(l.unit_price)}</td><td class="r">${inr(l.amount)}</td></tr>`).join("")}</table>` : ""}
      ${(d.notes || []).map((n) => `<div class="note">${esc(n)}</div>`).join("")}`;
  }
  if (key === "decide") return `<p>${esc(d.explanation)}</p>`;
  return `<ul class="checks">${d.map((c) => `<li><span class="ic ${c.status}">${{ pass: "✓", warn: "!", fail: "✕", info: "i" }[c.status]}</span><div><b>${esc(c.title)}</b>${esc(c.detail)}</div></li>`).join("")}</ul>`;
}

function renderDone(run) {
  $("#run-time").textContent = run.duration_ms != null ? `${(run.duration_ms / 1000).toFixed(2)} s end to end` : "";
  if (run.status === "error") { $("#run-title").textContent = "Could not process this file"; decisionCard({ decision: "REJECT", headline: "Processing error", reasons: [run.error], next_action: "Check the file is a readable invoice and try again.", owner: "AP team" }); return; }
  $("#run-title").textContent = `${run.vendor || "Unknown vendor"} · ${run.invoice_number || "no invoice no."} · ${inr(run.total)}`;
  decisionCard(run.result);
}

function decisionCard(r) {
  const el = $("#decision");
  el.className = "decision " + r.decision; el.hidden = false;
  el.innerHTML = `<div class="big">${{ APPROVE: "APPROVED", HOLD: "ON HOLD", REJECT: "REJECTED" }[r.decision] || r.decision}</div><h3>${esc(r.headline)}</h3>
    ${r.explanation ? `<p style="font-size:13px;margin-bottom:8px">${esc(r.explanation)}</p>` : ""}
    <ul>${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <div class="action"><b>Next step · ${esc(r.owner)}</b>${esc(r.next_action)}</div>
    ${r.vendor_email ? `<div class="email"><div class="card-head" style="padding:0;border:0"><b style="font-size:13px">Draft email to vendor</b><button class="ghost" id="copy">Copy</button></div><pre>${esc(r.vendor_email)}</pre></div>` : ""}`;
  const c = $("#copy", el); if (c) c.onclick = () => navigator.clipboard.writeText(r.vendor_email).then(() => toast("Email copied"));
}

async function openRun(id) {
  const run = await api("/api/runs/" + id).catch(() => null);
  if (!run) return;
  $("#intake").hidden = true; $("#run").hidden = false; $("#run-file").textContent = run.filename;
  stageShell();
  for (const [k, s] of Object.entries(run.stages)) renderStage(k, { ...s, status: s.status });
  $("#preview").src = `/api/runs/${id}/file`; $("#open-file").href = `/api/runs/${id}/file`;
  renderDone(run);
}

// ---------- dashboard ----------
let RUNS = [];
async function loadDashboard() {
  RUNS = await api("/api/runs");
  const done = RUNS.filter((r) => r.status === "done");
  const n = (d) => done.filter((r) => r.decision === d).length;
  const [a, h, x] = [n("APPROVE"), n("HOLD"), n("REJECT")];
  const approvedValue = done.filter((r) => r.decision === "APPROVE").reduce((s, r) => s + (r.total || 0), 0);
  const blocked = done.filter((r) => r.decision === "REJECT").reduce((s, r) => s + (r.total || 0), 0);
  const avg = done.length ? done.reduce((s, r) => s + (r.duration_ms || 0), 0) / done.length / 1000 : 0;
  const pct = (v) => (done.length ? Math.round((100 * v) / done.length) : 0);
  $("#kpis").innerHTML = `
    <div class="kpi"><small>Invoices processed</small><b>${done.length}</b><div class="bar"><i class="a" style="width:${pct(a)}%"></i><i class="h" style="width:${pct(h)}%"></i><i class="x" style="width:${pct(x)}%"></i></div></div>
    <div class="kpi"><small>Approved (touchless)</small><b>${a}</b><span class="sub">${pct(a)}% straight through</span></div>
    <div class="kpi"><small>On hold · need a person</small><b>${h}</b><span class="sub">${pct(h)}% routed with next step</span></div>
    <div class="kpi"><small>Rejected · payment stopped</small><b>${x}</b><span class="sub">${inr(blocked)} not paid out</span></div>
    <div class="kpi"><small>Value approved</small><b>${inr(approvedValue).replace(/\.\d+$/, "")}</b><span class="sub">avg ${avg.toFixed(1)} s per invoice</span></div>`;
  renderRuns();
}

function renderRuns() {
  const f = $("#filters .on").dataset.f, q = $("#search").value.toLowerCase();
  const rows = RUNS.filter((r) => (f === "ALL" || r.decision === f) && [r.vendor, r.invoice_number, r.po_number, r.filename].join(" ").toLowerCase().includes(q));
  $("#runs tbody").innerHTML = rows.map((r) => `<tr data-id="${r.id}">
      <td class="mono">${when(r.created_at)}</td><td><b>${esc(r.vendor || "—")}</b><span class="headline">${esc(r.filename)}</span></td>
      <td>${esc(r.invoice_number || "—")}</td><td>${esc(r.po_number || "—")}</td><td class="r">${inr(r.total)}</td>
      <td><span class="pill ${r.decision}">${esc(r.decision)}</span><span class="headline">${esc(r.headline || "")}</span></td>
      <td>${esc(r.decision === "APPROVE" ? "Payment run" : r.owner || "—")}</td><td class="r mono">${r.duration_ms != null ? (r.duration_ms / 1000).toFixed(2) + " s" : ""}</td></tr>`).join("");
  $("#runs-empty").hidden = rows.length > 0;
  $("#runs tbody").onclick = (e) => { const tr = e.target.closest("tr"); if (tr) location.hash = "#/process/" + tr.dataset.id; };
}

// ---------- reference ----------
async function loadReference() {
  const d = await api("/api/reference"), s = META.settings;
  $("#settings").textContent = `Tolerance: ${s.tolerance_pct}% or ${inr(s.tolerance_abs)} (whichever is lower) · unit price ±${s.unit_price_tolerance_pct}% · GST ${s.gst_rate}%`;
  $("#pos").innerHTML = `<tr><th>PO</th><th>Vendor</th><th>Description</th><th class="r">Amount (pre-tax)</th><th>Billed so far</th><th>Status</th></tr>` + d.purchase_orders.map((p) => {
    const pct = Math.min(100, (100 * p.billed) / p.subtotal);
    return `<tr><td class="mono">${p.po_number}</td><td>${esc(p.vendor_id)}</td><td>${esc(p.description)}<span class="headline">${p.lines.map((l) => `${l.qty} × ${esc(l.item)} @ ${inr(l.unit_price)}`).join(" · ")}</span></td>
      <td class="r">${inr(p.subtotal)}</td><td><span class="progress"><i style="width:${pct}%"></i></span>${inr(p.billed)}</td><td><span class="pill ${p.status}">${p.status}</span></td></tr>`;
  }).join("");
  $("#vendors").innerHTML = `<tr><th>ID</th><th>Vendor</th><th>GSTIN</th><th>Bank a/c</th><th>Terms</th><th>Status</th></tr>` + d.vendors.map((v) =>
    `<tr><td class="mono">${v.vendor_id}</td><td><b>${esc(v.name)}</b><span class="headline">${esc(v.contact_email)}</span></td><td class="mono">${v.gstin}</td><td class="mono">…${v.bank_last4}</td><td>${v.payment_terms_days} days</td>
      <td><span class="pill ${v.status}">${v.status}</span>${v.status_reason ? `<span class="headline">${esc(v.status_reason)}</span>` : ""}</td></tr>`).join("");
  $("#ledger").innerHTML = `<tr><th>Vendor</th><th>Invoice</th><th>Date</th><th>PO</th><th class="r">Total</th><th>Status</th><th>Recorded</th></tr>` + d.ledger.map((l) =>
    `<tr><td class="mono">${l.vendor_id}</td><td>${esc(l.invoice_number || "—")}</td><td>${esc(l.invoice_date || "—")}</td><td class="mono">${esc(l.po_number || "—")}</td><td class="r">${inr(l.total)}</td><td><span class="pill ${l.status}">${l.status}</span></td><td>${l.recorded_on}</td></tr>`).join("");
}

init();
