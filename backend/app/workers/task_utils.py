"""Shared Celery task-body runner (docs/01_ARCHITECTURE.md §2 — `worker` is a long-lived process
handling many task invocations, not a fresh process per task).

`asyncio.run(coro)` creates a *new* event loop for every call and tears it down when the coroutine
finishes. `db.base`'s engines (`get_engine`/`get_superadmin_engine`) are `@lru_cache`d at module —
i.e. process — scope, and an asyncpg connection pool is bound to the event loop it was created on.
The combination means: the first task in a worker process creates the engine against loop A; when
that task's `asyncio.run()` returns, loop A closes; the *next* task gets a brand-new loop B via its
own `asyncio.run()` call, but `get_engine()` still hands back the (now-defunct) loop-A-bound engine
— asyncpg then raises `RuntimeError: Task ... got Future ... attached to a different loop`.
Confirmed by hand: the *first* ingestion batch a real `celery worker` process handles succeeds, the
*second* crashes with exactly that error.

The disposal has to happen *inside* the same `asyncio.run()` call whose loop the engine was built
against — a `dispose()` issued from a second, later `asyncio.run()` call fails too
(`RuntimeError: Event loop is closed`), since by then the first loop is already gone and asyncpg's
connections can't be gracefully closed from a different one. Also confirmed by hand.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_worker_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async Celery task body, then — in the *same* event loop — dispose+clear this
    process's cached DB engines, so the next task's `asyncio.run()` (a genuinely fresh event loop)
    builds a fresh engine instead of reusing one bound to the loop that's about to close.
    """

    async def _run_and_cleanup() -> T:
        try:
            return await coro
        finally:
            await _dispose_cached_engines()

    return asyncio.run(_run_and_cleanup())


async def _dispose_cached_engines() -> None:
    from app.db import base as db_base

    if db_base.get_engine.cache_info().currsize:
        await db_base.get_engine().dispose()
        db_base.get_engine.cache_clear()
        db_base.get_sessionmaker.cache_clear()

    if db_base.get_superadmin_engine.cache_info().currsize:
        await db_base.get_superadmin_engine().dispose()
        db_base.get_superadmin_engine.cache_clear()
        db_base.get_superadmin_sessionmaker.cache_clear()
