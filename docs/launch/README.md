# Launch material (local only)

Everything in this folder except this README is git-ignored and never deployed,
because the GitHub repo is public. Paste HeyCatch output here.

- `research/`  audience research, competitor research, the 30-day plan, AI CMO answers,
  Reddit/X drafts, subreddit lists. Save it before the subscription ends.
- `articles/`  draft blog articles, one Markdown file each, named like
  `tailor-resume-without-lying.md` (lowercase words and dashes; that becomes the URL).

Article format:

    ---
    title: How to tailor a resume without making things up
    description: One sentence for search results, under 155 characters.
    date: 2026-11-20
    checked: false
    ---
    The article in Markdown.

Preview drafts locally (nothing goes online):

    python -m jobbot.blog preview          # -> output/blog-preview/index.html, plus a list of problems

To approve an article: check every claim against what job-bot really does, set
`checked: true`, and move the file to `jobbot/content/blog/`. It still isn't public
until the site launches (`cloud.launched: true`); before that /blog returns 404.
