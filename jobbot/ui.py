"""The dashboard page, shared by the local server (web.py) and the hosted app (cloud/webapp.py).

render(cfg) injects a small config object:
  hosted   - true on Firebase: Google sign-in, auth header on every API call,
             files fetched with the token, no automated pre-fill
  firebase - Firebase web config (hosted only)
"""
import json

FIREBASE_SDK = "https://www.gstatic.com/firebasejs/10.12.2"


def render(cfg):
    cfg = {"hosted": False, "firebase": None, **cfg}
    # </ can't appear inside the inline JSON (it would end the <script> tag)
    return PAGE.replace("__CFG__", json.dumps(cfg).replace("</", "<\\/")).replace("__SDK__", FIREBASE_SDK)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#2f5bd3">
<title>job-bot</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1b1f24;--muted:#5d6670;--line:#e3e6ea;--accent:#2f5bd3;
 --accent-ink:#fff;--good:#1f7a4d;--warn:#a15c00;--bad:#b3261e;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--panel:#181c21;--ink:#e6e9ed;--muted:#9aa3ad;
 --line:#2a3037;--accent:#6d8ff0;--accent-ink:#0b0e12;--good:#4cc38a;--warn:#e0a33a;--bad:#ef6b62;--chip:#232931}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 padding-bottom:env(safe-area-inset-bottom,0px)}
header{display:flex;align-items:center;gap:10px 14px;flex-wrap:wrap;padding:10px 16px;
 padding-top:calc(10px + env(safe-area-inset-top,0px));background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
h1{font-size:16px;margin:0}
.counts{color:var(--muted);font-size:13px}
.spacer{flex:1}
button,.btn{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;
 padding:7px 11px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:4px;white-space:nowrap;min-height:34px}
button:hover,.btn:hover{border-color:var(--accent)}
.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
button:disabled{opacity:.5;cursor:default}
.runbox{font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px;min-width:0}
#runtext{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46vw}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted);flex:none}
.dot.on{background:var(--good);animation:p 1s infinite alternate}@keyframes p{to{opacity:.3}}
#log{display:none;margin:0;padding:10px 16px;max-height:240px;overflow:auto;background:#0b0e12;color:#cfd6de;
 font:12px/1.4 ui-monospace,Menlo,monospace;white-space:pre-wrap}
#applybar{display:none;padding:9px 16px;background:var(--chip);border-bottom:1px solid var(--line);font-size:13px}
main{display:grid;grid-template-columns:minmax(320px,440px) 1fr;min-height:calc(100vh - 57px)}
#listcol{border-right:1px solid var(--line);background:var(--panel)}
.tabs{display:flex;gap:4px;padding:10px;border-bottom:1px solid var(--line);overflow-x:auto}
.tabs button{border:none;background:none;color:var(--muted)}
.tabs button.on{background:var(--chip);color:var(--ink);font-weight:600}
.row{padding:12px 14px;border-bottom:1px solid var(--line);cursor:pointer;display:grid;grid-template-columns:44px 1fr;gap:10px}
.row:hover{background:var(--chip)} .row.sel{background:var(--chip);box-shadow:inset 3px 0 var(--accent)}
.score{font-weight:700;font-size:15px;text-align:center;border-radius:7px;padding:6px 0;background:var(--chip);align-self:start}
.s85{color:var(--good)} .s70{color:var(--accent)} .slow{color:var(--muted)}
.co{font-weight:600} .ti{margin:1px 0 2px} .meta{color:var(--muted);font-size:12px}
.rowact{margin-top:7px;display:flex;gap:6px;flex-wrap:wrap}
.rowact .btn{padding:3px 9px;font-size:12px;min-height:28px}
.tag{display:inline-block;background:var(--chip);border-radius:5px;padding:0 6px;font-size:11px;color:var(--muted);margin-left:4px}
.tag.w{color:var(--warn)}
#detail{padding:22px 26px;max-width:1000px;min-width:0}
.back{display:none;margin-bottom:12px}
.empty{color:var(--muted);padding:40px 20px;text-align:center}
.dh{display:flex;gap:14px;align-items:flex-start}
.dh .score{font-size:20px;padding:10px 12px;min-width:58px}
h2{margin:0;font-size:20px} h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:24px 0 8px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 6px}
.marks{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:8px}
.marks .cur{background:var(--chip);font-weight:600}
.note{display:flex;gap:6px;margin-top:8px}
.note input{flex:1;min-width:0;font:inherit;font-size:16px;padding:6px 9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
.callout{border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:7px;padding:9px 12px;margin:10px 0;font-size:13px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
ul.plain{margin:0;padding-left:18px} ul.plain li{margin:3px 0}
.checks label{display:flex;gap:8px;align-items:flex-start;padding:5px 0}
.pdf{width:100%;height:760px;border:1px solid var(--line);border-radius:8px;background:#fff}
.qa{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0;background:var(--panel)}
.qa b{display:block;margin-bottom:4px}
.letter,.desc{white-space:pre-wrap;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-wrap:anywhere}
.desc{max-height:480px;overflow:auto;font-size:13px}
.kw span{display:inline-block;background:var(--chip);border-radius:5px;padding:1px 7px;margin:2px;font-size:12px}
.copy{float:right;font-size:12px;padding:2px 8px;min-height:26px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}.grid .wide{grid-column:1/-1}
.grid label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted)}
.grid input,.grid textarea,.grid select{font:inherit;font-size:16px;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 9px;min-width:0}
.timeline{border-left:2px solid var(--line);margin:4px 0 8px 6px;padding-left:14px}
.ev{margin:6px 0}.due{color:var(--bad);font-weight:600}
dialog{border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);width:min(640px,94vw);padding:20px 22px;max-height:90vh;overflow:auto}
dialog::backdrop{background:rgba(0,0,0,.35)}
dialog.wide{width:min(900px,96vw)}
#profyaml{width:100%;min-height:52vh;font:13px/1.45 ui-monospace,Menlo,monospace;color:var(--ink);background:var(--bg);
 border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px;tab-size:2}
@media (max-width:800px){#profyaml{font-size:16px;min-height:60vh}}
body.onboarding .dash,body.onboarding .counts,body.onboarding .runbox{display:none}
#welcome{max-width:640px;margin:28px auto;padding:0 16px}
#welcome h2{font-size:24px;margin-bottom:6px}
.step{display:flex;gap:14px;align-items:flex-start;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.step .num{flex:none;width:32px;height:32px;border-radius:50%;background:var(--chip);display:grid;place-items:center;font-weight:700}
.step.done .num{background:var(--good);color:#fff}
.step.locked{opacity:.5}.step.locked button{pointer-events:none}
.step .body{flex:1;min-width:0}.step p{margin:4px 0 10px}
.privacy{text-align:left;border-top:1px solid var(--line);padding-top:12px;margin-top:18px}
.hosted,.admin{display:none}
body.is-hosted .hosted{display:inline-flex} body.is-admin .admin{display:inline-flex}
.urow{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--line)}
.urow .who{flex:1;min-width:200px}
.grid label span{color:var(--muted);font-size:12px}
.grid label input[type=checkbox]{width:auto;min-height:0}
.grid label span.cityhint{color:var(--warn)}
#login{display:none;max-width:420px;margin:12vh auto;padding:28px;background:var(--panel);border:1px solid var(--line);border-radius:14px;text-align:center}
#login h1{font-size:22px;margin-bottom:8px}
#app{display:none}
/* phone: list OR detail, not both */
@media (max-width:800px){
  main{display:block;min-height:0}
  #listcol{border-right:none}
  body.showdetail #listcol{display:none}
  body:not(.showdetail) #detail{display:none}
  #detail{padding:14px 16px 40px}
  .back{display:inline-flex}
  .cols,.grid{grid-template-columns:1fr}
  .pdf{height:70vh}
  .counts{order:5;width:100%}
  .hide-sm{display:none}
}
</style></head><body>
<div id="login"><h1>job-bot</h1><p class="meta">Finds jobs that fit your background, drafts a truthful
  tailored resume and cover letter for each, and tracks your applications. You always review and submit yourself.</p>
  <p><button class="primary" onclick="signIn()">Sign in with Google</button></p><p class="meta" id="loginerr"></p>
  <p class="meta privacy">Privacy: your profile, resumes and applications are stored in this job-bot's private
  Google Cloud project. The person who runs it can technically access that data. Job descriptions and your profile
  are sent to Anthropic's API to score and tailor. You can delete everything anytime in Settings.</p></div>
<div id="pending" style="display:none;max-width:460px;margin:12vh auto;padding:28px;background:var(--panel);border:1px solid var(--line);border-radius:14px;text-align:center">
  <h1 style="font-size:22px">Almost there</h1><p id="pendingmsg"></p>
  <p class="meta">You'll get in as soon as the owner approves your request. Check back later.</p>
  <p><button onclick="signOut()">Sign out</button></p></div>
<div id="app">
<header>
  <h1>job-bot</h1><span class="counts" id="counts"></span><span class="spacer"></span>
  <span class="runbox"><span class="dot" id="dot"></span><span id="runtext">Idle</span>
    <button id="logbtn" class="hide-sm" onclick="toggleLog()">Log</button></span>
  <button onclick="openProfile()">Profile</button>
  <button class="hosted" onclick="openSettings()">Settings</button>
  <button class="admin" id="usersbtn" onclick="openUsers()">Users</button>
  <button class="dash" onclick="openAdd()">+ Add</button>
  <button class="primary dash" id="runbtn" onclick="startRun()">Run search</button>
  <button id="signout" style="display:none" onclick="signOut()">Sign out</button>
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
<div id="setup" class="callout" style="display:none;margin:12px 16px">Set up your profile first: it's the only
  source of truth the AI may use for your resumes. <button class="primary" onclick="openProfile()">Set up profile</button></div>
<div id="setup2" class="callout" style="display:none;margin:12px 16px">Next, choose the job titles and locations you
  want. <button class="primary" onclick="openSettings()">Open settings</button></div>
<dialog id="setmodal" class="wide"><form id="setform" onsubmit="saveSettings(event)">
  <h2>Search settings</h2>
  <p class="meta" id="usage"></p>
  <div class="grid">
    <label class="wide">Job titles to look for (one per line)<textarea name="title_keywords" rows="7"
      placeholder="qa engineer&#10;sdet&#10;test automation"></textarea>
      <span>Whole words, any capitalization. End with * to match word starts: <code>engineer*</code> also matches "engineering".</span></label>
    <label class="wide">Skip titles containing (one per line)<textarea name="exclude_keywords" rows="5"></textarea></label>
    <label><span><input type="checkbox" name="remote_only"> Remote jobs only</span></label>
    <label><span><input type="checkbox" name="us_only"> United States only</span></label>
    <label class="wide">Also include on-site / hybrid jobs in these cities (one per line)<textarea name="local_areas" rows="3"
      placeholder="Austin, TX&#10;Round Rock, TX" oninput="cityHint()"></textarea>
      <span class="cityhint" id="cityhint"></span></label>
    <label>Minimum match score (0-100)<input type="number" name="min_score" min="0" max="100"></label>
    <label class="wide">Companies to watch (optional, one careers link per line)<textarea name="companies" rows="3"
      placeholder="https://jobs.lever.co/acme&#10;https://job-boards.greenhouse.io/example"></textarea>
      <span>Greenhouse, Lever, Ashby, SmartRecruiters, Workable or Recruitee careers pages. Your job titles are also
      searched on Himalayas, Jobicy, The Muse and Adzuna, which cover every field. For local
      searches write cities as "Austin, TX".</span></label>
  </div>
  <p class="meta" id="seterr" style="color:var(--bad)"></p>
  <div class="marks"><button class="primary" type="submit">Save settings</button>
    <button type="button" onclick="$('setmodal').close()">Close</button><span class="meta" id="setsaved"></span></div>
  <h3>Browser extension</h3>
  <p class="meta">Fills applications in your own Chrome: contact details, resume and cover letter. Works on
    Greenhouse, Lever, Ashby and most other forms, including jobs found via Himalayas and other job sites.
    It never submits; you review and submit yourself.</p>
  <div id="extinstall"><a class="btn primary" id="extdl" href="/job-bot-extension.zip" download>Download extension (.zip)</a>
    <ol class="meta">
    <li>Unzip the download.</li>
    <li>In Chrome open <code>chrome://extensions</code> and turn on <b>Developer mode</b> (top right).</li>
    <li>Click <b>Load unpacked</b> and choose the unzipped <code>job-bot-extension</code> folder.</li>
    <li>Pin the job-bot icon (puzzle-piece menu), reload this page, then click <b>Connect browser extension</b>.</li></ol></div>
  <p class="meta" id="extstatus"></p>
  <div class="marks"><button type="button" onclick="connectExt()">Connect browser extension</button>
    <button type="button" onclick="disconnectExt()">Disconnect</button></div>
  <h3>Delete my data</h3>
  <p class="meta">Permanently deletes your profile, settings, prospects, applications, timelines and PDFs from job-bot.</p>
  <div class="note"><input id="delconfirm" placeholder="Type DELETE to confirm"><button type="button" onclick="deleteMe()">Delete everything</button></div>
  <p class="meta" id="delmsg"></p>
</form></dialog>
<dialog id="usersmodal" class="wide"><h2>Users</h2>
  <p class="meta">Everyone who has signed in. Their runs use your Claude API key, within the per-person and
  monthly limits in config.yaml. Revoke anyone who shouldn't have access.</p>
  <div id="userlist"></div>
  <div class="marks"><button onclick="$('usersmodal').close()">Close</button></div></dialog>
<dialog id="profmodal" class="wide">
  <h2>Your profile</h2>
  <p class="meta">The only facts the AI may use in your resumes and cover letters. Keep it true: company names,
    titles and dates are copied verbatim, skills are limited to your list, and numbers only appear if they're written here.</p>
  <div class="marks"><input type="file" id="pdffile" accept="application/pdf">
    <button onclick="importPdf()">Import from resume PDF</button><span class="meta" id="impstatus"></span></div>
  <div id="impwarn" class="callout" style="display:none"></div>
  <textarea id="profyaml" spellcheck="false" autocapitalize="off" autocomplete="off"
    placeholder="Import a resume PDF above, or paste your profile YAML (see profile.example.yaml)."></textarea>
  <div class="meta" id="proferr" style="color:var(--bad)"></div>
  <div class="marks"><button class="primary" onclick="saveProfile()">Save profile</button>
    <button onclick="$('profmodal').close()">Close</button><span class="meta" id="profsaved"></span></div>
</dialog>
<section id="welcome" style="display:none">
  <h2>Welcome to job-bot</h2>
  <p class="meta">Three quick steps. job-bot then searches public job boards every morning, scores each job against
    your background, and drafts a truthful tailored resume and cover letter for the good matches.</p>
  <div class="step" id="step1"><div class="num">1</div><div class="body"><b>Your profile</b>
    <p class="meta">Upload your resume. We turn it into your profile, the only facts the AI may use, and you check it.</p>
    <button class="primary" onclick="openProfile()">Set up profile</button></div></div>
  <div class="step" id="step2"><div class="num">2</div><div class="body"><b>What you're looking for</b>
    <p class="meta">Job titles, remote or on-site, and where.</p>
    <button onclick="openSettings()">Choose job titles</button></div></div>
  <div class="step" id="step3"><div class="num">3</div><div class="body"><b>Find jobs</b>
    <p class="meta">Takes 5-15 minutes. After that it runs automatically every morning at 7am Central.</p>
    <button onclick="firstRun()">Run your first search</button> <button onclick="finishWelcome()">Go to dashboard</button></div></div>
</section>
<main>
  <section id="listcol">
    <div class="tabs" id="tabs"></div>
    <div id="list"></div>
  </section>
  <section id="detail"><div class="empty">Select a prospect.</div></section>
</main>
</div>
<script>
const CFG=__CFG__;
const TABS=[["review","To review"],["pipeline","Applied"],["near","Near misses"],["skipped","Skipped"]];
const MARKS=[["applied","Applied"],["interview","Interview"],["offer","Offer"],["rejected","Rejected"],["withdrawn","Withdrawn"],["skipped","Skip"],["tailored","Back to review"]];
let view="review", sel=null, cur=null, wasRunning=false, wasApplying=false, getToken=async()=>null;
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const scls=s=>s>=85?"s85":s>=70?"s70":"slow";
const VIA={himalayas:"via Himalayas",jobicy:"via Jobicy",remotive:"via Remotive",muse:"via The Muse",adzuna:"via Adzuna"};
const srcLabel=s=>VIA[s]||s;
const today=()=>new Date().toLocaleDateString("en-CA");
const ago=d=>{if(!d)return"";const n=Math.round((new Date(today())-new Date(d.slice(0,10)))/864e5);return n<=0?"today":n==1?"1d ago":n+"d ago"};
const fmt=d=>d?new Date(d.slice(0,10)+"T12:00").toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"";
const phone=()=>matchMedia("(max-width:800px)").matches;

async function headers(){const h={"Content-Type":"application/json","X-JobBot":"1"};const t=await getToken();if(t)h.Authorization="Bearer "+t;return h}
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:await headers()});
  const j=await r.json().catch(()=>({}));if(r.status==401&&CFG.hosted){showLogin();throw new Error("Signed out")}
  if(r.status==403&&j.access&&j.access!="approved"){showPending(j.error);throw new Error(j.error)}
  if(!r.ok)throw new Error(j.error||r.statusText);return j}
const post=(p,b)=>api(p,{method:"POST",body:JSON.stringify(b||{})});
const fileUrl=(id,n)=>`/files/${encodeURIComponent(id)}/${encodeURIComponent(n)}`;
async function fileBlobUrl(id,n){const r=await fetch(fileUrl(id,n),{headers:await headers()});if(!r.ok)throw new Error("File unavailable");return URL.createObjectURL(await r.blob())}
async function openFile(id,n){ // hosted: fetch with the token, then open (window first, so phones don't block it)
  if(!CFG.hosted){window.open(fileUrl(id,n),"_blank");return}
  const w=window.open("","_blank");try{const u=await fileBlobUrl(id,n);if(w)w.location=u;else location.href=u}catch(e){if(w)w.close();alertBar(e.message)}}

function renderTabs(){$("tabs").innerHTML=TABS.map(([k,l])=>`<button class="${k==view?"on":""}" data-view="${k}">${l}</button>`).join("")}
$("tabs").onclick=e=>{const b=e.target.closest("button");if(b)setView(b.dataset.view)};
function setView(v){view=v;sel=null;document.body.classList.remove("showdetail");renderTabs();loadList();$("detail").innerHTML='<div class="empty">Select a prospect.</div>'}
function appLink(j,small){if(!j.form_url)return"";return `<a class="btn ${small?"":"primary"}" href="${esc(j.form_url)}" target="_blank" rel="noopener">Open application ↗</a>`}

async function loadList(){
  const jobs=await api("/api/jobs?view="+view);
  if(!jobs.length){$("list").innerHTML=`<div class="empty">${view=="review"?"No packets waiting. Run a job search.":"Nothing here yet."}</div>`;return}
  $("list").innerHTML=jobs.map(j=>`<div class="row ${j.id==sel?"sel":""}" data-id="${esc(j.id)}">
    <div class="score ${scls(j.score)}">${j.score??"–"}</div>
    <div><div class="co">${esc(j.company)}<span class="tag">${esc(srcLabel(j.source))}</span>${j.warnings?`<span class="tag w">${j.warnings} to check</span>`:""}${view!="review"?`<span class="tag">${esc(j.status)}</span>`:""}</div>
    <div class="ti">${esc(j.title)}</div><div class="meta">${CFG.hosted?"":"#"+esc(j.id)+" · "}${esc(j.location)}${j.applied_at?` · applied ${fmt(j.applied_at)} (${ago(j.applied_at)})`:""}</div>
    ${j.next_step?`<div class="meta">Next: ${esc(j.next_step)}</div>`:""}
    ${j.follow_up&&["applied","interview","offer"].includes(j.status)?`<div class="meta ${j.follow_up<=today()?"due":""}">Follow up ${fmt(j.follow_up)}${j.follow_up<=today()?" — due":""}</div>`:""}
    <div class="rowact">${appLink(j,true)}</div></div></div>`).join("");
}
$("list").onclick=e=>{if(e.target.closest("a"))return;const r=e.target.closest(".row");if(r)openJob(r.dataset.id)};

async function openJob(id){
  sel=id;document.querySelectorAll(".row").forEach(r=>r.classList.toggle("sel",r.dataset.id==id));
  const j=await api("/api/jobs/"+encodeURIComponent(id)); cur=j;
  const f=j.files||{};
  const list=a=>a&&a.length?`<ul class="plain">${a.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:'<div class="meta">none</div>';
  document.body.classList.add("showdetail"); if(phone())window.scrollTo(0,0);
  $("detail").innerHTML=`
  <button class="back" onclick="back()">← Back</button>
  <div class="dh"><div class="score ${scls(j.score)}">${j.score??"–"}</div>
    <div><h2>${esc(j.title)}</h2><div>${esc(j.company)}${j.location?" · "+esc(j.location):""}</div>
    <div class="meta">${CFG.hosted?"":"#"+esc(j.id)+" · "}${esc(srcLabel(j.source))} · status: <b>${esc(j.status)}</b>${j.applied_at?` · applied ${fmt(j.applied_at)} (${ago(j.applied_at)})`:""}</div></div></div>
  <div class="actions">${appLink(j)}
    ${j.url&&j.url!=j.form_url?`<a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">Job posting ↗</a>`:""}
    ${j.has_packet&&!CFG.hosted?`<button onclick="prefill()">Pre-fill in automated browser</button>`:""}
    ${f.resume?`<button onclick="openFile(cur.id,cur.files.resume)">Resume PDF</button>`:""}
    ${f.letter?`<button onclick="openFile(cur.id,cur.files.letter)">Cover letter PDF</button>`:""}</div>
  ${j.source=="ashby"&&j.has_packet?`<div class="callout">Ashby's spam filter can reject submissions from an automated browser. Use <b>Open application</b> in your normal browser and upload the PDFs from this packet.</div>`:""}
  <div class="marks"><span class="meta">Mark as:</span>${MARKS.filter(([s])=>s!="tailored"||j.has_packet).map(([s,l])=>`<button class="${j.status==s?"cur":""}" onclick="mark('${s}')">${l}</button>`).join("")}</div>
  ${j.warnings.length?`<h3>Check before submitting</h3><div class="checks">${j.warnings.map(w=>`<label><input type="checkbox"> <span>${esc(w)}</span></label>`).join("")}</div>`:""}
  ${j.score==null?"":`<div class="cols"><div><h3>Why it matches</h3>${list(j.reasons)}</div><div><h3>Concerns</h3>${list(j.concerns)}${j.dealbreakers.length?`<h3>Dealbreakers</h3>${list(j.dealbreakers)}`:""}</div></div>`}
  ${j.keywords.length?`<h3>Key terms</h3><div class="kw">${j.keywords.map(k=>`<span>${esc(k)}</span>`).join("")}</div>`:""}
  ${j.answers.length?`<h3>Screening answer drafts</h3>${j.answers.map((a,i)=>`<div class="qa"><button class="copy" onclick="copyText(this,'a${i}')">Copy</button><b>${esc(a.q)}</b><div id="a${i}">${esc(a.a)}</div></div>`).join("")}`:""}
  ${j.cover_letter?`<h3>Cover letter <button class="copy" onclick="copyText(this,'cl')">Copy</button></h3><div class="letter" id="cl">${esc(j.cover_letter)}</div>`:""}
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
  <div class="marks"><button onclick="saveDetails()">Save details</button><span class="meta" id="saved"></span></div>
  <h3>Timeline</h3>
  <div class="timeline">${(j.events||[]).map(e=>`<div class="ev"><span class="meta">${fmt(e.at)}</span> ${e.kind=="status"?`<b>${esc(e.text)}</b>`:esc(e.text)}</div>`).join("")||'<div class="meta">No activity yet.</div>'}</div>
  <div class="note"><input id="evtext" placeholder="Add to timeline" onkeydown="if(event.key=='Enter')addEvent()"><button onclick="addEvent()">Add</button></div>
  ${f.resume?`<h3>Resume</h3>${phone()?`<button onclick="openFile(cur.id,cur.files.resume)">Open resume PDF</button>`:`<iframe class="pdf" id="pdf"></iframe>`}`:""}
  ${j.description?`<h3>Job description</h3><div class="desc">${esc(j.description)}</div>`:""}`;
  if(f.resume&&!phone()){$("pdf").src=CFG.hosted?await fileBlobUrl(j.id,f.resume).catch(()=>"about:blank"):fileUrl(j.id,f.resume)}
}
function back(){document.body.classList.remove("showdetail");sel=null;loadList()}

const formData=el=>Object.fromEntries([...el.querySelectorAll("input,textarea,select")].map(i=>[i.name,i.value]));
const jpath=s=>`/api/jobs/${encodeURIComponent(cur.id)}/${s}`;
async function mark(status){await post(jpath("mark"),{status});await refresh();openJob(cur.id)}
async function saveDetails(){try{await post(jpath("details"),formData($("det")));$("saved").textContent="Saved";loadList();poll()}catch(e){$("saved").textContent=e.message}}
async function addEvent(){const t=$("evtext").value.trim();if(!t)return;await post(jpath("events"),{text:t});openJob(cur.id)}
async function prefill(){try{await post(jpath("prefill"));poll()}catch(e){alertBar(e.message)}}
function openAdd(){$("addform").reset();$("addform").applied_at.value=today();$("adderr").textContent="";$("addmodal").showModal()}
async function submitAdd(ev){ev.preventDefault();try{const r=await post("/api/jobs",formData($("addform")));$("addmodal").close();view="pipeline";renderTabs();await refresh();openJob(r.id)}catch(e){$("adderr").textContent=e.message}}
async function openProfile(){$("impwarn").style.display="none";$("proferr").textContent="";$("profsaved").textContent="";$("impstatus").textContent="";
  $("profyaml").value=(await api("/api/profile")).profile_yaml;$("profmodal").showModal()}
async function importPdf(){
  const f=$("pdffile").files[0];if(!f){$("impstatus").textContent="Choose a PDF first.";return}
  const h=await headers();delete h["Content-Type"];const fd=new FormData();fd.append("pdf",f);
  $("impstatus").textContent="Reading your resume (about 20 seconds)…";$("impwarn").style.display="none";
  try{const r=await fetch("/api/profile/import",{method:"POST",headers:h,body:fd});const j=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(j.error||r.statusText);
    $("profyaml").value=j.profile_yaml;$("impstatus").textContent="Draft ready. Review it, then Save.";
    const w=$("impwarn");w.style.display="block";
    w.innerHTML=`<b>Nothing is saved yet.</b> Check every line below against your real experience, and edit <code>targets</code> (roles, location, dealbreakers).`+
      (j.unsupported.length?`<br><br><b>These weren't found in your PDF's text — verify or delete them:</b><ul class="plain">${j.unsupported.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:"")}
  catch(e){$("impstatus").textContent=e.message}}
async function saveProfile(){$("proferr").textContent="";$("profsaved").textContent="";
  try{await post("/api/profile",{profile_yaml:$("profyaml").value});$("profsaved").textContent="Saved.";$("impwarn").style.display="none";
    if(onboarding)$("profmodal").close();poll()}
  catch(e){$("proferr").textContent=e.message}}
const lines=v=>(v||[]).join("\n");
async function openSettings(){const r=await api("/api/settings"),s=r.settings,f=$("setform");
  f.title_keywords.value=lines(s.title_keywords);f.exclude_keywords.value=lines(s.exclude_keywords);
  f.local_areas.value=lines(s.local_areas);f.remote_only.checked=!!s.remote_only;f.us_only.checked=!!s.us_only;
  f.min_score.value=s.min_score;f.companies.value=lines(s.companies);cityHint();$("seterr").textContent="";$("setsaved").textContent="";$("delmsg").textContent="";$("delconfirm").value="";
  const L=r.limits;$("usage").textContent=`Runs today: ${L.runs_today} of ${L.runs_per_day} · this month's estimated API cost: $${L.month_cost.toFixed(2)}`+(r.saved?"":" · not saved yet");
  $("extdl").href="/job-bot-extension.zip?v="+Date.now();$("setmodal").showModal();pingExt()}
let ext={present:false,connected:false};
window.addEventListener("message",e=>{if(e.source!==window||e.origin!==location.origin)return;const d=e.data||{};
  if(d.source!=="jobbot-ext")return;ext.present=true;
  if(d.type==="pong")ext.connected=!!d.connected;if(d.type==="connected")ext.connected=true;if(d.type==="disconnected")ext.connected=false;
  extStatus()});
function extStatus(){const el=$("extstatus");if(!el)return;
  $("extinstall").style.display=ext.connected?"none":"";
  el.textContent=!ext.present?"Extension not detected in this browser yet: download and install it above.":ext.connected?"Connected ✓ The job-bot icon can now fill applications.":"Installed, not connected yet."}
function pingExt(){window.postMessage({source:"jobbot-page",type:"ping"},location.origin);setTimeout(extStatus,400)}
async function connectExt(){if(!ext.present){$("extstatus").textContent="Install the extension first (Download extension above, then the steps), then reload this page.";return}
  try{const r=await post("/api/ext/connect");window.postMessage({source:"jobbot-page",type:"connect",token:r.token},location.origin)}
  catch(e){$("extstatus").textContent=e.message}}
async function disconnectExt(){try{const r=await post("/api/ext/disconnect");window.postMessage({source:"jobbot-page",type:"disconnect"},location.origin);
  $("extstatus").textContent=`Disconnected (${r.removed} browser${r.removed==1?"":"s"}).`}catch(e){$("extstatus").textContent=e.message}}
function cityHint(){ // same rule as settings.city_warnings on the server
  const bad=$("setform").local_areas.value.split("\n").map(x=>x.trim()).filter(x=>x&&!/,\s*[A-Za-z]{2}\.?\s*$/.test(x));
  $("cityhint").textContent=bad.length?`${bad.slice(0,3).map(x=>`'${x}'`).join(", ")}${bad.length>3?"…":""} ${bad.length==1?"has":"have"} no state. `+
    `Write cities like "Austin, TX" so The Muse can search them (filtering still works without it).`:""}
async function saveSettings(ev){ev.preventDefault();const f=$("setform");$("seterr").textContent="";$("setsaved").textContent="";
  try{const r=await post("/api/settings",{title_keywords:f.title_keywords.value,exclude_keywords:f.exclude_keywords.value,
    local_areas:f.local_areas.value,remote_only:f.remote_only.checked,us_only:f.us_only.checked,min_score:f.min_score.value,
    companies:f.companies.value});
    $("setsaved").textContent="Saved. The next run uses these."+((r.warnings||[]).length?" Note: "+r.warnings.join(" "):"");if(onboarding)$("setmodal").close();poll()}catch(e){$("seterr").textContent=e.message}}
async function deleteMe(){try{await post("/api/me/delete",{confirm:$("delconfirm").value.trim()});$("delmsg").textContent="Deleted.";
  setTimeout(signOut,1200)}catch(e){$("delmsg").textContent=e.message}}
async function openUsers(){await renderUsers();$("usersmodal").showModal()}
async function renderUsers(){const us=await api("/api/admin/users");
  $("userlist").innerHTML=us.map(u=>`<div class="urow"><div class="who"><b>${esc(u.email)}</b>${u.is_admin?' <span class="tag">owner</span>':""}
    <div class="meta">${esc(u.access)}${u.requested_at?" · signed up "+fmt(u.requested_at):""}${u.last_seen?" · last seen "+ago(u.last_seen):""}
    · ${u.has_profile?"profile ✓":"no profile"} · ${u.has_settings||u.is_admin?"settings ✓":"no settings"} · runs today ${u.runs_today} · $${u.month_cost.toFixed(2)} this month</div></div>
    ${u.is_admin?"":(u.access=="approved"?`<button onclick="setAccess('${u.uid}','denied')">Revoke</button>`:
      `<button class="primary" onclick="setAccess('${u.uid}','approved')">Approve</button>${u.access=="pending"?`<button onclick="setAccess('${u.uid}','denied')">Deny</button>`:""}`)}</div>`).join("")||'<p class="meta">No one yet.</p>'}
async function setAccess(uid,access){await post(`/api/admin/users/${encodeURIComponent(uid)}`,{access});await renderUsers();poll()}
let onboarding=false;
function renderWelcome(s){
  const p=!!s.has_profile, st=!!s.has_settings;
  if(!onboarding&&(!p||!st))onboarding=true;          // new or half-set-up account
  const show=onboarding; document.body.classList.toggle("onboarding",show);
  $("welcome").style.display=show?"block":"none"; document.querySelector("main").style.display=show?"none":"";
  $("tabs").style.display=show?"none":"";
  $("step1").className="step"+(p?" done":""); $("step2").className="step"+(st?" done":(p?"":" locked"));
  $("step3").className="step"+(p&&st?"":" locked");
  $("step1").querySelector("button").className=p?"":"primary"; $("step1").querySelector("button").textContent=p?"Edit profile":"Set up profile";
  $("step2").querySelector("button").className=p&&!st?"primary":""; $("step3").querySelector("button").className=p&&st?"primary":"";
}
function finishWelcome(){onboarding=false;document.body.classList.remove("onboarding");$("welcome").style.display="none";document.querySelector("main").style.display="";$("tabs").style.display="";loadList()}
async function firstRun(){finishWelcome();await startRun()}
function showPending(msg){$("app").style.display="none";$("login").style.display="none";$("pending").style.display="block";$("pendingmsg").textContent=msg}
async function startRun(){try{await post("/api/run");if(!phone())$("log").style.display="block";poll()}catch(e){alertBar(e.message)}}
function copyText(btn,id){navigator.clipboard.writeText($(id).innerText).then(()=>{btn.textContent="Copied";setTimeout(()=>btn.textContent="Copy",1200)})}
function toggleLog(){const l=$("log");l.style.display=l.style.display=="block"?"none":"block";l.scrollTop=l.scrollHeight}
function alertBar(msg){const b=$("applybar");b.style.display="block";b.textContent=msg;setTimeout(()=>b.style.display="none",5000)}

async function poll(){
  let s;try{s=await api("/api/state")}catch(e){return}
  const r=s.run||{}, a=s.apply||{}, c=s.counts||{};
  const n=k=>c[k]||0;
  $("counts").textContent=`${n("tailored")} to review · ${n("applied")+n("interview")+n("offer")+n("rejected")+n("withdrawn")} applied · ${n("interview")} interviewing`+(s.follow_ups_due?` · ${s.follow_ups_due} follow-up${s.follow_ups_due>1?"s":""} due`:"");
  $("dot").classList.toggle("on",!!r.running); $("runbtn").disabled=!!r.running;
  const lines=r.lines||[];
  if(r.running){$("runtext").textContent=(r.step||"Starting…")+(r.board&&(r.step||"").startsWith("[1/3]")?` (board ${r.board[0]}/${r.board[1]})`:"")}
  else if(r.started){const done=[...lines].reverse().find(l=>l.startsWith("Done."));$("runtext").textContent=r.exit_code?`Last run failed — see log`:(done||"Last run finished")}
  if(lines.length){const l=$("log");const atEnd=l.scrollTop+l.clientHeight>=l.scrollHeight-20;l.textContent=lines.join("\n");if(atEnd)l.scrollTop=l.scrollHeight}
  if(wasRunning&&!r.running){view="review";renderTabs();loadList()}
  wasRunning=!!r.running;
  if(CFG.hosted){renderWelcome(s);$("setup").style.display=$("setup2").style.display="none"}
  else $("setup").style.display=s.has_profile===false?"block":"none";
  document.body.classList.toggle("is-admin",!!s.is_admin);
  if(s.is_admin)$("usersbtn").textContent=s.pending_requests?`Users (${s.pending_requests} new)`:"Users";
  const bar=$("applybar");
  if(a.running){bar.style.display="block";bar.innerHTML=`Browser open for #${esc(a.job_id)}. Review everything, <b>submit it yourself</b>, close the window, then mark the outcome here.`}
  else if(wasApplying){bar.style.display="block";bar.innerHTML=a.exit_code?`Pre-fill for #${esc(a.job_id)} stopped: ${esc((a.lines||[]).slice(-2).join(" "))}`:`Browser closed for #${esc(a.job_id)}. Did you submit? Mark it as <b>Applied</b>.`;if(sel==a.job_id)openJob(sel)}
  wasApplying=!!a.running;
  clearTimeout(window._t);
  const busy=r.running||a.running;
  window._t=setTimeout(poll,busy?(CFG.hosted?3000:1500):(CFG.hosted?60000:8000));
}
document.addEventListener("visibilitychange",()=>{if(!document.hidden)poll()});
async function refresh(){await loadList();await poll()}
function showApp(){$("login").style.display="none";$("pending").style.display="none";$("app").style.display="block";renderTabs();refresh();
  if(CFG.hosted&&new URLSearchParams(location.search).get("settings")){history.replaceState(null,"",location.pathname);setTimeout(openSettings,300)}}
function showLogin(){$("app").style.display="none";$("pending").style.display="none";$("login").style.display="block"}

let fb=null;
async function signIn(){try{await fb.signInWithPopup(fb.auth,new fb.GoogleAuthProvider())}
  catch(e){if(e.code=="auth/popup-blocked"||e.code=="auth/operation-not-supported-in-this-environment")return fb.signInWithRedirect(fb.auth,new fb.GoogleAuthProvider());$("loginerr").textContent=e.message}}
async function signOut(){await fb.signOut(fb.auth);showLogin()}

(async()=>{
  if(!CFG.hosted){showApp();return}
  document.body.classList.add("is-hosted");
  const [{initializeApp},A]=await Promise.all([import("__SDK__/firebase-app.js"),import("__SDK__/firebase-auth.js")]);
  const conf={...CFG.firebase};
  // serve the sign-in handler from this site (Hosting's /__/auth) so Safari's storage rules don't break redirects
  if(/\.(web\.app|firebaseapp\.com)$/.test(location.hostname))conf.authDomain=location.hostname;
  const auth=A.getAuth(initializeApp(conf));
  fb={auth,...A};
  getToken=async()=>auth.currentUser?auth.currentUser.getIdToken():null;
  A.onAuthStateChanged(auth,u=>{if(u){$("signout").style.display="";showApp()}else showLogin()});
})();
</script></body></html>
"""
