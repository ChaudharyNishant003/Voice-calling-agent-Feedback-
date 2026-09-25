"""Demo MVP provider credential storage (spec §14) — encrypt/save/mask Gemini + OpenAI API keys.
Reuses `core/security.py`'s envelope-encryption primitives directly against the local KEK (no
per-account DEK indirection — see migration 0015's docstring for why that layer doesn't apply to a
single platform-global demo credential).

Deliberately has no knowledge of *how* a key gets tested — `save_key` takes an already-determined
`status` (the caller, `api/v1/demo.py`, calls `adapters.gemini.llm.test_api_key`/`adapters.openai.
llm.test_api_key` directly first). Importing those vendor modules from here would violate the
import-linter's "services never import vendor SDKs" contract; see `adapters/registry.py`'s note on
the same issue for the full reasoning.

The raw key is never returned once saved (masked read only) and never logged — `save_key` takes the
plaintext key as a parameter exactly once, encrypts it immediately, and only the encrypted form is
persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt, get_local_kek
from app.db.models.demo import ProviderCredential

Provider = Literal["gemini", "openai"]
Status = Literal["connected", "invalid", "error"]


async def save_key(
    session: AsyncSession, provider: Provider, api_key: str, model: str, status: Status
) -> ProviderCredential:
    now = datetime.now(UTC)
    kek = get_local_kek()

    row = await session.get(ProviderCredential, provider)
    if row is None:
        row = ProviderCredential(provider=provider, wrapped_key=encrypt(api_key, kek), model=model)
        session.add(row)
    else:
        row.wrapped_key = encrypt(api_key, kek)
        row.model = model
    row.status = status
    row.tested_at = now
    row.updated_at = now
    await session.flush()
    return row


async def get_status(session: AsyncSession, provider: Provider) -> ProviderCredential | None:
    return await session.get(ProviderCredential, provider)


async def list_status(session: AsyncSession) -> list[ProviderCredential]:
    return list((await session.scalars(select(ProviderCredential))).all())


async def get_decrypted_credentials(
    session: AsyncSession, providers: list[Provider]
) -> dict[str, tuple[str, str]]:
    """Returns {provider: (api_key, model)} for only the requested, connected providers — the
    shape `api/v1/demo.py` needs to build an `AdapterRegistry[LLMAdapter]`. Never used for API
    responses.
    """
    kek = get_local_kek()
    result: dict[str, tuple[str, str]] = {}
    for provider in providers:
        row = await session.get(ProviderCredential, provider)
        if row is not None and row.status == "connected":
            result[provider] = (decrypt(row.wrapped_key, kek), row.model)
    return result
