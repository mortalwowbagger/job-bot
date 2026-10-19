"""Is a stored job posting still open? Conservative on purpose.

check(job) -> (state, posted_at)
  state: "open" | "closed" | None (couldn't tell: blocked, error, unsupported) - None never removes a job
  posted_at: YYYY-MM-DD when the source tells us, else ""

"closed" only on a definite signal: the source's own API no longer lists the job
(or returns 404), or the listing page answers 404 / 410 Gone.
"""
import os
import re
import threading

import requests

from . import sources

UA = {"User-Agent": "job-bot/0.1 (personal job search)"}
TIMEOUT = 20
_cache, _lock = {}, threading.Lock()
_paced = {"himalayas": threading.Lock(), "adzuna": threading.Lock()}  # one request at a time, gently
ADZUNA_PER_RUN = 30
_adzuna_used = [0]


def _board(kind, slug, fetch):
    """Fetch a whole board once per run and share it across jobs (thread-safe)."""
    key = (kind, slug.lower())
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        jobs = {str(j["ext_id"]): j for j in fetch(slug)}
    except Exception:  # noqa: BLE001 - can't tell
        jobs = None
    with _lock:
        _cache[key] = jobs
    return jobs


def reset_cache():
    with _lock:
        _cache.clear()
        _adzuna_used[0] = 0


def _paced_get(kind, url, **params):
    """Serialized, retried-on-429 GET for APIs that throttle bursts."""
    import time
    with _paced[kind]:
        for attempt in range(3):
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
            if r.status_code != 429:
                time.sleep(0.25)
                return r
            time.sleep(2 * (attempt + 1))
        return r


def _status(url, **params):
    r = requests.get(url, params=params or None, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    return r


def _by_status(code):
    return "closed" if code in (404, 410) else ("open" if code == 200 else None)


def _himalayas(job):
    m = re.search(r"himalayas\.app/companies/([^/]+)/jobs/", job.get("url") or job.get("ext_id") or "")
    if not m:
        return None, ""

    def fetch(slug):
        out = []
        for page in (1, 2, 3):
            r = _paced_get("himalayas", "https://himalayas.app/jobs/api/search", company=slug, page=page)
            r.raise_for_status()
            batch = list(sources.parse_himalayas(r.json()))
            out += batch
            if len(batch) < 20:
                break
        return out
    live = _board("himalayas", m.group(1), fetch)
    if live is None:
        return None, ""
    hit = live.get(str(job.get("ext_id")))
    return ("open", hit.get("posted_at", "")) if hit else ("closed", "")


def _adzuna(job):
    """Adzuna blocks automated page checks, so ask its API for this exact title at this company."""
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    with _lock:
        if not (app_id and app_key) or _adzuna_used[0] >= ADZUNA_PER_RUN:
            return None, ""
        _adzuna_used[0] += 1
    # exact-title search (the API rejects a company filter); "closed" only when every match was returned
    r = _paced_get("adzuna", "https://api.adzuna.com/v1/api/jobs/us/search/1", app_id=app_id, app_key=app_key,
                   what_phrase=job.get("title", ""), results_per_page=50, **{"content-type": "application/json"})
    if r.status_code != 200:
        return None, ""
    data = r.json()
    results = data.get("results", [])
    for hit in results:
        if str(hit.get("id")) == str(job.get("ext_id")):
            return "open", sources.when(hit.get("created"))
    return ("closed", "") if (data.get("count") or 0) <= len(results) else (None, "")


def check(job):
    src, ext, board = job.get("source"), str(job.get("ext_id") or ""), job.get("board") or ""
    try:
        if src == "greenhouse":
            r = _status(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{ext}")
            if r.status_code == 200:
                d = r.json()
                return "open", sources.when(d.get("first_published") or d.get("updated_at"))
            return _by_status(r.status_code), ""
        if src == "lever":
            r = _status(f"https://api.lever.co/v0/postings/{board}/{ext}")
            if r.status_code == 200:
                return "open", sources.when(r.json().get("createdAt"))
            return _by_status(r.status_code), ""
        if src == "smartrecruiters":
            r = _status(f"https://api.smartrecruiters.com/v1/companies/{board}/postings/{ext}")
            if r.status_code == 200:
                return "open", sources.when(r.json().get("releasedDate"))
            return _by_status(r.status_code), ""
        if src in ("ashby", "workable", "recruitee"):
            live = _board(src, board, sources.FETCHERS[src])
            if live is None:
                return None, ""
            hit = live.get(ext)
            return ("open", hit.get("posted_at", "")) if hit else ("closed", "")
        if src == "himalayas":
            return _himalayas(job)
        if src == "muse":
            key = os.environ.get("MUSE_API_KEY")
            if not key:
                return None, ""
            r = _status(f"https://www.themuse.com/api/public/jobs/{ext}", api_key=key)
            if r.status_code == 200:
                return "open", sources.when(r.json().get("publication_date"))
            return _by_status(r.status_code), ""
        if src == "adzuna":
            return _adzuna(job)
        if src in ("jobicy", "remotive"):
            return _by_status(_status(job.get("url") or "").status_code), ""
    except Exception:  # noqa: BLE001 - network trouble: can't tell
        return None, ""
    return None, ""


def check_many(jobs, workers=8):
    """[(job, state, posted_at)] for many jobs, in parallel."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [(j, *res) for j, res in zip(jobs, pool.map(check, jobs))]
