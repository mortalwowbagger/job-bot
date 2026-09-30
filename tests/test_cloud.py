"""Offline tests for the hosted app: in-memory store, fake auth, fake LLM. No Google calls."""
import contextlib
import os
import unittest
from pathlib import Path
from unittest import mock

import yaml

from jobbot import sources
from jobbot.cloud import pipeline
from jobbot.cloud.store import MemoryStore, job_id
from jobbot.cloud.webapp import create_app

REPO = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
PROFILE_YAML = (REPO / "profile.example.yaml").read_text()


def fixture(name):
    import json
    return json.loads((FIX / name).read_text())


def fake_jobs():
    return (list(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
            + list(sources.parse_lever("beta", fixture("lever.json"))))


class FakeBrowser:
    """Stands in for Chromium: html_to_pdf just needs new_page().set_content/pdf/close."""
    def new_page(self):
        class P:
            def set_content(self, html, wait_until=None): self.html = html
            def pdf(self, path, **kw): Path(path).write_bytes(b"%PDF-1.4 " + self.html[:20].encode())
            def close(self): pass
        return P()


@contextlib.contextmanager
def fake_chromium():
    yield FakeBrowser()


class TestPipeline(unittest.TestCase):
    def run_once(self, store, uids=None):
        with mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "1"}), \
             mock.patch.object(sources, "iter_all", lambda c, log=print, **kw: iter(fake_jobs())):
            pipeline.run(store, CFG, uids=uids, browser_factory=fake_chromium)

    def owner(self, store, uid="u1", **extra):
        store.ensure_user(uid, f"{uid}@example.com", access="approved", is_admin=True, **extra)
        store.set_profile(uid, PROFILE_YAML)

    def test_run_scores_tailors_and_uploads(self):
        store = MemoryStore()
        self.owner(store)
        self.run_once(store)
        tailored = store.jobs("u1", ["tailored"])
        self.assertEqual(len(tailored), 2)
        j = tailored[0]
        self.assertTrue(j["has_packet"])
        self.assertTrue(any("Kubernetes" in w for w in j["warnings"]))  # guardrails still run
        for name in j["files"].values():
            self.assertTrue(name.startswith("Alex_Example_"))
            self.assertTrue(store.get_file("u1", j["id"], name).startswith(b"%PDF"))
        run = store.get_run("u1")
        self.assertFalse(run["running"])
        self.assertEqual(run["exit_code"], 0)
        self.assertTrue(any(l.startswith("Done. 2 new prospect") for l in run["lines"]))
        self.assertEqual(store.get_usage("u1", pipeline.datetime.now().strftime("%Y-%m"))["runs"], 1)
        # filtered-out jobs are never stored; a second run adds nothing
        self.assertEqual(len(store.jobsd), 2)
        self.run_once(store)
        self.assertEqual(len(store.jobsd), 2)

    def test_only_approved_users_with_profiles_run(self):
        store = MemoryStore()
        store.ensure_user("pending", "p@example.com", access="pending")
        store.set_profile("pending", PROFILE_YAML)
        store.ensure_user("noprofile", "n@example.com", access="approved")
        self.run_once(store)
        self.assertEqual(store.jobsd, {})

    def test_each_user_gets_their_own_filters_and_friend_limits(self):
        store = MemoryStore()
        self.owner(store)
        store.ensure_user("f1", "friend@example.com", access="approved", last_seen=pipeline.now(),
                          settings={"title_keywords": ["sdet"], "min_score": 70})
        store.set_profile("f1", PROFILE_YAML)
        self.run_once(store)
        titles = {j["title"] for j in store.jobs("f1", ["tailored", "low_score", "scored", "new"])}
        self.assertTrue(titles and all("sdet" in t.lower() for t in titles), titles)
        self.assertGreater(len(store.jobs("u1", ["tailored"])), len(titles) - 1)
        ucfg = pipeline.user_cfg(CFG, store.get_user("f1"))
        self.assertEqual(ucfg["max_tailor_per_run"], CFG["cloud"]["friend_limits"]["max_tailor_per_run"])

    def test_scheduled_run_skips_inactive_friends_but_manual_run_doesnt(self):
        store = MemoryStore()
        store.ensure_user("f1", "friend@example.com", access="approved", last_seen="2020-01-01T00:00:00",
                          settings={"title_keywords": ["sdet"]})
        store.set_profile("f1", PROFILE_YAML)
        self.run_once(store)                   # 7am schedule: skipped
        self.assertEqual(store.jobsd, {})
        self.run_once(store, uids=["f1"])      # pressed Run: runs
        self.assertTrue(store.jobsd)

    def test_missing_title_keywords_is_explained(self):
        store = MemoryStore()
        store.ensure_user("f1", "friend@example.com", access="approved", last_seen=pipeline.now())
        store.set_profile("f1", PROFILE_YAML)
        self.run_once(store, uids=["f1"])
        run = store.get_run("f1")
        self.assertEqual(run["exit_code"], 1)
        self.assertTrue(any("Settings" in l for l in run["lines"]))

    def test_cost_estimate(self):
        c = pipeline.Cost()
        c.add("claude-haiku-4-5-20251001", {"input_tokens": 1_000_000, "output_tokens": 0})
        c.add("claude-sonnet-5-5", {"input_tokens": 0, "output_tokens": 100_000})
        self.assertAlmostEqual(c.usd, 2.0)

    def test_job_id_is_firestore_safe(self):
        self.assertEqual(job_id({"source": "lever", "ext_id": "ab/c d"}), "lever-ab-c-d")


class TestSettings(unittest.TestCase):
    def test_phrases_match_whole_words_and_prefixes(self):
        from jobbot import settings
        import re
        m = lambda phrase, title: bool(re.search(settings.phrase_pattern(phrase), title.lower()))
        self.assertTrue(m("qa", "Senior QA Engineer"))
        self.assertFalse(m("qa", "Qatar Airways Analyst"))
        self.assertTrue(m("release engineer*", "Release Engineering Lead"))
        self.assertTrue(m("build & release", "Build & Release Engineer"))
        self.assertFalse(m("c++", "C Developer"))

    def test_clean_validates_input(self):
        from jobbot import settings
        ok, errs = settings.clean({"title_keywords": "QA Engineer\n\nsdet\nsdet", "min_score": "65"})
        self.assertEqual((ok["title_keywords"], ok["min_score"], errs), (["QA Engineer", "sdet"], 65, []))
        _, errs = settings.clean({"title_keywords": [], "min_score": 400})
        self.assertEqual(len(errs), 2)


class TestWebapp(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.runs = []
        tokens = {"good": {"uid": "u1", "email": "me@example.com"},
                  "other": {"uid": "u2", "email": "stranger@example.com"}}

        def verify(t):
            return tokens[t]
        app = create_app(self.store, verify, self.runs.append, admin_emails=["Me@example.com"],
                         firebase_config={"apiKey": "x"}, cloud_cfg=CFG["cloud"])
        self.c = app.test_client()
        self.h = {"Authorization": "Bearer good"}
        self.store.ensure_user("u1", "me@example.com")
        job = fake_jobs()[0]
        self.jid = job_id(job)
        self.store.put_job("u1", self.jid, {**job, "status": "tailored", "score": 80, "has_packet": True,
                                            "files": {"resume": "R_Resume.pdf"}, "warnings": ["w"],
                                            "score_json": {"reasons": ["r"]}})
        self.store.put_file("u1", self.jid, "R_Resume.pdf", b"%PDF-1.4 x")

    def test_auth_and_allowlist(self):
        self.assertEqual(self.c.get("/").status_code, 200)             # page itself is public
        self.assertEqual(self.c.get("/api/jobs").status_code, 401)
        self.assertEqual(self.c.get("/api/jobs", headers={"Authorization": "Bearer forged"}).status_code, 401)
        # open sign-up: a stranger gets in, but only ever sees their own (empty) data
        r = self.c.get("/api/jobs", headers={"Authorization": "Bearer other"})
        self.assertEqual((r.status_code, r.get_json()), (200, []))
        r = self.c.get("/api/jobs", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Cache-Control"], "private, no-store")

    def test_list_detail_file_and_tracking(self):
        rows = self.c.get("/api/jobs?view=review", headers=self.h).get_json()
        self.assertEqual([(r["id"], r["warnings"]) for r in rows], [(self.jid, 1)])
        self.assertEqual(self.c.get(f"/files/{self.jid}/R_Resume.pdf", headers=self.h).data, b"%PDF-1.4 x")
        self.assertEqual(self.c.get(f"/files/{self.jid}/other.pdf", headers=self.h).status_code, 404)
        self.c.post(f"/api/jobs/{self.jid}/mark", json={"status": "applied"}, headers=self.h)
        self.c.post(f"/api/jobs/{self.jid}/events", json={"text": "screen booked"}, headers=self.h)
        self.c.post(f"/api/jobs/{self.jid}/details", json={"follow_up": "2026-01-02"}, headers=self.h)
        d = self.c.get(f"/api/jobs/{self.jid}", headers=self.h).get_json()
        self.assertEqual(d["status"], "applied")
        self.assertIsNotNone(d["applied_at"])
        self.assertEqual([e["text"] for e in d["events"]], ["applied", "screen booked"])
        s = self.c.get("/api/state", headers=self.h).get_json()
        self.assertEqual((s["counts"], s["follow_ups_due"]), ({"applied": 1}, 1))

    def test_users_only_see_their_own_data(self):
        self.store.put_job("u2", "secret", {"status": "tailored", "company": "X", "title": "Y"})
        ids = [r["id"] for r in self.c.get("/api/jobs?view=review", headers=self.h).get_json()]
        self.assertNotIn("secret", ids)
        self.assertEqual(self.c.get("/api/jobs/secret", headers=self.h).status_code, 404)

    def test_add_manual_and_bad_input(self):
        r = self.c.post("/api/jobs", json={"company": "Initech", "title": "SDET", "applied_at": "2026-09-01"},
                        headers=self.h)
        jid = r.get_json()["id"]
        self.assertEqual(self.store.get_job("u1", jid)["source"], "manual")
        for body in ({"company": "", "title": "x"}, {"company": "a", "title": "b", "follow_up": "soon"}):
            self.assertEqual(self.c.post("/api/jobs", json=body, headers=self.h).status_code, 400)

    def test_run_needs_profile_and_is_single_flight(self):
        self.assertEqual(self.c.post("/api/run", headers=self.h).status_code, 400)
        self.store.set_profile("u1", PROFILE_YAML)
        self.assertEqual(self.c.post("/api/run", headers=self.h).status_code, 200)
        self.assertEqual(self.runs, ["u1"])
        self.assertEqual(self.c.post("/api/run", headers=self.h).status_code, 409)


if __name__ == "__main__":
    unittest.main()


class TestAccessAndSettings(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.runs = []
        people = {"owner": {"uid": "o", "email": "owner@example.com"},
                  "friend": {"uid": "f", "email": "friend@example.com"},
                  "unverified": {"uid": "x", "email": "x@example.com", "email_verified": False}}
        self.people = people
        self.H = {k: {"Authorization": f"Bearer {k}"} for k in people}
        self.c = self.app(signup="approval")

    def app(self, **cloud):
        return create_app(self.store, self.people.__getitem__, self.runs.append, admin_emails=["owner@example.com"],
                          cloud_cfg={**CFG["cloud"], **cloud}).test_client()

    def test_new_people_wait_for_approval(self):
        r = self.c.get("/api/jobs", headers=self.H["friend"])
        self.assertEqual((r.status_code, r.get_json()["access"]), (403, "pending"))
        self.assertEqual(self.c.get("/api/me", headers=self.H["friend"]).get_json()["access"], "pending")
        self.assertEqual(self.c.get("/api/jobs", headers=self.H["unverified"]).status_code, 403)
        # the friend can't approve themselves or see the user list
        self.assertEqual(self.c.get("/api/admin/users", headers=self.H["friend"]).status_code, 403)
        users = self.c.get("/api/admin/users", headers=self.H["owner"]).get_json()
        # pending first; the unverified account was never created
        self.assertEqual([(u["email"], u["access"]) for u in users],
                         [("friend@example.com", "pending"), ("owner@example.com", "approved")])
        self.assertEqual(self.c.get("/api/state", headers=self.H["owner"]).get_json()["pending_requests"], 1)
        self.c.post("/api/admin/users/f", json={"access": "approved"}, headers=self.H["owner"])
        self.assertEqual(self.c.get("/api/jobs", headers=self.H["friend"]).status_code, 200)
        self.assertEqual(self.c.post("/api/admin/users/o", json={"access": "denied"},
                                     headers=self.H["owner"]).status_code, 400)   # can't lock yourself out

    def test_open_signup_lets_people_straight_in_but_owner_can_revoke(self):
        c = self.app(signup="open")
        self.assertEqual(c.get("/api/jobs", headers=self.H["friend"]).status_code, 200)
        self.assertEqual(self.store.get_user("f")["access"], "approved")
        c.get("/api/me", headers=self.H["owner"])
        c.post("/api/admin/users/f", json={"access": "denied"}, headers=self.H["owner"])
        self.assertEqual(c.get("/api/jobs", headers=self.H["friend"]).status_code, 403)

    def test_monthly_budget_pauses_everyone_but_the_owner(self):
        c = self.app(signup="open", monthly_budget_usd=5)
        for who in ("owner", "friend"):
            c.get("/api/me", headers=self.H[who])
        self.store.set_profile("f", PROFILE_YAML)
        self.store.set_profile("o", PROFILE_YAML)
        c.post("/api/settings", json={"title_keywords": "sdet"}, headers=self.H["friend"])
        self.store.add_usage("f", pipeline.datetime.now().strftime("%Y-%m"), cost_usd=5.01)
        r = c.post("/api/run", headers=self.H["friend"])
        self.assertEqual(r.status_code, 429)
        self.assertIn("monthly budget", r.get_json()["error"])
        self.assertEqual(c.post("/api/run", headers=self.H["owner"]).status_code, 200)
        users = self.store.list_users()
        self.assertEqual([u for u, _ in pipeline.eligible(users, {**CFG, "cloud": {**CFG["cloud"], "monthly_budget_usd": 5}},
                                                           spent=pipeline.budget_used(self.store, users))], ["o"])

    def test_friend_settings_and_daily_run_limit(self):
        self.c.get("/api/me", headers=self.H["owner"])
        self.c.get("/api/me", headers=self.H["friend"])
        self.c.post("/api/admin/users/f", json={"access": "approved"}, headers=self.H["owner"])
        self.store.set_profile("f", PROFILE_YAML)
        s = self.c.get("/api/settings", headers=self.H["friend"]).get_json()
        self.assertEqual((s["saved"], s["settings"]["title_keywords"]), (False, []))
        r = self.c.post("/api/run", headers=self.H["friend"])
        self.assertIn("Settings", r.get_json()["error"])                      # no titles yet
        self.assertEqual(self.c.post("/api/settings", json={"title_keywords": ""},
                                     headers=self.H["friend"]).status_code, 400)
        self.c.post("/api/settings", json={"title_keywords": "sdet\nqa engineer", "min_score": 75},
                    headers=self.H["friend"])
        self.assertEqual(self.store.get_user("f")["settings"]["title_keywords"], ["sdet", "qa engineer"])
        per_day = CFG["cloud"]["friend_limits"]["runs_per_day"]
        for _ in range(per_day):
            self.assertEqual(self.c.post("/api/run", headers=self.H["friend"]).status_code, 200)
            self.store.set_run("f", running=False)
        self.assertEqual(self.c.post("/api/run", headers=self.H["friend"]).status_code, 429)
        self.assertEqual(self.runs, ["f"] * per_day)

    def test_owner_gets_their_original_filters_by_default(self):
        from jobbot import settings
        s = self.c.get("/api/settings", headers=self.H["owner"]).get_json()
        self.assertEqual(s["settings"], settings.OWNER_DEFAULTS)
        self.assertTrue(self.store.get_user("o")["is_admin"])
        self.assertIsNotNone(self.store.get_user("o")["last_seen"])

    def test_delete_my_data(self):
        self.c.get("/api/me", headers=self.H["friend"])
        self.store.put_job("f", "j1", {"status": "applied"})
        self.store.put_file("f", "j1", "a.pdf", b"x")
        self.assertEqual(self.c.post("/api/me/delete", json={}, headers=self.H["friend"]).status_code, 400)
        self.assertEqual(self.c.post("/api/me/delete", json={"confirm": "DELETE"},
                                     headers=self.H["friend"]).status_code, 200)
        self.assertIsNone(self.store.get_user("f"))
        self.assertEqual((self.store.jobsd, self.store.files), ({}, {}))


class TestProfile(unittest.TestCase):
    RESUME = ("Alex Example  alex.example@example.com  (555) 010-0000  Denver, CO\n"
              "QA engineer with 9 years of test automation.\n"
              "Northwind Bank - QA Automation Engineer - March 2026 - Present\n"
              "- Develop Appium tests in Java for iOS and Android.\n"
              "Skills: Appium, Java, Playwright, Selenium, Python, SQL, Jenkins, Git\n") * 2

    def test_import_keeps_targets_and_flags_what_the_pdf_doesnt_say(self):
        from jobbot import profile as prof
        current = yaml.safe_load(PROFILE_YAML)
        with mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "1"}):
            draft, flags = prof.import_resume(self.RESUME, current, "m")
        p, errors = prof.validate(draft)
        self.assertEqual(errors, [])
        self.assertEqual(p["targets"], current["targets"])       # user's targets survive an import
        self.assertEqual(p["contact"]["current_company"], "Northwind Bank")
        self.assertTrue(any("Kubernetes" in f for f in flags))   # invented bullet + skill flagged
        self.assertTrue(any(f.startswith("Skill") and "Kubernetes" in f for f in flags))
        self.assertFalse(any("Appium tests" in f for f in flags))  # real bullet isn't

    def test_import_rejects_unreadable_pdf_text(self):
        from jobbot import profile as prof
        with self.assertRaises(ValueError):
            prof.import_resume("   ", None, "m")

    def test_validate_explains_problems(self):
        from jobbot import profile as prof
        self.assertEqual(prof.validate(PROFILE_YAML)[1], [])
        _, errs = prof.validate("contact: {first_name: A}\nexperience: [{company: X}]\n")
        text = " ".join(errs)
        for bit in ("contact.last_name", "contact.email", "title is required", "facts", "skills"):
            self.assertIn(bit, text)
        self.assertIn("line", prof.validate("a: [unclosed")[1][0])

    def test_profile_endpoints(self):
        store = MemoryStore()
        store.ensure_user("u1", "me@example.com")
        c = create_app(store, lambda t: {"uid": "u1", "email": "me@example.com"}, lambda u: None,
                       admin_emails=["me@example.com"]).test_client()
        h = {"Authorization": "Bearer x"}
        self.assertFalse(c.get("/api/state", headers=h).get_json()["has_profile"])
        r = c.post("/api/profile", json={"profile_yaml": "contact: {}"}, headers=h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("first_name", r.get_json()["error"])
        self.assertEqual(c.post("/api/profile", json={"profile_yaml": PROFILE_YAML}, headers=h).status_code, 200)
        self.assertEqual(c.get("/api/profile", headers=h).get_json()["profile_yaml"], PROFILE_YAML)
        self.assertTrue(c.get("/api/state", headers=h).get_json()["has_profile"])
        import io
        r = c.post("/api/profile/import", data={"pdf": (io.BytesIO(b"not a pdf"), "r.pdf")}, headers=h)
        self.assertEqual(r.status_code, 400)
