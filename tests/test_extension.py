"""Browser extension: server-side keys + fill.js run against mock application forms (offline)."""
import base64
import json
import unittest
from pathlib import Path

from jobbot.cloud.store import MemoryStore
from jobbot.cloud.webapp import create_app

REPO = Path(__file__).parent.parent
FILL_JS = REPO / "extension" / "fill.js"
PDF = base64.b64encode(b"%PDF-1.4 test").decode()
PAYLOAD = {"contact": {"first_name": "Alex", "last_name": "Example", "email": "alex@example.com",
                       "phone": "(555) 010-0000", "linkedin": "https://linkedin.com/in/x", "github": "https://github.com/x",
                       "current_company": "Northwind"},
           "cover_letter": "Dear Hiring Team, ...",
           "files": {"resume": {"name": "Alex_Example_Acme_Resume.pdf", "b64": PDF},
                     "letter": {"name": "Alex_Example_Acme_Cover_Letter.pdf", "b64": PDF}}}

GREENHOUSE = """<label for=first_name>First Name*</label><input id=first_name>
<label for=last_name>Last Name*</label><input id=last_name><label for=email>Email*</label><input id=email>
<label for=phone>Phone</label><input id=phone type=tel>
<label for=q1>LinkedIn Profile</label><input id=q1>
<div><label for=resume>Resume/CV</label><input type=file id=resume></div>
<div><label for=cover_letter>Cover Letter</label><input type=file id=cover_letter></div>
<label for=q2>Will you now or in the future require sponsorship?</label><input id=q2>
<label for=q3>Desired salary</label><input id=q3>"""
LEVER = """<label>Full name ✱<input name=name></label><label>Email<input name=email type=email></label>
<label>Phone<input name=phone></label><label>Current company<input name=org></label>
<label>LinkedIn URL<input name="urls[LinkedIn]"></label><label>GitHub URL<input name="urls[GitHub]"></label>
<label>Resume/CV<input type=file name=resume></label>
<label>Additional information<textarea name=comments></textarea></label>"""
ASHBY = """<input type=file aria-label="Autofill from resume">
<label for=_systemfield_name>Preferred First &amp; Last Name</label><input id=_systemfield_name>
<label for=a>Legal First Name</label><input id=a><label for=b>Legal Last Name</label><input id=b>
<label for=c>Name Pronunciation</label><input id=c><label for=d>Preferred Pronouns</label><input id=d>
<label for=_systemfield_email>Email Address</label><input id=_systemfield_email type=email>
<label for=e>Phone Number</label><input id=e type=tel>
<label for=_systemfield_resume>Resume</label><input type=file id=_systemfield_resume>
<label for=f>Gender</label><input id=f>"""
CUSTOM = """<form><label>Your name <input id=n></label><label>E-mail address <input id=m value="keep@me.com"></label>
<label>Mobile <input id=t></label><label>Are you legally authorized to work in the US? <input id=w></label>
<label>Upload CV <input type=file id=cv></label><label>Cover letter (optional) <input type=file id=cl></label></form>"""


def run_fill(html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(f"<html><body>{html}</body></html>")
        pg.add_script_tag(path=str(FILL_JS))
        res = pg.evaluate("p => jobbotFill(p)", PAYLOAD)
        values = pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('input,textarea')].map((e, i) =>
            [e.id || e.name || ('#' + i), e.type === 'file' ? (e.files[0] ? e.files[0].name : '') : e.value]))""")
        b.close()
    return res["filled"], values


class TestFillScript(unittest.TestCase):
    def test_greenhouse(self):
        filled, v = run_fill(GREENHOUSE)
        self.assertEqual((v["first_name"], v["last_name"], v["email"], v["phone"], v["q1"]),
                         ("Alex", "Example", "alex@example.com", "(555) 010-0000", "https://linkedin.com/in/x"))
        self.assertTrue(v["resume"].endswith("_Resume.pdf"))
        self.assertTrue(v["cover_letter"].endswith("_Cover_Letter.pdf"))
        self.assertEqual((v["q2"], v["q3"]), ("", ""))          # sponsorship + salary untouched

    def test_lever(self):
        _, v = run_fill(LEVER)
        self.assertEqual((v["name"], v["email"], v["org"], v["urls[GitHub]"]),
                         ("Alex Example", "alex@example.com", "Northwind", "https://github.com/x"))
        self.assertTrue(v["resume"].endswith("_Resume.pdf"))
        self.assertTrue(v["comments"].startswith("Dear Hiring Team"))

    def test_ashby_traps(self):
        _, v = run_fill(ASHBY)
        self.assertEqual(v["_systemfield_name"], "Alex Example")
        self.assertEqual((v["a"], v["b"]), ("Alex", "Example"))
        self.assertEqual((v["c"], v["d"], v["f"]), ("", "", ""))   # pronunciation, pronouns, gender untouched
        self.assertTrue(v["_systemfield_resume"].endswith("_Resume.pdf"))
        self.assertEqual(v["#0"], "")                                # not the "autofill from resume" box

    def test_note_when_cover_letter_upload_is_missing(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page()
            pg.set_content("<label>Resume<input type=file id=r></label><p>Cover Letter</p><button>Attach</button>")
            pg.add_script_tag(path=str(FILL_JS))
            res = pg.evaluate("p => jobbotFill(p)", PAYLOAD)
            b.close()
        self.assertEqual(res["filled"], ["resume"])
        self.assertIn("Attach", res["notes"][0])

    def test_generic_form_respects_existing_answers_and_sensitive_questions(self):
        filled, v = run_fill(CUSTOM)
        self.assertEqual((v["n"], v["m"], v["t"], v["w"]), ("Alex Example", "keep@me.com", "(555) 010-0000", ""))
        self.assertTrue(v["cv"].endswith("_Resume.pdf"))
        self.assertTrue(v["cl"].endswith("_Cover_Letter.pdf"))
        self.assertNotIn("email", filled)


EMPLOYMENT = {"employment": [{"company": "Northwind", "title": "QA Lead", "start_month": "March", "start_year": "2026",
                             "end_month": "", "end_year": "", "current": True}],
              "education": [{"school": "University of Texas at Austin", "degree": "B.S.", "field": "Computer Science",
                             "start_year": "", "end_year": "2016"}]}
GH_EMPLOYMENT = """<label for=company-name-0>Company name</label><input id=company-name-0>
<label for=title-0>Title</label><input id=title-0><label for=start-date-year-0>Start date year</label><input id=start-date-year-0>
<label for=end-date-year-0>End date year</label><input id=end-date-year-0>
<label><input type=checkbox id=current-role-0_1> Current role</label>"""
# a stand-in for react-select: input -> fiber chain -> component with options / loadOptions / selectOption
MOCK_SELECTS = """<input role=combobox id=start-date-month-0><input role=combobox id=end-date-month-0>
<input role=combobox id=school--0><input role=combobox id=degree--0><input role=combobox id=discipline--0>
<script>
  window.picked = {};
  function mock(id, opts, load) {
    const comp = { props: { options: load ? [] : opts.map(l => ({label: l})),
                   loadOptions: load ? (q) => Promise.resolve({options: opts.filter(l => l.toLowerCase().includes(q.toLowerCase())).map(l => ({label: l}))}) : undefined },
                   getValue: () => (picked[id] ? [picked[id]] : []), selectOption: (o) => { picked[id] = o.label; } };
    document.getElementById(id)["__reactFiber$x"] = { stateNode: null, return: { stateNode: comp, return: null } };
  }
  const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  mock("start-date-month-0", months); mock("end-date-month-0", months);
  mock("school--0", ["University of Texas - Arlington", "University of Texas - Austin", "Austin College"], true);
  mock("degree--0", ["Associate's Degree", "Bachelor's Degree", "Master's Degree"], true);
  mock("discipline--0", ["Computer Engineering", "Computer Science"], true);
</script>"""


class TestEmploymentAndEducation(unittest.TestCase):
    def page(self, html, payload, script):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page()
            pg.set_content(f"<html><body>{html}</body></html>")
            pg.add_script_tag(path=str(REPO / "extension" / script))
            fn = "jobbotFill" if script == "fill.js" else "jobbotSelects"
            res = pg.evaluate(f"async p => {fn}(p)", payload)
            extra = pg.evaluate("""() => ({values: Object.fromEntries([...document.querySelectorAll('input')].map(e =>
                [e.id, e.type === 'checkbox' ? e.checked : e.value])), picked: window.picked || {}})""")
            b.close()
        return res, extra

    def test_greenhouse_employment_text_fields_and_current_role(self):
        res, x = self.page(GH_EMPLOYMENT, {**PAYLOAD, **EMPLOYMENT}, "fill.js")
        v = x["values"]
        self.assertEqual((v["company-name-0"], v["title-0"], v["start-date-year-0"], v["current-role-0_1"], v["end-date-year-0"]),
                         ("Northwind", "QA Lead", "2026", True, ""))   # current job: no end date

    def test_dropdowns_months_school_degree_field(self):
        res, x = self.page(MOCK_SELECTS, EMPLOYMENT, "select.js")
        self.assertEqual(x["picked"], {"start-date-month-0": "March", "school--0": "University of Texas - Austin",
                                       "degree--0": "Bachelor's Degree", "discipline--0": "Computer Science"})
        self.assertEqual(res["notes"], [])

    def test_no_education_gives_a_note_not_a_guess(self):
        res, x = self.page(MOCK_SELECTS, {"employment": [], "education": []}, "select.js")
        self.assertNotIn("school--0", x["picked"])
        self.assertIn("Add your education", res["notes"][0])


class TestProfileDates(unittest.TestCase):
    def test_parse_dates_and_education(self):
        from jobbot import profile as P
        self.assertEqual(P.parse_dates("March 2026 - Present"),
                         {"start_month": "March", "start_year": "2026", "end_month": "", "end_year": "", "current": True})
        self.assertEqual(P.parse_dates("Oct 2018 – Aug 2022")["end_month"], "August")
        self.assertEqual(P.education_line({"school": "UT Austin", "degree": "B.S.", "field": "CS", "end_year": "2016"}),
                         "B.S. in CS, UT Austin, 2016")
        self.assertEqual(P.education_line("B.A., Somewhere, 2010"), "B.A., Somewhere, 2010")
        ok = (REPO / "profile.example.yaml").read_text()
        self.assertEqual(P.validate(ok)[1], [])
        self.assertIn("school is required", " ".join(P.validate(ok.replace("school: University of Colorado Boulder", "school: ''"))[1]))


class TestExtensionKeys(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.c = create_app(self.store, lambda t: {"uid": "u", "email": "me@example.com"}, lambda u: None,
                            admin_emails=["me@example.com"]).test_client()
        self.web = {"Authorization": "Bearer firebase"}
        self.c.get("/api/me", headers=self.web)
        self.store.set_profile("u", (REPO / "profile.example.yaml").read_text())
        self.store.put_job("u", "j1", {"status": "tailored", "score": 80, "company": "Acme", "title": "QA",
                                       "source": "greenhouse", "url": "https://x", "apply_url": "https://x",
                                       "has_packet": True, "files": {"resume": "R_Resume.pdf"}})
        self.store.put_file("u", "j1", "R_Resume.pdf", b"%PDF-1.4 x")
        self.token = self.c.post("/api/ext/connect", headers=self.web).get_json()["token"]
        self.ext = {"Authorization": f"Bearer {self.token}"}

    def test_key_is_random_and_only_its_hash_is_stored(self):
        self.assertTrue(self.token.startswith("jbx_") and len(self.token) > 40)
        self.assertNotIn(self.token, json.dumps(self.store.ext))

    def test_extension_can_do_its_four_things(self):
        me = self.c.get("/api/ext/me", headers=self.ext).get_json()
        self.assertEqual((me["contact"]["first_name"], me["contact"]["email"]), ("Alex", "alex.example@example.com"))
        self.assertEqual((me["employment"][0]["company"], me["employment"][0]["current"]), ("Northwind Bank", True))
        self.assertEqual(me["education"][0]["degree"], "B.S.")
        import json as _j
        self.assertEqual(me["extension_version"], _j.loads((REPO / "extension" / "manifest.json").read_text())["version"])
        jobs = self.c.get("/api/ext/jobs", headers=self.ext).get_json()
        self.assertEqual([(j["id"], j["files"]["resume"]) for j in jobs], [("j1", "R_Resume.pdf")])
        self.assertEqual(self.c.get("/files/j1/R_Resume.pdf", headers=self.ext).data, b"%PDF-1.4 x")
        self.assertEqual(self.c.post("/api/jobs/j1/mark", json={"status": "applied"}, headers=self.ext).status_code, 200)
        self.assertEqual(self.store.get_job("u", "j1")["status"], "applied")

    def test_extension_key_cant_do_anything_else(self):
        for method, path in [("get", "/api/profile"), ("post", "/api/settings"), ("post", "/api/run"),
                             ("post", "/api/me/delete"), ("post", "/api/ext/connect"), ("get", "/api/admin/users")]:
            self.assertEqual(getattr(self.c, method)(path, headers=self.ext).status_code, 403, path)

    def test_disconnect_revokes_and_page_endpoints_reject_bad_keys(self):
        self.assertEqual(self.c.get("/api/ext/me", headers={"Authorization": "Bearer jbx_forged"}).status_code, 401)
        self.c.post("/api/ext/disconnect", headers=self.web)
        self.assertEqual(self.c.get("/api/ext/jobs", headers=self.ext).status_code, 401)


if __name__ == "__main__":
    unittest.main()
