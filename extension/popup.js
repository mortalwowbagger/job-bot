// job-bot popup: pick the matching prospect, fill the form on this tab, mark it applied.
const $ = (id) => document.getElementById(id);
const DEFAULT_API = "https://job-bot-app.web.app";
let api = DEFAULT_API, token = null, jobs = [], me = null, tab = null;

function show(id) { for (const s of ["disconnected", "main"]) $(s).hidden = s !== id; }
function error(msg) { $("err").hidden = !msg; $("err").textContent = msg || ""; }

async function call(path, opts = {}) {
  const r = await fetch(api + path, { ...opts, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" } });
  if (r.status === 401) { await chrome.storage.local.remove("token"); show("disconnected"); throw new Error("Please reconnect the extension."); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r;
}

// best guess at which prospect this page is for
function matchScore(j, url, title) {
  const strip = (u) => (u || "").split(/[?#]/)[0].replace(/\/(apply|application)\/?$/, "").replace(/\/$/, "");
  const page = strip(url);
  for (const u of [j.form_url, j.url]) {
    const s = strip(u);
    if (s && (page.startsWith(s) || s.startsWith(page))) return 100;
  }
  const words = (j.company || "").toLowerCase().split(/\W+/).filter((w) => w.length > 2);
  const hay = (url + " " + title).toLowerCase();
  const hits = words.filter((w) => hay.includes(w)).length;
  const titleWords = (j.title || "").toLowerCase().split(/\W+/).filter((w) => w.length > 3);
  const tHits = titleWords.filter((w) => hay.includes(w)).length;
  return (hits ? 40 + hits * 5 : 0) + tHits * 3;
}

function renderJobs() {
  const ranked = jobs.map((j) => ({ j, s: matchScore(j, tab.url || "", tab.title || "") }))
    .sort((a, b) => b.s - a.s || (b.j.score || 0) - (a.j.score || 0));
  $("job").innerHTML = "";
  for (const { j, s } of ranked) {
    const o = document.createElement("option");
    o.value = j.id;
    o.textContent = `${s >= 40 ? "★ " : ""}${j.company} — ${j.title}${j.status !== "tailored" ? ` (${j.status})` : ""}`;
    $("job").appendChild(o);
  }
  renderMeta();
}

function current() { return jobs.find((j) => j.id === $("job").value); }

function renderMeta() {
  const j = current();
  $("jobmeta").textContent = j ? `Score ${j.score ?? "–"} · ${j.location || ""}${j.has_packet ? "" : " · no resume packet"}` : "";
  $("fill").disabled = !j;
  $("applied").disabled = !j || j.status === "applied";
}

async function fileB64(jid, name) {
  const r = await call(`/files/${encodeURIComponent(jid)}/${encodeURIComponent(name)}`);
  const bytes = new Uint8Array(await r.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { name, b64: btoa(bin) };
}

async function fill() {
  error("");
  const j = current();
  $("fill").disabled = true;
  $("fill").textContent = "Filling…";
  try {
    const files = {};
    if (j.files && j.files.resume) files.resume = await fileB64(j.id, j.files.resume);
    if (j.files && j.files.letter) files.letter = await fileB64(j.id, j.files.letter);
    const payload = { contact: me.contact, cover_letter: j.cover_letter, files,
                      employment: me.employment || [], education: me.education || [] };
    const target = { tabId: tab.id, allFrames: true };
    let results;
    try {
      await chrome.scripting.executeScript({ target, files: ["fill.js"] });
      results = await chrome.scripting.executeScript({ target, func: (p) => self.jobbotFill(p), args: [payload] });
    } catch (e) { // a frame we may not touch: fall back to the page itself
      const main = { tabId: tab.id };
      await chrome.scripting.executeScript({ target: main, files: ["fill.js"] });
      results = await chrome.scripting.executeScript({ target: main, func: (p) => self.jobbotFill(p), args: [payload] });
    }
    // searchable dropdowns (months, school, degree) need the page's own context
    try {
      await chrome.scripting.executeScript({ target, world: "MAIN", files: ["select.js"] });
      results = results.concat(await chrome.scripting.executeScript({
        target, world: "MAIN", func: (p) => window.jobbotSelects(p), args: [payload] }));
    } catch (e) { /* frames we can't reach: text fields and files are already done */ }
    const filled = [...new Set(results.flatMap((r) => (r.result && r.result.filled) || []))];
    const notes = [...new Set(results.flatMap((r) => (r.result && r.result.notes) || []))];
    $("result").hidden = false;
    $("result").innerHTML = filled.length
      ? `<b>Filled:</b> ${filled.join(", ")}.<br><span class="meta">Now review every field, answer the rest yourself, and submit.</span>` +
        notes.map((n) => `<br><span class="meta">⚠ ${n}</span>`).join("")
      : `Nothing to fill here yet. Open the application form itself (click the site's <b>Apply</b> button), then try again.`;
  } catch (e) {
    error(/Cannot access|chrome:\/\//.test(e.message) ? "job-bot can't fill this kind of page." : e.message);
  } finally {
    $("fill").disabled = false;
    $("fill").textContent = "Fill this application";
  }
}

async function markApplied() {
  error("");
  const j = current();
  try {
    await call(`/api/jobs/${encodeURIComponent(j.id)}/mark`, { method: "POST", body: JSON.stringify({ status: "applied" }) });
    j.status = "applied";
    renderMeta();
    $("result").hidden = false;
    $("result").textContent = `Marked "${j.title}" as applied.`;
  } catch (e) { error(e.message); }
}

function openSite(settings) { chrome.tabs.create({ url: api + (settings ? "/?settings=1" : "/") }); }

(async () => {
  $("ver").textContent = "v" + chrome.runtime.getManifest().version;
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const st = await chrome.storage.local.get(["token", "api"]);
  token = st.token || null;
  api = st.api || DEFAULT_API;
  $("opensite").onclick = () => openSite(true);
  $("opensite2").onclick = () => openSite(false);
  $("fill").onclick = fill;
  $("applied").onclick = markApplied;
  $("job").onchange = renderMeta;
  if (!token) return show("disconnected");
  try {
    me = await (await call("/api/ext/me")).json();
    jobs = await (await call("/api/ext/jobs")).json();
    $("who").textContent = me.email || "";
    const mine = chrome.runtime.getManifest().version;
    const newer = (a, b) => { const x = a.split(".").map(Number), y = b.split(".").map(Number);
      for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
    if (me.extension_version && newer(me.extension_version, mine)) {
      $("update").hidden = false; $("newver").textContent = "v" + me.extension_version;
      $("getupdate").onclick = () => chrome.tabs.create({ url: api + "/job-bot-extension.zip?v=" + me.extension_version });
    }
    show("main");
    if (!jobs.length) { $("jobmeta").textContent = "No prospects yet. Run a search in job-bot."; $("fill").disabled = true; return; }
    renderJobs();
  } catch (e) { error(e.message); }
})();
