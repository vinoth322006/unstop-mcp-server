"""Unstop client, layered so each part depends only on the ones below it.

    _base         HTTP as the signed-in user, pagination, crash-proof parsing
    catalog       public listings (no sign-in)
    account       the user's own data            (builds on catalog)
    alerts        saved searches                 (builds on catalog)
    registration  registering and cancelling     (builds on account)
    teams         team management                (builds on registration)
"""

from unstop_mcp.client._base import gather_limited, parse_opportunity_id, parse_organisation_id
from unstop_mcp.client.alerts import AlertsService
from unstop_mcp.client.teams import TeamsService


class UnstopClient(TeamsService, AlertsService):
    """Every Unstop operation in one object (the composition of all service layers)."""


__all__ = ["UnstopClient", "gather_limited", "parse_opportunity_id", "parse_organisation_id"]
