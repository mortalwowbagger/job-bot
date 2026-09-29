"""Write an application packet folder: resume PDF, cover letter, answers, review notes."""
import html
import re
from pathlib import Path

CSS = """
@page { size: Letter; margin: 0.55in 0.6in; }
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; font-size: 10.3pt;
       color: #1a1a1a; line-height: 1.32; }
h1 { font-size: 19pt; margin: 0; letter-spacing: .3px; }
.contact { color: #444; margin: 2px 0 10px; font-size: 9.6pt; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 1px; color: #1f3a5f;
     border-bottom: 1.2px solid #1f3a5f; padding-bottom: 2px; margin: 12px 0 6px; }
.job { margin-bottom: 7px; page-break-inside: avoid; }
.job-head { display: flex; justify-content: space-between; font-weight: 600; }
.job-sub { color: #444; font-style: italic; font-size: 9.6pt; }
ul { margin: 3px 0 0 16px; padding: 0; } li { margin: 1.5px 0; }
.skills { line-height: 1.45; }
p { margin: 0 0 6px; }
"""


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:n]


def resume_html(profile, packet):
    c = profile["contact"]
    e = html.escape
    contact = " | ".join(x for x in [c.get("location"), c.get("phone"), c.get("email"),
                                     c.get("linkedin"), c.get("github")] if x)
    jobs = []
    for item in packet["experience"]:
        j = profile["experience"][item["index"]]
        bullets = "".join(f"<li>{e(b)}</li>" for b in item["bullets"])
        jobs.append(
            f'<div class="job"><div class="job-head"><span>{e(j["title"])} - {e(j["company"])}</span>'
            f'<span>{e(j["dates"])}</span></div><div class="job-sub">{e(j.get("location", ""))}</div>'
            f"<ul>{bullets}</ul></div>")
    edu = profile.get("education") or []
    edu_html = ("<h2>Education</h2>" + "".join(f"<p>{e(x)}</p>" for x in edu)) if edu else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>{e(c['first_name'])} {e(c['last_name'])}</h1><div class="contact">{e(contact)}</div>
<h2>Summary</h2><p>{e(packet['summary'])}</p>
<h2>Skills</h2><div class="skills">{e(' • '.join(packet['skills']))}</div>
<h2>Experience</h2>{''.join(jobs)}{edu_html}</body></html>"""


def letter_html(text):
    paras = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.strip().split("\n\n"))
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS} "
            f"body{{font-size:11pt}} p{{margin:0 0 12px}}</style></head><body>{paras}</body></html>")


def html_to_pdf(html_str, out_path, browser=None):
    from playwright.sync_api import sync_playwright
    if browser is not None:
        page = browser.new_page()
        page.set_content(html_str, wait_until="load")
        page.pdf(path=str(out_path), format="Letter", print_background=True)
        page.close()
        return
    with sync_playwright() as p:
        b = p.chromium.launch()
        html_to_pdf(html_str, out_path, b)
        b.close()


def write_packet(root, job, profile, packet, score, warnings, browser=None, pdf=True):
    name = f"{job['id']:04d}-{slug(job['company'], 20)}-{slug(job['title'])}"
    d = Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    c = profile["contact"]
    base = f"{c['first_name']}_{c['last_name']}"

    rhtml = resume_html(profile, packet)
    (d / "resume.html").write_text(rhtml)
    (d / "cover_letter.txt").write_text(packet["cover_letter"].strip() + "\n")
    if pdf:
        html_to_pdf(rhtml, d / f"{base}_Resume.pdf", browser)
        html_to_pdf(letter_html(packet["cover_letter"]), d / f"{base}_Cover_Letter.pdf", browser)

    qa = "\n\n".join(f"**{x['question']}**\n\n{x['answer']}" for x in packet["screening_answers"])
    (d / "answers.md").write_text(f"# Screening answers - {job['company']}\n\n{qa}\n")

    warn = "\n".join(f"- [ ] {w}" for w in warnings) or "- none"
    reasons = "\n".join(f"- {r}" for r in score.get("reasons", []))
    concerns = "\n".join(f"- {r}" for r in score.get("concerns", [])) or "- none"
    (d / "REVIEW.md").write_text(
        f"# {job['title']} - {job['company']}\n\n"
        f"**Score:** {score.get('score')} | **Location:** {job['location']}\n\n"
        f"**Posting:** {job['url']}\n**Apply:** {job['apply_url']}\n\n"
        f"## Check before submitting\n{warn}\n\n## Why it matches\n{reasons}\n\n"
        f"## Concerns\n{concerns}\n\n"
        f"Apply with: `python -m jobbot apply {job['id']}`\n\n---\n\n## Job description\n\n"
        f"{job['description']}\n")
    return d
