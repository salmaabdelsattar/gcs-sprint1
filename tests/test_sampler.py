import time

import pytest

from gcs.events import EventBus
from gcs.input import (
    GamepadState,
    KeyEvent,
    Sampler,
    gamepad_source,
    keyboard_source,
)


def test_sampler_runs_at_roughly_the_configured_rate():
    bus = EventBus()
    sampler = Sampler(bus, [lambda: []], rate_hz=50)
    sampler.start()
    time.sleep(0.5)
    sampler.stop()
    # ~25 ticks expected; generous bounds so slow machines don't flake
    assert 10 <= sampler.ticks <= 30


def test_slow_subscriber_never_blocks_sampling():
    bus = EventBus()
    bus.subscribe("input.test", maxsize=1)  # nobody ever reads this queue
    sampler = Sampler(bus, [lambda: [("input.test", {})]], rate_hz=100)
    sampler.start()
    time.sleep(0.3)
    sampler.stop()
    assert sampler.ticks > 10


def test_failing_source_does_not_stop_the_thread():
    bus = EventBus()
    sub = bus.subscribe("good")

    def bad():
        raise RuntimeError("device exploded")

    sampler = Sampler(bus, [bad, lambda: [("good", {"ok": True})]], rate_hz=50)
    sampler.start()
    time.sleep(0.2)
    sampler.stop()
    assert sampler.ticks > 3
    assert sub.get(timeout=1).data["ok"] is True


def test_stop_ends_the_thread():
    sampler = Sampler(EventBus(), [], rate_hz=50)
    sampler.start()
    sampler.stop()
    assert not sampler.is_alive()


def test_invalid_rate_raises():
    with pytest.raises(ValueError):
        Sampler(EventBus(), [], rate_hz=0)


def test_gamepad_source_empty_when_disconnected():
    class Disconnected:
        def read(self):
            return None

    assert gamepad_source(Disconnected())() == []


def test_gamepad_source_publishes_state():
    class FakePad:
        def read(self):
            return GamepadState("Pad", (0.0, 0.5), (True,), ((0, 1),))

    topic, data = gamepad_source(FakePad())()[0]
    assert topic == "input.gamepad"
    assert data["name"] == "Pad"
    assert data["axes"] == (0.0, 0.5)


def test_keyboard_source_publishes_key_events():
    class FakeKeyboard:
        def poll(self):
            return [KeyEvent("w", True)]

    assert keyboard_source(FakeKeyboard())() == [
        ("input.key", {"key": "w", "pressed": True})
    ]
