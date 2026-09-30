"""Local dashboard: `python -m jobbot web` -> http://localhost:8000 (this machine only).

Reads the same jobs.db / output/ as the CLI. Long jobs (run, apply) are spawned as
`python -m jobbot ...` subprocesses so the CLI stays the single source of behavior.
The bot still never submits an application: "Pre-fill" opens the headed browser,
you review and submit, then mark the outcome here.
"""
import json
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import db
from .apply import form_url

MARKABLE = db.TRACKED
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VIEWS = {
    "review": ("status='tailored'", "score DESC"),
    "pipeline": ("status IN ('applied','interview','offer','rejected','withdrawn')",
                 "CASE status WHEN 'offer' THEN 0 WHEN 'interview' THEN 1 WHEN 'applied' THEN 2 ELSE 3 END, "
                 "COALESCE(applied_at, updated_at) DESC"),
    "near": ("status='low_score' AND score >= 50", "score DESC"),
    "skipped": ("status='skipped'", "updated_at DESC"),
}
FILE_TYPES = {".pdf", ".txt", ".md", ".html"}


class Proc:
    """One background CLI process with a rolling log."""

    def __init__(self):
        self.p, self.code, self.started, self.meta = None, None, None, {}
        self.lines = deque(maxlen=500)

    def running(self):
        return self.p is not None and self.p.poll() is None

    def start(self, root, args, **meta):
        self.lines.clear()
        self.code, self.started, self.meta = None, db.now(), meta
        self.p = subprocess.Popen([sys.executable, "-u", "-m", "jobbot", *args], cwd=root,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.p.stdout:
            self.lines.append(line.rstrip("\n"))
        self.code = self.p.wait()

    def state(self):
        lines = list(self.lines)
        step = next((m.group(0) for ln in reversed(lines)
                     if (m := re.match(r"\[\d/3\] .*", ln))), None)
        board = next((m.groups() for ln in reversed(lines)
                      if (m := re.search(r"\((\d+)/(\d+)\)", ln))), None)
        return {"running": self.running(), "started": self.started, "exit_code": self.code,
                "step": step, "board": board, "lines": lines[-80:], **self.meta}


def _section(md, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1) if m else ""


def _packet(job):
    """Parse the packet folder written by render.write_packet."""
    out = {"warnings": [], "answers": [], "cover_letter": "", "files": {}}
    d = Path(job["packet_dir"] or "")
    if not job["packet_dir"] or not d.is_dir():
        return out
    review = (d / "REVIEW.md").read_text() if (d / "REVIEW.md").exists() else ""
    out["warnings"] = re.findall(r"^- \[ \] (.+)$", _section(review, "Check before submitting"), re.M)
    if (d / "answers.md").exists():
        parts = re.split(r"^\*\*(.+?)\*\*\s*$", (d / "answers.md").read_text(), flags=re.M)
        out["answers"] = [{"q": q.strip(), "a": a.strip()} for q, a in zip(parts[1::2], parts[2::2])]
    if (d / "cover_letter.txt").exists():
        out["cover_letter"] = (d / "cover_letter.txt").read_text()
    for f in d.iterdir():
        if f.name.endswith("_Resume.pdf"):
            out["files"]["resume"] = f.name
        elif f.name.endswith("_Cover_Letter.pdf"):
            out["files"]["letter"] = f.name
    return out


def _summary(r):
    return {k: r[k] for k in ("id", "company", "title", "location", "score", "status", "source",
                              "applied_at", "notes", "url", "contact", "salary", "next_step",
                              "follow_up")} | {"form_url": form_url(dict(r))}


def create_app(root):
    root = Path(root)
    app = Flask(__name__)
    run, applying = Proc(), Proc()

    def con():
        return db.connect(str(root / "jobs.db"))

    @app.before_request
    def guard():
        # local only: reject other Host headers (DNS rebinding) and cross-site POSTs
        # (a custom header can't be sent cross-origin without a CORS preflight we never allow)
        if request.host.split(":")[0] not in ("localhost", "127.0.0.1"):
            abort(403)
        if request.method == "POST" and request.headers.get("X-JobBot") != "1":
            abort(403)

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error=getattr(e, "description", "Bad request")), 400

    @app.get("/")
    def index():
        return Response(PAGE, mimetype="text/html")

    @app.get("/api/state")
    def state():
        c = con()
        counts = db.counts(c)
        due = c.execute("SELECT COUNT(*) FROM jobs WHERE follow_up IS NOT NULL AND follow_up != '' "
                        "AND follow_up <= date('now','localtime') AND status IN ('applied','interview','offer')"
                        ).fetchone()[0]
        c.close()
        return jsonify(run=run.state(), apply=applying.state(), counts=counts, follow_ups_due=due)

    @app.get("/api/jobs")
    def jobs():
        where, order = VIEWS.get(request.args.get("view", "review"), VIEWS["review"])
        c = con()
        rows = c.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY {order} LIMIT 300").fetchall()
        out = []
        for r in rows:
            s = _summary(r)
            s["warnings"] = len(_packet(r)["warnings"]) if r["packet_dir"] else 0
            out.append(s)
        c.close()
        return jsonify(out)

    @app.get("/api/jobs/<int:job_id>")
    def job(job_id):
        c = con()
        r = db.get(c, job_id)
        c.close()
        if not r:
            abort(404)
        score = json.loads(r["score_json"] or "{}")
        c = con()
        timeline = [dict(e) for e in db.events(c, job_id)]
        c.close()
        return jsonify(_summary(r) | _packet(r) | {
            "description": r["description"], "has_packet": bool(r["packet_dir"]),
            "reasons": score.get("reasons", []), "concerns": score.get("concerns", []),
            "dealbreakers": score.get("dealbreakers", []), "keywords": score.get("keywords", []),
            "events": timeline})

    @app.get("/files/<int:job_id>/<name>")
    def files(job_id, name):
        c = con()
        r = db.get(c, job_id)
        c.close()
        if not r or not r["packet_dir"]:
            abort(404)
        d = Path(r["packet_dir"])
        # only plain files that are directly inside this job's packet folder
        if Path(name).suffix not in FILE_TYPES or name not in {f.name for f in d.iterdir()}:
            abort(404)
        return send_from_directory(d.resolve(), name)

    @app.post("/api/jobs/<int:job_id>/mark")
    def mark(job_id):
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in MARKABLE:
            abort(400)
        c = con()
        if not db.get(c, job_id):
            abort(404)
        db.set_status(c, job_id, status, note=(body.get("note") or "").strip()[:2000] or None)
        out = _summary(db.get(c, job_id))
        c.close()
        return jsonify(out)

    def _clean_details(body):
        fields = {}
        for k in db.DETAIL_FIELDS + ["notes"]:
            if k in body:
                v = str(body[k] or "").strip()[:2000]
                if k in ("applied_at", "follow_up") and v and not DATE.match(v[:10]):
                    abort(400, f"{k} must be YYYY-MM-DD")
                if k in ("company", "title") and not v:
                    abort(400, f"{k} is required")
                fields[k] = v or None
        return fields

    @app.post("/api/jobs/<int:job_id>/details")
    def details(job_id):
        c = con()
        if not db.get(c, job_id):
            abort(404)
        fields = _clean_details(request.get_json(silent=True) or {})
        if fields:
            db.update(c, job_id, **fields)
        out = _summary(db.get(c, job_id))
        c.close()
        return jsonify(out)

    @app.post("/api/jobs/<int:job_id>/events")
    def add_event(job_id):
        text = str((request.get_json(silent=True) or {}).get("text") or "").strip()[:2000]
        if not text:
            abort(400)
        c = con()
        if not db.get(c, job_id):
            abort(404)
        db.add_event(c, job_id, "note", text)
        c.close()
        return jsonify(ok=True)

    @app.post("/api/jobs")
    def add_job():
        body = request.get_json(silent=True) or {}
        fields = _clean_details(dict(body, company=body.get("company", ""), title=body.get("title", "")))
        status = body.get("status") or "applied"
        if status not in db.APPLICATION_STATUSES:
            abort(400)
        c = con()
        job_id = db.add_manual(c, fields.pop("company"), fields.pop("title"),
                               url=fields.pop("url", None) or "", location=fields.pop("location", None) or "",
                               applied_at=fields.pop("applied_at", None), status=status, **fields)
        if fields.get("notes"):
            db.update(c, job_id, notes=fields["notes"])
        c.close()
        return jsonify(id=job_id)

    @app.post("/api/jobs/<int:job_id>/prefill")
    def prefill(job_id):
        if applying.running():
            return jsonify(error="A browser is already open - close it first."), 409
        applying.start(root, ["apply", str(job_id), "--no-prompt"], job_id=job_id)
        return jsonify(ok=True)

    @app.post("/api/run")
    def start_run():
        if run.running():
            return jsonify(error="A run is already in progress."), 409
        run.start(root, ["run"])
        return jsonify(ok=True)

    return app


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job-bot</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1b1f24;--muted:#5d6670;--line:#e3e6ea;--accent:#2f5bd3;
 --accent-ink:#fff;--good:#1f7a4d;--warn:#a15c00;--bad:#b3261e;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--panel:#181c21;--ink:#e6e9ed;--muted:#9aa3ad;
 --line:#2a3037;--accent:#6d8ff0;--accent-ink:#0b0e12;--good:#4cc38a;--warn:#e0a33a;--bad:#ef6b62;--chip:#232931}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:12px 20px;background:var(--panel);
 border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
h1{font-size:16px;margin:0}
.counts{color:var(--muted);font-size:13px}
.spacer{flex:1}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:7px;
 padding:6px 11px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
button:hover,.btn:hover{border-color:var(--accent)}
.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
button:disabled{opacity:.5;cursor:default}
.runbox{font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.dot.on{background:var(--good);animation:p 1s infinite alternate}@keyframes p{to{opacity:.3}}
#log{display:none;margin:0;padding:10px 20px;max-height:240px;overflow:auto;background:#0b0e12;color:#cfd6de;
 font:12px/1.4 ui-monospace,Menlo,monospace;white-space:pre-wrap}
#applybar{display:none;padding:9px 20px;background:var(--chip);border-bottom:1px solid var(--line);font-size:13px}
main{display:grid;grid-template-columns:minmax(320px,440px) 1fr;min-height:calc(100vh - 57px)}
@media (max-width:900px){main{grid-template-columns:1fr}}
#listcol{border-right:1px solid var(--line);background:var(--panel)}
.tabs{display:flex;gap:4px;padding:10px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.tabs button{border:none;background:none;color:var(--muted)}
.tabs button.on{background:var(--chip);color:var(--ink);font-weight:600}
.row{padding:11px 14px;border-bottom:1px solid var(--line);cursor:pointer;display:grid;grid-template-columns:44px 1fr;gap:10px}
.row:hover{background:var(--chip)} .row.sel{background:var(--chip);box-shadow:inset 3px 0 var(--accent)}
.score{font-weight:700;font-size:15px;text-align:center;border-radius:7px;padding:6px 0;background:var(--chip);align-self:start}
.s85{color:var(--good)} .s70{color:var(--accent)} .slow{color:var(--muted)}
.co{font-weight:600} .ti{margin:1px 0 2px} .meta{color:var(--muted);font-size:12px}
.rowact{margin-top:7px;display:flex;gap:6px;flex-wrap:wrap}
.rowact .btn{padding:3px 9px;font-size:12px}
.tag{display:inline-block;background:var(--chip);border-radius:5px;padding:0 6px;font-size:11px;color:var(--muted);margin-left:4px}
.tag.w{color:var(--warn)}
#detail{padding:22px 26px;max-width:1000px}
.empty{color:var(--muted);padding:40px 20px;text-align:center}
.dh{display:flex;gap:14px;align-items:flex-start}
.dh .score{font-size:20px;padding:10px 12px;min-width:58px}
h2{margin:0;font-size:20px} h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:24px 0 8px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 6px}
.marks{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px}
.marks .cur{background:var(--chip);font-weight:600}
.note{display:flex;gap:6px;margin-top:8px}
.note input{flex:1;font:inherit;padding:6px 9px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink)}
.callout{border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:7px;padding:9px 12px;margin:10px 0;font-size:13px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px} @media (max-width:700px){.cols{grid-template-columns:1fr}}
ul.plain{margin:0;padding-left:18px} ul.plain li{margin:3px 0}
.checks label{display:flex;gap:8px;align-items:flex-start;padding:5px 0}
.pdf{width:100%;height:760px;border:1px solid var(--line);border-radius:8px;background:#fff}
.qa{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0;background:var(--panel)}
.qa b{display:block;margin-bottom:4px}
.letter,.desc{white-space:pre-wrap;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.desc{max-height:480px;overflow:auto;font-size:13px}
.kw span{display:inline-block;background:var(--chip);border-radius:5px;padding:1px 7px;margin:2px;font-size:12px}
.copy{float:right;font-size:12px;padding:2px 8px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}.grid .wide{grid-column:1/-1}
@media (max-width:700px){.grid{grid-template-columns:1fr}}
.grid label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted)}
.grid input,.grid textarea,.grid select{font:inherit;font-size:14px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:6px 9px}
.timeline{border-left:2px solid var(--line);margin:4px 0 8px 6px;padding-left:14px}
.ev{margin:6px 0}.due{color:var(--bad);font-weight:600}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);width:min(640px,92vw);padding:20px 22px}
dialog::backdrop{background:rgba(0,0,0,.35)}
</style></head><body>
<header>
  <h1>job-bot</h1><span class="counts" id="counts"></span><span class="spacer"></span>
  <span class="runbox"><span class="dot" id="dot"></span><span id="runtext">Idle</span>
    <button id="logbtn" onclick="toggleLog()">Log</button></span>
  <button onclick="openAdd()">+ Add application</button>
  <button class="primary" id="runbtn" onclick="startRun()">Run job search</button>
</header>
<pre id="log"></pre>
<dialog id="addmodal"><form id="addform" onsubmit="submitAdd(event)">
  <h2>Add an application</h2><p class="meta">For jobs you applied to outside job-bot.</p>
  <div class="grid">
    <label>Company *<input name="company" required></label>
    <label>Job title *<input name="title" required></label>
    <label>Applied on<input type="date" name="applied_at"></label>
    <label>Status<select name="status"><option>applied</option><option>interview</option><option>offer</option><option>rejected</option><option>withdrawn</option></select></label>
    <label>Location<input name="location" placeholder="Remote / Austin, TX"></label>
    <label>Salary<input name="salary"></label>
    <label>Contact<input name="contact" placeholder="Recruiter name, email"></label>
    <label>Follow up on<input type="date" name="follow_up"></label>
    <label class="wide">Job URL<input name="url" placeholder="https://..."></label>
    <label class="wide">Notes<textarea name="notes" rows="3"></textarea></label>
  </div>
  <div class="marks"><button class="primary" type="submit">Add application</button><button type="button" onclick="$('addmodal').close()">Cancel</button><span class="meta" id="adderr"></span></div>
</form></dialog>
<div id="applybar"></div>
<main>
  <section id="listcol">
    <div class="tabs" id="tabs"></div>
    <div id="list"></div>
  </section>
  <section id="detail"><div class="empty">Select a prospect.</div></section>
</main>
<script>
const TABS=[["review","To review"],["pipeline","Applied"],["near","Near misses (50+)"],["skipped","Skipped"]];
const MARKS=[["applied","Applied"],["interview","Interview"],["offer","Offer"],["rejected","Rejected"],["withdrawn","Withdrawn"],["skipped","Skip"],["tailored","Back to review"]];
const today=()=>new Date().toLocaleDateString("en-CA");
const ago=d=>{if(!d)return"";const n=Math.round((new Date(today())-new Date(d.slice(0,10)))/864e5);return n<=0?"today":n==1?"1d ago":n+"d ago"};
const fmt=d=>d?new Date(d.slice(0,10)+"T12:00").toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"";
let view="review", sel=null, wasRunning=false, wasApplying=false;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const scls=s=>s>=85?"s85":s>=70?"s70":"slow";
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{"Content-Type":"application/json","X-JobBot":"1"}});
  const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j}
const post=(p,b)=>api(p,{method:"POST",body:JSON.stringify(b||{})});

function renderTabs(){$("tabs").innerHTML=TABS.map(([k,l])=>`<button class="${k==view?"on":""}" onclick="setView('${k}')">${l}</button>`).join("")}
function setView(v){view=v;sel=null;renderTabs();loadList();$("detail").innerHTML='<div class="empty">Select a prospect.</div>'}
function appLink(j,small){if(!j.form_url)return"";return `<a class="btn ${small?"":"primary"}" href="${esc(j.form_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Open application ↗</a>`}

async function loadList(){
  const jobs=await api("/api/jobs?view="+view);
  if(!jobs.length){$("list").innerHTML=`<div class="empty">${view=="review"?"No packets waiting. Run a job search.":"Nothing here yet."}</div>`;return}
  $("list").innerHTML=jobs.map(j=>`<div class="row ${j.id==sel?"sel":""}" onclick="openJob(${j.id})">
    <div class="score ${scls(j.score)}">${j.score??"–"}</div>
    <div><div class="co">${esc(j.company)}<span class="tag">${esc(j.source)}</span>${j.warnings?`<span class="tag w">${j.warnings} to check</span>`:""}${view!="review"?`<span class="tag">${esc(j.status)}</span>`:""}</div>
    <div class="ti">${esc(j.title)}</div><div class="meta">#${j.id}${j.location?" · "+esc(j.location):""}${j.applied_at?` · applied ${fmt(j.applied_at)} (${ago(j.applied_at)})`:""}</div>
    ${j.next_step?`<div class="meta">Next: ${esc(j.next_step)}</div>`:""}
    ${j.follow_up&&["applied","interview","offer"].includes(j.status)?`<div class="meta ${j.follow_up<=today()?"due":""}">Follow up ${fmt(j.follow_up)}${j.follow_up<=today()?" — due":""}</div>`:""}
    <div class="rowact">${appLink(j,true)}</div></div></div>`).join("");
}

async function openJob(id){
  sel=id;document.querySelectorAll(".row").forEach(r=>r.classList.toggle("sel",r.getAttribute("onclick")==`openJob(${id})`));
  const j=await api("/api/jobs/"+id);
  const f=j.files||{}, file=n=>`/files/${j.id}/${encodeURIComponent(n)}`;
  const list=a=>a&&a.length?`<ul class="plain">${a.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:'<div class="meta">none</div>';
  $("detail").innerHTML=`
  <div class="dh"><div class="score ${scls(j.score)}">${j.score??"–"}</div>
    <div><h2>${esc(j.title)}</h2><div>${esc(j.company)}${j.location?" · "+esc(j.location):""}</div>
    <div class="meta">#${j.id} · ${esc(j.source)} · status: <b>${esc(j.status)}</b>${j.applied_at?` · applied ${fmt(j.applied_at)} (${ago(j.applied_at)})`:""}</div></div></div>
  <div class="actions">${appLink(j)}
    ${j.url&&j.url!=j.form_url?`<a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">Job posting ↗</a>`:""}
    ${j.has_packet?`<button onclick="prefill(${j.id})">Pre-fill in automated browser</button>`:""}
    ${f.resume?`<a class="btn" href="${file(f.resume)}" target="_blank">Resume PDF</a>`:""}
    ${f.letter?`<a class="btn" href="${file(f.letter)}" target="_blank">Cover letter PDF</a>`:""}</div>
  ${j.source=="ashby"?`<div class="callout">Ashby's spam filter can reject submissions from the automated browser. Use <b>Open application</b> and upload the PDFs from this packet.</div>`:""}
  <div class="marks"><span class="meta">Mark as:</span>${MARKS.filter(([s])=>s!="tailored"||j.has_packet).map(([s,l])=>`<button class="${j.status==s?"cur":""}" onclick="mark(${j.id},'${s}')">${l}</button>`).join("")}</div>
  <h3>Application details</h3>
  <div class="grid" id="det">
    <label>Applied on<input type="date" name="applied_at" value="${esc((j.applied_at||"").slice(0,10))}"></label>
    <label>Follow up on<input type="date" name="follow_up" value="${esc(j.follow_up||"")}"></label>
    <label>Next step<input name="next_step" value="${esc(j.next_step)}" placeholder="e.g. Hiring manager call Thu 2pm"></label>
    <label>Contact<input name="contact" value="${esc(j.contact)}" placeholder="Recruiter name, email"></label>
    <label>Salary<input name="salary" value="${esc(j.salary)}" placeholder="e.g. $120-140K"></label>
    <label>Location<input name="location" value="${esc(j.location)}"></label>
    <label class="wide">Job URL<input name="url" value="${esc(j.url)}"></label>
    <label class="wide">Notes<textarea name="notes" rows="3">${esc(j.notes)}</textarea></label>
  </div>
  <div class="marks"><button onclick="saveDetails(${j.id})">Save details</button><span class="meta" id="saved"></span></div>
  <h3>Timeline</h3>
  <div class="timeline">${(j.events||[]).map(e=>`<div class="ev"><span class="meta">${fmt(e.at)}</span> ${e.kind=="status"?`<b>${esc(e.text)}</b>`:esc(e.text)}</div>`).join("")||'<div class="meta">No activity yet.</div>'}</div>
  <div class="note"><input id="evtext" placeholder="Add to timeline (e.g. Recruiter screen with Dana, went well)" onkeydown="if(event.key=='Enter')addEvent(${j.id})"><button onclick="addEvent(${j.id})">Add</button></div>
  ${j.warnings.length?`<h3>Check before submitting</h3><div class="checks">${j.warnings.map(w=>`<label><input type="checkbox"> <span>${esc(w)}</span></label>`).join("")}</div>`:""}
  ${j.score==null?"":`<div class="cols"><div><h3>Why it matches</h3>${list(j.reasons)}</div><div><h3>Concerns</h3>${list(j.concerns)}${j.dealbreakers.length?`<h3>Dealbreakers</h3>${list(j.dealbreakers)}`:""}</div></div>`}
  ${j.keywords.length?`<h3>Key terms</h3><div class="kw">${j.keywords.map(k=>`<span>${esc(k)}</span>`).join("")}</div>`:""}
  ${j.answers.length?`<h3>Screening answer drafts</h3>${j.answers.map((a,i)=>`<div class="qa"><button class="copy" onclick="copyText(this,'a${i}')">Copy</button><b>${esc(a.q)}</b><div id="a${i}">${esc(a.a)}</div></div>`).join("")}`:""}
  ${j.cover_letter?`<h3>Cover letter <button class="copy" onclick="copyText(this,'cl')">Copy</button></h3><div class="letter" id="cl">${esc(j.cover_letter)}</div>`:""}
  ${f.resume?`<h3>Resume</h3><iframe class="pdf" src="${file(f.resume)}"></iframe>`:""}
  ${j.description?`<h3>Job description</h3><div class="desc">${esc(j.description)}</div>`:""}`;
}

async function mark(id,status){await post(`/api/jobs/${id}/mark`,{status});await refresh();openJob(id)}
const formData=el=>Object.fromEntries([...el.querySelectorAll("input,textarea,select")].map(i=>[i.name,i.value]));
async function saveDetails(id){try{await post(`/api/jobs/${id}/details`,formData($("det")));$("saved").textContent="Saved";loadList();poll()}catch(e){$("saved").textContent=e.message}}
async function addEvent(id){const t=$("evtext").value.trim();if(!t)return;await post(`/api/jobs/${id}/events`,{text:t});openJob(id)}
function openAdd(){$("addform").reset();$("addform").applied_at.value=today();$("adderr").textContent="";$("addmodal").showModal()}
async function submitAdd(ev){ev.preventDefault();try{const r=await post("/api/jobs",formData($("addform")));$("addmodal").close();view="pipeline";renderTabs();await refresh();openJob(r.id)}catch(e){$("adderr").textContent=e.message}}
async function prefill(id){try{await post(`/api/jobs/${id}/prefill`);poll()}catch(e){alertBar(e.message)}}
async function startRun(){try{await post("/api/run");$("log").style.display="block";poll()}catch(e){alertBar(e.message)}}
function copyText(btn,id){navigator.clipboard.writeText($(id).innerText).then(()=>{btn.textContent="Copied";setTimeout(()=>btn.textContent="Copy",1200)})}
function toggleLog(){const l=$("log");l.style.display=l.style.display=="block"?"none":"block";l.scrollTop=l.scrollHeight}
function alertBar(msg){const b=$("applybar");b.style.display="block";b.textContent=msg;setTimeout(()=>b.style.display="none",5000)}

async function poll(){
  const s=await api("/api/state"), r=s.run, a=s.apply, c=s.counts;
  const n=k=>c[k]||0;
  $("counts").textContent=`${n("tailored")} to review · ${n("applied")+n("interview")+n("offer")+n("rejected")+n("withdrawn")} applied · ${n("interview")} interviewing`+(s.follow_ups_due?` · ${s.follow_ups_due} follow-up${s.follow_ups_due>1?"s":""} due`:"");
  $("dot").classList.toggle("on",r.running); $("runbtn").disabled=r.running;
  if(r.running){$("runtext").textContent=(r.step||"Starting…")+(r.board&&(r.step||"").startsWith("[1/3]")?` (board ${r.board[0]}/${r.board[1]})`:"")}
  else if(r.started){const done=[...r.lines].reverse().find(l=>l.startsWith("Done."));$("runtext").textContent=r.exit_code?`Last run failed (exit ${r.exit_code}) — see log`:(done||"Last run finished")}
  if(r.lines.length){const l=$("log");const atEnd=l.scrollTop+l.clientHeight>=l.scrollHeight-20;l.textContent=r.lines.join("\n");if(atEnd)l.scrollTop=l.scrollHeight}
  if(wasRunning&&!r.running){view="review";renderTabs();loadList()}
  wasRunning=r.running;
  const bar=$("applybar");
  if(a.running){bar.style.display="block";bar.innerHTML=`Browser open for #${a.job_id}. Review everything, <b>submit it yourself</b>, close the window, then mark the outcome here. <span class="meta">${esc(a.lines.filter(l=>l.includes("Pre-filled")).pop()||"")}</span>`}
  else if(wasApplying){bar.style.display="block";bar.innerHTML=a.exit_code?`Pre-fill for #${a.job_id} stopped: ${esc(a.lines.slice(-2).join(" "))}`:`Browser closed for #${a.job_id}. Did you submit? Mark it as <b>Applied</b> below.`;if(sel==a.job_id)openJob(sel)}
  wasApplying=a.running;
  clearTimeout(window._t);window._t=setTimeout(poll,(r.running||a.running)?1500:8000);
}
async function refresh(){await loadList();await poll()}
renderTabs();refresh();
</script></body></html>
"""
