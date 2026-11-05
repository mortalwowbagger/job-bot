"""Terms of Service and Privacy Policy for the hosted app, in plain language.

Every statement here should stay true of the code: if what's stored, who receives
it, or how deletion works changes, update this page in the same commit.
"""
import html

UPDATED = "November 4, 2026"
REPO = "https://github.com/mortalwowbagger/job-bot"

PRIVACY = f"""
<h1>Privacy Policy</h1>
<p class="meta">Last updated {UPDATED}</p>
<p>job-bot is a small, independently run job-search tool. This page says exactly what it stores, who else sees it,
  and how to delete it. The code is <a href="{REPO}" rel="noopener" target="_blank">open source</a>, so you can
  check every point.</p>

<h2>What job-bot stores</h2>
<ul>
  <li><b>Your Google sign-in:</b> your email address and an account ID. job-bot never sees your Google password.</li>
  <li><b>Your profile:</b> what you upload or type: contact details, work history, skills, education. If you import
    a resume PDF, the PDF's text is used to draft your profile; the PDF itself isn't kept.</li>
  <li><b>Your settings:</b> job titles, places and companies you choose.</li>
  <li><b>Jobs and applications:</b> postings found for you, their scores, the tailored resumes and cover letters
    (as PDFs), and anything you track: statuses, dates, contacts, notes.</li>
  <li><b>Usage counts:</b> how many searches and imports you ran and their estimated cost, to enforce plan limits.</li>
  <li><b>Messages</b> you send through the contact form, with the reply email you give (or your sign-in email if
    you send it from Settings).</li>
  <li><b>Billing</b> (only if you subscribe): your plan, subscription status and renewal date. Card details go
    straight to Stripe; job-bot never sees or stores them.</li>
</ul>
<p>job-bot doesn't use advertising, analytics or tracking cookies. Your browser keeps two small preferences
  (whether you're signed in, and how you sort your list), plus Google's sign-in session.</p>

<h2>Where it's stored</h2>
<p>In job-bot's own Google Cloud project in the United States (Firestore and Cloud Storage, us-central1).
  Server logs, which can include job titles and company names from your searches, are kept by Google Cloud for
  about 30 days.</p>

<h2>Who else receives your data</h2>
<ul>
  <li><b>Anthropic</b> (the Claude AI): your profile and job descriptions are sent to Anthropic's API to score jobs,
    write drafts and import resumes. It's processed under Anthropic's commercial API terms; see
    <a href="https://www.anthropic.com/legal/privacy" rel="noopener" target="_blank">Anthropic's privacy policy</a>.</li>
  <li><b>Google</b>: sign-in (Firebase Authentication) and hosting/storage (Google Cloud).</li>
  <li><b>Stripe</b>: payments, only if you subscribe.</li>
  <li><b>Job sites</b>: job-bot asks job boards for public listings using your job titles and places. It doesn't
    send them anything about you.</li>
</ul>
<p>That's the full list. job-bot doesn't sell your data, share it with employers or recruiters, or apply to jobs
  for you. The person who runs job-bot can technically access stored data and only looks at it to fix a problem
  or answer you.</p>

<h2>The browser extension</h2>
<p>The optional Chrome extension keeps a connection key in your browser. When you click <b>Fill this
  application</b>, it reads the form on that page and fills it with your profile and documents. Apart from
  job-bot's own site, where it connects to your account, it does nothing on a page until you click, and it never
  submits a form.</p>

<h2>Deleting your data</h2>
<p>Settings &rarr; <b>Delete my data</b> permanently removes your profile, settings, jobs, applications, PDFs,
  messages and extension keys, right away. Disconnect the extension in Settings to cancel its key. job-bot keeps
  no backups of deleted data. If you subscribed, Stripe keeps its own payment records as the law requires.</p>

<h2>Changes and questions</h2>
<p>If this policy changes in a way that matters, the change will be shown in the app before it applies.
  Questions: use the <a href="/#contact">contact form</a>.</p>
"""

TERMS = f"""
<h1>Terms of Service</h1>
<p class="meta">Last updated {UPDATED}</p>
<p>These terms cover your use of the hosted job-bot app. By signing in you agree to them. They're written to be
  read; if something's unclear, ask through the <a href="/#contact">contact form</a>.</p>

<h2>What job-bot does</h2>
<p>job-bot finds job postings, scores them against your profile, and drafts resumes, cover letters and answers
  for you to review. It never applies to jobs or submits forms for you.</p>

<h2>Your responsibilities</h2>
<ul>
  <li><b>Check before you send.</b> Drafts are written by AI and can be wrong. job-bot limits drafts to facts in your
    profile and flags things it can't match, but you're responsible for everything you submit to an employer.</li>
  <li><b>Keep your profile true.</b> Only add experience, skills and numbers that are accurate.</li>
  <li><b>Use it for your own job search.</b> Don't use job-bot to spam employers, scrape it, resell it, get around
    its limits, or interfere with it or with the job sites it uses.</li>
  <li><b>One account per person,</b> signed in with your own Google account.</li>
</ul>

<h2>No guarantees</h2>
<p>job-bot doesn't promise interviews, offers or any number of matches. Postings come from third-party job sites
  and may be out of date, closed or inaccurate. The service may be unavailable at times, and features or free-plan
  limits may change.</p>

<h2>Plans and payment</h2>
<p>The Free plan costs nothing. If Pro is offered, it's billed in advance monthly or yearly through Stripe and
  renews until you cancel. You can cancel anytime in Settings; Pro stays on until the end of the period you've paid
  for, and you aren't charged again. Payments already made aren't refunded, except where the law requires it.
  Price changes are announced before your next renewal, and you can cancel before they apply.</p>

<h2>Your content</h2>
<p>Your profile and documents are yours. You let job-bot store and process them only to provide the service,
  including sending them to the AI provider described in the <a href="/privacy">Privacy Policy</a>.</p>

<h2>Ending your use</h2>
<p>You can stop anytime and delete your data in Settings. Access can be suspended or closed for anyone who breaks
  these terms or puts the service or other users at risk. If job-bot shuts down, users will be told in advance
  and given time to save their documents.</p>

<h2>Liability</h2>
<p>job-bot is provided as is. To the extent the law allows, the person who runs it isn't liable for indirect
  losses, such as missed opportunities, or for more than the amount you paid for job-bot in the 12 months before
  the claim.</p>

<h2>Changes</h2>
<p>If these terms change in a way that matters, you'll see it in the app before it applies. Using job-bot
  afterwards means you accept the new terms.</p>
"""


def page(title, body, launched=True):
    robots = "" if launched else '<meta name="robots" content="noindex, nofollow">'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{robots}
<title>{html.escape(title)} - job-bot</title>
<style>
:root{{--bg:#f6f7f9;--ink:#1b1f24;--muted:#5b6570;--line:#e2e6ea;--accent:#2f5bd3;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1216;--ink:#e6e9ed;--muted:#9aa4af;--line:#2a3037;--accent:#6d8ff0;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:720px;margin:0 auto;padding:24px 18px 48px}}
a{{color:var(--accent)}} h1{{font-size:30px;margin:12px 0 4px}} h2{{font-size:19px;margin:28px 0 6px}}
.meta{{color:var(--muted);font-size:14px}} li{{margin:6px 0}}
nav{{display:flex;gap:16px;padding-bottom:10px;border-bottom:1px solid var(--line)}} nav b{{flex:1}}
footer{{margin-top:36px;padding-top:12px;border-top:1px solid var(--line)}}
</style></head><body><main>
<nav><b><a href="/" style="color:inherit;text-decoration:none">job-bot</a></b><a href="/terms">Terms</a><a href="/privacy">Privacy</a></nav>
{body}
<footer class="meta"><a href="/">Home</a> · <a href="/#contact">Contact</a> ·
  <a href="{REPO}" rel="noopener" target="_blank">Open source</a></footer>
</main></body></html>"""
