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
from .ui import render

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
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 + 64 * 1024
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
        return jsonify(run=run.state(), apply=applying.state(), counts=counts, follow_ups_due=due,
                       has_profile=(root / "profile.yaml").exists())

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

    @app.get("/api/profile")
    def get_profile():
        f = root / "profile.yaml"
        return jsonify(profile_yaml=f.read_text() if f.exists() else "")

    @app.post("/api/profile")
    def save_profile():
        from . import profile as prof
        text = str((request.get_json(silent=True) or {}).get("profile_yaml") or "")
        _, errors = prof.validate(text)
        if errors:
            return jsonify(error="Fix these before saving: " + "; ".join(errors[:6]), errors=errors), 400
        f = root / "profile.yaml"
        if f.exists():  # one-step undo
            (root / "profile.yaml.bak").write_text(f.read_text())
        f.write_text(text)
        return jsonify(ok=True)

    @app.post("/api/profile/import")
    def import_profile():
        import yaml as _yaml
        from . import llm, profile as prof
        f = request.files.get("pdf")
        if not f:
            abort(400, "Choose a PDF first.")
        data = f.read()
        if not data.startswith(b"%PDF"):
            abort(400, "That doesn't look like a PDF.")
        cfg = _yaml.safe_load((root / "config.yaml").read_text())
        llm.PROVIDER = cfg.get("provider", "claude")
        cur = root / "profile.yaml"
        try:
            current, _ = prof.validate(cur.read_text() if cur.exists() else "")
            draft, flags = prof.import_resume(prof.pdf_text(data), current, cfg["model_score"])
        except ValueError as e:
            abort(400, str(e))
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"Import failed: {type(e).__name__}: {str(e)[:200]}"), 502
        return jsonify(profile_yaml=draft, unsupported=flags)

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


PAGE = render({"hosted": False})
