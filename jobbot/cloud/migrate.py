"""Copy local job-bot data into the hosted app for one user.

  python -m jobbot.cloud.migrate you@example.com [--profile-only] [--dry-run]

Copies profile.yaml, every tracked job (packets, applications, near misses,
skipped) with its timeline, and the packet PDFs. Filtered-out listings stay
local. Sign in to the hosted site once first so your user record exists.
Uses your gcloud login (`gcloud auth login`), not a service-account key.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from .. import db
from ..web import _packet
from .store import JOB_FIELDS, FirestoreStore, job_id

PROJECT = "job-bot-app"
BUCKET = "job-bot-app-packets"
KEEP = ("tailored", "applied", "interview", "offer", "rejected", "withdrawn", "skipped",
        "low_score", "scored")


def gcloud_credentials(project):
    from google.oauth2.credentials import Credentials
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True,
                           check=True).stdout.strip()
    return Credentials(token, quota_project_id=project)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobbot.cloud.migrate")
    ap.add_argument("email")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--profile-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    store = FirestoreStore(project=args.project, bucket=args.bucket,
                           credentials=gcloud_credentials(args.project))
    uid = store.find_user(args.email.lower())
    if not uid:
        sys.exit(f"No hosted user for {args.email}. Sign in to the site once, then re-run.")
    print(f"Migrating into user {uid} ({args.email})")

    profile = Path("profile.yaml").read_text()
    if not args.dry_run:
        store.set_profile(uid, profile)
    print("  profile.yaml uploaded")
    if args.profile_only:
        return

    con = db.connect("jobs.db")
    rows = con.execute(f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(KEEP))})", KEEP).fetchall()
    import json
    already = store.existing_ids(uid, [job_id(r) for r in rows])
    for r in rows:
        jid = job_id(r)
        if jid in already:  # safe to re-run: never duplicates jobs or timeline entries
            continue
        data = {k: r[k] for k in JOB_FIELDS} | {
            k: r[k] for k in ("status", "score", "applied_at", "notes", "contact", "salary",
                              "next_step", "follow_up") if r[k] is not None}
        if r["score_json"]:
            data["score_json"] = json.loads(r["score_json"])
        pkt = _packet(r) if r["packet_dir"] else None
        if pkt and pkt["files"]:
            data.update(has_packet=True, warnings=pkt["warnings"], answers=pkt["answers"],
                        cover_letter=pkt["cover_letter"], files=pkt["files"])
        events = db.events(con, r["id"])
        print(f"  {r['status']:10s} {r['company'][:20]:20s} {r['title'][:40]:40s} "
              f"{len(events)} events{', packet' if pkt and pkt['files'] else ''}")
        if args.dry_run:
            continue
        store.put_job(uid, jid, data)
        for e in events:
            store.add_event(uid, jid, e["kind"], e["text"], at=e["at"])
        for name in (pkt or {}).get("files", {}).values():
            store.put_file(uid, jid, name, (Path(r["packet_dir"]) / name).read_bytes())
    print(f"Done: {len(rows)} jobs{' (dry run, nothing written)' if args.dry_run else ''}.")


if __name__ == "__main__":
    main()
