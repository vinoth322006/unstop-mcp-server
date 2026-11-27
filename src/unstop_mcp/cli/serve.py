"""`unstop-mcp serve`: run the MCP server over stdio (AI apps) or HTTP (remote, API keys)."""
from __future__ import annotations

import argparse

from unstop_mcp import __version__
from unstop_mcp.cli._ui import _settings
from unstop_mcp.cli.keys import _key_store
from unstop_mcp.logging_setup import configure_logging


def cmd_serve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    configure_logging(settings.log_level, settings.log_json)
    from unstop_mcp.server import build_server

    mcp = build_server(settings)
    if settings.transport == "stdio":
        mcp.run("stdio")
        return 0

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    from unstop_mcp.server import log

    hosts = list(settings.allowed_hosts)
    if not hosts:
        hosts = [f"{h}:{settings.port}" for h in ("127.0.0.1", "localhost")] + ["127.0.0.1", "localhost"]
        if settings.public_url:
            from urllib.parse import urlparse

            hosts.append(urlparse(settings.public_url).netloc)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=list(settings.allowed_origins) or [settings.resolved_public_url],
    )
    app = mcp.streamable_http_app(streamable_http_path=settings.path, transport_security=security, host=settings.host)
    if not [k for k in _key_store(settings).list() if k.active]:
        log.warning("No active API keys: every request will get 401. Create one with `unstop-mcp keys create`.")
    log.info("Unstop MCP %s listening on http://%s:%s%s", __version__, settings.host, settings.port, settings.path)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower(),
                proxy_headers=True, forwarded_allow_ips="*" if settings.public_url else "127.0.0.1",
                access_log=False, server_header=False, timeout_graceful_shutdown=10)
    return 0
