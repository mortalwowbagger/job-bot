"""Free relevance pre-ranking: decides which queued jobs get (paid) LLM scoring first.

Compares words from the candidate's profile (skills, target roles, past titles,
summary) with each job's title and description. No API calls. It only orders the
queue; the LLM score still decides what's a match.
"""
import math
import re
from collections import Counter

STOP = set("""a an and are as at be by for from in into is it of on or the to with our we you your
 will this that who work team role job jobs experience years year across within including using
 able strong skills new help plus etc about all also can more other their they us""".split())


def words(text):
    return [w for w in re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", (text or "").lower())
            if w not in STOP and len(w) > 1]


def profile_terms(profile):
    """Weighted terms: skills and target roles count most, past titles next, summary least."""
    t = Counter()
    for s in profile.get("skills") or []:
        for w in words(s):
            t[w] += 3
    for r in (profile.get("targets") or {}).get("roles") or []:
        for w in words(r):
            t[w] += 3
    for e in profile.get("experience") or []:
        for w in words(e.get("title")):
            t[w] += 2
    for w in words(profile.get("summary")):
        t[w] += 1
    return t


def relevance(job, terms):
    title = Counter(words(job.get("title")))
    desc = Counter(words((job.get("description") or "")[:6000]))
    hit = sum(wt * (3 * (w in title) + min(desc[w], 3)) for w, wt in terms.items())
    return hit / math.sqrt(10 + sum(desc.values()) / 50)


def order(jobs, profile):
    """Best candidates first (ties: newest first)."""
    terms = profile_terms(profile)
    return sorted(jobs, key=lambda j: (-relevance(j, terms), j.get("created_at") or ""), reverse=False)
