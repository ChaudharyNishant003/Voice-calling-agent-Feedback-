from app.core.clock import FrozenClock
from app.services.metrics_service import CallEventWriter


def test_emit_records_event_with_clock_timestamp() -> None:
    clock = FrozenClock()
    writer = CallEventWriter(clock=clock)

    event = writer.emit("call_1", "call.queued", {"attempt_no": 1})

    assert event.call_id == "call_1"
    assert event.type == "call.queued"
    assert event.data == {"attempt_no": 1}
    assert event.ts == clock.now()
    assert writer.events == [event]


def test_emit_defaults_data_to_empty_dict() -> None:
    writer = CallEventWriter()
    event = writer.emit("call_1", "call.status")
    assert event.data == {}
