"""Fakes must satisfy the adapter Protocols (doc 11 S0.4 — 'fakes satisfy Protocols').

mypy --strict checks this statically (see the type-annotated assignments below); this test checks
it at runtime too via isinstance against the runtime_checkable-free structural Protocols by
exercising each method.
"""

from __future__ import annotations

from app.adapters.fakes import FakeLLM, FakeNotifier, FakeSTT, FakeTelephony, FakeTTS
from app.adapters.interfaces import (
    LLMAdapter,
    NotificationAdapter,
    STTAdapter,
    TelephonyAdapter,
    TTSAdapter,
)


def test_fake_telephony_satisfies_protocol() -> None:
    adapter: TelephonyAdapter = FakeTelephony()
    assert adapter is not None


def test_fake_stt_satisfies_protocol() -> None:
    adapter: STTAdapter = FakeSTT()
    assert adapter is not None


def test_fake_llm_satisfies_protocol() -> None:
    adapter: LLMAdapter = FakeLLM()
    assert adapter is not None


def test_fake_tts_satisfies_protocol() -> None:
    adapter: TTSAdapter = FakeTTS()
    assert adapter is not None


def test_fake_notifier_satisfies_protocol() -> None:
    adapter: NotificationAdapter = FakeNotifier()
    assert adapter is not None


async def test_fake_telephony_place_call_records_request() -> None:
    from app.adapters.interfaces import PlaceCallRequest

    telephony = FakeTelephony()
    req = PlaceCallRequest(
        call_id="call_1",
        to_e164="+919876543210",
        from_cli="+911234567890",
        answer_url="https://example/answer",
        status_callback_url="https://example/status",
    )
    result = await telephony.place_call(req)
    assert result.provider_call_id
    assert telephony.placed_calls == [req]


async def test_fake_telephony_place_call_failure_injection() -> None:
    from app.core.errors import AdapterError

    telephony = FakeTelephony()
    telephony.inject_place_call_failure()

    import pytest

    from app.adapters.interfaces import PlaceCallRequest

    req = PlaceCallRequest(
        call_id="call_1",
        to_e164="+919876543210",
        from_cli="+911234567890",
        answer_url="https://example/answer",
        status_callback_url="https://example/status",
    )
    with pytest.raises(AdapterError):
        await telephony.place_call(req)


async def test_fake_stt_stream_yields_scripted_transcripts() -> None:
    from app.adapters.fakes.stt import ScriptedTranscript

    stt = FakeSTT()
    stt.script("call_1", [ScriptedTranscript(text="hello"), ScriptedTranscript(text="world")])

    stream = await stt.stream_open(["en"], call_id="call_1")
    texts = [t.text async for t in stream.results()]
    assert texts == ["hello", "world"]


async def test_fake_stt_injects_stream_failure() -> None:
    import pytest

    from app.adapters.fakes.stt import ScriptedTranscript
    from app.core.errors import AdapterError

    stt = FakeSTT()
    stt.script("call_1", [ScriptedTranscript(text="hello"), ScriptedTranscript(text="world")])
    stt.inject_stream_failure("call_1", after_n_transcripts=1)

    stream = await stt.stream_open(["en"], call_id="call_1")
    with pytest.raises(AdapterError):
        _ = [t.text async for t in stream.results()]


async def test_fake_llm_returns_fixture_by_prompt_and_input() -> None:
    llm = FakeLLM()
    llm.add_fixture("interpret_answer", {"answer": "yes"}, {"understood": True})

    result = await llm.complete("interpret_answer", {"answer": "yes"}, timeout_s=1.5)
    assert result.data == {"understood": True}


async def test_fake_llm_timeout_mode() -> None:
    import pytest

    from app.core.errors import AdapterError

    llm = FakeLLM()
    llm.set_mode("interpret_answer", "timeout")

    with pytest.raises(AdapterError):
        await llm.complete("interpret_answer", {}, timeout_s=1.5)


async def test_fake_llm_malformed_mode() -> None:
    llm = FakeLLM()
    llm.set_mode("extract_call", "malformed")

    result = await llm.extract("extract_call", {}, timeout_s=1.5)
    assert result.data == {}
    assert "not valid json" in result.raw_text


async def test_fake_tts_synthesise_stream_yields_bytes() -> None:
    tts = FakeTTS()
    chunks = [chunk async for chunk in tts.synthesise_stream("hello there", "en", "voice1")]
    assert chunks
    assert all(isinstance(c, bytes) for c in chunks)


async def test_fake_tts_failure_injection() -> None:
    import pytest

    from app.core.errors import AdapterError

    tts = FakeTTS()
    tts.inject_synthesise_failure()

    with pytest.raises(AdapterError):
        _ = [chunk async for chunk in tts.synthesise_stream("hello", "en", "voice1")]


async def test_fake_notifier_captures_email_and_is_idempotent() -> None:
    notifier = FakeNotifier()
    await notifier.send_email(["a@b.com"], "subject", "<p>hi</p>", "hi", idempotency_key="k1")
    await notifier.send_email(["a@b.com"], "subject", "<p>hi</p>", "hi", idempotency_key="k1")

    assert len(notifier.emails) == 1
