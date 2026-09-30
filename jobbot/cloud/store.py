"""Storage for the hosted app: Firestore for data, Cloud Storage for packet PDFs.

Layout (everything is per user, so friends can be added later):
  users/{uid}                      email, access (pending/approved/denied), is_admin,
                                   settings, profile_yaml, last_seen, created_at
  users/{uid}/usage/{YYYY-MM[-DD]} runs, manual_runs, cost_usd (cost guardrails)
  users/{uid}/jobs/{job_id}        one prospect or application (only jobs that
                                   passed the free filters are stored)
  users/{uid}/jobs/{job_id}/events timeline entries
  users/{uid}/runs/latest          progress of the current / last run
  gs://{bucket}/users/{uid}/jobs/{job_id}/{file}   resume + cover letter PDFs

MemoryStore implements the same methods in memory for tests.
"""
import re
from datetime import datetime

JOB_FIELDS = ["source", "ext_id", "board", "company", "title", "location", "url", "apply_url",
              "description", "remote_hint"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def job_id(job):
    """Stable Firestore document id for a fetched job, e.g. 'greenhouse-8011568'."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{job['source']}-{job['ext_id']}")[:200]


class FirestoreStore:
    def __init__(self, project=None, bucket=None, credentials=None):
        from google.cloud import firestore, storage
        self.db = firestore.Client(project=project, credentials=credentials)
        self.bucket = storage.Client(project=project, credentials=credentials).bucket(bucket) if bucket else None

    # --- users
    def _user(self, uid):
        return self.db.collection("users").document(uid)

    def get_user(self, uid):
        snap = self._user(uid).get()
        return snap.to_dict() if snap.exists else None

    def ensure_user(self, uid, email, **defaults):
        snap = self._user(uid).get()
        if not snap.exists:
            data = {"email": email, "created_at": now(), **defaults}
            self._user(uid).set(data)
            return data
        return snap.to_dict()

    def update_user(self, uid, **fields):
        self._user(uid).set(fields, merge=True)

    def list_users(self):
        return [(s.id, s.to_dict()) for s in self.db.collection("users").stream()]

    def add_usage(self, uid, key, **inc):
        from google.cloud import firestore
        self._user(uid).collection("usage").document(key).set(
            {k: firestore.Increment(v) for k, v in inc.items()}, merge=True)

    def get_usage(self, uid, key):
        snap = self._user(uid).collection("usage").document(key).get()
        return snap.to_dict() if snap.exists else {}

    def delete_user_data(self, uid):
        """Everything: jobs, timelines, runs, usage, profile, settings, PDFs."""
        self.db.recursive_delete(self._user(uid))
        if self.bucket:
            for blob in self.bucket.list_blobs(prefix=f"users/{uid}/"):
                blob.delete()

    def set_profile(self, uid, profile_yaml):
        self._user(uid).set({"profile_yaml": profile_yaml, "profile_updated_at": now()}, merge=True)

    def find_user(self, email):
        for snap in self.db.collection("users").where("email", "==", email).limit(1).stream():
            return snap.id
        return None

    def users_with_profiles(self):
        return [(s.id, s.to_dict()) for s in self.db.collection("users").stream()
                if (s.to_dict() or {}).get("profile_yaml")]

    # --- jobs
    def _jobs(self, uid):
        return self._user(uid).collection("jobs")

    def existing_ids(self, uid, ids):
        refs = [self._jobs(uid).document(i) for i in ids]
        return {s.id for s in self.db.get_all(refs) if s.exists} if refs else set()

    def put_job(self, uid, jid, data):
        self._jobs(uid).document(jid).set({**data, "id": jid, "created_at": now(), "updated_at": now()})

    def update_job(self, uid, jid, **fields):
        self._jobs(uid).document(jid).update({**fields, "updated_at": now()})

    def get_job(self, uid, jid):
        snap = self._jobs(uid).document(jid).get()
        return snap.to_dict() if snap.exists else None

    def jobs(self, uid, statuses):
        from google.cloud.firestore_v1.base_query import FieldFilter
        q = self._jobs(uid).where(filter=FieldFilter("status", "in", list(statuses)[:30]))
        return [s.to_dict() for s in q.stream()]

    def status_summary(self, uid):
        """Just status + follow_up for every stored job (for header counts)."""
        return [s.to_dict() for s in self._jobs(uid).select(["status", "follow_up"]).stream()]

    # --- events
    def add_event(self, uid, jid, kind, text, at=None):
        self._jobs(uid).document(jid).collection("events").add({"at": at or now(), "kind": kind, "text": text})

    def events(self, uid, jid):
        evs = [s.to_dict() for s in self._jobs(uid).document(jid).collection("events").stream()]
        return sorted(evs, key=lambda e: e["at"])

    # --- files
    def put_file(self, uid, jid, name, data, content_type="application/pdf"):
        self.bucket.blob(f"users/{uid}/jobs/{jid}/{name}").upload_from_string(data, content_type=content_type)

    def get_file(self, uid, jid, name):
        blob = self.bucket.blob(f"users/{uid}/jobs/{jid}/{name}")
        return blob.download_as_bytes() if blob.exists() else None

    # --- run status
    def get_run(self, uid):
        snap = self._user(uid).collection("runs").document("latest").get()
        return snap.to_dict() if snap.exists else {}

    def set_run(self, uid, **fields):
        self._user(uid).collection("runs").document("latest").set(fields, merge=True)


class MemoryStore:
    """In-memory stand-in with the same interface (tests, dry runs)."""

    def __init__(self):
        self.users, self.jobsd, self.eventsd, self.files, self.runs, self.usage = {}, {}, {}, {}, {}, {}

    def get_user(self, uid):
        return self.users.get(uid)

    def ensure_user(self, uid, email, **defaults):
        if uid not in self.users:
            self.users[uid] = {"email": email, "created_at": now(), **defaults}
        return dict(self.users[uid])

    def update_user(self, uid, **fields):
        self.users.setdefault(uid, {}).update(fields)

    def list_users(self):
        return [(u, dict(d)) for u, d in self.users.items()]

    def add_usage(self, uid, key, **inc):
        doc = self.usage.setdefault((uid, key), {})
        for k, v in inc.items():
            doc[k] = doc.get(k, 0) + v

    def get_usage(self, uid, key):
        return dict(self.usage.get((uid, key), {}))

    def delete_user_data(self, uid):
        self.users.pop(uid, None)
        self.runs.pop(uid, None)
        for d in (self.jobsd, self.eventsd, self.usage):
            for k in [k for k in d if k[0] == uid]:
                d.pop(k)
        for k in [k for k in self.files if k[0] == uid]:
            self.files.pop(k)

    def set_profile(self, uid, profile_yaml):
        self.users.setdefault(uid, {})["profile_yaml"] = profile_yaml

    def find_user(self, email):
        return next((u for u, d in self.users.items() if d.get("email") == email), None)

    def users_with_profiles(self):
        return [(u, d) for u, d in self.users.items() if d.get("profile_yaml")]

    def existing_ids(self, uid, ids):
        return {i for i in ids if (uid, i) in self.jobsd}

    def put_job(self, uid, jid, data):
        self.jobsd[(uid, jid)] = {**data, "id": jid, "created_at": now(), "updated_at": now()}

    def update_job(self, uid, jid, **fields):
        if (uid, jid) not in self.jobsd:
            raise KeyError(jid)
        self.jobsd[(uid, jid)].update(fields, updated_at=now())

    def get_job(self, uid, jid):
        j = self.jobsd.get((uid, jid))
        return dict(j) if j else None

    def jobs(self, uid, statuses):
        return [dict(j) for (u, _), j in self.jobsd.items() if u == uid and j.get("status") in statuses]

    def status_summary(self, uid):
        return [{"status": j.get("status"), "follow_up": j.get("follow_up")}
                for (u, _), j in self.jobsd.items() if u == uid]

    def add_event(self, uid, jid, kind, text, at=None):
        self.eventsd.setdefault((uid, jid), []).append({"at": at or now(), "kind": kind, "text": text})

    def events(self, uid, jid):
        return sorted(self.eventsd.get((uid, jid), []), key=lambda e: e["at"])

    def put_file(self, uid, jid, name, data, content_type="application/pdf"):
        self.files[(uid, jid, name)] = data

    def get_file(self, uid, jid, name):
        return self.files.get((uid, jid, name))

    def get_run(self, uid):
        return dict(self.runs.get(uid, {}))

    def set_run(self, uid, **fields):
        self.runs.setdefault(uid, {}).update(fields)
