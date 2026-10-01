"""Hosted dashboard (Cloud Run, behind Firebase Hosting). Same API as the local web.py.

Auth: the page signs in with Firebase Auth (Google) and sends the ID token as
`Authorization: Bearer ...`. Only emails in JOBBOT_ALLOWED_EMAILS get in.
Every response is `Cache-Control: private, no-store` so Hosting's CDN never
caches one user's data.
"""
import hashlib
import json
from pathlib import Path
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta

from flask import Flask, Response, abort, g, jsonify, request

from ..apply import form_url
from ..ui import render

STATUSES = ["tailored", "applied", "interview", "offer", "rejected", "withdrawn", "skipped"]
APPLICATION = ["applied", "interview", "offer", "rejected", "withdrawn"]
DETAIL_FIELDS = ["company", "title", "location", "url", "applied_at", "contact", "salary",
                 "next_step", "follow_up", "notes"]
STAGE = {"offer": 0, "interview": 1, "applied": 2}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def _ext_version():
    for path in (Path(__file__).parents[2] / "extension" / "manifest.json", Path("extension/manifest.json")):
        if path.exists():
            return json.loads(path.read_text()).get("version", "")
    return ""


EXT_VERSION = _ext_version()  # newest extension; the popup offers an update when it's older
# the only things a browser-extension key may do
EXT_PATHS = [r"/api/ext/me", r"/api/ext/jobs", r"/files/[^/]+/[^/]+", r"/api/jobs/[^/]+/mark"]
RUN_STALE = timedelta(minutes=70)  # a "running" flag older than this is a crashed run


def now():
    return datetime.now().isoformat(timespec="seconds")


def summary(j):
    j = dict(j)
    return {k: j.get(k) for k in ("id", "company", "title", "location", "score", "status", "source",
                                  "applied_at", "notes", "url", "contact", "salary", "next_step",
                                  "follow_up")} | {"form_url": form_url(j) if (j.get("apply_url") or j.get("url")) else "",
                                                   "warnings": len(j.get("warnings") or [])}


def view_jobs(store, uid, view):
    if view == "pipeline":
        rows = store.jobs(uid, APPLICATION)
        rows.sort(key=lambda r: r.get("applied_at") or r.get("updated_at") or "", reverse=True)
        rows.sort(key=lambda r: STAGE.get(r["status"], 3))
    elif view == "near":
        rows = [r for r in store.jobs(uid, ["low_score"]) if (r.get("score") or 0) >= 50]
        rows.sort(key=lambda r: -(r.get("score") or 0))
    elif view == "skipped":
        rows = sorted(store.jobs(uid, ["skipped"]), key=lambda r: r.get("updated_at") or "", reverse=True)
    else:
        rows = sorted(store.jobs(uid, ["tailored"]), key=lambda r: -(r.get("score") or 0))
    return [summary(r) for r in rows[:300]]


def create_app(store, verify_token, start_run, allowed_emails=(), firebase_config=None,
               import_model="claude-haiku-4-5-20251001", admin_emails=(), cloud_cfg=None):
    """verify_token(token) -> {"uid", "email"} or raises; start_run(uid) starts a run job.

    admin_emails: the owner(s) - always approved, see the Users screen, higher limits.
    allowed_emails: always approved. Everyone else is approved on sign-in when
    cloud.signup is "open" (default), or 'pending' until approved when it's "approval".
    Admins can revoke anyone either way."""
    from .. import profile as prof
    from .. import settings as st
    cloud_cfg = cloud_cfg or {}
    open_signup = cloud_cfg.get("signup", "open") == "open"
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = prof.MAX_PDF_BYTES + 64 * 1024
    admins = {e.strip().lower() for e in admin_emails if e.strip()}
    allowed = {e.strip().lower() for e in allowed_emails if e.strip()} | admins
    user_cache = {}
    page = render({"hosted": True, "firebase": firebase_config or {}})
    counts_cache = {}

    @app.after_request
    def no_cache(resp):
        resp.headers["Cache-Control"] = "private, no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error=getattr(e, "description", "Bad request")), 400

    @app.before_request
    def auth():
        if request.path == "/" or request.path == "/health":
            return None
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Sign in required"), 401
        if header.startswith("Bearer jbx_"):  # browser-extension key: limited to EXT_PATHS
            return ext_auth(header[7:])
        g.via_extension = False
        try:
            claims = verify_token(header[7:])
        except Exception:  # noqa: BLE001 - expired / forged token
            return jsonify(error="Sign in required"), 401
        email = (claims.get("email") or "").lower()
        if not claims.get("email_verified", True):
            return jsonify(error="Your Google account's email isn't verified."), 403
        g.uid = claims["uid"]
        user = store.ensure_user(g.uid, email, access="approved" if (email in allowed or open_signup) else "pending",
                                 requested_at=now(), is_admin=email in admins)
        fix = {}
        if email in allowed and user.get("access") != "approved":
            fix["access"] = "approved"
        if (email in admins) != bool(user.get("is_admin")):
            fix["is_admin"] = email in admins
        if (user.get("last_seen") or "") < (datetime.now() - timedelta(hours=1)).isoformat():
            fix["last_seen"] = now()
        if fix:
            store.update_user(g.uid, **fix)
            user.update(fix)
        g.user, g.is_admin = user, bool(user.get("is_admin"))
        if user.get("access") != "approved" and request.path not in ("/api/me", "/api/me/delete"):
            msg = ("Your access request is waiting for approval." if user.get("access") == "pending"
                   else "Access to this job-bot isn't available for your account.")
            return jsonify(error=msg, access=user.get("access")), 403
        return None

    def ext_auth(token):
        h = hashlib.sha256(token.encode()).hexdigest()
        rec = store.get_ext_token(h)
        if not rec:
            return jsonify(error="Extension disconnected. Reconnect it from job-bot Settings."), 401
        if not any(re.fullmatch(p, request.path) for p in EXT_PATHS):
            return jsonify(error="Not available to the extension."), 403
        user = store.get_user(rec["uid"]) or {}
        if user.get("access") != "approved":
            return jsonify(error="Access to this job-bot isn't available for your account."), 403
        if (rec.get("last_used") or "") < (datetime.now() - timedelta(hours=1)).isoformat():
            store.touch_ext_token(h)
        g.uid, g.user, g.is_admin, g.via_extension = rec["uid"], user, bool(user.get("is_admin")), True
        return None

    def job_or_404(jid):
        j = store.get_job(g.uid, jid)
        if not j:
            abort(404)
        return j

    def clean(body):
        fields = {}
        for k in DETAIL_FIELDS:
            if k in body:
                v = str(body[k] or "").strip()[:2000]
                if k in ("applied_at", "follow_up") and v and not DATE.match(v[:10]):
                    abort(400, f"{k} must be YYYY-MM-DD")
                if k in ("company", "title") and not v:
                    abort(400, f"{k} is required")
                fields[k] = v or None
        return fields

    def set_status(jid, status, note=None):
        j = job_or_404(jid)
        fields = {"status": status}
        if status == "applied" and not j.get("applied_at"):
            fields["applied_at"] = now()
        store.update_job(g.uid, jid, **fields)
        if j.get("status") != status:
            store.add_event(g.uid, jid, "status", status)
        if note:
            store.add_event(g.uid, jid, "note", note)
        counts_cache.pop(g.uid, None)

    @app.get("/")
    def index():
        return Response(page, mimetype="text/html")

    @app.get("/health")
    def health():
        return "ok"

    @app.get("/api/state")
    def state():
        cached = counts_cache.get(g.uid)
        if not cached or time.time() - cached[0] > 60:
            rows = store.status_summary(g.uid)
            counts = {}
            for r in rows:
                counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
            today = date.today().isoformat()
            due = sum(1 for r in rows if r.get("follow_up") and r["follow_up"] <= today
                      and r.get("status") in ("applied", "interview", "offer"))
            cached = counts_cache[g.uid] = (time.time(), counts, due)
        run = store.get_run(g.uid)
        if run.get("running") and run.get("started") and \
                datetime.fromisoformat(run["started"]) < datetime.now() - RUN_STALE:
            run["running"] = False
        me = store.get_user(g.uid) or {}
        pending = None
        if g.is_admin:
            pc = user_cache.get("pending")
            if not pc or time.time() - pc[0] > 60:
                pc = user_cache["pending"] = (time.time(), sum(
                    1 for _, d in store.list_users() if (d.get("access") or "pending") == "pending"))
            pending = pc[1]
        return jsonify(run=run, apply={}, counts=cached[1], follow_ups_due=cached[2],
                       has_profile=bool(me.get("profile_yaml")),
                       has_settings=bool(me.get("settings")) or g.is_admin,
                       is_admin=g.is_admin, pending_requests=pending)

    @app.get("/api/jobs")
    def jobs():
        return jsonify(view_jobs(store, g.uid, request.args.get("view", "review")))

    @app.get("/api/jobs/<jid>")
    def job(jid):
        j = job_or_404(jid)
        score = j.get("score_json") or {}
        return jsonify(summary(j) | {
            "description": j.get("description") or "", "has_packet": bool(j.get("has_packet")),
            "warnings": j.get("warnings") or [], "answers": j.get("answers") or [],
            "cover_letter": j.get("cover_letter") or "", "files": j.get("files") or {},
            "reasons": score.get("reasons", []), "concerns": score.get("concerns", []),
            "dealbreakers": score.get("dealbreakers", []), "keywords": score.get("keywords", []),
            "events": store.events(g.uid, jid)})

    @app.get("/files/<jid>/<name>")
    def files(jid, name):
        j = job_or_404(jid)
        if name not in (j.get("files") or {}).values():  # only this job's own packet files
            abort(404)
        data = store.get_file(g.uid, jid, name)
        if data is None:
            abort(404)
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}"'})

    @app.post("/api/jobs/<jid>/mark")
    def mark(jid):
        body = request.get_json(silent=True) or {}
        if body.get("status") not in STATUSES:
            abort(400)
        set_status(jid, body["status"], (body.get("note") or "").strip()[:2000] or None)
        return jsonify(summary(store.get_job(g.uid, jid)))

    @app.post("/api/jobs/<jid>/details")
    def details(jid):
        job_or_404(jid)
        fields = clean(request.get_json(silent=True) or {})
        if fields:
            store.update_job(g.uid, jid, **fields)
            counts_cache.pop(g.uid, None)
        return jsonify(summary(store.get_job(g.uid, jid)))

    @app.post("/api/jobs/<jid>/events")
    def add_event(jid):
        job_or_404(jid)
        text = str((request.get_json(silent=True) or {}).get("text") or "").strip()[:2000]
        if not text:
            abort(400)
        store.add_event(g.uid, jid, "note", text)
        return jsonify(ok=True)

    @app.post("/api/jobs")
    def add_job():
        body = request.get_json(silent=True) or {}
        fields = clean({**body, "company": body.get("company", ""), "title": body.get("title", "")})
        status = body.get("status") or "applied"
        if status not in APPLICATION:
            abort(400)
        import uuid
        jid = f"manual-{uuid.uuid4().hex[:12]}"
        at = fields.pop("applied_at", None) or now()
        store.put_job(g.uid, jid, {**fields, "source": "manual", "status": status, "applied_at": at,
                                   "apply_url": fields.get("url") or ""})
        store.add_event(g.uid, jid, "status", status, at=at)
        counts_cache.pop(g.uid, None)
        return jsonify(id=jid)

    def limits():
        day = date.today().isoformat()
        per_day = cloud_cfg.get("owner_runs_per_day", 10) if g.is_admin else \
            (cloud_cfg.get("friend_limits") or {}).get("runs_per_day", 2)
        return {"runs_per_day": per_day,
                "runs_today": int(store.get_usage(g.uid, day).get("manual_runs", 0)),
                "month_cost": round(store.get_usage(g.uid, day[:7]).get("cost_usd", 0.0), 2)}

    @app.get("/api/me")
    def me():
        return jsonify(email=g.user.get("email"), access=g.user.get("access"), is_admin=g.is_admin)

    @app.post("/api/me/delete")
    def delete_me():
        if (request.get_json(silent=True) or {}).get("confirm") != "DELETE":
            abort(400, 'Type DELETE to confirm.')
        store.delete_user_data(g.uid)
        counts_cache.pop(g.uid, None)
        return jsonify(ok=True)

    @app.post("/api/ext/connect")
    def ext_connect():
        if g.via_extension:
            abort(403)
        token = "jbx_" + secrets.token_urlsafe(32)
        store.put_ext_token(hashlib.sha256(token.encode()).hexdigest(), g.uid)
        return jsonify(token=token)

    @app.post("/api/ext/disconnect")
    def ext_disconnect():
        if g.via_extension:
            abort(403)
        return jsonify(removed=store.delete_ext_tokens(g.uid))

    @app.get("/api/ext/me")
    def ext_me():
        p, _ = prof.validate(g.user.get("profile_yaml") or "")
        c = (p or {}).get("contact") or {}
        return jsonify(email=g.user.get("email"), contact={k: c.get(k) or "" for k in
                       ("first_name", "last_name", "email", "phone", "location", "linkedin", "github",
                        "current_company")},
                       employment=prof.employment(p or {}), education=prof.education(p or {}),
                       extension_version=EXT_VERSION)

    @app.get("/api/ext/jobs")
    def ext_jobs():
        rows = store.jobs(g.uid, ["tailored", "applied", "interview"])
        rows.sort(key=lambda r: (r["status"] != "tailored", -(r.get("score") or 0)))
        return jsonify([{**summary(r), "files": r.get("files") or {}, "has_packet": bool(r.get("has_packet")),
                         "cover_letter": r.get("cover_letter") or ""} for r in rows[:100]])

    @app.get("/api/settings")
    def get_settings():
        saved = g.user.get("settings")
        default = st.OWNER_DEFAULTS if g.is_admin else st.NEW_USER_DEFAULTS
        return jsonify(settings=saved or default, saved=bool(saved), limits=limits())

    @app.post("/api/settings")
    def save_settings():
        clean_s, errors = st.clean(request.get_json(silent=True) or {})
        if errors:
            return jsonify(error="; ".join(errors), errors=errors), 400
        store.update_user(g.uid, settings=clean_s)
        return jsonify(ok=True, settings=clean_s, warnings=st.city_warnings(clean_s["local_areas"]))

    def budget_used():
        """Estimated API spend this month by everyone except admins (cached 5 min)."""
        bc = user_cache.get("budget")
        if not bc or time.time() - bc[0] > 300:
            month = date.today().isoformat()[:7]
            used = sum(store.get_usage(u, month).get("cost_usd", 0.0)
                       for u, d in store.list_users() if not d.get("is_admin"))
            bc = user_cache["budget"] = (time.time(), used)
        return bc[1]

    def admin_only():
        if not g.is_admin:
            abort(403)

    @app.get("/api/admin/users")
    def admin_users():
        admin_only()
        day = date.today().isoformat()
        out = []
        for uid, d in store.list_users():
            out.append({"uid": uid, "email": d.get("email"), "access": d.get("access") or "pending",
                        "is_admin": bool(d.get("is_admin")), "requested_at": d.get("requested_at"),
                        "last_seen": d.get("last_seen"), "has_profile": bool(d.get("profile_yaml")),
                        "has_settings": bool(d.get("settings")),
                        "runs_today": int(store.get_usage(uid, day).get("manual_runs", 0)),
                        "month_cost": round(store.get_usage(uid, day[:7]).get("cost_usd", 0.0), 2)})
        order = {"pending": 0, "approved": 1, "denied": 2}
        user_cache.pop("budget", None)
        out.sort(key=lambda u: (order.get(u["access"], 3), u["email"] or ""))
        return jsonify(out)

    @app.post("/api/admin/users/<uid>")
    def admin_set_access(uid):
        admin_only()
        access = (request.get_json(silent=True) or {}).get("access")
        if access not in ("approved", "denied", "pending") or uid == g.uid:
            abort(400, "Can't change that.")
        if not store.get_user(uid):
            abort(404)
        store.update_user(uid, access=access, access_changed_at=now())
        user_cache.pop("pending", None)
        return jsonify(ok=True)

    @app.get("/api/profile")
    def get_profile():
        return jsonify(profile_yaml=(store.get_user(g.uid) or {}).get("profile_yaml") or "")

    @app.post("/api/profile")
    def save_profile():
        text = str((request.get_json(silent=True) or {}).get("profile_yaml") or "")
        _, errors = prof.validate(text)
        if errors:
            return jsonify(error="Fix these before saving: " + "; ".join(errors[:6]), errors=errors), 400
        store.set_profile(g.uid, text)
        return jsonify(ok=True)

    @app.post("/api/profile/import")
    def import_profile():
        f = request.files.get("pdf")
        if not f:
            abort(400, "Choose a PDF first.")
        data = f.read()
        if not data.startswith(b"%PDF"):
            abort(400, "That doesn't look like a PDF.")
        try:
            text = prof.pdf_text(data)
            current, _ = prof.validate((store.get_user(g.uid) or {}).get("profile_yaml") or "")
            draft, flags = prof.import_resume(text, current, import_model)
        except ValueError as e:
            abort(400, str(e))
        except Exception as e:  # noqa: BLE001 - PDF parser / LLM trouble
            return jsonify(error=f"Import failed: {type(e).__name__}: {str(e)[:200]}"), 502
        return jsonify(profile_yaml=draft, unsupported=flags)

    @app.post("/api/jobs/<jid>/prefill")
    def prefill(jid):
        return jsonify(error="Pre-fill only works in the local version. Use Open application."), 400

    @app.post("/api/run")
    def run():
        me = store.get_user(g.uid) or {}
        if not me.get("profile_yaml"):
            return jsonify(error="Set up your profile first (Profile button)."), 400
        if not me.get("settings") and not g.is_admin:
            return jsonify(error="Choose the job titles you want first (Settings button)."), 400
        lim = limits()
        if not g.is_admin and budget_used() >= cloud_cfg.get("monthly_budget_usd", 25):
            return jsonify(error="job-bot has reached its monthly budget for searches. They resume "
                                 "next month; your saved prospects and applications are still here."), 429
        if lim["runs_today"] >= lim["runs_per_day"]:
            return jsonify(error=f"You've used today's {lim['runs_per_day']} runs. "
                                 "The automatic 7am search still runs tomorrow."), 429
        cur = store.get_run(g.uid)
        if cur.get("running") and cur.get("started") and \
                datetime.fromisoformat(cur["started"]) > datetime.now() - RUN_STALE:
            return jsonify(error="A run is already in progress."), 409
        store.set_run(g.uid, running=True, started=now(), finished=None, exit_code=None,
                      step="Starting…", board=None, lines=["Starting a run (takes 5-15 minutes)..."])
        store.add_usage(g.uid, date.today().isoformat(), manual_runs=1)
        start_run(g.uid)
        return jsonify(ok=True)

    return app


def make_app():
    """Cloud Run entry point (gunicorn): wires in Firestore, Firebase Auth and the run job."""
    import firebase_admin
    from firebase_admin import auth

    from .store import FirestoreStore
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    region = os.environ.get("JOBBOT_REGION", "us-central1")
    job = os.environ.get("JOBBOT_RUN_JOB", "jobbot-run")
    firebase_admin.initialize_app(options={"projectId": project})
    store = FirestoreStore(project=project, bucket=os.environ["JOBBOT_BUCKET"])

    def start_run(uid):
        from google.cloud import run_v2
        O = run_v2.RunJobRequest.Overrides
        run_v2.JobsClient().run_job(request=run_v2.RunJobRequest(
            name=f"projects/{project}/locations/{region}/jobs/{job}",
            overrides=O(container_overrides=[O.ContainerOverride(args=["--uid", uid])])))

    from .pipeline import load_cfg
    cfg = load_cfg()  # also sets the LLM provider for resume import
    return create_app(store, auth.verify_id_token, start_run,
                      allowed_emails=os.environ.get("JOBBOT_ALLOWED_EMAILS", "").split(","),
                      firebase_config=json.loads(os.environ.get("JOBBOT_FIREBASE_CONFIG", "{}")),
                      import_model=cfg["model_score"],
                      admin_emails=os.environ.get("JOBBOT_ADMIN_EMAILS", "").split(","),
                      cloud_cfg=cfg.get("cloud") or {})
