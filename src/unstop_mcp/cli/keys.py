"""`keys`: API keys for remote (HTTP) clients."""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from unstop_mcp.cli._ui import _err, _settings, fail, ok
from unstop_mcp.config import Settings


def _key_store(settings: Settings) -> Any:
    from unstop_mcp.auth.api_keys import ApiKeyStore

    return ApiKeyStore(settings.api_keys_file)


def cmd_keys(args: argparse.Namespace) -> int:
    store = _key_store(_settings(args))
    if args.keys_cmd == "create":
        scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
        key, rec = store.create(args.tenant, scopes=scopes, label=args.label or "", ttl_days=args.ttl_days)
        _err(f"API key for tenant '{rec.tenant}' (id {rec.id}, scopes {','.join(rec.scopes)}).")
        _err("Store it now; it will not be shown again:")
        print(key)
        return 0
    if args.keys_cmd == "list":
        rows = [
            {"id": r.id, "tenant": r.tenant, "label": r.label, "hint": r.hint, "scopes": r.scopes,
             "created": time.strftime("%Y-%m-%d", time.localtime(r.created_at)),
             "expires": time.strftime("%Y-%m-%d", time.localtime(r.expires_at)) if r.expires_at else None,
             "active": r.active}
            for r in store.list()
        ]
        print(json.dumps(rows, indent=2))
        return 0
    if args.keys_cmd == "revoke":
        if store.revoke(args.key_id):
            ok(f"Revoked {args.key_id}.")
            return 0
        fail(f"No active key with id {args.key_id}.")
        return 1
    return 2
