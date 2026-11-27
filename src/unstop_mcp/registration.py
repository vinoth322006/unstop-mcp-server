"""Register for Unstop opportunities, safely.

Only "simple" registrations are automated: free, no custom questions, no identity/face/audio verification, no
proctoring consent, registration on unstop.com itself, and no minimum team size above one. Everything else returns a
clear reason plus the link, so the user finishes on unstop.com.

Flow (mirrors the unstop.com registration page):
  1. GET  /api/registration/restricted/{id}/       page bootstrap: gates, existing team, profile pre-fill
  2. POST /api/registration/team/{id}/create       {"team": {team_name, players: [player]}, "subscription": 0}
  3. DELETE /api/registration/cancel/{id}/{team}   undo

Registering is two-step: ``prepare`` evaluates every gate and returns an HMAC-signed, 10-minute confirmation token
bound to (tenant, opportunity). ``register`` requires that token and re-checks the gates before posting.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from pydantic import BaseModel, Field

from unstop_mcp.errors import InvalidInput

TOKEN_TTL = 600
_PROCESS_KEY = secrets.token_bytes(32)  # tokens are only valid inside the server process that issued them


class RegistrationPlan(BaseModel):
    opportunity_id: int
    title: str
    url: str | None = None
    can_register: bool
    already_registered: bool = False
    blockers: list[str] = Field(default_factory=list, description="Why it can't be done automatically")
    notes: list[str] = Field(default_factory=list)
    will_submit: dict[str, Any] = Field(default_factory=dict, description="Exactly what will be sent to Unstop")
    confirmation_token: str | None = Field(
        default=None, description="Pass to register() after the user confirms. Valid for 10 minutes.")
    next_step: str


class RegistrationResult(BaseModel):
    opportunity_id: int
    title: str
    registered: bool
    team_id: int | None = None
    registration_id: str | None = None
    complete: bool | None = Field(default=None, description="False = Unstop still needs something (e.g. teammates)")
    message: str
    url: str | None = None


# ---------------------------------------------------------------- confirmation tokens

def make_token(tenant: str, opportunity_id: int, now: float | None = None) -> str:
    exp = int((now or time.time()) + TOKEN_TTL)
    sig = hmac.new(_PROCESS_KEY, f"{tenant}|{opportunity_id}|{exp}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{exp}.{sig}"


def check_token(token: str, tenant: str, opportunity_id: int, now: float | None = None) -> None:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError) as exc:
        raise InvalidInput("Invalid confirmation token. Call prepare_registration first.") from exc
    expected = hmac.new(_PROCESS_KEY, f"{tenant}|{opportunity_id}|{exp}".encode(), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(sig, expected):
        raise InvalidInput("This confirmation token is for a different opportunity or account. "
                           "Call prepare_registration again.")
    if (now or time.time()) > exp:
        raise InvalidInput("The confirmation expired (10 minutes). Call prepare_registration again.")


# ---------------------------------------------------------------- gates

def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "none", "null")
    return bool(v)


def _extended_form_required(form: Any) -> bool:
    """player_extended_form looks like {"resume_field": {"enabled": false, "customFields": [...]}, ...}."""
    if not isinstance(form, dict):
        return _truthy(form)
    for section in form.values():
        if isinstance(section, dict):
            if _truthy(section.get("enabled")):
                return True
            for field in section.get("customFields") or []:
                if isinstance(field, dict) and str(field.get("mandatory")) == "1":
                    return True
    return False


def evaluate(boot: dict[str, Any], profile: dict[str, Any], opp: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (blockers, notes) for automatic registration.

    ``boot``   = data from /api/registration/restricted/{id}/
    ``profile``= full /api/user/profile data
    ``opp``    = raw /api/public/competition/{id} competition
    """
    req = boot.get("regnRequirements") or {}
    blockers: list[str] = []
    notes: list[str] = []

    if boot.get("user_restricted_to_register"):
        blockers.append(str(boot.get("user_restricted_to_register_message") or "Unstop has restricted you from "
                                                                                  "registering for this one."))
    if opp.get("regn_url"):
        blockers.append("Registration happens on the organiser's own website.")
    if not _truthy(opp.get("regn_open", 1)) or str(opp.get("status", "")).upper() in ("FINISHED", "EXPIRED", "CLOSED"):
        blockers.append("Registration is closed.")
    if _truthy(boot.get("linkedPayment")) or _truthy(req.get("enable_payment")) or _truthy(req.get("reg_amount")) \
            or _truthy(opp.get("paid")) or _truthy(opp.get("isPaid")):
        blockers.append("It has a registration fee. Pay and register yourself on unstop.com.")
    if _truthy(req.get("extendRegForm")) or _truthy(req.get("extendedFormData")) or _truthy(boot.get("extendedForm")) \
            or _truthy(req.get("extend_basic_form")) or _extended_form_required(req.get("player_extended_form")):
        blockers.append("It asks extra questions or documents (custom form / resume). Fill them on unstop.com.")
    checks = {
        "consent_needed": "It needs you to accept the organiser's consent terms.",
        "verified_aadhaar": "It needs Aadhaar verification.",
        "verified_aadhaar_face": "It needs face verification.",
        "verified_aadhaar_face_via_digilocker": "It needs DigiLocker face verification.",
        "verified_driving_licence_face": "It needs driving-licence verification.",
        "audio_capture": "It needs an audio check.",
    }
    for key, why in checks.items():
        if _truthy(req.get(key)):
            blockers.append(why)
    if req.get("proctoring") and req.get("proctoring") != {}:
        blockers.append("It is proctored and needs your consent and camera setup.")
    if _truthy(boot.get("faceVerfication")) or _truthy(boot.get("audio_capture_enable")):
        blockers.append("It needs a face or audio check.")

    min_team = int(req.get("min_team_size") or 1)
    max_team = int(req.get("max_team_size") or 1)
    if min_team > 1:
        blockers.append(f"It needs a team of at least {min_team}. Form the team on unstop.com.")
    elif max_team > 1:
        notes.append(f"Teams of up to {max_team} are allowed; you'll be registered as a team of one and can invite "
                     "teammates later on unstop.com.")

    if _truthy(req.get("verified_mobile")) and not profile.get("mobile_verified_at"):
        blockers.append("It needs a verified mobile number. Verify it in your Unstop profile first.")
    if _truthy(req.get("verified_email")) and not profile.get("email_verified_at"):
        blockers.append("It needs a verified email address. Verify it in your Unstop profile first.")
    core = req.get("core_req_fields") or {}
    needed = {"name": "name", "email": "email", "mobile_no": "mobile", "gender": "gender", "organization": "organisation"}
    for field, key in needed.items():
        rule = core.get(field) if isinstance(core, dict) else None
        if isinstance(rule, dict) and (_truthy(rule.get("mandatory")) or _truthy(rule.get("required"))) \
                and not profile.get(key):
            blockers.append(f"Your Unstop profile is missing your {key}, which this registration requires.")
    return blockers, notes


# ---------------------------------------------------------------- payload

_PLAYER_FIELDS = ("first_name", "last_name", "email", "mobile", "gender", "user_type", "course_pursuing",
                  "course_stream", "course_specialization", "course_programme", "course_duration", "passing_out_year",
                  "study_year", "designation", "work_experience", "differently_abled", "city_id", "others", "skills")


def build_payload(boot: dict[str, Any], profile: dict[str, Any], team_name: str | None) -> dict[str, Any]:
    """Build the same body the unstop.com form submits, from the page's own pre-fill plus the full profile."""
    prefill: dict[str, Any] = boot["user"] if isinstance(boot.get("user"), dict) else {}
    player: dict[str, Any] = {"id": 0, "user_id": profile.get("id"), "player_type": 1, "unsaved": True,
                              "subscription": 0}
    for key in _PLAYER_FIELDS:
        value = prefill.get(key) if prefill.get(key) not in (None, "") else profile.get(key)
        if value not in (None, ""):
            player[key] = value
    name = profile.get("name") or " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
    player["name"] = name
    org = prefill.get("organisation") if isinstance(prefill.get("organisation"), dict) else profile.get("organisation")
    if isinstance(org, dict) and org.get("id"):
        player["organisation"] = {"id": org["id"], "name": org.get("name")}
        player["organisation_id"] = org["id"]
    return {
        "team": {"team_name": team_name, "players": [player], "subscription": 0,
                 "formValidStatus": True, "formValidMsg": ""},
        "subscription": 0,  # never opt the user into newsletters
    }


def summary_of(payload: dict[str, Any]) -> dict[str, Any]:
    """What the user should see before confirming (no internal ids)."""
    p = payload["team"]["players"][0]
    org = p.get("organisation") or {}
    return {
        "team_name": payload["team"]["team_name"] or "(set by Unstop: your username)",
        "name": p.get("name"),
        "email": p.get("email"),
        "mobile": (str(p.get("mobile"))[:2] + "******" + str(p.get("mobile"))[-2:]) if p.get("mobile") else None,
        "gender": p.get("gender"),
        "organisation": org.get("name"),
        "course": p.get("course_specialization"),
        "graduation_year": p.get("passing_out_year"),
        "newsletter_subscription": False,
    }
