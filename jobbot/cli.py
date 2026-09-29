"""job-bot command line.

  python -m jobbot run            fetch + filter + score + tailor (the daily command)
  python -m jobbot fetch          pull new listings from all sources
  python -m jobbot score          score new listings with the LLM
  python -m jobbot tailor         build packets for high scorers
  python -m jobbot review         list packets waiting for you
  python -m jobbot apply [ID]     open + pre-fill the form (next best job if no ID)
  python -m jobbot mark ID STATUS [--note ...]   e.g. mark 12 applied / skipped / interview
  python -m jobbot status         pipeline counts
  python -m jobbot export         write tracker.csv
  python -m jobbot check-boards   test every company slug in config.yaml
  python -m jobbot ping           check API key + model IDs (costs < $0.01)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import db, filters, sources
from .llm import FatalLLMError

ROOT = Path.cwd()


def load_yaml(name):
    p = ROOT / name
    if not p.exists():
        sys.exit(f"Missing {name} - run this from the job-bot folder.")
    return yaml.safe_load(p.read_text())


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def cmd_fetch(con, cfg, args):
    print("Fetching listings...")
    new = kept = 0
    for job in sources.iter_all(cfg):
        if not db.upsert(con, job):
            continue
        new += 1
        row = con.execute("SELECT id FROM jobs WHERE source=? AND ext_id=?",
                          (job["source"], job["ext_id"])).fetchone()
        ok, why = filters.passes(job, cfg)
        if ok:
            kept += 1
        else:
            con.execute("UPDATE jobs SET status='filtered_out', filter_reason=? WHERE id=?",
                        (why, row["id"]))
    con.commit()
    print(f"New listings: {new}  |  passed title/location filters: {kept}")


def cmd_score(con, cfg, args):
    from .score import score_job
    profile = load_yaml("profile.yaml")
    rows = db.by_status(con, "new", limit=cfg.get("max_score_per_run", 60))
    if not rows:
        print("Nothing new to score.")
        return
    print(f"Scoring {len(rows)} jobs with {cfg['model_score']}...")
    tokens = 0
    for r in rows:
        try:
            s = score_job(dict(r), profile, cfg["model_score"])
        except FatalLLMError as e:
            sys.exit(f"Stopping: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  #{r['id']} ERROR {e}")
            continue
        tokens += (s.pop("_usage", {}) or {}).get("total_tokens", 0)
        status = "scored" if s["score"] >= cfg["min_score"] and not s["dealbreakers"] else "low_score"
        db.update(con, r["id"], score=s["score"], score_json=s, status=status)
        flag = "✓" if status == "scored" else " "
        print(f"  {flag} {s['score']:3d}  #{r['id']:<5} {r['company'][:18]:18s} {r['title'][:55]}")
    if tokens:
        print(f"Tokens used: {tokens:,}")


def cmd_tailor(con, cfg, args):
    from playwright.sync_api import sync_playwright

    from .render import write_packet
    from .tailor import tailor_job, validate
    profile = load_yaml("profile.yaml")
    rows = db.by_status(con, "scored", order="score DESC", limit=cfg.get("max_tailor_per_run", 15))
    if not rows:
        print("No scored jobs waiting for tailoring.")
        return
    print(f"Tailoring {len(rows)} packets with {cfg['model_write']}...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for r in rows:
            job = dict(r)
            score = json.loads(job["score_json"] or "{}")
            try:
                packet = tailor_job(job, profile, score, cfg["model_write"])
            except FatalLLMError as e:
                sys.exit(f"Stopping: {e}")
            except Exception as e:  # noqa: BLE001
                print(f"  #{job['id']} ERROR {e}")
                continue
            packet.pop("_usage", None)
            packet, warnings = validate(packet, profile)
            d = write_packet(ROOT / "output", job, profile, packet, score, warnings, browser)
            db.update(con, job["id"], status="tailored", packet_dir=str(d))
            w = f"  ({len(warnings)} to check)" if warnings else ""
            print(f"  {job['score']:3d}  #{job['id']:<5} {job['company'][:18]:18s} "
                  f"{job['title'][:45]}{w}")
        browser.close()
    print("\nNext: `python -m jobbot review`, then `python -m jobbot apply`")


def cmd_review(con, cfg, args):
    rows = db.by_status(con, "tailored", order="score DESC")
    if not rows:
        print("No packets waiting. Run `python -m jobbot run`.")
        return
    print(f"{len(rows)} packets ready (best first):\n")
    for r in rows:
        print(f"  #{r['id']:<5} {r['score']:3d}  {r['company'][:20]:20s} {r['title'][:50]}")
        print(f"         {r['packet_dir']}/REVIEW.md")


def cmd_apply(con, cfg, args):
    from . import apply
    if args.id:
        row = db.get(con, args.id)
    else:
        rows = db.by_status(con, "tailored", order="score DESC", limit=1)
        row = rows[0] if rows else None
    if not row:
        sys.exit("No job to apply to. Run `python -m jobbot review`.")
    if not row["packet_dir"]:
        sys.exit(f"Job #{row['id']} has no packet yet. Run `python -m jobbot tailor`.")
    applied_today = con.execute("SELECT COUNT(*) FROM jobs WHERE applied_at >= ?",
                                (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    limit = cfg.get("daily_apply_limit", 20)
    if applied_today >= limit:
        sys.exit(f"Already applied to {applied_today} today (daily_apply_limit={limit}).")
    status = apply.run(dict(row), load_yaml("profile.yaml"), row["packet_dir"])
    fields = {"status": status}
    if status == "applied":
        fields["applied_at"] = db.now()
    db.update(con, row["id"], **fields)
    print(f"#{row['id']} -> {status}")


def cmd_mark(con, cfg, args):
    fields = {"status": args.status}
    if args.status == "applied":
        fields["applied_at"] = db.now()
    if args.note:
        fields["notes"] = args.note
    db.update(con, args.id, **fields)
    print(f"#{args.id} -> {args.status}")


def cmd_status(con, cfg, args):
    c = db.counts(con)
    order = ["new", "filtered_out", "low_score", "scored", "tailored", "applied", "skipped"]
    for k in order + sorted(set(c) - set(order)):
        if k in c:
            print(f"  {k:14s} {c[k]:5d}")


def cmd_export(con, cfg, args):
    n = db.export_csv(con, ROOT / "tracker.csv")
    print(f"Wrote tracker.csv ({n} rows) - open in Numbers/Excel/Google Sheets.")


def cmd_check(con, cfg, args):
    src = cfg.get("sources", {})
    for kind, fn in [("greenhouse", sources.fetch_greenhouse), ("lever", sources.fetch_lever),
                     ("ashby", sources.fetch_ashby)]:
        for slug in src.get(kind, []) or []:
            try:
                jobs = list(fn(slug))
                hits = sum(filters.passes(j, cfg)[0] for j in jobs)
                print(f"  OK    {kind}:{slug:16s} {len(jobs):4d} jobs, {hits} match filters")
            except Exception as e:  # noqa: BLE001
                print(f"  BAD   {kind}:{slug:16s} {type(e).__name__} - remove or fix slug")


def cmd_ping(con, cfg, args):
    from .llm import chat_json
    schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}
    for key in ("model_score", "model_write"):
        try:
            out = chat_json(cfg[key], "Reply with JSON.", "Return ok=true.", schema, name="ping")
            print(f"  OK    {cfg.get('provider', 'claude')}:{cfg[key]}  ({key})  -> {out.get('ok')}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {cfg[key]}  ({key}): {e}")


def cmd_run(con, cfg, args):
    cmd_fetch(con, cfg, args)
    cmd_score(con, cfg, args)
    cmd_tailor(con, cfg, args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobbot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ["run", "fetch", "score", "tailor", "review", "status", "export", "check-boards", "ping"]:
        sub.add_parser(name)
    a = sub.add_parser("apply")
    a.add_argument("id", nargs="?", type=int)
    m = sub.add_parser("mark")
    m.add_argument("id", type=int)
    m.add_argument("status")
    m.add_argument("--note")
    args = ap.parse_args(argv)

    load_env()
    cfg = load_yaml("config.yaml")
    from . import llm
    llm.PROVIDER = cfg.get("provider", "claude")
    con = db.connect(str(ROOT / "jobs.db"))
    {"run": cmd_run, "fetch": cmd_fetch, "score": cmd_score, "tailor": cmd_tailor,
     "review": cmd_review, "apply": cmd_apply, "mark": cmd_mark, "status": cmd_status,
     "export": cmd_export, "check-boards": cmd_check, "ping": cmd_ping}[args.cmd](con, cfg, args)
