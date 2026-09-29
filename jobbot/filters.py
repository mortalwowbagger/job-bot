"""Cheap, deterministic filters that run before any (paid) LLM call."""
import re

NON_US = [
    "uk", "united kingdom", "england", "london", "ireland", "dublin", "canada", "toronto",
    "vancouver", "emea", "europe", "eu", "germany", "berlin", "france", "paris", "spain",
    "netherlands", "amsterdam", "poland", "portugal", "india", "bangalore", "bengaluru",
    "apac", "asia", "singapore", "japan", "tokyo", "australia", "sydney", "latam",
    "brazil", "mexico", "argentina", "colombia", "israel", "philippines", "romania",
    "ukraine", "serbia", "south africa", "new zealand", "hong kong", "taiwan", "taipei",
    "china", "shanghai", "beijing", "shenzhen", "korea", "seoul", "vietnam", "thailand",
    "malaysia", "indonesia", "dubai", "uae", "turkey", "istanbul", "egypt", "nigeria", "kenya",
    "pakistan", "sweden", "stockholm", "denmark", "copenhagen", "norway", "finland",
    "switzerland", "zurich", "austria", "italy", "belgium", "czech", "prague", "hungary",
    "budapest", "bulgaria", "greece", "chile", "peru", "costa rica", "uruguay",
]
US_OK = ["us", "usa", "u.s.", "united states", "north america", "americas", "anywhere",
         "worldwide", "global"]
HYBRID_ONSITE = ["hybrid", "on-site", "onsite", "in office", "in-office"]


def _has_word(text, words):
    return any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text) for w in words)


def title_ok(title, cfg):
    t = title.lower()
    inc = cfg.get("title_include") or []
    exc = cfg.get("title_exclude") or []
    if inc and not any(re.search(p, t) for p in inc):
        return False
    return not any(re.search(p, t) for p in exc)


def location_ok(job, cfg):
    loc = (job.get("location") or "").lower()
    if cfg.get("remote_only", True):
        if not job.get("remote_hint") and "remote" not in loc:
            return False
        if _has_word(loc, HYBRID_ONSITE):
            return False
    if cfg.get("us_only", True) and loc:
        if _has_word(loc, NON_US) and not _has_word(loc, US_OK):
            return False
    return True


def passes(job, cfg):
    """Return (ok, reason)."""
    if not title_ok(job.get("title", ""), cfg):
        return False, "title"
    if not location_ok(job, cfg):
        return False, "location"
    return True, ""
