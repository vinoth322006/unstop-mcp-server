"""Two independent auth layers.

* **Upstream** (``session``, ``store``, ``unstop_auth``): this server acting *as an Unstop user*. Sessions come from
  an interactive OTP/password login run by the account owner and are stored encrypted at rest, then refreshed
  automatically.
* **Downstream** (``api_keys``): MCP clients authenticating *to this server* over HTTP with bearer API keys. Each key
  is bound to one tenant, and each tenant has its own Unstop session.
"""
