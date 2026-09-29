"""Fetch job listings from public job-board APIs (no scraping, no login)."""
import html
import re

import requests

UA = {"User-Agent": "job-bot/0.1 (personal job search)"}
TIMEOUT = 20


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<\s*(br|/p|/li|/h\d|/div)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _get(url, **params):
    r = requests.get(url, params=params or None, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# --- parsers take raw JSON so they can be unit-tested with fixtures ---

def parse_greenhouse(slug, data):
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        yield dict(
            source="greenhouse", ext_id=str(j["id"]),
            company=j.get("company_name") or slug, board=slug,
            title=j.get("title", ""), location=loc,
            remote_hint="remote" in loc.lower(),
            url=j.get("absolute_url", ""),
            # hosted form works even when absolute_url is a company page w/ iframe
            apply_url=f"https://job-boards.greenhouse.io/{slug}/jobs/{j['id']}",
            description=strip_html(j.get("content", "")),
        )


def parse_lever(slug, data):
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        parts = [j.get("descriptionPlain", "")]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", "") + "\n" + strip_html(lst.get("content", "")))
        parts.append(j.get("additionalPlain", ""))
        yield dict(
            source="lever", ext_id=j["id"], company=slug, board=slug,
            title=j.get("text", ""), location=loc,
            remote_hint=(j.get("workplaceType") == "remote") or "remote" in loc.lower(),
            url=j.get("hostedUrl", ""),
            apply_url=j.get("applyUrl") or (j.get("hostedUrl", "") + "/apply"),
            description="\n\n".join(p for p in parts if p).strip(),
        )


def parse_ashby(slug, data):
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location", "") or ""
        wt = (j.get("workplaceType") or "").lower()
        yield dict(
            source="ashby", ext_id=j["id"], company=slug, board=slug,
            title=j.get("title", ""), location=loc,
            remote_hint=bool(j.get("isRemote")) or wt == "remote" or "remote" in loc.lower(),
            url=j.get("jobUrl", ""),
            apply_url=j.get("applyUrl") or (j.get("jobUrl", "") + "/application"),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
        )


def parse_remotive(data):
    for j in data.get("jobs", []):
        loc = j.get("candidate_required_location", "") or ""
        yield dict(
            source="remotive", ext_id=str(j["id"]),
            company=j.get("company_name", ""), board="remotive",
            title=j.get("title", ""), location=f"Remote ({loc})" if loc else "Remote",
            remote_hint=True, url=j.get("url", ""), apply_url=j.get("url", ""),
            description=strip_html(j.get("description", "")),
        )


# --- fetchers ---

def fetch_greenhouse(slug):
    return parse_greenhouse(slug, _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", content="true"))


def fetch_lever(slug):
    return parse_lever(slug, _get(f"https://api.lever.co/v0/postings/{slug}", mode="json"))


def fetch_ashby(slug):
    return parse_ashby(slug, _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}"))


def fetch_remotive(category):
    return parse_remotive(_get("https://remotive.com/api/remote-jobs", category=category))


def iter_all(cfg, log=print):
    """Yield every job from every configured source; log (don't crash on) bad slugs."""
    src = cfg.get("sources", {})
    plan = [(fetch_greenhouse, s) for s in src.get("greenhouse", []) or []]
    plan += [(fetch_lever, s) for s in src.get("lever", []) or []]
    plan += [(fetch_ashby, s) for s in src.get("ashby", []) or []]
    rem = src.get("remotive") or {}
    if rem.get("enabled"):
        plan += [(fetch_remotive, c) for c in rem.get("categories", [])]
    for fn, arg in plan:
        name = f"{fn.__name__.replace('fetch_', '')}:{arg}"
        try:
            jobs = list(fn(arg))
            log(f"  {name:32s} {len(jobs):4d} jobs")
            yield from jobs
        except Exception as e:  # noqa: BLE001 - one bad board shouldn't stop the run
            log(f"  {name:32s} FAILED ({type(e).__name__}: {str(e)[:80]})")
