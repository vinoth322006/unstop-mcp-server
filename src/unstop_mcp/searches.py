"""Saved searches with "what's new since I last looked" tracking, stored per tenant on local disk."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from unstop_mcp.auth.session import validate_tenant
from unstop_mcp.auth.store import atomic_write
from unstop_mcp.errors import InvalidInput, NotFound

MAX_SEARCHES = 25
MAX_SEEN = 600
_NAME_RE = re.compile(r"^[\w .,&+#'-]{1,60}$")


class SavedSearch(BaseModel):
    name: str
    query: str | None = None
    opportunity_type: str = "all"
    payment: Literal["free", "paid", "all"] = "all"
    region: Literal["online", "offline", "all"] = "all"
    created_at: float = Field(default_factory=time.time)
    last_checked_at: float | None = None
    seen_ids: list[int] = Field(default_factory=list)


class SearchStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    def _path(self, tenant: str) -> Path:
        return self.directory / f"{validate_tenant(tenant)}.json"

    def load(self, tenant: str) -> list[SavedSearch]:
        path = self._path(tenant)
        if not path.exists():
            return []
        try:
            return [SavedSearch.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
        except (ValueError, TypeError):
            return []  # a corrupt file must never break the server; it is rewritten on next save

    def save(self, tenant: str, items: list[SavedSearch]) -> None:
        data = json.dumps([i.model_dump() for i in items], indent=1).encode()
        atomic_write(self._path(tenant), data)

    def upsert(self, tenant: str, search: SavedSearch) -> SavedSearch:
        if not _NAME_RE.fullmatch(search.name):
            raise InvalidInput("Give the search a short name (letters, numbers, spaces; up to 60 characters).")
        with self._lock:
            items = [i for i in self.load(tenant) if i.name.lower() != search.name.lower()]
            if len(items) >= MAX_SEARCHES:
                raise InvalidInput(f"You can keep up to {MAX_SEARCHES} saved searches. Delete one first.")
            items.append(search)
            self.save(tenant, items)
        return search

    def delete(self, tenant: str, name: str) -> None:
        with self._lock:
            items = self.load(tenant)
            kept = [i for i in items if i.name.lower() != name.lower()]
            if len(kept) == len(items):
                raise NotFound(f"No saved search called '{name}'.")
            self.save(tenant, kept)

    def mark_seen(self, tenant: str, name: str, ids: list[int]) -> None:
        with self._lock:
            items = self.load(tenant)
            for i in items:
                if i.name.lower() == name.lower():
                    merged = list(dict.fromkeys(ids + i.seen_ids))[:MAX_SEEN]
                    i.seen_ids, i.last_checked_at = merged, time.time()
            self.save(tenant, items)
