"""Real Postgres + the actual FastAPI app, through `httpx.AsyncClient` (docs/04_API_SPEC.md §4):
upload happy path, wrong-role rejection, cross-tenant batch access, `template.csv`.

`process_ingestion_batch.delay(...)` (the enqueue call in `api/v1/ingestion.py`'s `upload`, run via
`BackgroundTasks` after the response) is patched to a no-op here — it talks to Redis, which this
sandbox's validation container has no route to, and the actual CSV processing is already covered
end-to-end (real Postgres, real worker function) by `test_ingestion_service.py`. This file is about
the HTTP contract: status codes, permission gating, cross-tenant isolation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.tenancy import Account, User
from app.domain.enums import UserRole

_PASSWORD = "correct horse battery staple"
_CSV_CONTENT = (
    b"external_patient_id,phone,visit_date,visit_type,department,doctor_name,"
    b"preferred_language,patient_age,consent_flag,location_id\n"
    b"PAT-1,9876543210,2026-09-20,outpatient,cardiology,,en,45,yes,loc-1\n"
)


def _account(name: str) -> Account:
    return Account(
        name=name,
        display_name_tts=name,
        caller_id_e164="+911234567890",
        retention_policy={"audio_days": 30, "transcript_days": 180, "verbatim_days": 365},
        sla_config={"p1": {"ack": 1, "resolve": 24}},
    )


@pytest_asyncio.fixture
async def configured_app(configured_db_env: None) -> AsyncIterator[FastAPI]:
    del configured_db_env
    from app.main import app as fastapi_app

    yield fastapi_app


@pytest_asyncio.fixture
async def client(configured_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=configured_app)
    with patch("app.api.v1.ingestion.process_ingestion_batch.delay"):
        async with AsyncClient(transport=transport, base_url="https://testserver") as ac:
            yield ac


async def _new_client(configured_app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=configured_app), base_url="https://testserver")


async def _login(client: AsyncClient, user: User) -> None:
    await client.post("/api/v1/auth/login", json={"email": user.email, "password": _PASSWORD})


async def _seed_user(
    session: AsyncSession, *, account_name: str, role: UserRole
) -> User:
    account = _account(account_name)
    session.add(account)
    await session.commit()

    user = User(
        account_id=account.account_id,
        email=f"{role.value}-{account.account_id}@example.com",
        name=f"{role.value} user",
        role=role,
        password_hash=hash_password(_PASSWORD),
    )
    session.add(user)
    await session.commit()
    return user


@pytest.fixture
async def quality_user(superadmin_session: AsyncSession) -> User:
    return await _seed_user(
        superadmin_session, account_name="Ingestion API Test Hospital", role=UserRole.quality
    )


@pytest.fixture
async def read_only_user(superadmin_session: AsyncSession) -> User:
    return await _seed_user(
        superadmin_session, account_name="Read Only Test Hospital", role=UserRole.read_only
    )


@pytest.fixture
async def other_account_quality_user(superadmin_session: AsyncSession) -> User:
    return await _seed_user(
        superadmin_session, account_name="Other Tenant Hospital", role=UserRole.quality
    )


@pytest.mark.asyncio
async def test_upload_happy_path_returns_batch_info(
    client: AsyncClient, quality_user: User
) -> None:
    await _login(client, quality_user)

    response = await client.post(
        "/api/v1/ingestion/uploads",
        files={"file": ("patients.csv", _CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"].startswith("batch_")
    assert body["status"] == "received"
    assert body["filename"] == "patients.csv"


@pytest.mark.asyncio
async def test_upload_without_upload_lists_permission_is_rejected(
    client: AsyncClient, read_only_user: User
) -> None:
    await _login(client, read_only_user)

    response = await client.post(
        "/api/v1/ingestion/uploads",
        files={"file": ("patients.csv", _CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PFA-USR-001"


@pytest.mark.asyncio
async def test_upload_bad_extension_returns_pfa_ing_001(
    client: AsyncClient, quality_user: User
) -> None:
    await _login(client, quality_user)

    response = await client.post(
        "/api/v1/ingestion/uploads",
        files={"file": ("patients.xlsx", _CSV_CONTENT, "application/vnd.ms-excel")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PFA-ING-001"


@pytest.mark.asyncio
async def test_list_and_get_batch(client: AsyncClient, quality_user: User) -> None:
    await _login(client, quality_user)

    upload_response = await client.post(
        "/api/v1/ingestion/uploads",
        files={"file": ("patients.csv", _CSV_CONTENT, "text/csv")},
    )
    batch_id = upload_response.json()["batch_id"]

    list_response = await client.get("/api/v1/ingestion/batches")
    assert list_response.status_code == 200
    assert any(b["batch_id"] == batch_id for b in list_response.json())

    batch_uuid = batch_id.removeprefix("batch_")
    get_response = await client.get(f"/api/v1/ingestion/batches/{batch_uuid}")
    assert get_response.status_code == 200
    assert get_response.json()["batch_id"] == batch_id


@pytest.mark.asyncio
async def test_cross_tenant_batch_access_is_404(
    configured_app: FastAPI,
    client: AsyncClient,
    quality_user: User,
    other_account_quality_user: User,
) -> None:
    await _login(client, quality_user)
    upload_response = await client.post(
        "/api/v1/ingestion/uploads",
        files={"file": ("patients.csv", _CSV_CONTENT, "text/csv")},
    )
    batch_uuid = upload_response.json()["batch_id"].removeprefix("batch_")

    async with await _new_client(configured_app) as other_client:
        await _login(other_client, other_account_quality_user)
        # Same permission (`upload_lists`, via the `quality` role) as the uploader, but a different
        # tenant — RLS hides the row, so this is a 404, never a 403 (doc 04 §1: never leak existence
        # of another tenant's resource).
        response = await other_client.get(f"/api/v1/ingestion/batches/{batch_uuid}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PFA-ING-007"

        errors_response = await other_client.get(f"/api/v1/ingestion/batches/{batch_uuid}/errors")
        assert errors_response.status_code == 404


@pytest.mark.asyncio
async def test_template_csv_reachable_by_any_authenticated_role(
    client: AsyncClient, read_only_user: User
) -> None:
    await _login(client, read_only_user)
    response = await client.get("/api/v1/ingestion/template.csv")
    assert response.status_code == 200
    assert "external_patient_id" in response.text
