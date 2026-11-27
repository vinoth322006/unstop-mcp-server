"""Eligibility check: compares the user's profile with an opportunity's published eligibility rules.

Unstop's rules look like ``{"sector": ["students"], "engineering": [{"course": "btech", "specialization": [...],
"passoutYear": ["all"]}], "studentPassoutYearsSelected": [2026, 2027]}``. We evaluate what the profile can answer
and say "unclear" for the rest. The organiser's decision on unstop.com is always final.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from unstop_mcp.models import IST, OpportunityDetail, Profile

Verdict = Literal["likely_eligible", "likely_not_eligible", "unclear"]
CheckResult = Literal["pass", "fail", "unknown"]

_COURSE_GROUPS = ("engineering", "bSchools", "arts", "medicine", "law", "others")


class Check(BaseModel):
    rule: str
    result: CheckResult
    detail: str


class Eligibility(BaseModel):
    opportunity_id: int
    opportunity: str
    url: str | None = None
    verdict: Verdict
    summary: str
    checks: list[Check] = Field(default_factory=list)
    your_profile: dict[str, Any] = Field(default_factory=dict)
    note: str = "Based on your Unstop profile and the published rules; the organiser's decision on unstop.com is final."


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def _has_all(values: Any) -> bool:
    return not values or any(_norm(v) == "all" for v in (values if isinstance(values, list) else [values]))


def user_status(p: Profile, now: datetime | None = None) -> str:
    """student / fresher / professional, derived from graduation year."""
    year = (now or datetime.now(IST)).year
    if p.graduation_year is None:
        return "unknown"
    if p.graduation_year >= year:
        return "student"
    return "fresher" if p.graduation_year >= year - 1 else "professional"


def check_eligibility(profile: Profile, opp: OpportunityDetail, now: datetime | None = None) -> Eligibility:
    rules = opp.eligibility or {}
    status = user_status(profile, now)
    grad = profile.graduation_year
    spec = _norm(profile.specialization or "")
    checks: list[Check] = []

    # 1) Who may apply: students / freshers / working professionals / school students
    sectors = [_norm(s) for s in rules.get("sector") or []]
    if sectors:
        wanted = {"student": "students", "fresher": "fresher", "professional": "corporates"}.get(status)
        accepted = {wanted} if wanted else set()
        year = (now or datetime.now(IST)).year
        if status == "student" and grad is not None and grad <= year + 1:
            accepted.add("fresher")  # final-year students are usually welcome in fresher listings
        if wanted is None:
            checks.append(Check(rule="Open to", result="unknown", detail=f"Open to: {', '.join(sectors)}. "
                                "Add your graduation year to your Unstop profile to check this."))
        elif accepted & set(sectors):
            checks.append(Check(rule="Open to", result="pass", detail=f"Open to {', '.join(sectors)}; you are a {status}."))
        else:
            checks.append(Check(rule="Open to", result="fail", detail=f"Open to {', '.join(sectors)} only; your "
                                f"profile says you are a {status}."))

    # 2) Graduation (pass-out) year limits
    for key, label in (("studentPassoutYearsSelected", "Student graduation year"),
                       ("fresherPassoutYearsSelected", "Fresher graduation year")):
        years = rules.get(key)
        if years and not _has_all(years):
            allowed = sorted({int(y) for y in years if str(y).isdigit()})
            if grad is None:
                checks.append(Check(rule=label, result="unknown", detail=f"Allowed: {allowed}. Your graduation year "
                                    "is not on your profile."))
            elif (key.startswith("student") and status != "student") or (key.startswith("fresher") and status != "fresher"):
                continue  # rule applies to the other group
            else:
                ok = grad in allowed
                checks.append(Check(rule=label, result="pass" if ok else "fail",
                                    detail=f"Allowed: {allowed}; yours: {grad}."))

    # 3) Course / specialization lists (engineering, MBA, arts, ...)
    entries = [e for g in _COURSE_GROUPS for e in (rules.get(g) or []) if isinstance(e, dict)]
    if entries:
        if not spec:
            checks.append(Check(rule="Course", result="unknown", detail="Your specialization is not on your profile."))
        else:
            matched = None
            for e in entries:
                specs = e.get("specialization") or []
                if _has_all(specs) or any(_norm(s) == spec or spec in _norm(s) or _norm(s) in spec for s in specs):
                    years = e.get("passoutYear") or []
                    if _has_all(years) or (grad is not None and str(grad) in {str(y) for y in years}):
                        matched = e
                        break
            if matched:
                checks.append(Check(rule="Course", result="pass", detail=f"Your specialization ({profile.specialization}) "
                                    f"matches the allowed {matched.get('course', 'courses')} list."))
            else:
                courses = sorted({str(e.get("course")) for e in entries if e.get("course")})
                checks.append(Check(rule="Course", result="fail", detail=f"Your specialization ({profile.specialization}) "
                                    f"is not in the allowed list for {', '.join(courses) or 'listed courses'}."))

    # 4) Work-experience requirements (only meaningful for professionals)
    exp = rules.get("experience")
    if exp and not _has_all(exp):
        result: CheckResult = "fail" if status == "student" else "unknown"
        checks.append(Check(rule="Experience", result=result, detail=f"Asks for experience: {', '.join(map(str, exp))}."))

    # 5) Registration still open?
    if opp.registration_open is False:
        checks.append(Check(rule="Registration", result="fail", detail="Registration is closed."))

    fails = [c for c in checks if c.result == "fail"]
    unknown = [c for c in checks if c.result == "unknown"]
    if fails:
        verdict: Verdict = "likely_not_eligible"
        summary = "Probably not eligible: " + "; ".join(c.detail for c in fails)
    elif unknown or not checks:
        verdict = "unclear"
        summary = ("No specific rules published; check the listing." if not checks
                   else "Can't fully tell: " + "; ".join(c.detail for c in unknown))
    else:
        verdict = "likely_eligible"
        summary = "Looks eligible: every published rule matches your profile."
    return Eligibility(
        opportunity_id=opp.id, opportunity=opp.title, url=opp.url, verdict=verdict, summary=summary, checks=checks,
        your_profile={"status": status, "graduation_year": grad, "specialization": profile.specialization},
    )
