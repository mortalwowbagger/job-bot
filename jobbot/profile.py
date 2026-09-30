"""Profile editing + resume import, shared by the local and hosted dashboards.

The profile is the only source of truth the tailoring AI may use, so an
imported resume is only a *draft*: the model is told to copy, never invent,
anything it produced that isn't found in the PDF text is flagged, and nothing
is saved until the user reviews it and clicks Save.
"""
import io
import re

import yaml

from .llm import chat_json

MAX_PDF_BYTES = 5 * 1024 * 1024

IMPORT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["contact", "summary", "experience", "skills", "education", "extra_facts"],
    "properties": {
        "contact": {
            "type": "object", "additionalProperties": False,
            "required": ["first_name", "last_name", "email", "phone", "location", "linkedin", "github"],
            "properties": {k: {"type": "string"} for k in
                           ("first_name", "last_name", "email", "phone", "location", "linkedin", "github")},
        },
        "summary": {"type": "string"},
        "experience": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["company", "location", "title", "dates", "facts"],
            "properties": {"company": {"type": "string"}, "location": {"type": "string"},
                           "title": {"type": "string"}, "dates": {"type": "string"},
                           "facts": {"type": "array", "items": {"type": "string"}}}}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "education": {"type": "array", "items": {"type": "string"}},
        "extra_facts": {"type": "array", "items": {"type": "string"}},
    },
}

IMPORT_SYSTEM = """You convert a resume's extracted text into a structured profile.

COPY, DON'T WRITE. Every value must come from the resume text:
- Company names, job titles, locations and dates exactly as written.
- `facts`: that job's bullet points, one per item, kept as close to the original
  wording as possible (fix only broken line-wrapping or bullet characters).
- `skills`: tools, languages and skills the resume actually lists.
- `summary`: the resume's own summary/objective if it has one, else "".
- `extra_facts`: any sentence with a specific number or metric not already
  covered by a bullet (e.g. awards, team sizes). Usually empty.
- `education`: one line per degree/certification as written.
- Missing contact fields are "" - never guess an email, phone or URL.
Never add, embellish, infer or summarize beyond what the text says. Jobs in the
order the resume lists them (most recent first)."""

STOP = set("a an and are as at be by for from in into is of on or the to with using via "
           "across over under per our their my we i".split())


def pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def _words(s):
    return [w for w in re.findall(r"[a-z0-9+#.]+", s.lower()) if w not in STOP and len(w) > 1]


def unsupported(profile, text):
    """Items in a profile draft whose words mostly don't appear in the resume text."""
    have = set(_words(text))
    flat = re.sub(r"\s+", " ", text.lower())
    out = []

    def check(label, value, strict=False):
        value = (value or "").strip()
        if not value:
            return
        if strict:  # names, companies, dates: must appear (almost) verbatim
            if re.sub(r"\s+", " ", value.lower()) not in flat and \
                    not all(w in have for w in _words(value)):
                out.append(f"{label}: {value!r}")
            return
        words = _words(value)
        if words and sum(w in have for w in words) / len(words) < 0.8:
            out.append(f"{label}: {value!r}")

    c = profile.get("contact") or {}
    for k in ("first_name", "last_name", "email", "phone"):
        check(f"Contact {k}", c.get(k), strict=True)
    for e in profile.get("experience") or []:
        where = e.get("company") or "?"
        for k in ("company", "title", "dates"):
            check(f"{where} {k}", e.get(k), strict=True)
        for f in e.get("facts") or []:
            check(f"{where} bullet", f)
    for s in profile.get("skills") or []:
        check("Skill", s, strict=True)
    for f in profile.get("extra_facts") or []:
        check("Extra fact", f)
    return out


def import_resume(text, current, model):
    """Draft a profile from resume text. Keeps the user's targets (roles, dealbreakers...)."""
    if len(text) < 200:
        raise ValueError("Couldn't read enough text from that PDF (is it a scanned image?).")
    draft = chat_json(model, IMPORT_SYSTEM, "RESUME TEXT:\n\n" + text[:40000], IMPORT_SCHEMA,
                      name="profile_import")
    draft.pop("_usage", None)
    targets = (current or {}).get("targets") or DEFAULT_TARGETS
    ordered = {"contact": {**draft["contact"], "current_company":
                           (draft["experience"][0]["company"] if draft["experience"] else "")},
               "targets": targets, "summary": draft["summary"], "experience": draft["experience"],
               "skills": draft["skills"], "highlights": (current or {}).get("highlights") or [],
               "extra_facts": draft["extra_facts"], "education": draft["education"]}
    return dump(ordered), unsupported(ordered, text)


def dump(profile):
    return yaml.safe_dump(profile, sort_keys=False, allow_unicode=True, width=100)


def validate(profile_yaml):
    """Returns (profile, errors). Checks what scoring/tailoring rely on."""
    try:
        p = yaml.safe_load(profile_yaml or "")
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        return None, [f"Not valid YAML{where}: {getattr(e, 'problem', e)}"]
    if not isinstance(p, dict):
        return None, ["The profile must be a YAML mapping (key: value lines)."]
    errors = []
    c = p.get("contact")
    if not isinstance(c, dict):
        errors.append("contact: missing")
    else:
        for k in ("first_name", "last_name", "email"):
            if not str(c.get(k) or "").strip():
                errors.append(f"contact.{k} is required")
    exp = p.get("experience")
    if not isinstance(exp, list) or not exp:
        errors.append("experience: add at least one job")
    else:
        for i, e in enumerate(exp, 1):
            if not isinstance(e, dict):
                errors.append(f"experience #{i}: must be a mapping")
                continue
            for k in ("company", "title", "dates"):
                if not str(e.get(k) or "").strip():
                    errors.append(f"experience #{i} ({e.get('company') or '?'}): {k} is required")
            facts = e.get("facts")
            if not isinstance(facts, list) or not any(str(f).strip() for f in facts):
                errors.append(f"experience #{i} ({e.get('company') or '?'}): add at least one bullet under facts")
    skills = p.get("skills")
    if not isinstance(skills, list) or not skills:
        errors.append("skills: list at least one skill")
    for k in ("highlights", "extra_facts", "education"):
        if p.get(k) is not None and not isinstance(p.get(k), list):
            errors.append(f"{k}: must be a list")
    return (p if not errors else None), errors


DEFAULT_TARGETS = {
    "roles": ["EDIT ME: e.g. QA Engineer / SDET"],
    "location": "Remote, United States",
    "min_salary_usd": None,
    "dealbreakers": ["Requires relocation or on-site / hybrid attendance"],
    "preferences": [],
}
