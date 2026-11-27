"""The compact, LLM-friendly shapes every tool returns (pydantic models)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

OPPORTUNITY_TYPES: dict[str, str] = {
    "all": "Everything",
    "hackathons": "Hackathons and coding challenges",
    "competitions": "Competitions (case studies, quizzes, innovation challenges, ...)",
    "jobs": "Jobs",
    "internships": "Internships",
    "quizzes": "Quizzes",
    "scholarships": "Scholarships",
    "workshops": "Workshops and webinars",
    "conferences": "Conferences",
    "cultural": "Cultural events",
}


REGISTRATION_TYPES = ["competitions", "hackathons", "quizzes", "scholarships", "internships", "jobs",
                      "workshops", "conferences", "cultural"]


class Prize(BaseModel):
    rank: str | None = None
    cash: float | None = None
    currency: str | None = None
    details: str | None = None


class Round(BaseModel):
    id: int | None = None
    title: str
    start: str | None = None
    end: str | None = None
    kind: str | None = None


class OpportunitySummary(BaseModel):
    id: int
    title: str
    type: str | None = None
    subtype: str | None = None
    organisation: str | None = None
    organisation_id: int | None = None
    url: str | None = None
    short_url: str | None = None
    status: str | None = None
    registration_open: bool | None = None
    registration_deadline: str | None = None
    time_left: str | None = None
    region: str | None = Field(default=None, description="online / offline")
    locations: list[str] = Field(default_factory=list)
    team_size: str | None = None
    paid_entry: bool | None = None
    total_cash_prize: float | None = None
    prize_currency: str | None = None
    registrations: int | None = None
    views: int | None = None
    skills: list[str] = Field(default_factory=list)
    eligible: list[str] = Field(default_factory=list)


class OpportunityDetail(OpportunitySummary):
    start_date: str | None = None
    end_date: str | None = None
    registration_starts: str | None = None
    prizes: list[Prize] = Field(default_factory=list)
    rounds: list[Round] = Field(default_factory=list)
    eligibility: dict[str, Any] = Field(default_factory=dict)
    job: dict[str, Any] | None = None
    external_registration_url: str | None = None
    description: str = ""


class SearchResult(BaseModel):
    total: int
    page: int
    last_page: int
    per_page: int
    results: list[OpportunitySummary]


class Profile(BaseModel):
    id: int | None = None
    name: str | None = None
    username: str | None = None
    email: str | None = None
    gender: str | None = None
    country: str | None = None
    user_category: str | None = None
    specialization: str | None = None
    study_year: int | None = None
    course_start_year: int | None = None
    graduation_year: int | None = None
    summary: str | None = None
    profile_completion_percent: int | None = None
    coins: int | None = None
    profile_url: str | None = None


class Registration(BaseModel):
    id: int
    title: str
    type: str | None = None
    opportunity_status: str | None = Field(default=None, description="LIVE / FINISHED / ...")
    url: str | None = None
    organisation: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    registration_deadline: str | None = None
    team_name: str | None = None
    registration_complete: bool | None = Field(default=None, description="False = form or team still incomplete")
    team_valid: bool | None = None
    team_members: int | None = None
    max_team_size: int | None = None
    rejected_in_a_round: bool | None = None
    registered_at: str | None = None


class RegistrationPage(BaseModel):
    total: int
    page: int
    last_page: int
    items: list[Registration]


class WatchlistPage(BaseModel):
    total: int
    page: int
    last_page: int
    items: list[OpportunitySummary]


class Certificate(BaseModel):
    id: int
    cert_id: str | None = None
    kind: str | None = Field(default=None, description="winners / opportunity-participation / merit / ...")
    event: str | None = None
    parent_event: str | None = None
    organiser: str | None = None
    round: str | None = None
    achievement: str | None = None
    team: str | None = None
    issued_at: str | None = None
    url: str | None = None


class CertificatePage(BaseModel):
    total: int
    page: int
    last_page: int
    items: list[Certificate]


class RoundStatus(BaseModel):
    order: int | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    round_status: str | None = None
    registered: bool | None = None
    participated: bool | None = None
    can_play_now: bool | None = None
    note: str | None = None


class Participation(BaseModel):
    opportunity_id: int
    registered: bool
    title: str | None = None
    url: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    registration_id: str | None = None
    registration_complete: bool | None = None
    rounds: list[RoundStatus] = Field(default_factory=list)


DeadlineKind = Literal["round_starts", "round_ends", "registration_closes"]


DeadlineSource = Literal["my_round", "incomplete_registration", "watchlist"]


class DeadlineItem(BaseModel):
    when: str = Field(description="ISO-8601 with IST offset")
    days_left: float
    kind: DeadlineKind
    what: str
    action: str = Field(description="What the user should do")
    opportunity_id: int | None = None
    opportunity: str
    url: str | None = None
    source: DeadlineSource


class Deadlines(BaseModel):
    generated_at: str
    window_days: int
    total: int
    items: list[DeadlineItem]
    partial_errors: list[str] = Field(default_factory=list, description="Sources that failed; results may be partial")


class Comparison(BaseModel):
    items: list[OpportunityDetail]
    errors: dict[str, str] = Field(default_factory=dict)


class Snapshot(BaseModel):
    """One-glance overview of the user's Unstop activity."""

    name: str | None = None
    status: str | None = Field(default=None, description="student / fresher / professional")
    graduation_year: int | None = None
    profile_completion_percent: int | None = None
    total_registrations: int = 0
    registrations_by_type: dict[str, int] = Field(default_factory=dict)
    certificates_total: int = 0
    wins: int = Field(default=0, description="Winner/merit certificates")
    certificates_by_kind: dict[str, int] = Field(default_factory=dict)
    watchlist_total: int = 0
    coins: int | None = None
    upcoming_deadlines: int = 0
    next_deadline: DeadlineItem | None = None
    partial_errors: list[str] = Field(default_factory=list)


class SearchAlert(BaseModel):
    name: str
    query: str | None = None
    opportunity_type: str = "all"
    first_check: bool = Field(description="True when this run set the baseline")
    new_count: int
    new: list[OpportunitySummary]


class AlertsReport(BaseModel):
    checked_at: str
    total_new: int
    searches: list[SearchAlert]
    errors: dict[str, str] = Field(default_factory=dict)


class Notification(BaseModel):
    id: str
    kind: str = Field(description="team_registration / registration_success / registration_cancelled / result / "
                                  "rewards / other")
    text: str
    url: str | None = None
    at: str | None = None
    read: bool


class NotificationPage(BaseModel):
    page: int
    has_more: bool
    unread_on_page: int
    items: list[Notification]


class Course(BaseModel):
    id: int
    title: str
    progress_percent: int | None = None
    modules: int | None = None
    enrolled_on: str | None = None
    completed_on: str | None = None
    certificate_url: str | None = None
    url: str | None = None
    continue_url: str | None = None


class Organisation(BaseModel):
    id: int
    name: str
    url: str | None = None
    website: str | None = None
    location: str | None = None
    about: str | None = None
    mission: str | None = None
    vision: str | None = None


class LeaderboardEntry(BaseModel):
    rank: int | None = None
    name: str
    username: str | None = None
    organisation: str | None = None
    points: float | None = None
    certificates: int | None = None
    rank_change: int | None = None


class Leaderboard(BaseModel):
    page: int
    last_page: int | None = None
    total: int | None = None
    entries: list[LeaderboardEntry]
