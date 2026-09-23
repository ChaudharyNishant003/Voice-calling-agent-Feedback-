# 0005 — HTTP QUERY method for complex read/list/search endpoints

Status: Accepted

## Context
Several planned endpoints are read-only but need a request body because their filters don't fit
cleanly into query params — e.g. listing visits/calls/cases by date range + status + department +
location + account scoping (doc 04 §5–§7, ~S1.5–S1.8 and beyond). Until now the convention would
have been `GET` with a long query string (hits practical URL-length limits and gets awkward past a
handful of filter fields) or `POST` (works, but tells caches, proxies, WAFs, and audit tooling that
the request *might* mutate state, since POST carries no safety/idempotency guarantee).

RFC 10008, "The HTTP QUERY Method" (IETF Proposed Standard, published 2026-06-15), defines exactly
this gap: a method that is safe and idempotent like GET, but — like POST — can carry a request body.
A repeated QUERY is guaranteed not to change server state, so it can be retried, cached (where
appropriate), and reasoned about by security tooling the same way GET is.

## Decision
New search/list/filter endpoints whose filters don't fit in query params use `QUERY` instead of
`POST` (doc 04 §1). Simple filters stay on `GET` + query params — this is additive, not a wholesale
replacement of existing conventions. `QUERY` is never used for anything that creates, updates, or
deletes data; those stay on POST/PUT/PATCH/DELETE as normal (doc 04 already reserves POST for
resource creation and actions).

**Tooling status as of this ADR** (checked 2026-09-24):
- **FastAPI/Starlette**: no dedicated `@app.query(...)` decorator yet — the framework-level PR
  (fastapi/fastapi#15838) is still open. It works today via explicit method registration:
  `@app.api_route("/visits/search", methods=["QUERY"])`, since Starlette's router doesn't restrict
  the set of method strings it will dispatch on, and FastAPI's usual body-binding (Pydantic models,
  validation, OpenAPI schema generation) works the same way regardless of which method the route is
  registered under.
- **httpx** (our test/adapter HTTP client, doc 01 §3): no `.query()` convenience method yet. The
  generic `client.request("QUERY", url, json=...)` works — httpx doesn't restrict which methods may
  carry a body, that restriction only applies to the named shortcuts (`.get`, `.post`, etc.).
- **OpenAPI 3.2**: already has first-class QUERY support, so `backend/openapi.json` and the
  generated dashboard client (`openapi-typescript`, doc 04 line 4) aren't blocked by this.

Given both FastAPI and httpx support QUERY today through their generic/explicit APIs (just without
a named shortcut yet), there's no need for a POST fallback — we implement directly with
`methods=["QUERY"]` server-side and `.request("QUERY", ...)` client-side, and revisit if a framework
upgrade later adds a nicer shortcut.

## Consequences
- A route registered with `methods=["QUERY"]` needs the same auth/RBAC/tenant-scoping dependencies
  as any other route (doc 04 §1's `require(Permission.X)` pattern, doc 07 §1) — QUERY being "safe"
  doesn't mean unauthenticated; it only constrains what the *server* is allowed to do with it.
- Any reverse proxy, WAF, or infra config that allowlists HTTP methods (e.g. nginx `limit_except`)
  needs `QUERY` added explicitly — a known early-adoption gap for this method generally, not
  specific to us. Flag this in doc 10's deployment checklist when infra config is written.
- Browser `fetch()`/XHR support for QUERY is a separate, unrelated question — irrelevant here since
  these endpoints are called from our own dashboard's server-side API client and backend adapters,
  not directly from a browser form.
