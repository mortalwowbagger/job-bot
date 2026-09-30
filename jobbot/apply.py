"""Open an application form, pre-fill the basics, and hand control to you.

The bot NEVER clicks submit. You review everything in the browser, fill in
anything it missed (work authorization, EEO, custom questions), submit
yourself, then confirm in the terminal so the tracker is updated.
"""
import re
from pathlib import Path


def _fill(page, selectors, value):
    if not value:
        return False
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible() and not loc.input_value():
                loc.fill(value)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _fill_label(page, pattern, value):
    if not value:
        return False
    try:
        # first visible, still-empty match (an earlier match may already be filled)
        for loc in page.get_by_label(re.compile(pattern, re.I)).all():
            if loc.is_visible() and loc.is_editable() and not loc.input_value():
                loc.fill(value)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _upload(page, selectors, path):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.set_input_files(str(path))
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _upload_label(page, pattern, path):
    if not path:
        return False
    try:
        loc = page.get_by_label(re.compile(pattern, re.I)).and_(page.locator("input[type=file]")).first
        if loc.count():
            loc.set_input_files(str(path))
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def prefill(page, source, contact, resume_pdf, letter_pdf, letter_text):
    c = contact
    full = f"{c['first_name']} {c['last_name']}"
    done = []

    def mark(ok, what):
        if ok:
            done.append(what)

    if source == "greenhouse":
        # standard hosted form uses fixed ids; custom forms (form_legal_first_name_2_0_0 ...) need labels
        mark(_fill(page, ["#first_name"], c["first_name"]) or
             _fill_label(page, r"first name", c["first_name"]), "first name")
        mark(_fill(page, ["#last_name"], c["last_name"]) or
             _fill_label(page, r"last name", c["last_name"]), "last name")
        mark(_fill(page, ["#email"], c["email"]) or _fill_label(page, r"^\s*e-?mail", c["email"]), "email")
        mark(_fill(page, ["#phone"], c["phone"]) or _fill_label(page, r"^\s*phone", c["phone"]), "phone")
        mark(_upload(page, ["input#resume", "input[type=file][id*=resume]"], resume_pdf) or
             _upload_label(page, r"resume|\bcv\b", resume_pdf) or
             _upload(page, ["input[type=file]"], resume_pdf), "resume")
        mark(_upload(page, ["input#cover_letter", "input[type=file][id*=cover]"], letter_pdf) or
             _upload_label(page, r"cover letter", letter_pdf), "cover letter")
        mark(_fill_label(page, r"linkedin", c.get("linkedin")), "LinkedIn")
        mark(_fill_label(page, r"github", c.get("github")), "GitHub")
    elif source == "lever":
        mark(_fill(page, ["input[name=name]"], full), "name")
        mark(_fill(page, ["input[name=email]"], c["email"]), "email")
        mark(_fill(page, ["input[name=phone]"], c["phone"]), "phone")
        mark(_fill(page, ["input[name=org]"], c.get("current_company")), "current company")
        mark(_fill(page, ["input[name='urls[LinkedIn]']"], c.get("linkedin")), "LinkedIn")
        mark(_fill(page, ["input[name='urls[GitHub]']"], c.get("github")), "GitHub")
        mark(_upload(page, ["input[name=resume]", "input[type=file]"], resume_pdf), "resume")
        mark(_fill(page, ["textarea[name=comments]"], letter_text), "cover letter (comments)")
    else:  # ashby (fixed _systemfield_* ids) + anything else: label heuristics
        # anchored so "Name Pronunciation" / "Preferred Pronouns" never match
        mark(_fill(page, ["#_systemfield_name"], full) or
             _fill_label(page, r"^\s*(full |preferred )?(first (&|and) last )?name\s*\*?\s*$", full), "name")
        mark(_fill_label(page, r"first name", c["first_name"]), "first name")
        mark(_fill_label(page, r"last name", c["last_name"]), "last name")
        mark(_fill(page, ["#_systemfield_email"], c["email"]) or
             _fill_label(page, r"^\s*e-?mail", c["email"]), "email")
        mark(_fill_label(page, r"^\s*phone", c["phone"]), "phone")
        mark(_fill_label(page, r"linkedin", c.get("linkedin")), "LinkedIn")
        mark(_fill_label(page, r"github", c.get("github")), "GitHub")
        mark(_upload(page, ["#_systemfield_resume", "input[type=file][id*=resume]"], resume_pdf) or
             _upload_label(page, r"resume|\bcv\b", resume_pdf), "resume")
    return done


def form_url(job):
    """URL of the application form itself.

    Many companies (Pinterest, Coinbase, ...) redirect Greenhouse job links to their
    own careers site, often behind a Cloudflare check with the form in an iframe.
    Greenhouse's embed URL serves the same official form directly.
    """
    if job["source"] == "greenhouse" and job.get("board") and job.get("ext_id"):
        return f"https://job-boards.greenhouse.io/embed/job_app?for={job['board']}&token={job['ext_id']}"
    return job["apply_url"] or job["url"]


def run(job, profile, packet_dir, user_data_dir=".browser-profile", interactive=True):
    """Pre-fill the form and hand over. Returns the new status, or None when
    interactive=False (waits for the browser window to close instead of asking)."""
    from playwright.sync_api import sync_playwright

    d = Path(packet_dir)
    resume = next(d.glob("*_Resume.pdf"), None)
    letter = next(d.glob("*_Cover_Letter.pdf"), None)
    letter_text = (d / "cover_letter.txt").read_text() if (d / "cover_letter.txt").exists() else ""
    if not resume:
        raise SystemExit(f"No resume PDF in {d}. Re-run `python -m jobbot tailor`.")

    with sync_playwright() as p:
        # persistent profile = logins/cookies survive between runs
        ctx = p.chromium.launch_persistent_context(user_data_dir, headless=False,
                                                   viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(form_url(job), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        print("\n" + "=" * 64)
        print(f" {job['title']} - {job['company']}  (score {job['score']})")
        print(f" Packet:     {d}")
        print(" Answers for custom questions are in answers.md")
        print(" -> Review EVERYTHING in the browser and submit it yourself.")
        print("=" * 64)
        if not interactive:
            done = [] if job["source"] == "remotive" else prefill(
                page, job["source"], profile["contact"], resume, letter, letter_text)
            print(f" Pre-filled: {', '.join(done) or 'nothing'}", flush=True)
            print(" Close the browser window when you're done.", flush=True)
            try:
                while ctx.pages:
                    ctx.pages[0].wait_for_timeout(1000)
            except Exception:  # noqa: BLE001 - window closed mid-wait
                pass
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
            return None
        while True:
            done = [] if job["source"] == "remotive" else prefill(
                page, job["source"], profile["contact"], resume, letter, letter_text)
            print(f" Pre-filled: {', '.join(done) or 'nothing new (fill manually, or pass any check and retry)'}")
            ans = input("Did you submit? [y]es / [n]o, keep for later / [s]kip this job / "
                        "[r]etry pre-fill: ").strip().lower()
            if not ans.startswith("r"):
                break
        ctx.close()
    return {"y": "applied", "s": "skipped"}.get(ans[:1], "tailored")
