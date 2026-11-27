"""Turn raw Unstop JSON into the schemas: type-safe readers, HTML-to-text, dates and the normalisers.

Raw Unstop objects carry 150+ fields (and full HTML). Tools return only what helps an assistant decide, which
keeps responses small and stable even when Unstop adds or renames internal fields.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any

from unstop_mcp.models.schemas import (
    Certificate,
    Course,
    LeaderboardEntry,
    Notification,
    OpportunityDetail,
    OpportunitySummary,
    Organisation,
    Participation,
    Prize,
    Profile,
    Registration,
    Round,
    RoundStatus,
)


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str | None, max_chars: int | None = None) -> str:
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        text = "".join(parser.parts)
    except Exception:  # noqa: BLE001 - malformed HTML: fall back to tag stripping
        text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …[truncated]"
    return text


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _str(v: Any) -> str | None:
    if v is None or isinstance(v, dict | list):
        return None
    s = str(v).strip()
    return s or None


def _g(obj: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return default if obj is None else obj


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _names(items: Any, *keys: str) -> list[str]:
    out: list[str] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                for k in keys:
                    if it.get(k):
                        out.append(str(it[k]).strip())
                        break
            elif isinstance(it, str):
                out.append(it)
    return list(dict.fromkeys(out))  # dedupe, keep order


def _int(v: Any) -> int | None:
    if v is None or v == "" or isinstance(v, bool):  # note: `1 in (True,)` is True in Python, so test the type
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return None


def _require_id(v: Any) -> int:
    """Ids must be positive integers; anything else makes the record unusable (callers skip it)."""
    i = _int(v)
    if i is None or i <= 0:
        raise ValueError(f"invalid id {v!r}")
    return i


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if v in (0, 1, "0", "1"):
        return str(v) == "1"
    return None


def _public_url(raw: dict[str, Any]) -> str | None:
    seo = _str(raw.get("seo_url"))
    if seo and seo.startswith("https://"):
        return seo
    path = _str(raw.get("public_url")) or _str(raw.get("opp_url"))
    return f"https://unstop.com/{str(path).lstrip('/')}" if path else None


_CURRENCY = {"fa-rupee": "INR", "fa-dollar": "USD", "fa-euro": "EUR", "fa-gbp": "GBP"}


IST = timezone(timedelta(hours=5, minutes=30))


def parse_dt(value: Any) -> datetime | None:
    """Unstop mixes '2026-12-12T23:59:00+05:30', '2026-05-23 00:00:00+05:30' and naive '2026-06-05 21:51:00'
    (which is IST). Returns an aware datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"\s*GMT([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def iso_ist(dt: datetime) -> str:
    return dt.astimezone(IST).isoformat(timespec="minutes")


def _locations(raw: dict[str, Any]) -> list[str]:
    locs = _names(raw.get("locations"), "city")
    if not locs:
        locs = _names(_g(raw, "job_detail", "locations", default=[]))
    city = _str(_g(raw, "address_with_country_logo", "city"))
    if city and city not in locs:
        locs.append(city)
    return locs


def _prizes(raw: dict[str, Any]) -> tuple[list[Prize], float | None, str | None]:
    prizes: list[Prize] = []
    total = 0.0
    currency = None
    for p in _list(raw.get("prizes")):
        if not isinstance(p, dict):
            continue
        cash = _num(p.get("cash"))
        cur = _str(p.get("currencyCode")) or _CURRENCY.get(_str(p.get("currency")) or "")
        currency = currency or cur
        if cash:
            total += cash
        prizes.append(Prize(rank=_str(p.get("rank")), cash=cash, currency=cur,
                            details=html_to_text(p.get("others"), 300) or None))
    return prizes, (total or None), currency


def _team(req: dict[str, Any]) -> str | None:
    lo, hi = _int(req.get("min_team_size")), _int(req.get("max_team_size"))
    if not lo and not hi:
        return None
    if lo == hi or not hi:
        return "solo" if lo == 1 else f"{lo}"
    return f"{lo or 1}-{hi}"


_CLOSED_STATUSES = {"FINISHED", "EXPIRED", "CLOSED", "COMPLETED", "ARCHIVED"}


def _registration_open(raw: dict[str, Any], deadline: str | None) -> bool | None:
    """Unstop keeps regn_open=1 on long-finished listings, so status, is_expired and the deadline all count."""
    flag = raw.get("regn_open")
    if flag is None:
        return None
    if not flag or raw.get("is_expired") or str(raw.get("status") or "").upper() in _CLOSED_STATUSES:
        return False
    end = parse_dt(deadline)
    return not (end is not None and end < datetime.now(IST))


def summarize(raw: dict[str, Any]) -> OpportunitySummary:
    req = _dict(raw.get("regnRequirements"))
    _, total, currency = _prizes(raw)
    return OpportunitySummary(
        id=_require_id(raw.get("id")),
        title=_str(raw.get("title")) or "(untitled)",
        type=_str(raw.get("type")),
        subtype=_str(raw.get("subtype")),
        organisation=_str(_g(raw, "organisation", "name")),
        organisation_id=_int(_g(raw, "organisation", "id") or raw.get("organization_id")),
        url=_public_url(raw),
        short_url=_str(raw.get("short_url")),
        status=_str(raw.get("status")),
        registration_open=_registration_open(raw, _str(req.get("end_regn_dt"))),
        registration_deadline=_str(req.get("end_regn_dt")),
        time_left=re.sub(r"^1 days\b", "1 day", _str(req.get("remain_days")) or "") or None,
        region=_str(raw.get("region")),
        locations=_locations(raw),
        team_size=_team(req),
        paid_entry=bool(raw.get("isPaid") if "isPaid" in raw else raw.get("paid")),
        total_cash_prize=total,
        prize_currency=currency,
        registrations=_int(raw.get("registerCount")),
        views=_int(raw.get("viewsCount")),
        skills=_names(raw.get("required_skills") or raw.get("skills"), "skill_name", "skill")[:10],
        eligible=_names(raw.get("filters"), "name")[:10],
    )


def _eligibility(req: dict[str, Any]) -> dict[str, Any]:
    raw = _dict(req).get("eligibility")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    keep = {}
    for key, val in raw.items():
        if val in (None, [], {}, "", ["all"]) or key in ("minMarks",):
            continue
        keep[key] = val
    return keep


def _rounds(raw: dict[str, Any]) -> list[Round]:
    out: list[Round] = []
    for r in _list(raw.get("rounds")):
        if not isinstance(r, dict):
            continue
        details = r.get("details") if isinstance(r.get("details"), list) else []
        d = details[0] if details and isinstance(details[0], dict) else {}
        title = _str(d.get("title")) or _str(r.get("title"))
        if title:
            out.append(Round(id=_int(r.get("id")), title=title, start=_str(d.get("start_date")),
                             end=_str(d.get("end_date")), kind=_str(r.get("subtype"))))
    return out


def _job(raw: dict[str, Any]) -> dict[str, Any] | None:
    jd = raw.get("job_detail")
    if not isinstance(jd, dict):
        return None
    jd = {k: v for k, v in jd.items() if not isinstance(v, dict)}
    fields = ("type", "timing", "openings", "working_days", "min_experience", "max_experience",
              "min_salary", "max_salary", "fixed_salary", "salary", "stipend", "pay_in", "paid_unpaid",
              "internship_duration", "perks", "locations", "not_disclosed")
    job = {k: jd[k] for k in fields if jd.get(k) not in (None, "", [], 0)}
    if _str(jd.get("currency")):
        job["currency"] = _CURRENCY.get(str(jd["currency"]), str(jd["currency"]))
    return job or None


def detail(raw: dict[str, Any], description_max_chars: int = 6000) -> OpportunityDetail:
    base = summarize(raw).model_dump()
    req = _dict(raw.get("regnRequirements"))
    prizes, _, _ = _prizes(raw)
    return OpportunityDetail(
        **base,
        start_date=_str(raw.get("start_date")),
        end_date=_str(raw.get("end_date")),
        registration_starts=_str(req.get("start_regn_dt")),
        prizes=prizes,
        rounds=_rounds(raw),
        eligibility=_eligibility(req),
        job=_job(raw),
        external_registration_url=_str(raw.get("regn_url")),
        description=html_to_text(_str(raw.get("details")), description_max_chars),
    )


def profile(raw: dict[str, Any]) -> Profile:
    """Only fields useful to an assistant. Mobile number, OTP fields and internal ids are never returned."""
    name = _str(raw.get("name")) or " ".join(filter(None, [_str(raw.get("first_name")),
                                                           _str(raw.get("last_name"))])) or None
    username = _str(raw.get("username"))
    return Profile(
        id=_int(raw.get("id")),
        name=name,
        username=username,
        email=_str(raw.get("email")),
        gender={"M": "male", "F": "female", "O": "other"}.get(_str(raw.get("gender")) or "", _str(raw.get("gender"))),
        country=_str(raw.get("country")),
        user_category=_str(raw.get("user_category")),
        specialization=_str(raw.get("course_specialization")),
        study_year=_int(raw.get("study_year")),
        course_start_year=_int(raw.get("course_start_year")),
        graduation_year=_int(raw.get("passing_out_year")),
        summary=html_to_text(_str(raw.get("user_summary")), 600) or None,
        profile_completion_percent=_int(raw.get("profile_percent")),
        coins=_int(raw.get("coins")),
        profile_url=f"https://unstop.com/u/{username}" if username else None,
    )


def registration(raw: dict[str, Any]) -> Registration:
    """Teammates' names/emails are deliberately dropped; only counts and the team's own status are kept."""
    teams = _list(raw.get("registered_teams"))
    team = teams[0] if teams and isinstance(teams[0], dict) else {}
    regi = team.get("regi_status")
    valid = team.get("isTeamValid")
    return Registration(
        id=_require_id(raw.get("id")),
        title=_str(raw.get("title")) or "(untitled)",
        type=_str(raw.get("type")),
        opportunity_status=_str(raw.get("status")),
        url=_public_url(raw),
        organisation=_str(_g(raw, "organisation", "name")),
        start_date=_str(raw.get("start_date")),
        end_date=_str(raw.get("end_date")),
        registration_deadline=_str(raw.get("end_regn_dt")),
        team_name=_str(team.get("team_name")),
        registration_complete=(regi == "complete") if regi else None,
        team_valid=str(valid) == "1" if valid is not None else None,
        team_members=len(raw["players_registration"]) if isinstance(raw.get("players_registration"), list) else None,
        max_team_size=_int(raw.get("max_team_size")),
        rejected_in_a_round=raw.get("userRejectedRoundStatus") if isinstance(raw.get("userRejectedRoundStatus"),
                                                                             bool) else None,
        registered_at=_str(team.get("created_at")),
    )


def certificate(raw: dict[str, Any]) -> Certificate:
    data = _dict(raw.get("certData"))
    rd = _dict(raw.get("round_details"))
    cert_id = _str(raw.get("cert_id"))
    return Certificate(
        id=_require_id(raw.get("id")),
        cert_id=cert_id,
        kind=_str(raw.get("certificate_type")),
        event=_str(data.get("event")) or _str(raw.get("title")),
        parent_event=_str(data.get("parentEvent")),
        organiser=_str(data.get("organiser")) or _str(data.get("organisation")) or _str(raw.get("issued_by")),
        round=_str(rd.get("title")),
        achievement=_str(data.get("winnerString")) or _str(data.get("rankString")),
        team=_str(data.get("team")) if data.get("team_name_visibiilty") else None,  # sic: Unstop's key
        issued_at=_str(raw.get("sent_at")),
        url=_str(raw.get("certificate_url")) or (f"https://unstop.com/certificate-preview/{cert_id}" if cert_id else None),
    )


def participation(opportunity_id: int, rounds_raw: Any) -> Participation:
    rounds: list[RoundStatus] = []
    title = url = None
    for rd in rounds_raw if isinstance(rounds_raw, list) else []:
        if not isinstance(rd, dict):
            continue
        ps = _dict(rd.get("play_status"))
        dets = _list(rd.get("details"))
        det = _dict(dets[0]) if dets else {}
        title = title or _str(ps.get("opportunity_title"))
        url = url or (f"https://unstop.com/{str(ps['opportunity_url']).lstrip('/')}" if _str(ps.get("opportunity_url"))
                      else None)
        rounds.append(RoundStatus(
            order=_int(rd.get("round_order")),
            title=_str(det.get("title")),
            start=_str(rd.get("start_date")) or _str(det.get("start_date")),
            end=_str(rd.get("end_date")) or _str(det.get("end_date")),
            round_status=_str(ps.get("round_status")) or _str(rd.get("status")),
            registered=_bool(ps.get("registered")),
            participated=_bool(ps.get("participated")),
            can_play_now=_bool(ps.get("can_play")),
            note=_str(ps.get("can_play_msg")),
        ))
    rounds.sort(key=lambda r: r.order or 0)
    # Unstop returns the rounds of some listings (e.g. jobs) even when the user never applied, flagged
    # registered=false, so the per-round flag decides; an empty list means not registered.
    flags = [r.registered for r in rounds if r.registered is not None]
    registered = any(flags) if flags else bool(rounds)
    return Participation(opportunity_id=opportunity_id, registered=registered, title=title, url=url, rounds=rounds)


_NOTIFICATION_KINDS = (
    ("TeamRegistration", "team_registration"),
    ("RegistrationSucce", "registration_success"),
    ("RegistrationCance", "registration_cancelled"),
    ("Result", "result"),
    ("Gamify", "rewards"),
)


def notification(raw: dict[str, Any]) -> Notification:
    data: dict[str, Any] = raw["data"] if isinstance(raw.get("data"), dict) else {}
    kind = next((k for marker, k in _NOTIFICATION_KINDS if marker in str(raw.get("type") or "")), "other")
    url = _str(data.get("actionUrl"))
    if isinstance(url, str) and url.startswith("/"):
        url = "https://unstop.com" + url
    return Notification(
        id=str(raw.get("id")),
        kind=kind,
        text=html_to_text(_str(data.get("text")) or "", 500),
        url=url if isinstance(url, str) and url.startswith("http") else None,
        at=_str(raw.get("created_at")) or _str(data.get("time")),
        read=raw.get("read_at") is not None,
    )


def course(raw: dict[str, Any]) -> Course:
    cert = _str(raw.get("cert_id"))
    last = _str(raw.get("lastVisitedModuleLink"))
    return Course(
        id=_require_id(raw.get("course_id") or raw.get("id")),
        title=_str(raw.get("title")) or "(untitled)",
        progress_percent=_int(raw.get("module_percent")),
        modules=_int(raw.get("module_count")),
        enrolled_on=_str(raw.get("enrolled_on")),
        completed_on=_str(raw.get("completion_date")),
        certificate_url=f"https://unstop.com/certificate-preview/{cert}" if cert else None,
        url=_str(raw.get("url")) if (_str(raw.get("url")) or "").startswith("http") else _public_url(raw),
        continue_url=f"https://unstop.com/{last.lstrip('/')}" if last and not last.startswith("http") else last,
    )


def organisation(raw: dict[str, Any]) -> Organisation:
    loc = ", ".join(s for s in (_str(raw.get("city")), _str(raw.get("state")), _str(raw.get("country"))) if s)
    return Organisation(
        id=_require_id(raw.get("id")),
        name=_str(raw.get("name")) or "(unnamed)",
        url=_public_url(raw),
        website=_str(raw.get("website")),
        location=loc or None,
        about=html_to_text(_str(raw.get("description")), 1500) or None,
        mission=html_to_text(_str(raw.get("mission")), 600) or None,
        vision=html_to_text(_str(raw.get("vision")), 600) or None,
    )


def leaderboard_entry(raw: dict[str, Any]) -> LeaderboardEntry:
    """Public leaderboard rows. Avatars and internal ids are dropped."""
    org = raw.get("organisation")
    return LeaderboardEntry(
        rank=_int(raw.get("rank")),
        name=_str(raw.get("name")) or " ".join(filter(None, [_str(raw.get("first_name")),
                                                                _str(raw.get("last_name"))])) or "?",
        username=_str(raw.get("username")),
        organisation=_str(raw.get("organisation_name")) or (_str(org.get("name")) if isinstance(org, dict) else None),
        points=_num(raw.get("points")),
        certificates=_int(raw.get("certificates_count")),
        rank_change=_int(raw.get("rankChange")),
    )
