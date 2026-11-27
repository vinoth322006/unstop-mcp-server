"""Team management: view your team, suggest past teammates, invite by email, and handle invitations/requests.

Endpoints mirror the unstop.com registration page:
  GET  /api/registration/restricted/{opp}/                   your team (members, limits, invite permission)
  GET  /api/registration/previousTeams-player/{opp}/{team}   people you've teamed with before
  GET  /api/registration/team/target/getAll/invitation/{opp} invitations your team sent
  GET  /api/registration/team/source/getAll/invitation/{opp} invitations you received
  GET  /api/registration/team/target/getAll/request/{opp}    requests to join your team
  GET  /api/registration/user/getAll/request/{opp}           your requests to join other teams
  POST /api/registration/send-invitation-request-by-email    {"targetTeamId", "email"}
  POST /api/registration/invitation/team/delete/{id}         cancel an invitation you sent
  POST /api/registration/invitation/{accept|decline}/{id}    answer an invitation
  POST /api/registration/request/{accept|decline}/{id}       answer a join request
  DELETE /api/registration/delete/player/{opp}/{player}      remove a member / leave a team

Privacy: Unstop returns full user records (including phone numbers) for teammates. Only names, organisation and
course leave this module; emails are used server-side to send invites and are never returned to the model.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

INVITE_STATUS = {0: "pending", 1: "accepted", 2: "declined", 3: "expired", 4: "cancelled"}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


class TeamMember(BaseModel):
    player_id: int | None = None
    name: str
    is_leader: bool = False
    organisation: str | None = None
    course: str | None = None
    graduation_year: int | None = None
    is_you: bool = False


class Team(BaseModel):
    opportunity_id: int
    opportunity: str | None = None
    url: str | None = None
    registered: bool
    team_id: int | None = None
    team_name: str | None = None
    registration_complete: bool | None = None
    team_valid: bool | None = None
    you_are_leader: bool = False
    members: list[TeamMember] = Field(default_factory=list)
    max_team_size: int | None = None
    min_team_size: int | None = None
    spots_left: int | None = None
    invites_allowed: bool = False
    message: str | None = None


class TeammateSuggestion(BaseModel):
    teammate_id: int = Field(description="Pass to invite_teammate as teammate_id")
    name: str
    organisation: str | None = None
    course: str | None = None
    graduation_year: int | None = None


class Invitation(BaseModel):
    id: int
    direction: str = Field(description="sent / received / request_received / request_sent")
    status: str
    team_name: str | None = None
    person: str | None = Field(default=None, description="The other side (name, or masked email)")
    at: str | None = None


class TeamInbox(BaseModel):
    opportunity_id: int
    invitations_sent: list[Invitation] = Field(default_factory=list)
    invitations_received: list[Invitation] = Field(default_factory=list)
    join_requests_received: list[Invitation] = Field(default_factory=list)
    join_requests_sent: list[Invitation] = Field(default_factory=list)


class TeamActionResult(BaseModel):
    ok: bool
    message: str
    opportunity_id: int | None = None
    url: str | None = None


# ---------------------------------------------------------------- helpers

def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    user, _, domain = email.partition("@")
    return f"{user[:2]}***@{domain}"


def _int(v: Any) -> int | None:
    try:
        return int(str(v)) if v is not None and str(v).lstrip("-").isdigit() else None
    except ValueError:
        return None


def _name(p: dict[str, Any]) -> str:
    return (p.get("name") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")])) or "Unknown").strip()


def _org(p: dict[str, Any]) -> str | None:
    org = p.get("organisation")
    return (org.get("name") if isinstance(org, dict) else org) or p.get("organisation_name")


def team_from_boot(boot: dict[str, Any], opportunity_id: int, user_id: int | None) -> Team:
    req = boot.get("regnRequirements") or {}
    team = boot.get("oRegisteredTeam") if isinstance(boot.get("oRegisteredTeam"), dict) else None
    max_size, min_size = _int(req.get("max_team_size")), _int(req.get("min_team_size"))
    if not team:
        return Team(opportunity_id=opportunity_id, registered=False, max_team_size=max_size, min_team_size=min_size,
                    message="You are not registered for this one yet. Use prepare_registration first.")
    members: list[TeamMember] = []
    leader_is_you = False
    for p in team.get("players") or []:
        if not isinstance(p, dict):
            continue
        is_leader = str(p.get("player_type")) == "1"
        is_you = user_id is not None and _int(p.get("user_id")) == user_id
        leader_is_you = leader_is_you or (is_leader and is_you)
        members.append(TeamMember(player_id=_int(p.get("id")), name=_name(p), is_leader=is_leader,
                                  organisation=_org(p), course=p.get("course_specialization"),
                                  graduation_year=_int(p.get("passing_out_year")), is_you=is_you))
    regi = team.get("regi_status")
    spots = max(0, max_size - len(members)) if max_size else None
    invites = bool(boot.get("invitations_allowed")) and str(team.get("invite_allowed", "1")) == "1"
    return Team(
        opportunity_id=opportunity_id, registered=True, team_id=_int(team.get("id")), team_name=team.get("team_name"),
        registration_complete=(regi == "complete") if regi else None,
        team_valid=str(team.get("isTeamValid")) == "1" if team.get("isTeamValid") is not None else None,
        you_are_leader=leader_is_you, members=members, max_team_size=max_size, min_team_size=min_size,
        spots_left=spots, invites_allowed=invites and bool(spots),
    )


def suggestion(raw: dict[str, Any]) -> TeammateSuggestion | None:
    tid = _int(raw.get("id"))
    if tid is None:
        return None
    return TeammateSuggestion(teammate_id=tid, name=_name(raw), organisation=_org(raw),
                              course=raw.get("course_specialization"), graduation_year=_int(raw.get("passing_out_year")))


def invitation(raw: dict[str, Any], direction: str) -> Invitation | None:
    iid = _int(raw.get("id"))
    if iid is None:
        return None
    code = _int(raw.get("status"))
    status = INVITE_STATUS.get(code, f"unknown ({code})") if code is not None else "unknown"
    team: dict[str, Any] = next((raw[k] for k in ("target_team", "source_team", "team")
                                 if isinstance(raw.get(k), dict)), {})
    other: dict[str, Any] = next((raw[k] for k in ("source_player", "target_player", "player", "user")
                                  if isinstance(raw.get(k), dict)), {})
    person = _name(other) if other else None
    if (not person or person == "Unknown") and raw.get("email"):
        person = mask_email(str(raw["email"]))
    return Invitation(id=iid, direction=direction, status=status, team_name=team.get("team_name"),
                      person=person, at=raw.get("created_at"))


def list_from(payload: Any, *keys: str) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return [x for x in data[k] if isinstance(x, dict)]
    return []
