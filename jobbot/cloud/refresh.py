"""One-off: check your hosted queue for postings that have closed.

  python -m jobbot.cloud.refresh you@example.com [--dry-run] [--adzuna N]

Same check the daily run does every 2 days, for all queued jobs at once.
Closed jobs move to the Closed tab (nothing is deleted). Uses your gcloud login.
"""
import argparse
import sys
from collections import Counter

from dotenv import load_dotenv

from .. import liveness
from .migrate import BUCKET, PROJECT, gcloud_credentials
from .pipeline import refresh_queue
from .store import FirestoreStore


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobbot.cloud.refresh")
    ap.add_argument("email")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--adzuna", type=int, default=100, help="max Adzuna API checks (daily quota)")
    args = ap.parse_args(argv)
    load_dotenv(".env")  # Muse / Adzuna keys for those sources' checks
    liveness.ADZUNA_PER_RUN = args.adzuna
    store = FirestoreStore(project=PROJECT, bucket=BUCKET, credentials=gcloud_credentials(PROJECT))
    uid = store.find_user(args.email.lower())
    if not uid:
        sys.exit(f"No hosted user for {args.email}.")
    if args.dry_run:
        q = store.jobs(uid, ["tailored", "new", "scored"])
        res = liveness.check_many(q)
        by = Counter((j["source"], st) for j, st, _ in res)
        for src in sorted({j["source"] for j in q}):
            print(f"  {src:10s} open={by[(src, 'open')]:3d} closed={by[(src, 'closed')]:3d} can't tell={by[(src, None)]:3d}")
        print(f"Would remove {sum(1 for _, st, _ in res if st == 'closed')} of {len(q)} (dry run, nothing written).")
        return
    refresh_queue(store, uid, every_days=0, cap=10_000)


if __name__ == "__main__":
    main()
