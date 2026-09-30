"""Generate a tailored resume + cover letter, then check it for fabrication."""
import re

import yaml

from .llm import chat_json

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "experience", "skills", "cover_letter", "screening_answers"],
    "properties": {
        "summary": {"type": "string"},
        "experience": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["index", "bullets"],
                "properties": {"index": {"type": "integer"},
                               "bullets": {"type": "array", "items": {"type": "string"}}},
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "cover_letter": {"type": "string"},
        "screening_answers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["question", "answer"],
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
            },
        },
    },
}

SYSTEM = """You tailor a real candidate's resume to a specific job.

HARD RULES - violating any of these is a failure:
1. Use ONLY facts in the candidate profile. Never invent tools, metrics, numbers,
   team sizes, domains, certifications, or responsibilities. If the job wants
   something the candidate doesn't have, leave it out - do not imply it, and
   do not name tools the candidate lacks even when quoting the posting.
   Do not add details, scope, or context to a fact (e.g. "for web applications"
   must not become "for data-visualization tools"). Years of experience must be
   stated exactly as in the profile summary, never rounded up.
2. You may reword, reorder, merge and emphasize facts, and mirror the job's
   terminology ONLY where it truthfully describes the same work.
3. `experience`: one entry per profile job, `index` = its 0-based position in
   the profile list. The resume must fit on ONE page: 4-5 bullets for the 2
   most relevant jobs, 3 for the next one, exactly 2 for every other job
   (about 19 bullets total). Strong verbs, no first person, no fluff.
4. `skills`: 10-18 items chosen ONLY from the profile's skills list, most
   relevant to this job first. Copy spelling exactly.
5. `summary`: 2-3 sentences, specific to this role.
6. `cover_letter`: 150-220 words, plain text, addressed "Dear Hiring Team,".
   Mention the company by name and 1-2 concrete things from the posting.
   Sign as the candidate's full name. No cliches ("I am thrilled", "passionate").
7. `screening_answers`: short, truthful answers (<=80 words) for: "Why are you
   interested in this role?", "Describe your most relevant experience for this
   role.", and up to 2 more questions this posting is likely to ask.
   NEVER answer work authorization, sponsorship, salary, EEO/demographic or
   legal questions - skip them entirely."""


def tailor_job(job, profile, score, model):
    prof = {k: profile.get(k) for k in
            ("contact", "summary", "experience", "skills", "highlights", "extra_facts")}
    prof["contact"] = {k: prof["contact"].get(k) for k in ("first_name", "last_name")}
    user = (
        "CANDIDATE PROFILE (YAML):\n" + yaml.safe_dump(prof, sort_keys=False)
        + f"\n\nKEY TERMS FROM SCREENING: {', '.join(score.get('keywords', []))}"
        + f"\n\nJOB: {job['title']} at {job['company']}\nLocation: {job['location']}\n\n"
        + (job["description"] or "")[:14000]
    )
    return chat_json(model, SYSTEM, user, SCHEMA, name="tailored_packet")


def _profile_text(profile):
    return yaml.safe_dump(profile, sort_keys=False).lower()


def validate(packet, profile):
    """Enforce guardrails in code (don't just trust the prompt).

    Returns (clean_packet, warnings). Invented skills are removed; suspicious
    bullets are kept but flagged for your review.
    """
    warnings = []
    exp = profile.get("experience", [])
    ptext = _profile_text(profile)
    skills = profile.get("skills", [])
    skill_lc = {s.lower(): s for s in skills}

    # 1. skills must come from the profile
    kept = []
    for s in packet.get("skills", []):
        if s.lower() in skill_lc:
            if skill_lc[s.lower()] not in kept:
                kept.append(skill_lc[s.lower()])
        else:
            warnings.append(f"Removed skill not in profile: {s!r}")
    packet["skills"] = kept

    # 2. experience indices must be valid; fill any missing job with original facts
    by_idx = {}
    for e in packet.get("experience", []):
        i = e.get("index")
        if isinstance(i, int) and 0 <= i < len(exp) and i not in by_idx:
            by_idx[i] = [b.strip() for b in e.get("bullets", []) if b.strip()]
        else:
            warnings.append(f"Dropped experience entry with bad index {i!r}")
    for i, e in enumerate(exp):
        if not by_idx.get(i):
            by_idx[i] = list(e.get("facts", []))[:3]
            warnings.append(f"Model skipped {e['company']}; used original bullets")
    packet["experience"] = [{"index": i, "bullets": by_idx[i]} for i in range(len(exp))]

    # 3. flag numbers and known-tool names that aren't in the profile
    texts = [packet.get("summary", ""), packet.get("cover_letter", "")]
    texts += [b for e in packet["experience"] for b in e["bullets"]]
    texts += [a.get("answer", "") for a in packet.get("screening_answers", [])]
    for t in texts:
        for num in re.findall(r"\d[\d,.]*\s*%|\$\s?\d[\d,.]*[kKmM]?|\b\d{2,}[\d,]*\+?", t):
            n = num.strip()
            if n.rstrip("+%").replace(",", "") not in ptext.replace(",", ""):
                warnings.append(f"Number not found in profile: {n!r} in: {t[:90]!r}")
        for m in re.finditer(r"(\d+)\s*\+?\s*(?:years|yrs)", t, re.I):
            if not re.search(rf"\b{m.group(1)}\+?\s*(?:years|yrs)", ptext):
                warnings.append(f"Years-of-experience claim not in profile: {m.group(0)!r}")
        for tool in COMMON_TOOLS:
            if re.search(rf"(?<![\w]){re.escape(tool)}(?![\w])", t, re.I) and tool.lower() not in ptext:
                warnings.append(f"Tool not in profile: {tool!r} in: {t[:90]!r}")

    # 4. never let legal/eligibility answers through
    safe = []
    for qa in packet.get("screening_answers", []):
        if re.search(r"authori[sz]|sponsor|visa|citizen|salary|compensation|gender|race|"
                     r"ethnic|veteran|disabilit|criminal|background check", qa.get("question", ""), re.I):
            warnings.append(f"Removed sensitive screening question: {qa['question']!r}")
        else:
            safe.append(qa)
    packet["screening_answers"] = safe
    return packet, sorted(set(warnings), key=warnings.index)


COMMON_TOOLS = [
    "Cypress", "WebdriverIO", "Espresso", "XCUITest", "Detox", "Maestro", "Robot Framework",
    "Cucumber", "Gherkin", "JUnit", "TestNG", "pytest", "Jest", "Mocha", "k6", "JMeter",
    "Gatling", "Locust", "LoadRunner", "Kubernetes", "Docker", "Terraform", "Ansible",
    "AWS", "GCP", "Azure", "GitHub Actions", "GitLab CI", "CircleCI", "Buildkite",
    "BrowserStack", "Sauce Labs", "LambdaTest", "Golang", "C#", ".NET", "Kotlin",
    "Swift", "Rust", "Scala", "GraphQL", "Kafka", "Snowflake", "Datadog", "Grafana",
    "Splunk", "ISTQB", "Zephyr", "Xray", "qTest", "SOC 2", "HIPAA", "PCI",
    "Ruby", "MySQL", "PostgreSQL", "MongoDB", "Redis", "Linux", "Node.js", "Angular",
    "Vue", "C++", "PHP", "Perl", "Groovy", "Katalon", "Ranorex", "UFT", "SoapUI",
    "REST Assured", "Karate", "Selenium Grid", "Appvance", "FDA", "ISO 13485",
    "IEC 62304", "ISO 14971", "DHF", "GxP", "Salesforce", "SAP", "Workday",
]
