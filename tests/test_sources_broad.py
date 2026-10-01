"""Offline tests for the broader search: new sources, company links, ranking, queue rules."""
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import yaml

from jobbot import rank, settings, sources
from jobbot.cloud import pipeline
from jobbot.cloud.store import MemoryStore

REPO = Path(__file__).parent.parent
CFG = yaml.safe_load((REPO / "config.yaml").read_text())
PROFILE_YAML = (REPO / "profile.example.yaml").read_text()
PROFILE = yaml.safe_load(PROFILE_YAML)

HIMALAYAS = {"jobs": [{"title": "Marketing Manager", "companyName": "Acme", "locationRestrictions": ["United States"],
                       "guid": "https://himalayas.app/companies/acme/jobs/marketing-manager",
                       "applicationLink": "https://himalayas.app/companies/acme/jobs/marketing-manager",
                       "description": "<p>Own <b>campaigns</b></p>"}]}
JOBICY = {"jobs": [{"id": 7, "url": "https://jobicy.com/jobs/7-x", "jobTitle": "Data Analyst &amp; Reporting",
                    "companyName": "Beta", "jobGeo": "USA", "jobDescription": "<p>SQL</p>"}]}
SMARTREC = {"totalFound": 1, "content": [{"id": "99", "name": "Store Manager", "company": {"name": "Gamma Co"},
            "location": {"city": "Austin", "region": "TX", "country": "us", "remote": False},
            "ref": "https://api.smartrecruiters.com/v1/companies/Gamma/postings/99"}]}
WORKABLE = {"name": "Delta", "jobs": [{"title": "Nurse Recruiter", "shortcode": "AB1", "url": "https://apply.workable.com/j/AB1",
            "application_url": "https://apply.workable.com/j/AB1/apply", "city": "Denver", "state": "CO",
            "country": "United States", "telecommuting": True, "description": "<p>Hire nurses</p>"}]}
RECRUITEE = {"offers": [{"id": 5, "title": "Accountant", "company_name": "Epsilon", "location": "Chicago, IL",
             "remote": False, "careers_url": "https://e.recruitee.com/o/accountant",
             "careers_apply_url": "https://e.recruitee.com/o/accountant/c/new", "description": "<p>Books</p>",
             "requirements": "<p>CPA</p>"}]}


class TestNewSources(unittest.TestCase):
    def test_parsers_produce_standard_jobs(self):
        cases = [(sources.parse_himalayas(HIMALAYAS), "himalayas", "Remote (United States)", True),
                 (sources.parse_jobicy(JOBICY), "jobicy", "Remote (USA)", True),
                 (sources.parse_smartrecruiters("Gamma", SMARTREC), "smartrecruiters", "Austin, TX, US", False),
                 (sources.parse_workable("delta", WORKABLE), "workable", "Remote - Denver, CO, United States", True),
                 (sources.parse_recruitee("e", RECRUITEE), "recruitee", "Chicago, IL", False)]
        for jobs, src, loc, remote in cases:
            j = list(jobs)[0]
            self.assertEqual((j["source"], j["location"], j["remote_hint"]), (src, loc, remote), src)
            for k in ("ext_id", "company", "title", "url", "apply_url"):
                self.assertTrue(j[k], (src, k))
            self.assertNotIn("<", j["description"])
        self.assertEqual(list(sources.parse_jobicy(JOBICY))[0]["title"], "Data Analyst & Reporting")

    def test_smartrecruiters_description_is_fetched_only_when_missing(self):
        j = list(sources.parse_smartrecruiters("Gamma", SMARTREC))[0]
        detail = {"applyUrl": "https://jobs.smartrecruiters.com/Gamma/99/apply",
                  "jobAd": {"sections": {"jobDescription": {"text": "<p>Run the store</p>"}}}}
        with mock.patch.object(sources, "_get", return_value=detail) as g:
            sources.fill_description(j)
            sources.fill_description(j)
        self.assertEqual(g.call_count, 1)
        self.assertEqual(j["description"], "Run the store")
        self.assertTrue(j["apply_url"].endswith("/apply"))

    def test_plan_dedupes_and_adds_extras(self):
        cfg = {"sources": {"greenhouse": ["acme"]}, "search": {"jobicy": True, "himalayas": True, "keywords": ["qa"]}}
        plan = sources.plan_for(cfg, extra=[("greenhouse", "ACME"), ("lever", "beta"), ("bogus", "x")])
        self.assertEqual(plan, [("greenhouse", "acme"), ("jobicy", "usa"), ("himalayas", "qa"), ("lever", "beta")])

    def test_one_failing_source_does_not_stop_the_rest(self):
        cfg = {"sources": {"greenhouse": ["ok", "bad"]}}
        def fake(slug):
            if slug == "bad":
                raise RuntimeError("404")
            return [{"title": "t"}]
        logs = []
        with mock.patch.dict(sources.FETCHERS, {"greenhouse": fake}):
            jobs = list(sources.iter_all(cfg, log=logs.append))
        self.assertEqual(len(jobs), 1)
        self.assertTrue(any("FAILED" in l for l in logs))


MUSE = {"page_count": 1, "results": [{"id": 11, "name": "HR Generalist", "company": {"name": "Zeta"},
        "locations": [{"name": "Flexible / Remote"}], "refs": {"landing_page": "https://www.themuse.com/jobs/zeta/hr"},
        "contents": "<p>People ops</p>"}]}
ADZUNA = {"results": [{"id": "5", "title": "<strong>Marketing</strong> Manager", "company": {"display_name": "Eta"},
          "location": {"display_name": "Austin, Travis County"}, "redirect_url": "https://www.adzuna.com/land/ad/5",
          "description": "Lead campaigns..."}]}


class TestKeyedSources(unittest.TestCase):
    def test_muse_and_adzuna_parsers(self):
        m = list(sources.parse_muse(MUSE))[0]
        self.assertEqual((m["source"], m["location"], m["remote_hint"], m["url"]),
                         ("muse", "Flexible / Remote", True, "https://www.themuse.com/jobs/zeta/hr"))
        a = list(sources.parse_adzuna(ADZUNA, remote_query=True))[0]
        self.assertEqual(a["title"], "Marketing Manager")
        self.assertIn("listing mentions remote", a["location"])   # honest: not assumed fully remote
        self.assertIn("Short description", a["description"])
        self.assertEqual(list(sources.parse_adzuna(ADZUNA))[0]["location"], "Austin, Travis County")

    def test_keyed_sources_are_skipped_without_keys(self):
        cfg = {"search": {"muse": True, "adzuna": True, "keywords": ["qa"]}}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sources.plan_for(cfg), [])
            with self.assertRaises(RuntimeError):
                sources.fetch_muse()
        keys = {"MUSE_API_KEY": "m", "ADZUNA_APP_ID": "i", "ADZUNA_APP_KEY": "k"}
        with mock.patch.dict(os.environ, keys, clear=True):
            self.assertEqual(sources.plan_for(cfg), [("muse", "Flexible / Remote"), ("adzuna", "qa|")])


class TestCompaniesAndSearches(unittest.TestCase):
    def test_careers_links_are_recognized(self):
        cases = {"https://job-boards.greenhouse.io/acme/jobs/123": ("greenhouse", "acme"),
                 "https://boards.greenhouse.io/acme": ("greenhouse", "acme"),
                 "https://jobs.lever.co/beta/uuid/apply": ("lever", "beta"),
                 "jobs.ashbyhq.com/gamma": ("ashby", "gamma"),
                 "https://jobs.smartrecruiters.com/BoschGroup/7440": ("smartrecruiters", "BoschGroup"),
                 "https://apply.workable.com/huggingface/": ("workable", "huggingface"),
                 "https://bunq.recruitee.com/o/ios": ("recruitee", "bunq"),
                 "lever: acme": ("lever", "acme")}
        for text, want in cases.items():
            self.assertEqual(settings.parse_company(text), want, text)
        self.assertIsNone(settings.parse_company("https://www.linkedin.com/jobs/view/123"))

    def test_settings_keep_companies_and_explain_bad_links(self):
        ok, errs = settings.clean({"title_keywords": "analyst", "companies": "https://jobs.lever.co/acme\njobs.lever.co/ACME\n"})
        self.assertEqual((ok["companies"], errs), (["lever:acme"], []))
        _, errs = settings.clean({"title_keywords": "analyst", "companies": "https://indeed.com/acme"})
        self.assertIn("couldn't recognize", errs[0])

    def test_job_titles_become_searches(self):
        self.assertEqual(settings.search_queries({"title_keywords": ["qa", "Marketing Manager", "engineer*", "marketing manager"]}),
                         ["Marketing Manager", "engineer"])
        users = [("a", {"settings": {"title_keywords": ["data analyst"], "companies": ["lever:acme"]}}),
                 ("b", {"settings": {"title_keywords": ["Data Analyst", "accountant"]}})]
        self.assertEqual(pipeline.extra_fetches(users, {**CFG, "search": {"himalayas": True}}),
                         [("lever", "acme"), ("himalayas", "data analyst"), ("himalayas", "accountant")])

    def test_muse_and_adzuna_queries_follow_titles_and_cities(self):
        users = [("a", {"settings": {"title_keywords": ["nurse recruiter"], "remote_only": False,
                                     "local_areas": ["denver, co", "Boulder"]}})]
        got = pipeline.extra_fetches(users, {**CFG, "search": {"adzuna": True, "muse": True}})
        self.assertEqual(got, [("himalayas", "nurse recruiter"), ("adzuna", "nurse recruiter|denver, co"),
                               ("adzuna", "nurse recruiter|Boulder"), ("muse", "Denver, CO")])

    def test_city_with_state_still_matches_spelled_out_states(self):
        from jobbot import filters
        cfg = settings.to_cfg(CFG, {"title_keywords": ["analyst"], "local_areas": ["Austin, TX"]})
        self.assertTrue(filters.passes({"title": "Data Analyst", "location": "Austin, Texas"}, cfg)[0])


class TestRanking(unittest.TestCase):
    def test_relevant_jobs_are_scored_first(self):
        jobs = [{"title": "Line Cook", "description": "Prepare food in a busy kitchen."},
                {"title": "Senior QA Automation Engineer", "description": "Appium and Playwright tests in CI/CD, Java, Python."},
                {"title": "Account Executive", "description": "Close enterprise deals."}]
        self.assertEqual(rank.order(jobs, PROFILE)[0]["title"], "Senior QA Automation Engineer")


class TestQueueRules(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.store.ensure_user("u", "u@example.com", access="approved", is_admin=True)
        self.store.set_profile("u", PROFILE_YAML)
        self.prog = pipeline.Progress(self.store, "u", every=999)

    def job(self, i, company="Acme", title=None):
        return {"source": "greenhouse", "ext_id": str(i), "board": "acme", "company": company,
                "title": title or f"QA Automation Engineer {i}", "location": "Remote", "remote_hint": True,
                "url": "u", "apply_url": "u", "description": "Appium Playwright"}

    def run_user(self, passing, cfg):
        with mock.patch.dict(os.environ, {"JOBBOT_FAKE_LLM": "1"}):
            pipeline.run_user(self.store, cfg, "u", PROFILE, passing, None, self.prog)

    def test_duplicates_across_sources_are_stored_once(self):
        dup = dict(self.job(2, title="QA Automation Engineer 1"), source="himalayas", ext_id="h1")
        cfg = {**CFG, "max_tailor_per_run": 0}
        self.run_user([self.job(1), dup], cfg)
        self.assertEqual(len(self.store.jobsd), 1)

    def test_first_run_gets_bigger_caps_and_the_rest_wait(self):
        cfg = {**CFG, "max_score_per_run": 2, "max_tailor_per_run": 0}
        self.run_user([self.job(i) for i in range(10)], cfg)          # first run: 2 x 2 scored
        self.assertEqual(len(self.store.jobs("u", ["new"])), 6)
        self.run_user([], cfg)                                         # later runs: 2
        self.assertEqual(len(self.store.jobs("u", ["new"])), 4)

    def test_stale_queue_expires(self):
        self.store.put_job("u", "old", {**self.job(1), "status": "new"})
        self.store.jobsd[("u", "old")]["created_at"] = (datetime.now() - timedelta(days=30)).isoformat()
        self.run_user([], {**CFG, "max_tailor_per_run": 0})
        self.assertEqual(self.store.get_job("u", "old")["status"], "expired")


if __name__ == "__main__":
    unittest.main()
