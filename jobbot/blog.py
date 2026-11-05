"""Blog for the hosted site: Markdown articles, safely rendered.

Workflow (see docs/launch/README.md):
  docs/launch/articles/*.md      drafts (git-ignored, never deployed)
  jobbot/content/blog/*.md       approved articles (deployed)

    python -m jobbot.blog preview [folder]   -> output/blog-preview/index.html (local only)

An article is public only when ALL of these hold: it's in jobbot/content/blog, its
front matter says `checked: true` (claims verified against what job-bot really
does), and the site is launched (cloud.launched). Otherwise /blog 404s.

Article file:
    ---
    title: How to tailor a resume without making things up
    description: One sentence for search results (under 155 characters).
    date: 2026-11-20
    checked: false
    ---
    Markdown body: # / ## / ### headings, paragraphs, - or 1. lists, > quotes,
    **bold**, *italic*, [links](https://...). Raw HTML is shown as text, never run.
"""
import html
import json
import re
import sys
from pathlib import Path

PUBLISHED = Path(__file__).parent / "content" / "blog"
DRAFTS = Path(__file__).parents[1] / "docs" / "launch" / "articles"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse(text):
    """-> (meta dict, markdown body). Front matter is simple `key: value` lines between --- fences."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip():
                meta[k.strip().lower()] = v.strip().strip('"').strip("'")
        body = m.group(2)
    meta["checked"] = meta.get("checked", "").lower() == "true"
    return meta, body


def _inline(text):
    """Escape everything, then allow bold, italic, inline code and http(s)/relative links."""
    t = html.escape(text, quote=True)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", t)

    def link(m):
        label, url = m.group(1), html.unescape(m.group(2))
        if not re.match(r"^(https?://|/|#)", url):  # no javascript:, data:, etc.
            return m.group(0)
        ext = ' rel="noopener" target="_blank"' if url.startswith("http") else ""
        return f'<a href="{html.escape(url, quote=True)}"{ext}>{label}</a>'
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)


def render_markdown(md):
    out, para, items, kind, quote = [], [], [], None, []

    def flush():
        nonlocal para, items, kind, quote
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{kind}>")
        if quote:
            out.append(f"<blockquote>{_inline(' '.join(quote))}</blockquote>")
        para, items, kind, quote = [], [], None, []

    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        li = re.match(r"^(?:[-*]|(\d+)[.)])\s+(.*)$", line)
        if h:
            flush()
            level = len(h.group(1)) + 1  # the page title is the only h1
            out.append(f"<h{level}>{_inline(h.group(2))}</h{level}>")
        elif li:
            want = "ol" if li.group(1) else "ul"
            if para or quote or (kind and kind != want):
                flush()
            kind = want
            items.append(li.group(2))
        elif line.startswith(">"):
            if para or items:
                flush()
            quote.append(line.lstrip("> "))
        elif items:  # continuation of the last list item
            items[-1] += " " + line
        else:
            para.append(line)
    flush()
    return "\n".join(out)


def load(folder=None, only_checked=True):
    """Articles in a folder (default: the published one), newest first:
    [{slug, title, description, date, checked, body_md}]."""
    folder, posts = folder or PUBLISHED, []
    for f in sorted(Path(folder).glob("*.md")) if Path(folder).exists() else []:
        meta, body = parse(f.read_text())
        slug = f.stem.lower()
        if not SLUG.match(slug) or not meta.get("title"):
            continue
        if only_checked and not meta["checked"]:
            continue
        posts.append({"slug": slug, "title": meta["title"], "description": meta.get("description", ""),
                      "date": meta.get("date", ""), "checked": meta["checked"], "body_md": body})
    return sorted(posts, key=lambda p: p["date"], reverse=True)


def problems(post):
    """Checks to pass before an article is approved."""
    out = []
    if len(post["description"]) > 155:
        out.append(f"description is {len(post['description'])} characters (keep it under 155)")
    if not post["description"]:
        out.append("missing description")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", post["date"]):
        out.append("date should be YYYY-MM-DD")
    risky = re.compile(r"\b(?:guarantee[sd]?|\d+(?:\.\d+)?x|\d+% (?:more|higher|faster|better))\b", re.I)
    for line in post["body_md"].splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            if risky.search(sentence):  # outcome promises job-bot can't back up
                out.append(f"check this claim: {sentence.replace('**', '')[:120]}")
    return out


def article_page(post, base_url="", launched=True):
    e = html.escape
    from .legal import page
    schema = {"@context": "https://schema.org", "@type": "Article", "headline": post["title"],
              "description": post["description"], "datePublished": post["date"],
              "author": {"@type": "Organization", "name": "job-bot", "url": f"{base_url}/"},
              "publisher": {"@type": "Organization", "name": "job-bot", "url": f"{base_url}/"}}
    body = (f'<p class="meta"><a href="/blog">Blog</a> · {e(post["date"])}</p><h1>{e(post["title"])}</h1>\n'
            + render_markdown(post["body_md"])
            + '\n<p style="margin-top:28px"><a href="/">Try job-bot</a>: a daily job search that never invents '
              "your experience.</p>"
            + f'<script type="application/ld+json">{json.dumps(schema).replace("</", "<\\/")}</script>')
    return page(post["title"], body, launched, description=post["description"])


def index_page(posts, launched=True):
    e = html.escape
    from .legal import page
    rows = "".join(f'<li><a href="/blog/{e(p["slug"])}"><b>{e(p["title"])}</b></a><div class="meta">{e(p["date"])}'
                   f' · {e(p["description"])}</div></li>' for p in posts) or "<p>No articles yet.</p>"
    return page("Blog", f'<h1>Blog</h1><ul style="list-style:none;padding:0">{rows}</ul>', launched,
                description="Plain advice on job searching, resumes and applications from job-bot.")


def preview(folder=None):
    """Render every article in a folder (checked or not) to output/blog-preview/, with its problems listed."""
    out = Path(__file__).parents[1] / "output" / "blog-preview"
    out.mkdir(parents=True, exist_ok=True)
    folder = folder or DRAFTS
    posts = load(folder, only_checked=False)
    for p in posts:
        (out / f"{p['slug']}.html").write_text(article_page(p, launched=False).replace('href="/blog/', 'href="./')
                                                .replace('href="/blog"', 'href="index.html"'))
    rows = []
    for p in posts:
        issues = problems(p)
        status = "checked" if p["checked"] else "NOT checked"
        rows.append(f'<li><a href="{p["slug"]}.html">{html.escape(p["title"])}</a> <span class="meta">{status}</span>'
                    + "".join(f'<div class="meta">⚠ {html.escape(i)}</div>' for i in issues) + "</li>")
    from .legal import page
    (out / "index.html").write_text(page("Blog preview", f"<h1>Blog preview</h1><p class='meta'>{html.escape(str(folder))}"
                                         f"</p><ul>{''.join(rows) or '<li>No articles found.</li>'}</ul>", False))
    return out / "index.html", posts


if __name__ == "__main__":
    if sys.argv[1:2] == ["preview"]:
        path, posts = preview(Path(sys.argv[2]) if len(sys.argv) > 2 else None)
        print(f"{len(posts)} article(s) -> {path}")
        for p in posts:
            for issue in problems(p):
                print(f"  {p['slug']}: {issue}")
    else:
        print(__doc__)
