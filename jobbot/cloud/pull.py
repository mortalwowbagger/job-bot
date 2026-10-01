"""Copy your hosted prospects and applications down to the local job-bot (one-way).

  python -m jobbot.cloud.pull you@example.com [--dry-run]

Adds hosted jobs to jobs.db (or updates their status - the hosted site is the
main copy), downloads each packet's PDFs into output/, writes the cover letter,
answers and REVIEW.md there, and copies timeline entries. Then `python -m jobbot
apply` / the local dashboard can pre-fill those applications. Safe to re-run.
Uses your gcloud login, like migrate.py.
"""
import argparse
import json
import sys
from pathlib import Path

from .. import db
from ..render import slug
from .migrate import BUCKET, PROJECT, gcloud_credentials
from .store import JOB_FIELDS, FirestoreStore

PULL = ("tailored", "applied", "interview", "offer", "rejected", "withdrawn", "skipped")


def review_md(j):
    score = j.get("score_json") or {}
    warn = "\n".join(f"- [ ] {w}" for w in j.get("warnings") or []) or "- none"
    li = lambda xs: "\n".join(f"- {x}" for x in xs) or "- none"
    return (f"# {j['title']} - {j['company']}\n\n**Score:** {j.get('score')} | **Location:** {j.get('location')}\n\n"
            f"**Posting:** {j.get('url')}\n**Apply:** {j.get('apply_url')}\n\n## Check before submitting\n{warn}\n\n"
            f"## Why it matches\n{li(score.get('reasons', []))}\n\n## Concerns\n{li(score.get('concerns', []))}\n\n"
            f"(Synced from the hosted job-bot.)\n\n---\n\n## Job description\n\n{j.get('description') or ''}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobbot.cloud.pull")
    ap.add_argument("email")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    store = FirestoreStore(project=PROJECT, bucket=BUCKET, credentials=gcloud_credentials(PROJECT))
    uid = store.find_user(args.email.lower())
    if not uid:
        sys.exit(f"No hosted user for {args.email}.")
    con = db.connect("jobs.db")
    added = updated = packets = 0
    for j in sorted(store.jobs(uid, PULL), key=lambda r: -(r.get("score") or 0)):
        job = {k: j.get(k) or "" for k in JOB_FIELDS}
        job["ext_id"] = job["ext_id"] or j["id"]  # manual entries
        job["remote_hint"] = bool(j.get("remote_hint"))
        row = con.execute("SELECT * FROM jobs WHERE source=? AND ext_id=?", (job["source"], job["ext_id"])).fetchone()
        what = "add" if row is None else ("update" if row["status"] != j["status"] else "same")
        need_packet = j.get("has_packet") and not (row and row["packet_dir"] and Path(row["packet_dir"]).is_dir())
        print(f"  {what:6s} {j['status']:10s} {str(j.get('score') or ''):>3s}  {j['company'][:20]:20s} "
              f"{j['title'][:44]}{'  + packet' if need_packet else ''}")
        if args.dry_run or (what == "same" and not need_packet):
            continue
        if row is None:
            db.upsert(con, job)
            row = con.execute("SELECT * FROM jobs WHERE source=? AND ext_id=?", (job["source"], job["ext_id"])).fetchone()
            added += 1
        elif what == "update":
            updated += 1
        fields = {k: j.get(k) for k in ("status", "score", "applied_at", "notes", "contact", "salary",
                                        "next_step", "follow_up") if j.get(k) is not None}
        if j.get("score_json"):
            fields["score_json"] = json.dumps(j["score_json"])
        if need_packet:
            d = Path("output") / f"{row['id']:04d}-{slug(j['company'], 20)}-{slug(j['title'])}"
            d.mkdir(parents=True, exist_ok=True)
            for name in (j.get("files") or {}).values():
                data = store.get_file(uid, j["id"], name)
                if data:
                    (d / name).write_bytes(data)
            (d / "cover_letter.txt").write_text((j.get("cover_letter") or "").strip() + "\n")
            qa = "\n\n".join(f"**{a['q']}**\n\n{a['a']}" for a in j.get("answers") or [])
            (d / "answers.md").write_text(f"# Screening answers - {j['company']}\n\n{qa}\n")
            (d / "REVIEW.md").write_text(review_md(j))
            fields["packet_dir"] = str(d)
            packets += 1
        db.update(con, row["id"], **fields)
        have = {(e["at"], e["text"]) for e in db.events(con, row["id"])}
        for e in store.events(uid, j["id"]):
            if (e["at"], e["text"]) not in have:
                db.add_event(con, row["id"], e["kind"], e["text"], at=e["at"])
    print(f"Done: {added} added, {updated} status updates, {packets} packets downloaded"
          + (" (dry run, nothing written)" if args.dry_run else "."))


if __name__ == "__main__":
    main()
