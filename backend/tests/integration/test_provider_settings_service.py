"""Real Postgres: `provider_settings_service` (Demo MVP spec §14) — encrypt-on-save, mask-on-read,
upsert-by-provider, and `get_decrypted_credentials` only ever returning providers whose saved key
actually passed validation (`status == "connected"`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.demo import ProviderCredential
from app.services import provider_settings_service


async def test_save_key_encrypts_and_upserts(superadmin_session: AsyncSession) -> None:
    saved = await provider_settings_service.save_key(
        superadmin_session, "gemini", "AIza-real-looking-key", "gemini-3.8-flash", "connected"
    )
    assert saved.status == "connected"
    assert saved.model == "gemini-3.8-flash"
    # The plaintext key must never be stored — only its encrypted form.
    assert b"AIza-real-looking-key" not in saved.wrapped_key

    # Saving again for the same provider updates the existing row rather than inserting a second
    # one — `provider` is the primary key, a fixed-set config table, not per-test unique data.
    updated = await provider_settings_service.save_key(
        superadmin_session, "gemini", "AIza-new-key", "gemini-3.5-flash-lite", "invalid"
    )
    assert updated.status == "invalid"
    assert updated.model == "gemini-3.5-flash-lite"

    rows = (
        await superadmin_session.scalars(
            select(ProviderCredential).where(ProviderCredential.provider == "gemini")
        )
    ).all()
    assert len(rows) == 1


async def test_saved_key_survives_a_fresh_session(
    superadmin_session: AsyncSession, migrated_database: dict[str, str]
) -> None:
    """Persistence, not just in-process identity-map visibility: save and commit through one
    session, then read it back through a completely independent session/connection — the same
    shape as the credential surviving an API-process restart.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    await provider_settings_service.save_key(
        superadmin_session, "openai", "sk-real-looking-key", "gpt-6-sol", "connected"
    )
    await superadmin_session.commit()

    engine = create_async_engine(migrated_database["superadmin"])
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as fresh_session:
            row = await provider_settings_service.get_status(fresh_session, "openai")
            assert row is not None
            assert row.status == "connected"
            assert row.model == "gpt-6-sol"

            creds = await provider_settings_service.get_decrypted_credentials(
                fresh_session, ["openai"]
            )
            api_key, model = creds["openai"]
            assert api_key == "sk-real-looking-key"
            assert model == "gpt-6-sol"
    finally:
        await engine.dispose()


async def test_get_decrypted_credentials_excludes_unconnected_providers(
    superadmin_session: AsyncSession,
) -> None:
    await provider_settings_service.save_key(
        superadmin_session, "gemini", "key-a", "gemini-3.8-flash", "invalid"
    )
    await provider_settings_service.save_key(
        superadmin_session, "openai", "key-b", "gpt-6-sol", "connected"
    )
    await superadmin_session.flush()

    creds = await provider_settings_service.get_decrypted_credentials(
        superadmin_session, ["gemini", "openai"]
    )
    assert "gemini" not in creds
    assert creds["openai"][0] == "key-b"


async def test_list_status_returns_every_saved_provider(superadmin_session: AsyncSession) -> None:
    await provider_settings_service.save_key(
        superadmin_session, "gemini", "key-a", "gemini-3.8-flash", "connected"
    )
    await provider_settings_service.save_key(
        superadmin_session, "openai", "key-b", "gpt-6-sol", "error"
    )
    await superadmin_session.flush()

    all_rows = await provider_settings_service.list_status(superadmin_session)
    rows = {row.provider: row for row in all_rows}
    assert rows["gemini"].status == "connected"
    assert rows["openai"].status == "error"
