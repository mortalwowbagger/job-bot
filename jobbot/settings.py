"""Per-user search settings for the hosted app.

People edit plain phrases, not regex: one per line, case-insensitive, whole
words. A trailing * matches word starts ("engineer*" -> engineer, engineering).
to_cfg() turns them into the title_include/title_exclude patterns filters.py uses.
"""
import re

LIMITS = {"include": 60, "exclude": 150, "local": 20, "len": 60}

# Equivalent to the owner's original config.yaml filters (see tests).
OWNER_DEFAULTS = {
    "title_keywords": ["qa", "quality", "test", "tests", "testing", "tester", "sdet", "engineer in test",
                       "automation", "devops", "test infrastructure", "release engineer*",
                       "build and release", "build & release", "developer productivity"],
    "exclude_keywords": [
        "intern", "internship", "supplier", "manufactur*", "clinical", "mechanical", "hardware", "food",
        "content quality", "data quality analyst", "sales", "marketing", "account partner", "regulatory",
        "customer success", "solution", "solutions", "strategist", "people systems", "finance systems",
        "product manager", "product operations", "electrical", "search quality", "answer quality",
        "evaluation quality", "consultant", "engagement manager", "program manager", "designer",
        "accelerator program", "new grad", "graduate", "student", "psycholog*", "physician", "nurse*",
        "clinician", "therapist", "pharmac*", "electronics", "rf", "structures", "actuator*", "propulsion",
        "avionics", "firmware", "pcb", "credentialing", "data modeling", "loan salability"],
    "remote_only": True,
    "us_only": True,
    "local_areas": ["austin", "round rock", "cedar park", "pflugerville", "kyle", "san marcos"],
    "min_score": 70,
}

NEW_USER_DEFAULTS = {
    "title_keywords": [],
    "exclude_keywords": ["intern", "internship", "new grad", "student"],
    "remote_only": True,
    "us_only": True,
    "local_areas": [],
    "min_score": 70,
}


def phrase_pattern(phrase):
    """'release engineer*' -> regex matching whole words, * = word start."""
    p = phrase.strip().lower()
    star = p.endswith("*")
    core = r"\s+".join(re.escape(w) for w in p.rstrip("*").split())
    return rf"(?<![a-z0-9]){core}" + ("" if star else r"(?![a-z0-9])")


def clean(body):
    """Validate user input. Returns (settings, errors)."""
    errors, out = [], {}

    def lines(key, limit, label):
        raw = body.get(key, [])
        if isinstance(raw, str):
            raw = raw.splitlines()
        vals = []
        for v in raw:
            v = re.sub(r"\s+", " ", str(v)).strip()
            if not v or v.lower() in (x.lower() for x in vals):
                continue
            if len(v) > LIMITS["len"]:
                errors.append(f"{label}: '{v[:30]}…' is too long")
            elif not re.sub(r"[\s*]", "", v):
                errors.append(f"{label}: '{v}' needs letters or numbers")
            else:
                vals.append(v)
        if len(vals) > limit:
            errors.append(f"{label}: at most {limit} lines")
        out[key] = vals[:limit]

    lines("title_keywords", LIMITS["include"], "Job titles")
    lines("exclude_keywords", LIMITS["exclude"], "Skip titles")
    lines("local_areas", LIMITS["local"], "Cities")
    if not out["title_keywords"]:
        errors.append("Job titles: add at least one (e.g. qa engineer, sdet)")
    for k in ("remote_only", "us_only"):
        out[k] = bool(body.get(k, True))
    try:
        out["min_score"] = int(body.get("min_score", 70))
        if not 0 <= out["min_score"] <= 100:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Minimum score must be a number from 0 to 100")
    return out, errors


def to_cfg(base, settings):
    """Base config.yaml values with this user's search settings applied."""
    s = {**NEW_USER_DEFAULTS, **(settings or {})}
    return {**base,
            "title_include": [phrase_pattern(p) for p in s["title_keywords"]],
            "title_exclude": [phrase_pattern(p) for p in s["exclude_keywords"]],
            "remote_only": s["remote_only"], "us_only": s["us_only"],
            "local_areas": list(s["local_areas"]), "min_score": s["min_score"]}
