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
    if name == "profile_import":
        return {
            "contact": {"first_name": "Alex", "last_name": "Example", "email": "alex.example@example.com",
                        "phone": "(555) 010-0000", "location": "Denver, CO", "linkedin": "", "github": ""},
            "summary": "QA engineer with 9 years of test automation.",
            "experience": [{"company": "Northwind Bank", "location": "Denver, CO",
                            "title": "QA Automation Engineer", "dates": "March 2026 - Present",
                            "facts": ["Develop Appium tests in Java for iOS and Android.",
                                      "Led a migration to Kubernetes."]}],  # 2nd bullet isn't in the PDF
            "skills": ["Appium", "Java", "Kubernetes"],
            "education": [], "extra_facts": [],
        }
    raise ValueError(name)
