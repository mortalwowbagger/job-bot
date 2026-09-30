"""Offline tests: no network, no API key, no cost.  Run: python -m unittest -v"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from jobbot import db, filters, sources, tailor

HERE = Path(__file__).parent
FIX = HERE / "fixtures"
REPO = HERE.parent
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
# tests use the fictional example profile, so they run on any clone
PROFILE = yaml.safe_load((REPO / "profile.example.yaml").read_text())


def fixture(name):
    return json.loads((FIX / name).read_text())


class TestParsers(unittest.TestCase):
    def test_greenhouse(self):
        jobs = list(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
        self.assertEqual(len(jobs), 3)
        j = jobs[0]
        self.assertEqual(j["apply_url"], "https://job-boards.greenhouse.io/acme/jobs/111")
        self.assertIn("Playwright", j["description"])
        self.assertNotIn("<", j["description"])
        self.assertTrue(j["remote_hint"])

    def test_lever(self):
        jobs = list(sources.parse_lever("beta", fixture("lever.json")))
        self.assertEqual(jobs[0]["apply_url"], "https://jobs.lever.co/beta/abc/apply")
        self.assertIn("Appium", jobs[0]["description"])
        self.assertTrue(jobs[0]["remote_hint"])

    def test_ashby_skips_unlisted(self):
        jobs = list(sources.parse_ashby("gamma", fixture("ashby.json")))
        self.assertEqual([j["title"] for j in jobs], ["Senior SDET"])

    def test_remotive(self):
        jobs = list(sources.parse_remotive(fixture("remotive.json")))
        self.assertEqual(jobs[0]["company"], "Delta Co")
        self.assertTrue(jobs[0]["location"].startswith("Remote"))


class TestFilters(unittest.TestCase):
    def check(self, title, loc, remote=False):
        return filters.passes({"title": title, "location": loc, "remote_hint": remote}, CFG)[0]

    def test_titles(self):
        self.assertTrue(self.check("Senior QA Engineer", "Remote - US"))
        self.assertTrue(self.check("Software Engineer in Test", "Remote"))
        self.assertTrue(self.check("SDET II", "Remote, United States"))
        self.assertTrue(self.check("DevOps Engineer", "Remote (US)"))
        self.assertFalse(self.check("Backend Engineer", "Remote"))
        self.assertFalse(self.check("QA Intern", "Remote"))
        self.assertFalse(self.check("Supplier Quality Engineer", "Remote"))
        self.assertFalse(self.check("Contest Manager", "Remote"))  # 'test' inside a word

    def test_locations(self):
        self.assertFalse(self.check("QA Engineer", "San Francisco, CA"))
        self.assertFalse(self.check("QA Engineer", "Remote - UK"))
        self.assertFalse(self.check("QA Engineer", "Hybrid - Dallas, TX"))
        self.assertFalse(self.check("QA Engineer", "Remote, India"))
        self.assertTrue(self.check("QA Engineer", "Remote - US or Canada"))
        self.assertTrue(self.check("QA Engineer", "Anywhere", remote=True))

    def test_local_areas(self):
        cfg = dict(CFG, local_areas=["austin"])
        ok = lambda loc: filters.passes({"title": "QA Engineer", "location": loc}, cfg)[0]
        self.assertTrue(ok("Austin, TX"))                      # on-site in a local area
        self.assertTrue(ok("Hybrid - Austin, Texas"))
        self.assertTrue(ok("San Francisco, CA; Austin, TX"))
        self.assertFalse(ok("Dallas, TX"))                     # other cities still need remote
        self.assertFalse(ok("Hybrid - Dallas, TX"))


class TestDB(unittest.TestCase):
    def test_dedupe(self):
        con = db.connect(":memory:")
        job = next(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
        self.assertTrue(db.upsert(con, job))
        self.assertFalse(db.upsert(con, job))
        self.assertEqual(db.counts(con), {"new": 1})


class TestGuardrails(unittest.TestCase):
    def packet(self, **over):
        p = {
            "summary": "QA engineer with 9 years of experience.",
            "experience": [{"index": 0, "bullets": ["Maintain Appium suites."]},
                           {"index": 99, "bullets": ["bogus"]}],
            "skills": ["Playwright", "playwright", "Kubernetes", "Appium"],
            "cover_letter": "I improved coverage by 45% using Cypress.",
            "screening_answers": [
                {"question": "Are you authorized to work in the US?", "answer": "Yes"},
                {"question": "Why this role?", "answer": "Fit."}],
        }
        p.update(over)
        return p

    def test_validate(self):
        p, w = tailor.validate(self.packet(), PROFILE)
        self.assertEqual(p["skills"], ["Playwright", "Appium"])        # dedupe + no invention
        self.assertEqual(len(p["experience"]), len(PROFILE["experience"]))
        self.assertEqual(p["experience"][1]["bullets"], PROFILE["experience"][1]["facts"][:3])
        self.assertEqual([q["question"] for q in p["screening_answers"]], ["Why this role?"])
        text = "\n".join(w)
        self.assertIn("Kubernetes", text)
        self.assertIn("45%", text)
        self.assertIn("Cypress", text)
        self.assertIn("bad index 99", text)
        self.assertNotIn("Years-of-experience", text)  # "9 years" IS in the profile

    def test_flags_details_from_the_ai_written_resume(self):
        """Claims that came from the AI-generated resume must be flagged, not trusted."""
        bad = self.packet(
            summary="Senior QA Engineer with 12 years of experience.",
            cover_letter="I used Cypress on Linux, and supported FDA / ISO 13485 audits.",
            skills=["Ruby", "Linux", "Kubernetes", "Playwright"])
        p, w = tailor.validate(bad, PROFILE)
        text = "\n".join(w)
        self.assertEqual(p["skills"], ["Ruby", "Playwright"])
        for claim in ["12 years", "Cypress", "Linux", "FDA", "ISO 13485", "Kubernetes"]:
            self.assertIn(claim, text)

    @unittest.skipUnless((REPO / "profile.yaml").exists(), "no personal profile.yaml")
    def test_personal_profile_has_no_ai_invented_claims(self):
        """Details that came from an AI-written resume must never enter your real profile."""
        blob = (REPO / "profile.yaml").read_text().lower()
        # offline messaging / reliability monitoring were
        # confirmed true by the candidate (2026-09-28); these were not
        for invented in ["linux", "data visualization", "fda", "iso 13485"]:
            self.assertNotIn(invented, blob)

    def test_company_dates_never_from_llm(self):
        from jobbot.render import resume_html
        p, _ = tailor.validate(self.packet(), PROFILE)
        h = resume_html(PROFILE, p)
        for e in PROFILE["experience"]:
            self.assertIn(e["company"], h)
            self.assertIn(e["dates"], h)


class TestApply(unittest.TestCase):
    def test_greenhouse_uses_embed_form(self):
        from jobbot import apply
        job = next(sources.parse_greenhouse("pinterest", fixture("greenhouse.json")))
        self.assertEqual(apply.form_url(job), "https://job-boards.greenhouse.io/embed/job_app"
                         f"?for=pinterest&token={job['ext_id']}")
        lever = next(sources.parse_lever("beta", fixture("lever.json")))
        self.assertEqual(apply.form_url(lever), lever["apply_url"])


class TestClaudeClient(unittest.TestCase):
    """Request shape + response parsing for the Anthropic Messages API (mocked HTTP)."""

    def fake_post(self, reply, status=200):
        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "body": json, "headers": headers})
            r = mock.Mock(status_code=status, text="err")
            r.json.return_value = reply
            return r
        return post, calls

    def test_structured_output(self):
        from jobbot import llm, score
        result = {"score": 77, "reasons": ["r"], "concerns": [], "dealbreakers": [],
                  "keywords": ["Playwright"]}
        reply = {"stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 20},
                 "content": [{"type": "thinking", "thinking": ""},
                             {"type": "text", "text": json.dumps(result)}]}
        post, calls = self.fake_post(reply)
        with mock.patch.object(llm, "PROVIDER", "claude"), \
             mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "JOBBOT_FAKE_LLM": "0"}), \
             mock.patch.object(llm.requests, "post", post):
            job = next(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
            out = score.score_job(job, PROFILE, "claude-haiku-4-5-20251001")
        self.assertEqual(out["score"], 77)
        self.assertEqual(out["_usage"]["total_tokens"], 120)
        c = calls[0]
        self.assertEqual(c["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(c["headers"]["x-api-key"], "k")
        self.assertEqual(c["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("tool_choice", c["body"])
        self.assertEqual(c["body"]["output_config"],
                         {"format": {"type": "json_schema", "schema": score.SCHEMA}})
        self.assertIn("Playwright", c["body"]["messages"][0]["content"])

    def test_missing_key_and_auth_errors_are_fatal(self):
        from jobbot import llm
        env = {"JOBBOT_FAKE_LLM": "0", "ANTHROPIC_API_KEY": ""}
        with mock.patch.object(llm, "PROVIDER", "claude"), mock.patch.dict(os.environ, env):
            with self.assertRaises(llm.FatalLLMError):
                llm.chat_json("m", "s", "u", {}, name="x")
        post, calls = self.fake_post({}, status=401)
        with mock.patch.object(llm, "PROVIDER", "claude"), \
             mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "0", "ANTHROPIC_API_KEY": "bad"}), \
             mock.patch.object(llm.requests, "post", post):
            with self.assertRaises(llm.FatalLLMError):
                llm.chat_json("m", "s", "u", {}, name="x")
        self.assertEqual(len(calls), 1)  # no pointless retries on 401

    def test_overloaded_is_retried(self):
        from jobbot import llm
        ok = {"stop_reason": "end_turn", "usage": {}, "content": [
            {"type": "text", "text": '{"a": 1}'}]}
        seq = iter([(None, 529), (ok, 200)])

        def post(url, json=None, headers=None, timeout=None):
            reply, status = next(seq)
            r = mock.Mock(status_code=status, text="overloaded")
            r.json.return_value = reply
            return r
        with mock.patch.object(llm, "PROVIDER", "claude"), \
             mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "0", "ANTHROPIC_API_KEY": "k"}), \
             mock.patch.object(llm.requests, "post", post), mock.patch.object(llm.time, "sleep"):
            self.assertEqual(llm.chat_json("m", "s", "u", {}, name="x")["a"], 1)

    def test_refusal_is_not_retried(self):
        from jobbot import llm
        post, calls = self.fake_post({"stop_reason": "refusal", "content": [],
                                      "stop_details": {"category": "cyber"}})
        with mock.patch.object(llm, "PROVIDER", "claude"), \
             mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "0", "ANTHROPIC_API_KEY": "k"}), \
             mock.patch.object(llm.requests, "post", post), mock.patch.object(llm.time, "sleep"):
            with self.assertRaises(llm.RefusalError):
                llm.chat_json("m", "s", "u", {}, name="x")
        self.assertEqual(len(calls), 1)


class TestTracking(unittest.TestCase):
    def test_migrates_old_database_and_backfills_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            import sqlite3
            old = sqlite3.connect(path)
            old.executescript(db.SCHEMA)
            old.execute("INSERT INTO jobs (source, ext_id, company, title, status, applied_at) "
                        "VALUES ('greenhouse','1','Acme','QA','applied','2026-09-01T10:00:00')")
            old.commit()
            old.close()
            con = db.connect(path)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
            self.assertTrue({"contact", "salary", "next_step", "follow_up"} <= cols)
            self.assertEqual([tuple(e) for e in db.events(con, 1)], [("2026-09-01T10:00:00", "status", "applied")])
            db.connect(path)  # idempotent: no duplicate backfill
            self.assertEqual(len(db.events(con, 1)), 1)

    def test_manual_application_and_status_log(self):
        con = db.connect(":memory:")
        jid = db.add_manual(con, "Globex", "QA Lead", applied_at="2026-08-15", salary="$130K")
        db.set_status(con, jid, "interview", note="Onsite next week")
        db.set_status(con, jid, "interview")  # unchanged: not logged twice
        row = db.get(con, jid)
        self.assertEqual((row["source"], row["status"], row["applied_at"], row["salary"]),
                         ("manual", "interview", "2026-08-15", "$130K"))
        self.assertEqual([e["text"] for e in db.events(con, jid)], ["applied", "interview", "Onsite next week"])


class TestRender(unittest.TestCase):
    def test_file_names_are_unique_per_application(self):
        from jobbot.render import file_base
        a = file_base(PROFILE, {"company": "Wikimedia Foundation", "title": "Software Quality Manager"})
        b = file_base(PROFILE, {"company": "Pinterest", "title": "SDET II, tvScientific / Web Platform (Remote)"})
        self.assertEqual(a, "Alex_Example_Wikimedia-Foundation_Software-Quality-Manager")
        self.assertTrue(b.startswith("Alex_Example_Pinterest_SDET-II-tvScientific"))
        self.assertLessEqual(len(b), 80)
        self.assertRegex(b, r"^[A-Za-z0-9_-]+$")
        self.assertIn("_Veeva_", file_base(PROFILE, {"company": "veeva", "title": "QA Engineer"}))


class TestWeb(unittest.TestCase):
    def setUp(self):
        from jobbot.web import create_app
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        con = db.connect(str(root / "jobs.db"))
        job = next(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
        db.upsert(con, job)
        pkt = root / "output" / "0001-acme"
        pkt.mkdir(parents=True)
        (pkt / "Alex_Example_Resume.pdf").write_bytes(b"%PDF-1.4 test")
        (pkt / "REVIEW.md").write_text("# t\n\n## Check before submitting\n- [ ] Tool not in profile: 'Go'\n\n## Why it matches\n- x\n")
        (pkt / "answers.md").write_text("# a\n\n**Why this role?**\n\nBecause.\n")
        (root / "secret.txt").write_text("nope")
        db.update(con, 1, status="tailored", score=80, packet_dir=str(pkt),
                  score_json={"reasons": ["r"], "concerns": [], "dealbreakers": [], "keywords": ["k"]})
        con.close()
        self.root = root
        self.c = create_app(root).test_client()
        self.h = {"X-JobBot": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_and_detail(self):
        rows = self.c.get("/api/jobs?view=review").get_json()
        self.assertEqual([r["id"] for r in rows], [1])
        self.assertEqual(rows[0]["warnings"], 1)
        self.assertIn("job-boards.greenhouse.io/embed/job_app", rows[0]["form_url"])
        d = self.c.get("/api/jobs/1").get_json()
        self.assertEqual(d["answers"], [{"q": "Why this role?", "a": "Because."}])
        self.assertEqual(d["files"]["resume"], "Alex_Example_Resume.pdf")
        self.assertEqual(self.c.get("/files/1/Alex_Example_Resume.pdf").status_code, 200)

    def test_mark_requires_header_and_valid_status(self):
        self.assertEqual(self.c.post("/api/jobs/1/mark", json={"status": "applied"}).status_code, 403)
        self.assertEqual(self.c.post("/api/jobs/1/mark", json={"status": "hired!"},
                                     headers=self.h).status_code, 400)
        r = self.c.post("/api/jobs/1/mark", json={"status": "applied", "note": "hi"}, headers=self.h)
        self.assertEqual(r.get_json()["status"], "applied")
        con = db.connect(str(self.root / "jobs.db"))
        self.assertIsNotNone(db.get(con, 1)["applied_at"])

    def test_add_application_details_and_timeline(self):
        r = self.c.post("/api/jobs", json={"company": "Initech", "title": "SDET", "applied_at": "2026-09-01",
                                           "salary": "$120K", "url": "https://x.example/job"}, headers=self.h)
        jid = r.get_json()["id"]
        self.c.post(f"/api/jobs/{jid}/details", json={"follow_up": "2026-09-10", "contact": "Dana"}, headers=self.h)
        self.c.post(f"/api/jobs/{jid}/mark", json={"status": "interview"}, headers=self.h)
        self.c.post(f"/api/jobs/{jid}/events", json={"text": "Phone screen went well"}, headers=self.h)
        d = self.c.get(f"/api/jobs/{jid}").get_json()
        self.assertEqual((d["source"], d["status"], d["salary"], d["contact"], d["follow_up"]),
                         ("manual", "interview", "$120K", "Dana", "2026-09-10"))
        self.assertEqual([e["text"] for e in d["events"]], ["applied", "interview", "Phone screen went well"])
        self.assertIn(jid, [x["id"] for x in self.c.get("/api/jobs?view=pipeline").get_json()])
        self.assertEqual(self.c.get("/api/state").get_json()["follow_ups_due"], 1)  # 2026-09-10 is past

    def test_bad_input_is_rejected(self):
        bad = [("/api/jobs", {"company": "", "title": "x"}),
               ("/api/jobs", {"company": "a", "title": "b", "applied_at": "last week"}),
               ("/api/jobs/1/details", {"follow_up": "soon"}),
               ("/api/jobs/1/events", {"text": "  "})]
        for url, body in bad:
            r = self.c.post(url, json=body, headers=self.h)
            self.assertEqual(r.status_code, 400, (url, body))

    def test_files_stay_inside_packet(self):
        for bad in ("..%2Fsecret.txt", "../secret.txt", "REVIEW.py"):
            self.assertEqual(self.c.get(f"/files/1/{bad}").status_code, 404, bad)

    def test_rejects_foreign_host(self):
        self.assertEqual(self.c.get("/api/jobs", headers={"Host": "evil.example"}).status_code, 403)


class TestEndToEndOffline(unittest.TestCase):
    """fetch -> filter -> score -> tailor -> PDFs, with fixtures and a fake LLM."""

    def test_pipeline(self):
        from jobbot import cli
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "config.yaml").write_text((REPO / "config.yaml").read_text())
            (tmp / "profile.yaml").write_text((REPO / "profile.example.yaml").read_text())
            cfg = yaml.safe_load((tmp / "config.yaml").read_text())
            fake_jobs = (list(sources.parse_greenhouse("acme", fixture("greenhouse.json")))
                         + list(sources.parse_lever("beta", fixture("lever.json"))))
            with mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "1"}), \
                 mock.patch.object(cli, "ROOT", tmp), \
                 mock.patch.object(sources, "iter_all", lambda c, log=print: iter(fake_jobs)):
                con = db.connect(str(tmp / "jobs.db"))
                cli.cmd_run(con, cfg, None)
                cli.cmd_run(con, cfg, None)  # second run: no duplicates, nothing new
                c = db.counts(con)
                self.assertEqual(sum(c.values()), 4)
                self.assertEqual(c.get("tailored"), 2, c)
                self.assertEqual(c.get("filtered_out"), 2, c)
                pdfs = sorted(p.name for p in (tmp / "output").rglob("*.pdf"))
                self.assertEqual(len(pdfs), 4, pdfs)
                review = next((tmp / "output").rglob("REVIEW.md")).read_text()
                self.assertIn("Kubernetes", review)     # fake LLM's invented tool is flagged
                self.assertIn("80%", review)            # and its invented metric
                self.assertEqual(cli.db.export_csv(con, tmp / "t.csv"), 2)


if __name__ == "__main__":
    unittest.main()
