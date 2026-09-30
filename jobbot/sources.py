"""Fetch job listings from public job-board APIs (no scraping, no login).

Company boards (a fixed list of employers): Greenhouse, Lever, Ashby,
SmartRecruiters, Workable, Recruitee. Search sources (keyword/feed based, so
people outside tech get results too): Himalayas and Jobicy remote-job APIs, and
Remotive. Aggregators ask for credit: jobs keep a link to their page and the UI
shows "via Himalayas" etc.
"""
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


def parse_himalayas(data):
    for j in data.get("jobs", []):
        where = ", ".join(j.get("locationRestrictions") or []) or "Worldwide"
        yield dict(
            source="himalayas", ext_id=j.get("guid") or j.get("applicationLink"), board="himalayas",
            company=j.get("companyName", ""), title=j.get("title", ""), location=f"Remote ({where})",
            remote_hint=True, url=j.get("guid") or j.get("applicationLink", ""),
            apply_url=j.get("applicationLink") or j.get("guid", ""),
            description=strip_html(j.get("description") or j.get("excerpt", "")),
        )


def parse_jobicy(data):
    for j in data.get("jobs", []):
        yield dict(
            source="jobicy", ext_id=str(j["id"]), board="jobicy", company=j.get("companyName", ""),
            title=html.unescape(j.get("jobTitle", "")), location=f"Remote ({j.get('jobGeo') or 'Anywhere'})",
            remote_hint=True, url=j.get("url", ""), apply_url=j.get("url", ""),
            description=strip_html(j.get("jobDescription", "")),
        )


def parse_smartrecruiters(slug, data):
    for j in data.get("content", []):
        loc = j.get("location") or {}
        where = ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
        remote = bool(loc.get("remote"))
        url = f"https://jobs.smartrecruiters.com/{slug}/{j['id']}"
        yield dict(
            source="smartrecruiters", ext_id=str(j["id"]), board=slug,
            company=(j.get("company") or {}).get("name") or slug, title=j.get("name", ""),
            location=("Remote - " if remote else "") + where, remote_hint=remote,
            url=url, apply_url=url, description="", detail_url=j.get("ref", ""),
        )


def parse_workable(slug, data):
    company = data.get("name") or slug
    for j in data.get("jobs", []):
        where = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        remote = str(j.get("telecommuting")).lower() == "true"
        yield dict(
            source="workable", ext_id=j.get("shortcode") or j.get("url"), board=slug, company=company,
            title=j.get("title", ""), location=("Remote - " if remote else "") + where, remote_hint=remote,
            url=j.get("url", ""), apply_url=j.get("application_url") or j.get("url", ""),
            description=strip_html(j.get("description", "")),
        )


def parse_recruitee(slug, data):
    for j in data.get("offers", []):
        remote = bool(j.get("remote"))
        loc = j.get("location") or ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        if remote and "remote" not in loc.lower():
            loc = f"Remote - {loc}" if loc else "Remote"
        yield dict(
            source="recruitee", ext_id=str(j["id"]), board=slug, company=j.get("company_name") or slug,
            title=j.get("title", ""), location=loc, remote_hint=remote,
            url=j.get("careers_url", ""), apply_url=j.get("careers_apply_url") or j.get("careers_url", ""),
            description=strip_html((j.get("description") or "") + "\n" + (j.get("requirements") or "")),
        )


def fill_description(job):
    """Some list APIs (SmartRecruiters) omit descriptions; fetch it for jobs we keep."""
    if job.get("description") or not job.get("detail_url"):
        return job
    d = _get(job["detail_url"])
    secs = ((d.get("jobAd") or {}).get("sections") or {})
    parts = [strip_html((secs.get(k) or {}).get("text", "")) for k in
             ("jobDescription", "qualifications", "additionalInformation", "companyDescription")]
    job["description"] = "\n\n".join(x for x in parts if x)
    job["apply_url"] = d.get("applyUrl") or job.get("apply_url")
    return job


# --- fetchers ---

def fetch_greenhouse(slug):
    return parse_greenhouse(slug, _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", content="true"))


def fetch_lever(slug):
    return parse_lever(slug, _get(f"https://api.lever.co/v0/postings/{slug}", mode="json"))


def fetch_ashby(slug):
    return parse_ashby(slug, _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}"))


def fetch_remotive(category):
    return parse_remotive(_get("https://remotive.com/api/remote-jobs", category=category))


def fetch_smartrecruiters(slug, country="us", cap=500):
    jobs, offset = [], 0
    while offset < cap:
        data = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                    limit=100, offset=offset, country=country)
        jobs += list(parse_smartrecruiters(slug, data))
        offset += 100
        if offset >= data.get("totalFound", 0):
            break
    return jobs


def fetch_workable(slug):
    return parse_workable(slug, _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", details="true"))


def fetch_recruitee(slug):
    return parse_recruitee(slug, _get(f"https://{slug}.recruitee.com/api/offers/"))


def fetch_himalayas(query, country="US", pages=2):
    jobs = []
    for page in range(1, pages + 1):
        data = _get("https://himalayas.app/jobs/api/search", q=query, country=country, sort="recent", page=page)
        batch = list(parse_himalayas(data))
        jobs += batch
        if len(batch) < 20:
            break
    return jobs


def fetch_jobicy(geo="usa"):
    """The 200 newest remote jobs for a region (one request; Jobicy asks for <= 1 automated check/hour)."""
    return parse_jobicy(_get("https://jobicy.com/api/v2/remote-jobs", count=200, geo=geo))


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "smartrecruiters": fetch_smartrecruiters, "workable": fetch_workable,
            "recruitee": fetch_recruitee, "remotive": fetch_remotive, "himalayas": fetch_himalayas,
            "jobicy": fetch_jobicy}
BOARD_KINDS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee"]


def plan_for(cfg, extra=()):
    """(kind, arg) pairs to fetch: config boards + search sources + extras (e.g. users' companies)."""
    src = cfg.get("sources", {})
    plan = [(k, slug) for k in BOARD_KINDS for slug in (src.get(k) or [])]
    rem = src.get("remotive") or {}
    if rem.get("enabled"):
        plan += [("remotive", c) for c in rem.get("categories", [])]
    search = cfg.get("search") or {}
    if search.get("jobicy"):
        plan.append(("jobicy", "usa"))
    if search.get("himalayas"):
        plan += [("himalayas", q) for q in search.get("keywords") or []]
    seen, out = set(), []
    for item in list(plan) + list(extra):
        key = (item[0], str(item[1]).lower())
        if key not in seen and item[0] in FETCHERS:
            seen.add(key)
            out.append(item)
    return out


def iter_all(cfg, log=print, extra=(), workers=8):
    """Yield every job from every source (fetched in parallel); log, don't crash on, bad ones."""
    from concurrent.futures import ThreadPoolExecutor
    plan = plan_for(cfg, extra)

    def one(item):
        kind, arg = item
        try:
            return item, list(FETCHERS[kind](arg)), None
        except Exception as e:  # noqa: BLE001 - one bad board shouldn't stop the run
            return item, [], e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, ((kind, arg), jobs, err) in enumerate(pool.map(one, plan), 1):
            name = f"({i}/{len(plan)}) {kind}:{arg}"
            if err:
                log(f"  {name:40s} FAILED ({type(err).__name__}: {str(err)[:80]})")
            else:
                log(f"  {name:40s} {len(jobs):4d} jobs")
                yield from jobs
