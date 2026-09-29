"""Deterministic stand-in for the LLM, used when JOBBOT_FAKE_LLM=1."""


def respond(name, user):
    if name == "job_score":
        good = any(k in user.lower() for k in ("playwright", "appium", "sdet", "automation"))
        return {"score": 82 if good else 40,
                "reasons": ["Automation stack overlaps with profile"] if good else ["Weak overlap"],
                "concerns": [], "dealbreakers": [],
                "keywords": ["Playwright", "CI/CD", "Kubernetes"]}
    if name == "tailored_packet":
        return {
            "summary": "Senior QA automation engineer with 9 years building Playwright and Appium frameworks.",
            "experience": [
                {"index": 0, "bullets": ["Maintain Appium + Java mobile suites for iOS and Android.",
                                         "Stabilize automation in CI environments."]},
                {"index": 1, "bullets": ["Built a modular Playwright framework wired into CI/CD.",
                                         "Cut regression time by 80% with Kubernetes."]},
            ],
            "skills": ["Playwright", "Appium", "Kubernetes", "Python", "CI/CD"],
            "cover_letter": "Dear Hiring Team,\n\nI'd like to apply...\n\nBest,\nAlex Example",
            "screening_answers": [{"question": "Why this role?", "answer": "Strong overlap."}],
        }
    raise ValueError(name)
