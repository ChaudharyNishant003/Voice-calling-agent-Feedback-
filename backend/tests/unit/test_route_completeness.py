"""Route-permission completeness (docs/07_SECURITY_AND_COMPLIANCE.md §1 — "a test enumerates every
route and asserts it declares a permission (no unguarded routes)"). Built now as infrastructure,
even though only the auth/health/me routers exist yet — S1.5+ adds the routes this actually
protects against silently shipping unguarded.

FastAPI's `include_router(prefix=...)` doesn't flatten routes into `app.routes` with their final
path — routers show up as an internal `_IncludedRouter` wrapper, and the prefix is only resolved at
request-match time. `_iter_api_routes` walks that structure to reconstruct each route's real path;
it degrades gracefully (via `getattr`/`hasattr`, not a hard dependency on the private class) if a
future FastAPI version changes this internal shape again.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from app.main import app

# Explicitly not permission-gated: public (health, login) or "any authenticated user" (/me,
# refresh/logout act on the caller's own session, not a specific resource).
_PUBLIC_OR_SELF_SERVICE_PATHS = {
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/me",
}


def _iter_api_routes(routes: Iterable[object], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        # Newer FastAPI (>=0.141): included sub-routers are wrapped, not flattened, and carry
        # their prefix on `include_context` rather than baked into each route's own `.path`.
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is not None and include_context is not None:
            sub_prefix = prefix + getattr(include_context, "prefix", "")
            yield from _iter_api_routes(original_router.routes, sub_prefix)


def _has_permission_marker(dependant: Dependant) -> bool:
    if getattr(dependant.call, "__pfa_permission__", None) is not None:
        return True
    return any(_has_permission_marker(sub) for sub in dependant.dependencies)


def test_every_route_is_public_or_permission_gated() -> None:
    unguarded: list[str] = []
    for path, route in _iter_api_routes(app.routes):
        if path in _PUBLIC_OR_SELF_SERVICE_PATHS:
            continue
        if not _has_permission_marker(route.dependant):
            unguarded.append(f"{sorted(route.methods or [])} {path}")

    assert not unguarded, (
        f"Route(s) with no require(Permission.X) dependency and not in the explicit "
        f"public/self-service allowlist: {unguarded}"
    )


def test_allowlist_entries_still_exist_as_real_routes() -> None:
    # Catches the allowlist going stale (a route renamed/removed but the string left behind,
    # silently making the completeness check weaker than it looks).
    known_paths = {path for path, _route in _iter_api_routes(app.routes)}
    missing = _PUBLIC_OR_SELF_SERVICE_PATHS - known_paths
    assert not missing, f"Allowlist references routes that no longer exist: {missing}"


def test_iter_api_routes_actually_finds_routes() -> None:
    # A regression guard for the walker itself: if a future FastAPI version changes shape again
    # such that `_iter_api_routes` silently finds nothing, both tests above would trivially pass
    # (vacuously) instead of failing loudly — this makes that failure mode visible.
    assert len(list(_iter_api_routes(app.routes))) >= 6
