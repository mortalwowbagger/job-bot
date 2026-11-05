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
DESCRIPTION = ("A daily job search that scores roles against your real background and drafts resumes "
               "using only facts from your profile. You review and submit.")  # < 155 chars: Google shows it whole

# One list feeds both the visible FAQ and its FAQPage schema.
FAQ = [
    ("Does job-bot apply to jobs for me?", "No. It finds jobs, prepares your documents and can fill an application "
     "form in your browser, but you review it and click submit. That's deliberate."),
    ("Will the AI make things up on my resume?", "It's only allowed to use what's in your profile, and job-bot checks "
     "its drafts in code: skills you don't list are removed, and numbers or tools that aren't in your profile are "
     "flagged for you to verify."),
    ("Which job boards does it search?", ", ".join(SOURCES) + ", plus any company careers pages you add. No LinkedIn "
     "or Indeed scraping (it breaks their terms and gets accounts banned)."),
    ("Is it only for tech jobs?", "No. You choose the job titles. The job sources have the most openings in sales, "
     "marketing, design, HR and recruiting, accounting, customer support, nursing and engineering. They have fewer "
     "for teaching, and very few for logistics, warehouse and trades jobs, so job-bot isn't a good fit there yet."),
    ("Who isn't job-bot for?", "If you want a bot that sends hundreds of applications for you without you reading "
     "them, job-bot isn't it. It's for people who want fewer, better applications and to check each one."),
    ("Does it answer work-authorization, salary or demographic questions?", "Never. Those are always left for you."),
    ("Is it free?", "Yes, there's a free plan with a weekly search. Pro adds a daily search, more tailored packets "
     "and the browser extension."),
]


def head(base_url, launched=True, plans=None, payments_enabled=False):
    e = html.escape
    hidden = "" if launched else '<meta name="robots" content="noindex, nofollow">\n'
    return hidden + f"""<meta name="description" content="{e(DESCRIPTION)}">
<link rel="canonical" href="{e(base_url)}/">
<meta property="og:type" content="website"><meta property="og:url" content="{e(base_url)}/">
<meta property="og:title" content="{e(TITLE)}"><meta property="og:description" content="{e(DESCRIPTION)}">
<meta property="og:image" content="{e(base_url)}/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(TITLE)}">
<meta name="twitter:description" content="{e(DESCRIPTION)}"><meta name="twitter:image" content="{e(base_url)}/og.png">
<script type="application/ld+json">{_schema(base_url, plans, payments_enabled)}</script>"""


def _schema(base_url, plans=None, payments_enabled=False):
    """schema.org description for search engines and AI assistants (facts only: no ratings or review counts).
    Offers match the visible pricing; Pro is a pre-order until payments are switched on."""
    offers = [{"@type": "Offer", "name": "Free", "price": "0", "priceCurrency": "USD"}]
    pro = (plans or {}).get("pro") or {}
    if pro.get("price_monthly_usd"):
        offers.append({"@type": "Offer", "name": "Pro", "price": str(pro["price_monthly_usd"]), "priceCurrency": "USD",
                       "availability": "https://schema.org/" + ("InStock" if payments_enabled else "PreOrder")})
    data = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebApplication", "name": "job-bot", "url": f"{base_url}/", "description": DESCRIPTION,
         "applicationCategory": "BusinessApplication", "operatingSystem": "Web", "offers": offers,
         "isAccessibleForFree": True, "publisher": {"@id": f"{base_url}/#org"}},
        {"@type": "Organization", "@id": f"{base_url}/#org", "name": "job-bot", "url": f"{base_url}/", "sameAs": [REPO]},
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer":
                                              {"@type": "Answer", "text": a}} for q, a in FAQ]}]}
    return json.dumps(data).replace("</", "<\\/")


LIVE_MARK = "<!--live-stats-->"
WAIT_MARK = "<!--waitlist-->"


def waitlist_line(waiting, minimum=10):
    """Real count of people waiting for access (pre-launch), shown once it's big enough to mean something."""
    return f'<p class="lp-wait"><b>{waiting:,}</b> people in line for access.</p>' if waiting >= minimum else ""


def quotes_section(quotes):
    """Real users' quotes from config (cloud.testimonials). Hidden while there are none; never filled in for you."""
    rows = [q for q in (quotes or []) if q.get("quote") and q.get("name")]
    if not rows:
        return ""
    e = html.escape
    cards = "".join(f'<figure class="lp-q"><blockquote>"{e(q["quote"])}"</blockquote><figcaption>{e(q["name"])}'
                    + (f", {e(q['role'])}" if q.get("role") else "") + "</figcaption></figure>" for q in rows[:6])
    return f'\n  <section id="quotes" class="lp-sec"><h2>From people using it</h2><div class="lp-quotes">{cards}</div></section>'


def live_line(stats, today=None):
    """One factual line from the last daily search, or "" when there's nothing recent worth showing."""
    from datetime import date, datetime
    try:
        at = datetime.fromisoformat(stats["at"]).date()
        listings, nsrc = int(stats["listings"]), int(stats.get("sources") or 0)
    except (KeyError, TypeError, ValueError):
        return ""
    if listings < 100 or ((today or date.today()) - at).days > 8:
        return ""
    when = f"{at:%b} {at.day}"
    scored = int(stats.get("scored") or 0)
    tail = f", then scored {scored:,} new ones against people's profiles" if scored else ""
    return (f'<p class="lp-live"><span class="lp-dot"></span><span>Daily search on {when}: checked <b>{listings:,}</b> '
            f"open postings from <b>{nsrc}</b> sources{tail}.</span></p>")


# Worked example (made-up candidate and company) in the same shape as a real result.
EXAMPLE = """
  <section id="example" class="lp-sec"><h2>What you get for each job</h2>
    <p class="meta">An example with a made-up candidate and company. Your results use your own profile.</p>
    <div class="lp-ex">
      <div class="lp-ex-head"><div><b>Senior QA Automation Engineer</b><div class="meta">Acme Payments · Remote (US) · posted 2 days ago</div></div>
        <span class="lp-score">86</span></div>
      <div class="lp-ex-grid">
        <div><h4>Why it fits</h4><ul>
          <li>Asks for Playwright and API testing; the profile has 4 years of both.</li>
          <li>Payments domain matches the candidate's last role.</li>
          <li>Remote, US: matches the location settings.</li></ul>
          <h4>Worth knowing</h4><ul><li>Wants load-testing experience (k6); the profile doesn't mention it.</li></ul></div>
        <div><h4>Tailored resume (excerpt)</h4>
          <p class="lp-quote">Built a Playwright suite of 600 end-to-end tests for checkout and refunds, run on every pull request.</p>
          <p class="lp-quote">Load-tested the refunds API with <u>k6</u> before each release.</p>
          <p class="meta">Reordered and reworded from the profile. Employer, title and dates are copied exactly.</p>
          <h4>Checks before you send</h4>
          <div class="lp-flag">⚠ "k6" isn't in your profile. Remove it or add it to your profile if it's true.</div></div>
      </div>
      <div class="lp-ex-foot"><h4>Draft answer: "Why are you interested in Acme Payments?"</h4>
        <p class="lp-quote">I've spent the last four years testing payment flows, where a missed edge case costs real
          money. Your team's focus on refunds and disputes is the part of payments I like testing most.</p>
        <p class="meta">Plus a cover letter and PDFs ready to attach. Edit anything; nothing is sent until you submit.</p></div>
    </div>
    <figure class="lp-shots">
      <img class="lp-shot-wide" src="/shot-matches.jpg" width="2560" height="1520" loading="lazy"
        alt="job-bot's review screen: a list of matched jobs with scores, and the selected job showing a check-before-submitting warning, why it matches, concerns and a drafted answer">
      <img class="lp-shot-phone" src="/shot-phone.jpg" width="780" height="1688" loading="lazy"
        alt="The same job on a phone: score 86, Open application button, the k6 warning to check, and reasons it matches">
      <figcaption class="meta">The real app, filled with the example above (made-up data).</figcaption>
    </figure>
  </section>"""

CONTACT = """
  <section id="contact" class="lp-sec"><h2>Questions or feedback</h2>
    <p class="meta">Goes straight to the person who runs job-bot. Add an email if you'd like a reply.</p>
    <form class="lp-form" onsubmit="lpSend(event)">
      <textarea name="message" rows="4" maxlength="3000" required placeholder="Your question or idea"></textarea>
      <input name="reply_to" type="email" maxlength="200" placeholder="Email for a reply (optional)">
      <input name="website" class="lp-hp" tabindex="-1" autocomplete="off" aria-hidden="true">
      <div><button class="primary" type="submit">Send</button> <span class="meta" id="lpsent"></span></div>
    </form>
  </section>
<script>
async function lpSend(ev){ev.preventDefault();const f=ev.target,out=document.getElementById("lpsent");
  const h={"Content-Type":"application/json"};try{const t=await getToken();if(t)h.Authorization="Bearer "+t}catch(e){}
  try{const r=await fetch("/api/feedback",{method:"POST",headers:h,body:JSON.stringify(
    {message:f.message.value,reply_to:f.reply_to.value,website:f.website.value})});const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||"Couldn't send. Try again.");f.reset();out.textContent="Sent. Thank you!"}
  catch(e){out.textContent=e.message}}
</script>"""


def _plan_list(p):
    rows = [f"{'Daily' if p.get('scheduled') == 'daily' else 'Weekly'} automatic search",
            f"{p.get('runs_per_day')} manual search{'es' if (p.get('runs_per_day') or 0) > 1 else ''} a day",
            f"Up to {p.get('max_score_per_run')} jobs scored per search",
            f"{p.get('max_tailor_per_run')} tailored resume + cover letter packets per search",
            "Browser extension that fills applications" if p.get("extension") else "Application tracker and timeline"]
    return "".join(f"<li>{html.escape(r)}</li>" for r in rows)


def body(plans=None, payments_enabled=False, operator=None, launched=True, quotes=None):
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
    faq = "\n    ".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in FAQ)
    cta = "Start free with Google" if launched else "Sign in to request access"
    invite = "" if launched else ('<p class="lp-invite">job-bot is invite-only while it\'s being finished. '
                                  "Sign in with Google to request access; you'll get in once you're approved.</p>")
    return f"""<div id="login" class="landing">
  <header class="lp-top"><b>job-bot</b><span class="spacer"></span>
    <a href="#how">How it works</a><a href="#example">Example</a><a href="#pricing">Pricing</a><a href="#faq">FAQ</a>
    <button class="primary" onclick="signIn()">Sign in</button></header>

  <section class="lp-hero">
    <p class="lp-eyebrow">For sales, marketing, design, HR, finance, healthcare, engineering and QA jobs: you pick the titles.</p>
    <h1>A daily job search that never invents your experience.</h1>
    <p class="lp-sub">job-bot scans 10 job sources every morning, scores each role against your real background,
      and drafts a tailored resume and cover letter using <b>only facts from your profile</b>.
      You review everything and <b>click submit yourself</b>.</p>
    <p><button class="primary lp-cta" onclick="signIn()">{cta}</button>
       <a class="btn" href="#example">See an example</a></p>
    {invite}{"" if launched else WAIT_MARK}
    <p class="meta lp-agree">By signing in you agree to the <a href="/terms">Terms</a> and <a href="/privacy">Privacy Policy</a>.</p>
    <p class="meta" id="loginerr"></p>
    {LIVE_MARK}
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
      <li><b>Apply on your terms.</b> Stop retyping your work history into yet another ATS form. Let the extension fill it; you check and submit.</li>
      <li><b>Track it.</b> Applied, interviewing, offers, follow-ups and notes, in one place on your phone or laptop instead of a spreadsheet.</li>
    </ol>
    <p class="meta">Searches: <span class="lp-chips">{chips}</span></p>
  </section>
{EXAMPLE}{quotes_section(quotes)}
  <p class="lp-midcta">See this with your own profile. <button class="primary" onclick="signIn()">{cta}</button></p>
{pricing}
  <section class="lp-sec"><h2>Plain talk about your data</h2>
    <p>Your profile, resumes and applications are stored in this job-bot's private Google Cloud project. The person who
      runs it can technically access that data. Job descriptions and your profile are sent to Anthropic's API to score
      and tailor. That's it: no selling, no sharing with employers, no applying on your behalf.</p>
    <p><b>Delete everything, yourself, anytime:</b> one button in Settings removes your profile, settings, jobs,
      applications and PDFs. The <a href="/privacy">Privacy Policy</a> has the details. job-bot is also <a href="{REPO}" rel="noopener" target="_blank">open source</a>,
      so you can read exactly what it does.</p>
    {op}
  </section>

  <section id="faq" class="lp-sec"><h2>Questions</h2>
    {faq}
  </section>

{CONTACT}

  <section class="lp-sec lp-end"><h2>Spend your time on the applications worth sending.</h2>
    <p><button class="primary lp-cta" onclick="signIn()">{cta}</button></p></section>
  <footer class="lp-foot meta"><a href="/terms">Terms</a> · <a href="/privacy">Privacy</a> · <a href="#contact">Contact</a> · <a href="{REPO}" rel="noopener" target="_blank">Open source on GitHub</a></footer>
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
.lp-demo u,.lp-ex u{text-decoration-color:var(--warn);text-decoration-thickness:2px}
.lp-flag{margin-top:8px;color:var(--warn);font-weight:600;font-size:12px}
.lp-steps{padding-left:20px}.lp-steps li{margin:8px 0}
.lp-chips span{display:inline-block;background:var(--chip);border-radius:6px;padding:1px 8px;margin:2px;font-size:12px}
.lp-plans{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.lp-plan{border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--panel)}
.lp-plan h3{margin:0;font-size:18px;text-transform:none;letter-spacing:0;color:var(--ink)}
.lp-pro{border-color:var(--accent)}.lp-price{font-size:22px;font-weight:700;margin:6px 0}
.lp-plan ul{padding-left:18px;margin:8px 0}
#faq details{border-bottom:1px solid var(--line);padding:10px 0}#faq details[open] summary{margin-bottom:4px}#faq summary{cursor:pointer;font-weight:600}
.lp-end{text-align:center}.lp-foot{padding-top:18px;border-top:1px solid var(--line)}
.lp-eyebrow{font-size:14px;font-weight:600;color:var(--accent);margin:0 0 10px}
.lp-midcta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:4px 0 26px;font-weight:600}
.lp-wait{margin:8px 0 0;font-size:14px}
.lp-quotes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.lp-q{margin:0;border:1px solid var(--line);border-radius:12px;padding:14px;background:var(--panel)}
.lp-q blockquote{margin:0 0 8px}.lp-q figcaption{color:var(--muted);font-size:13px}
.lp-live{display:flex;gap:8px;align-items:baseline;font-size:14px;color:var(--muted);margin:14px 0 0}
.lp-dot{width:8px;height:8px;border-radius:50%;background:var(--good,#2e9d5b);flex:none}
.lp-ex{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:16px;margin-top:10px}
.lp-ex-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:10px}
.lp-score{font-size:22px;font-weight:700;border:2px solid var(--accent);border-radius:10px;padding:2px 10px}
.lp-ex-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding-top:6px}
#login.landing .lp-ex h4{margin:12px 0 4px;font-size:13px;text-transform:none;letter-spacing:0;color:var(--ink)}
.lp-ex ul{margin:0;padding-left:18px}.lp-ex li{margin:3px 0}
.lp-quote{margin:4px 0;padding:6px 10px;border-left:3px solid var(--line);font-style:italic}
.lp-shots{margin:16px 0 0;display:grid;grid-template-columns:3fr 1fr;gap:14px;align-items:start}
.lp-shots img{width:100%;height:auto;border:1px solid var(--line);border-radius:10px;display:block}
.lp-shots figcaption{grid-column:1/-1}
.lp-ex-foot{border-top:1px solid var(--line);margin-top:12px}
.lp-form{display:grid;gap:8px;max-width:560px}.lp-form textarea,.lp-form input{width:100%;box-sizing:border-box;font:inherit;padding:8px 10px;border:1px solid var(--line);
  border-radius:8px;background:var(--panel);color:var(--ink)}
.lp-hp{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}
.lp-invite{border:1px solid var(--line);border-left:3px solid var(--warn);border-radius:8px;padding:8px 12px;
  background:var(--panel);font-size:14px;max-width:620px}
html.signed-in #login.landing{display:none}
@media (pointer:coarse),(max-width:800px){#login.landing button,#login.landing .btn{min-height:44px}
  #faq summary{padding:12px 0}.lp-foot a{display:inline-block;padding:14px 4px}}
@media (max-width:800px){.lp-shots{grid-template-columns:1fr;max-width:340px;margin-inline:auto}.lp-shot-wide{display:none!important}
  .lp-pillars,.lp-plans,.lp-ex-grid{grid-template-columns:1fr}.lp-top a{display:none}.lp-hero{padding-top:24px}}
"""
