"""Public landing page for the hosted app (what signed-out visitors and link previews see).

Server-rendered HTML (not built by JavaScript) so search engines and LinkedIn/Slack
link previews can read it. It leads with what job-bot does differently: drafts that
only use the user's own facts, a human who reviews and submits, a daily search
across named sources, and plain-spoken data handling. No invented user counts,
testimonials or outcome statistics.
"""
import html
import json

SOURCES = ["Greenhouse", "Lever", "Ashby", "SmartRecruiters", "Workable", "Recruitee", "Himalayas", "Jobicy",
           "The Muse", "Adzuna"]
REPO = "https://github.com/mortalwowbagger/job-bot"

TITLE = "job-bot: a daily job search that never invents your experience"
DESCRIPTION = ("job-bot searches 10 job sources every morning, scores each role against your real background, "
               "and drafts tailored resumes and cover letters using only facts from your profile. "
               "You review everything and submit it yourself.")


def head(base_url):
    e = html.escape
    return f"""<meta name="description" content="{e(DESCRIPTION)}">
<link rel="canonical" href="{e(base_url)}/">
<meta property="og:type" content="website"><meta property="og:url" content="{e(base_url)}/">
<meta property="og:title" content="{e(TITLE)}"><meta property="og:description" content="{e(DESCRIPTION)}">
<meta property="og:image" content="{e(base_url)}/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(TITLE)}">
<meta name="twitter:description" content="{e(DESCRIPTION)}"><meta name="twitter:image" content="{e(base_url)}/og.png">
<script type="application/ld+json">{_schema(base_url)}</script>"""


def _schema(base_url):
    """schema.org description for search engines and AI assistants (facts only: no ratings or review counts)."""
    data = {"@context": "https://schema.org", "@type": "WebApplication", "name": "job-bot", "url": f"{base_url}/",
            "description": DESCRIPTION, "applicationCategory": "BusinessApplication", "operatingSystem": "Web",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}, "isAccessibleForFree": True,
            "codeRepository": REPO}
    return json.dumps(data).replace("</", "<\\/")


def _plan_list(p):
    rows = [f"{'Daily' if p.get('scheduled') == 'daily' else 'Weekly'} automatic search",
            f"{p.get('runs_per_day')} manual search{'es' if (p.get('runs_per_day') or 0) > 1 else ''} a day",
            f"Up to {p.get('max_score_per_run')} jobs scored per search",
            f"{p.get('max_tailor_per_run')} tailored resume + cover letter packets per search",
            "Browser extension that fills applications" if p.get("extension") else "Application tracker and timeline"]
    return "".join(f"<li>{html.escape(r)}</li>" for r in rows)


def body(plans=None, payments_enabled=False, operator=None):
    e = html.escape
    plans = plans or {}
    free, pro = plans.get("free") or {}, plans.get("pro") or {}
    pricing = ""
    if free and pro:
        pro_price = f"${pro.get('price_monthly_usd')}/month" + (f" or ${pro.get('price_yearly_usd')}/year" if pro.get("price_yearly_usd") else "")
        pricing = f"""
  <section id="pricing" class="lp-sec"><h2>Pricing</h2>
    <div class="lp-plans">
      <div class="lp-plan"><h3>Free</h3><p class="lp-price">$0</p><ul>{_plan_list(free)}</ul></div>
      <div class="lp-plan lp-pro"><h3>Pro</h3><p class="lp-price">{e(pro_price)}</p><ul>{_plan_list(pro)}</ul>
        <p class="meta">{"Upgrade anytime from Settings. Cancel anytime." if payments_enabled else "Coming soon. Start free today."}</p></div>
    </div></section>"""
    op = ""
    if operator and operator.get("name"):
        link = f' (<a href="{e(operator["url"])}" rel="noopener" target="_blank">LinkedIn</a>)' if operator.get("url") else ""
        op = f"<p><b>Who runs this:</b> built and run by {e(operator['name'])}{link}" + \
             (f", {e(operator['role'])}" if operator.get("role") else "") + ". Questions or problems: reach out directly.</p>"
    chips = "".join(f"<span>{e(s)}</span>" for s in SOURCES)
    return f"""<div id="login" class="landing">
  <header class="lp-top"><b>job-bot</b><span class="spacer"></span>
    <a href="#how">How it works</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a>
    <button class="primary" onclick="signIn()">Sign in</button></header>

  <section class="lp-hero">
    <h1>A daily job search that never invents your experience.</h1>
    <p class="lp-sub">job-bot scans 10 job sources every morning, scores each role against your real background,
      and drafts a tailored resume and cover letter using <b>only facts from your profile</b>.
      You review everything and <b>click submit yourself</b>.</p>
    <p><button class="primary lp-cta" onclick="signIn()">Start free with Google</button>
       <a class="btn" href="#how">See how it works</a></p>
    <p class="meta" id="loginerr"></p>
  </section>

  <section class="lp-sec lp-pillars">
    <div><h3>Truthful by construction</h3>
      <p>Your profile is the only source of facts. Company names, titles and dates are copied, never rewritten;
        skills are limited to the ones you list; and anything the AI adds that isn't in your profile is flagged
        for you before you send it.</p>
      <div class="lp-demo"><div class="meta">AI draft</div>"Led the migration of our test suite to <u>Kubernetes</u>, cutting runtime <u>80%</u>."
        <div class="lp-flag">⚠ Not in your profile: "Kubernetes", "80%". Check before submitting.</div></div></div>
    <div><h3>You review and submit</h3>
      <p>job-bot never applies for you and never clicks submit. No mass applications, no spammy footprint with
        recruiters, no surprises. It fills the form; you read it and decide.</p></div>
    <div><h3>A fresh search every morning</h3>
      <p>Every day at 7am Central it checks job boards and company career pages for the titles and places you
        choose, removes postings that have closed, and puts the best matches at the top.</p></div>
  </section>

  <section id="how" class="lp-sec"><h2>How it works</h2>
    <ol class="lp-steps">
      <li><b>Upload your resume.</b> job-bot turns it into your profile, and you check every line. That profile is all the AI is allowed to use.</li>
      <li><b>Pick job titles and places.</b> Remote, your city, or both. Add companies you want to watch.</li>
      <li><b>Wake up to matches.</b> Each job gets a score with reasons and concerns, plus a tailored resume, cover letter and draft answers.</li>
      <li><b>Apply on your terms.</b> Open the application, let the browser extension fill your details and attach the PDFs, review, and submit.</li>
      <li><b>Track it.</b> Applied, interviewing, offers, follow-ups and notes, in one place on your phone or laptop.</li>
    </ol>
    <p class="meta">Searches: <span class="lp-chips">{chips}</span></p>
  </section>
{pricing}
  <section class="lp-sec"><h2>Plain talk about your data</h2>
    <p>Your profile, resumes and applications are stored in this job-bot's private Google Cloud project. The person who
      runs it can technically access that data. Job descriptions and your profile are sent to Anthropic's API to score
      and tailor. That's it: no selling, no sharing with employers, no applying on your behalf.</p>
    <p><b>Delete everything, yourself, anytime:</b> one button in Settings removes your profile, settings, jobs,
      applications and PDFs. job-bot is also <a href="{REPO}" rel="noopener" target="_blank">open source</a>,
      so you can read exactly what it does.</p>
    {op}
  </section>

  <section id="faq" class="lp-sec"><h2>Questions</h2>
    <details><summary>Does job-bot apply to jobs for me?</summary><p>No. It finds jobs, prepares your documents and can
      fill an application form in your browser, but you review it and click submit. That's deliberate.</p></details>
    <details><summary>Will the AI make things up on my resume?</summary><p>It's only allowed to use what's in your
      profile, and job-bot checks its drafts in code: skills you don't list are removed, and numbers or tools that
      aren't in your profile are flagged for you to verify.</p></details>
    <details><summary>Which job boards does it search?</summary><p>{e(", ".join(SOURCES))}, plus any company careers
      pages you add. No LinkedIn or Indeed scraping (it breaks their terms and gets accounts banned).</p></details>
    <details><summary>Is it only for tech jobs?</summary><p>No. You choose the job titles, so it works for marketing,
      data, HR, healthcare and more. It started with QA and engineering roles, where coverage is deepest.</p></details>
    <details><summary>Does it answer work-authorization, salary or demographic questions?</summary><p>Never. Those are
      always left for you.</p></details>
    <details><summary>Is it free?</summary><p>Yes, there's a free plan with a weekly search. Pro adds a daily search,
      more tailored packets and the browser extension.</p></details>
  </section>

  <section class="lp-sec lp-end"><h2>Spend your time on the applications worth sending.</h2>
    <p><button class="primary lp-cta" onclick="signIn()">Start free with Google</button></p></section>
  <footer class="lp-foot meta"><a href="{REPO}" rel="noopener" target="_blank">Open source on GitHub</a></footer>
</div>"""


CSS = """
#login.landing{display:block;max-width:980px;margin:0 auto;padding:0 18px 40px;border:none;border-radius:0;
  background:none;text-align:left}
.lp-top{display:flex;gap:14px;align-items:center;padding:14px 0;position:static;background:none;border:none}
.lp-top a{color:var(--muted);text-decoration:none;font-size:14px}.lp-top b{font-size:17px}
.lp-hero{padding:48px 0 28px;max-width:760px}
#login.landing .lp-hero h1{font-size:clamp(28px,5vw,46px);line-height:1.1;margin:0 0 16px;letter-spacing:-.5px}
.lp-sub{font-size:18px;color:var(--muted);margin:0 0 20px}.lp-sub b{color:var(--ink)}
.lp-cta{font-size:16px;padding:10px 18px}
.lp-sec{padding:26px 0;border-top:1px solid var(--line)}.lp-sec h2{font-size:24px;margin:0 0 12px}
.lp-pillars{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}.lp-pillars h3{font-size:17px;margin:0 0 6px;text-transform:none;letter-spacing:0;color:var(--ink)}
.lp-pillars p{margin:0;color:var(--muted)}
.lp-demo{margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--panel);font-size:13px}
.lp-demo u{text-decoration-color:var(--warn);text-decoration-thickness:2px}
.lp-flag{margin-top:8px;color:var(--warn);font-weight:600;font-size:12px}
.lp-steps{padding-left:20px}.lp-steps li{margin:8px 0}
.lp-chips span{display:inline-block;background:var(--chip);border-radius:6px;padding:1px 8px;margin:2px;font-size:12px}
.lp-plans{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.lp-plan{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--panel)}
.lp-plan h3{margin:0;font-size:18px;text-transform:none;letter-spacing:0;color:var(--ink)}
.lp-pro{border-color:var(--accent)}.lp-price{font-size:22px;font-weight:700;margin:6px 0}
.lp-plan ul{padding-left:18px;margin:8px 0}
#faq details{border-bottom:1px solid var(--line);padding:10px 0}#faq summary{cursor:pointer;font-weight:600}
.lp-end{text-align:center}.lp-foot{padding-top:18px;border-top:1px solid var(--line)}
html.signed-in #login.landing{display:none}
@media (max-width:800px){.lp-pillars,.lp-plans{grid-template-columns:1fr}.lp-top a{display:none}.lp-hero{padding-top:24px}}
"""
