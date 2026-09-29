"""Score a job against the profile with the configured LLM."""
import yaml

from .llm import chat_json

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "reasons", "concerns", "dealbreakers", "keywords"],
    "properties": {
        "score": {"type": "integer"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "dealbreakers": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = """You are a blunt technical recruiter screening jobs for ONE candidate.
Score 0-100 how strong a match the job is, using these weights:
- Role fit vs candidate target roles ........ 30
- Tech stack overlap (tools, languages) ..... 25
- Seniority / years-of-experience fit ....... 15
- Remote-in-US compatibility ................ 15
- Domain / company fit vs preferences ....... 10
- Compensation vs minimum (if both known) ... 5
Be strict: 85+ = would be a top candidate; 70-84 = solid, worth applying;
below 60 = poor fit. List the candidate's dealbreakers that this job clearly
violates in `dealbreakers` (empty if none). `keywords` = the 8-15 most important
skills/terms from the JOB posting, for resume tailoring. Reasons and concerns:
max 4 short items each."""


def score_job(job, profile, model):
    prof = {k: profile.get(k) for k in ("targets", "summary", "skills", "highlights")}
    prof["experience"] = [
        {"title": e["title"], "company": e["company"], "dates": e["dates"]}
        for e in profile.get("experience", [])
    ]
    user = (
        "CANDIDATE PROFILE (YAML):\n" + yaml.safe_dump(prof, sort_keys=False)
        + f"\n\nJOB: {job['title']} at {job['company']}\nLocation: {job['location']}\n\n"
        + (job["description"] or "")[:14000]
    )
    out = chat_json(model, SYSTEM, user, SCHEMA, name="job_score")
    out["score"] = max(0, min(100, int(out.get("score", 0))))
    return out
