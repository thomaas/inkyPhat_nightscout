from types import SimpleNamespace

import pytest

tandemCalls = pytest.importorskip("tandemCalls")


def event(class_name, timestamp, **fields):
    cls = type(class_name, (), {})
    obj = cls()
    obj.raw = SimpleNamespace(timestampRaw=timestamp)
    for name, value in fields.items():
        setattr(obj, name, value)
    return obj


def test_uses_latest_delivery_rate_and_converts_milliunits_per_hour():
    events = [
        event("LidBasalDelivery", 20, commandedRate=850),
        event("LidBasalDelivery", 30, commandedRate=1250),
    ]
    assert tandemCalls._current_basal(events) == pytest.approx(1.25)


def test_newer_rate_change_takes_precedence_over_older_delivery_sample():
    events = [
        event("LidBasalDelivery", 20, commandedRate=850),
        event("LidBasalRateChange", 30, commandedBasalRate=0.6),
    ]
    assert tandemCalls._current_basal(events) == pytest.approx(0.6)


def test_newer_delivery_takes_precedence_over_older_rate_change():
    events = [
        event("LidBasalRateChange", 20, commandedBasalRate=0.6),
        event("LidBasalDelivery", 30, commandedRate=850),
    ]
    assert tandemCalls._current_basal(events) == pytest.approx(0.85)


def test_zero_delivery_rate_is_valid():
    assert tandemCalls._current_basal([
        event("LidBasalDelivery", 30, commandedRate=0),
    ]) == 0.0


def test_returns_none_when_no_supported_basal_event_has_a_rate():
    events = [event("LidBasalDelivery", 30, commandedRate=None)]
    assert tandemCalls._current_basal(events) is None
