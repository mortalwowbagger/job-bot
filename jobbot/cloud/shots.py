"""Screenshots of the real app for the landing page, filled with made-up demo data.

    python -m jobbot.cloud.shots      -> hosting_public/shot-matches.jpg, shot-phone.jpg

Runs the actual dashboard (same HTML/JS as the hosted app) against an in-memory
store, so the images always show the current interface. The candidate, companies
and jobs are invented, matching the worked example on the landing page; the page
labels the images as example data.
"""
from datetime import date, datetime, timedelta
from pathlib import Path

from ..ui import render
from .store import MemoryStore
from .webapp import create_app

OUT = Path(__file__).parents[2] / "hosting_public"


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


JOBS = [
    ("acme", "Acme Payments", "Senior QA Automation Engineer", "Remote (US)", 86, 2, {
        "reasons": ["Asks for Playwright and API testing; the profile has 4 years of both.",
                    "Payments domain matches the candidate's last role.",
                    "Remote, US: matches the location settings."],
        "concerns": ["Wants load-testing experience (k6); the profile doesn't mention it."],
        "keywords": ["Playwright", "API testing", "CI/CD", "payments", "TypeScript"]},
     ["Tool not in profile: 'k6' in: 'Load-tested the refunds API with k6 before each release.'"],
     [{"q": "Why are you interested in Acme Payments?",
       "a": "I've spent the last four years testing payment flows, where a missed edge case costs real money. "
            "Your team's focus on refunds and disputes is the part of payments I like testing most."}]),
    ("lumen", "Lumen Health", "SDET II", "Austin, TX (hybrid)", 81, 1, {}, [], []),
    ("orbit", "Orbit Logistics", "QA Engineer, Mobile", "Remote (US)", 77, 3, {}, [], []),
    ("brightdesk", "Brightdesk", "Test Automation Engineer", "Remote (US)", 74, 4, {}, [], []),
    ("fernway", "Fernway", "Quality Engineer", "Remote (US)", 70, 6, {}, [], []),
    ("tallgrass", "Tallgrass Software", "QA Analyst", "Round Rock, TX", 66, 8, {}, [], []),
]

LETTER = ("Dear Acme Payments hiring team,\n\nI'm applying for the Senior QA Automation Engineer role. For the last "
          "four years I've built and run Playwright and API test suites for checkout and refund flows...")


def demo_store():
    store = MemoryStore()
    store.ensure_user("demo", "demo@example.com", access="approved", settings={"title_keywords": ["qa engineer"]},
                      profile_yaml="contact: {first_name: Jordan}")
    for slug, company, title, loc, score, age, sj, warnings, answers in JOBS:
        jid = f"greenhouse-{slug}"
        store.put_job("demo", jid, {
            "source": "greenhouse", "ext_id": slug, "board": slug, "company": company, "title": title,
            "location": loc, "url": f"https://job-boards.greenhouse.io/{slug}/jobs/1", "posted_at": _days_ago(age),
            "status": "tailored", "score": score, "has_packet": bool(sj),
            "score_json": {"reasons": [], "concerns": [], "dealbreakers": [], "keywords": [], **sj},
            "warnings": warnings, "answers": answers, "cover_letter": LETTER if sj else "",
            "description": "Example posting."})
    return store


def main():
    from playwright.sync_api import sync_playwright
    store = demo_store()
    client = create_app(store, lambda t: {"uid": "demo", "email": "demo@example.com"}, lambda u: None).test_client()
    page_html = render({"hosted": False}).replace(  # the hosted UI, minus Google sign-in
        'if(!CFG.hosted){showApp();return}',
        'CFG.hosted=true;document.body.classList.add("is-hosted");showApp();return')

    def handle(route):
        url = route.request.url.split("demo.local", 1)[1] or "/"
        if url == "/":
            return route.fulfill(body=page_html, content_type="text/html")
        r = client.open(url, method=route.request.method, data=route.request.post_data,
                        headers={"Authorization": "Bearer demo", "Content-Type": "application/json"})
        route.fulfill(status=r.status_code, body=r.data, content_type=r.content_type)

    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, size in (("shot-matches.jpg", (1280, 760)), ("shot-phone.jpg", (390, 844))):
            pg = b.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2,
                            color_scheme="light")
            pg.route("http://demo.local/**", handle)
            pg.goto("http://demo.local/")
            pg.wait_for_selector(".row")
            pg.click('.row[data-id="greenhouse-acme"]')
            pg.wait_for_selector("#detail h2")
            pg.mouse.move(0, size[1] - 1)          # no hover highlight
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(OUT / name), type="jpeg", quality=82)
            print("wrote", OUT / name)
        b.close()


if __name__ == "__main__":
    main()
