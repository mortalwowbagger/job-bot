"""Per-user search settings for the hosted app.

People edit plain phrases, not regex: one per line, case-insensitive, whole
words. A trailing * matches word starts ("engineer*" -> engineer, engineering).
to_cfg() turns them into the title_include/title_exclude patterns filters.py uses.
"""
import re

LIMITS = {"include": 60, "exclude": 150, "local": 20, "len": 60, "companies": 30}

# careers-page URL (or "kind:slug") -> (kind, slug)
BOARD_URLS = [
    ("greenhouse", r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([A-Za-z0-9_-]+)\.recruitee\.com"),
]
KINDS = [k for k, _ in BOARD_URLS]


def parse_company(text):
    """'https://jobs.lever.co/acme/123' -> ('lever', 'acme'); 'greenhouse:acme' also works."""
    t = text.strip()
    m = re.match(rf"^({'|'.join(KINDS)})\s*:\s*([A-Za-z0-9_.-]+)$", t, re.I)
    if m:
        return m.group(1).lower(), m.group(2)
    for kind, pat in BOARD_URLS:
        m = re.search(pat, t)
        if m and m.group(1).lower() not in ("jobs", "embed", "www", "api"):
            return kind, m.group(1)
    return None


STATE = re.compile(r",\s*[A-Za-z]{2}\.?\s*$")


def city_warnings(cities):
    """Non-blocking reminders for cities missing a state ("austin" -> "Austin, TX")."""
    missing = [c for c in cities or [] if c.strip() and not STATE.search(c)]
    if not missing:
        return []
    shown = ", ".join(f"'{c}'" for c in missing[:3]) + ("…" if len(missing) > 3 else "")
    return [f"{shown} {'has' if len(missing) == 1 else 'have'} no state. Write cities like "
            f"\"Austin, TX\" so The Muse can search them (filtering still works without it)."]


def search_queries(s):
    """Job-title phrases usable as keyword searches (no wildcards, not too short)."""
    out = []
    for p in (s or {}).get("title_keywords") or []:
        q = p.rstrip("*").strip()
        if len(q) >= 3 and q.lower() not in (x.lower() for x in out):
            out.append(q)
    return out[:8]

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
    "local_areas": ["Austin, TX", "Round Rock, TX", "Cedar Park, TX", "Pflugerville, TX", "Kyle, TX",
                    "San Marcos, TX"],
    "min_score": 70,
    "companies": [],
}

NEW_USER_DEFAULTS = {
    "companies": [],
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
    companies, bad = [], []
    raw = body.get("companies", [])
    for line in (raw.splitlines() if isinstance(raw, str) else raw):
        line = str(line).strip()
        if not line:
            continue
        hit = parse_company(line)
        if hit:
            if f"{hit[0]}:{hit[1]}".lower() not in (c.lower() for c in companies):
                companies.append(f"{hit[0]}:{hit[1]}")
        else:
            bad.append(line[:60])
    if bad:
        errors.append("Companies: couldn't recognize " + ", ".join(repr(b) for b in bad[:3]) +
                      ". Paste a careers link from Greenhouse, Lever, Ashby, SmartRecruiters, Workable or Recruitee.")
    if len(companies) > LIMITS["companies"]:
        errors.append(f"Companies: at most {LIMITS['companies']}")
    out["companies"] = companies[:LIMITS["companies"]]
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
            # "Austin, TX" -> match "austin" so "Austin, Texas" postings count too
            "local_areas": [a.split(",")[0].strip() for a in s["local_areas"] if a.strip()],
            "min_score": s["min_score"]}
