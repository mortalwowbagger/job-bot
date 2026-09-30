"""Job search run for the hosted app (a Cloud Run Job).

  python -m jobbot.cloud.pipeline              every user with a profile (the daily schedule)
  python -m jobbot.cloud.pipeline --uid UID    one user ("Run search" button)

Same steps as `python -m jobbot run`: fetch public boards once, then per user
filter -> score (Haiku) -> tailor (Sonnet) -> guardrails -> PDFs. Progress is
written to users/{uid}/runs/latest so the dashboard can show it.
"""
import argparse
import os
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

import yaml

from datetime import datetime, timedelta

from .. import filters, llm, settings, sources
from ..llm import FatalLLMError
from .store import JOB_FIELDS, job_id, now

# $ per million tokens (input, output), for cost estimates only
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
          "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-4-6": (3.0, 15.0)}


def price(model):
    return next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if model.startswith(k)),
                (0.0, 0.0))


class Cost:
    def __init__(self):
        self.usd = 0.0

    def add(self, model, usage):
        if usage:
            pin, pout = price(model)
            self.usd += (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1e6


def user_cfg(cfg, user):
    """config.yaml + this user's search settings + (for non-owners) the friend limits."""
    s = user.get("settings") or (settings.OWNER_DEFAULTS if user.get("is_admin") else {})
    ucfg = settings.to_cfg(cfg, s)
    if not user.get("is_admin"):
        lim = (cfg.get("cloud") or {}).get("friend_limits") or {}
        for k in ("max_score_per_run", "max_tailor_per_run"):
            if k in lim:
                ucfg[k] = min(ucfg.get(k, lim[k]), lim[k])
    return ucfg


def budget_used(store, users):
    month = datetime.now().strftime("%Y-%m")
    return sum(store.get_usage(u, month).get("cost_usd", 0.0) for u, d in users if not d.get("is_admin"))


def eligible(users, cfg, uids=None, scheduled=False, spent=0.0):
    days = (cfg.get("cloud") or {}).get("inactive_days", 14)
    over_budget = spent >= (cfg.get("cloud") or {}).get("monthly_budget_usd", 25)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    for u, d in users:
        if uids and u not in uids:
            continue
        if not d.get("profile_yaml") or d.get("access") != "approved":
            continue
        if over_budget and not d.get("is_admin"):
            print(f"Skipping {d.get('email')}: monthly budget reached")
            continue
        if scheduled and not d.get("is_admin") and (d.get("last_seen") or "") < cutoff:
            print(f"Skipping {d.get('email')}: inactive for {days}+ days")
            continue
        out.append((u, d))
    return out


class Progress:
    """Rolling log for one user's run, flushed to the store every few seconds."""

    def __init__(self, store, uid, every=3.0):
        self.store, self.uid, self.every = store, uid, every
        self.lines, self.last, self.step_text, self.board = deque(maxlen=150), 0.0, None, None

    def start(self):
        self.store.set_run(self.uid, running=True, started=now(), finished=None, exit_code=None,
                           step="Starting…", board=None, lines=[])

    def log(self, line, force=False):
        print(f"[{self.uid[:6]}] {line}", flush=True)
        self.lines.append(line)
        if "/" in line and line.strip().startswith("("):
            num = line.strip()[1:].split(")")[0].split("/")
            if len(num) == 2 and all(n.isdigit() for n in num):
                self.board = num
        if force or time.time() - self.last >= self.every:
            self.flush()

    def step(self, text):
        self.step_text = text
        self.log(text, force=True)

    def flush(self, **extra):
        self.last = time.time()
        self.store.set_run(self.uid, step=self.step_text, board=self.board, lines=list(self.lines)[-80:], **extra)

    def finish(self, exit_code):
        self.flush(running=False, finished=now(), exit_code=exit_code)


def run(store, cfg, uids=None, browser_factory=None):
    everyone = store.list_users()
    users = eligible(everyone, cfg, uids, scheduled=not uids, spent=budget_used(store, everyone))
    if not users:
        print("No approved users with a profile to run for.")
        return
    progs = {u: Progress(store, u) for u, _ in users}
    for p in progs.values():
        p.start()

    def broadcast(line, force=False):
        for p in progs.values():
            p.log(line, force)

    for p in progs.values():
        p.step("[1/3] Fetching listings")
    try:
        jobs = list(sources.iter_all(cfg, log=broadcast))
    except Exception as e:  # noqa: BLE001
        broadcast(f"Fetching failed: {e}", force=True)
        for p in progs.values():
            p.finish(1)
        raise
    broadcast(f"Fetched {len(jobs)} listings", force=True)

    factory = browser_factory or _chromium
    with factory() as browser:
        for uid, udata in users:
            prog = progs[uid]
            cost = Cost()
            try:
                ucfg = user_cfg(cfg, udata)
                if not ucfg["title_include"]:
                    raise ValueError("Add the job titles you want in Settings first.")
                passing = [j for j in jobs if filters.passes(j, ucfg)[0]]
                prog.log(f"{len(passing)} match your job titles and locations", force=True)
                profile = yaml.safe_load(udata["profile_yaml"])
                run_user(store, ucfg, uid, profile, passing, browser, prog, cost)
                prog.finish(0)
            except Exception as e:  # noqa: BLE001 - one user's failure shouldn't stop the others
                prog.log(f"ERROR: {type(e).__name__}: {e}", force=True)
                prog.finish(1)
            finally:
                day = datetime.now().strftime("%Y-%m-%d")
                store.add_usage(uid, day[:7], runs=1, cost_usd=round(cost.usd, 4))
                store.add_usage(uid, day, cost_usd=round(cost.usd, 4))


class _chromium:
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.p = sync_playwright().start()
        self.b = self.p.chromium.launch()
        return self.b

    def __exit__(self, *exc):
        self.b.close()
        self.p.stop()


def run_user(store, cfg, uid, profile, passing, browser, prog, cost=None):
    from ..render import file_base, html_to_pdf, letter_html, resume_html
    from ..score import score_job
    from ..tailor import tailor_job, validate

    cost = cost or Cost()
    started = now()
    by_id = {job_id(j): j for j in passing}
    new_ids = sorted(set(by_id) - store.existing_ids(uid, list(by_id)))
    for jid in new_ids:
        j = by_id[jid]
        store.put_job(uid, jid, {**{k: j.get(k) for k in JOB_FIELDS}, "status": "new"})
    prog.log(f"New for you: {len(new_ids)}", force=True)

    prog.step("[2/3] Scoring")
    rows = store.jobs(uid, ["new"])[: cfg.get("max_score_per_run", 60)]
    prog.log(f"Scoring {len(rows)} jobs with {cfg['model_score']}...")
    for r in rows:
        try:
            s = score_job(r, profile, cfg["model_score"])
        except FatalLLMError:
            raise
        except Exception as e:  # noqa: BLE001
            prog.log(f"  ERROR scoring {r['company']}: {e}")
            continue
        cost.add(cfg["model_score"], s.pop("_usage", None))
        status = "scored" if s["score"] >= cfg["min_score"] and not s["dealbreakers"] else "low_score"
        store.update_job(uid, r["id"], score=s["score"], score_json=s, status=status)
        prog.log(f"  {'✓' if status == 'scored' else ' '} {s['score']:3d}  {r['company'][:18]:18s} {r['title'][:50]}")

    prog.step("[3/3] Tailoring")
    rows = sorted(store.jobs(uid, ["scored"]), key=lambda r: -(r.get("score") or 0))
    rows = rows[: cfg.get("max_tailor_per_run", 15)]
    prog.log(f"Tailoring {len(rows)} packets with {cfg['model_write']}...")
    with tempfile.TemporaryDirectory() as tmp:
        for r in rows:
            try:
                packet = tailor_job(r, profile, r.get("score_json") or {}, cfg["model_write"])
            except FatalLLMError:
                raise
            except Exception as e:  # noqa: BLE001
                prog.log(f"  ERROR tailoring {r['company']}: {e}")
                continue
            cost.add(cfg["model_write"], packet.pop("_usage", None))
            packet, warnings = validate(packet, profile)
            base = file_base(profile, r)
            files = {"resume": f"{base}_Resume.pdf", "letter": f"{base}_Cover_Letter.pdf"}
            for key, html in (("resume", resume_html(profile, packet)),
                              ("letter", letter_html(packet["cover_letter"]))):
                out = Path(tmp) / files[key]
                html_to_pdf(html, out, browser)
                store.put_file(uid, r["id"], files[key], out.read_bytes())
            store.update_job(
                uid, r["id"], status="tailored", has_packet=True, warnings=warnings, files=files,
                cover_letter=packet["cover_letter"].strip(),
                answers=[{"q": a["question"], "a": a["answer"]} for a in packet["screening_answers"]])
            w = f"  ({len(warnings)} to check)" if warnings else ""
            prog.log(f"  {r['score']:3d}  {r['company'][:18]:18s} {r['title'][:45]}{w}")

    new = [r for r in store.jobs(uid, ["tailored"]) if r.get("updated_at", "") >= started]
    new.sort(key=lambda r: -(r.get("score") or 0))
    prog.log(f"Estimated API cost: ${cost.usd:.2f}")
    prog.log(f"Done. {len(new)} new prospect(s)" + (":" if new else "."), force=True)
    for r in new:
        prog.log(f"  {r['score']:3d}  {r['company'][:20]:20s} {r['title'][:50]}")


def load_cfg():
    cfg = yaml.safe_load(Path(os.getenv("JOBBOT_CONFIG", "config.yaml")).read_text())
    llm.PROVIDER = cfg.get("provider", "claude")
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobbot.cloud.pipeline")
    ap.add_argument("--uid", action="append", help="run only for this user (repeatable)")
    args = ap.parse_args(argv)
    from .store import FirestoreStore
    store = FirestoreStore(project=os.getenv("GOOGLE_CLOUD_PROJECT"), bucket=os.environ["JOBBOT_BUCKET"])
    run(store, load_cfg(), uids=args.uid)


if __name__ == "__main__":
    sys.exit(main())
