import time

import pytest

from gcs.config import ProfileAutoLoader, ProfileManager
from gcs.control import (
    ControlLoop,
    Failsafe,
    MotionMapper,
    compute_setpoint,
    manual_control_action,
    to_manual_control,
)
from gcs.control.queues import drain
from gcs.events import EventBus

PROFILE = {
    "axes": {"0": "sway", "1": "surge"},
    "invert": [],
    "keys": {"w": "surge+", "s": "surge-"},
}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeMav:
    def __init__(self):
        self.calls = []

    def manual_control_send(self, *args):
        self.calls.append(args)


class FakeConn:
    target_system = 1
    target_component = 1

    def __init__(self):
        self.mav = FakeMav()


def decode(action):
    conn = FakeConn()
    action(conn)
    return conn.mav.calls[0][1:5]


def pad(*axes):
    return {"name": "Pad", "axes": tuple(axes), "buttons": (), "hats": ()}


def zeros():
    return {"surge": 0.0, "sway": 0.0, "heave": 0.0, "yaw": 0.0}


def alerts(sub):
    return [e.data for e in drain(sub) if e.data["level"] == "alert"]


def test_stick_axes_map_to_motions():
    result = compute_setpoint((0.5, -0.25), set(), PROFILE)
    assert result == {"surge": -0.25, "sway": 0.5, "heave": 0.0, "yaw": 0.0}


def test_invert_flips_a_motion():
    profile = {"axes": {"1": "surge"}, "invert": ["surge"]}
    assert compute_setpoint((0.0, 0.5), set(), profile)["surge"] == -0.5


def test_held_keys_push_motion():
    assert compute_setpoint((), {"w"}, PROFILE)["surge"] == 1.0
    assert compute_setpoint((), {"w", "s"}, PROFILE)["surge"] == 0.0
    assert compute_setpoint((), {"s"}, PROFILE)["surge"] == -1.0


def test_sticks_and_keys_add_and_are_clamped():
    profile = {"axes": {"0": "yaw"}, "keys": {"e": "yaw+"}}
    assert compute_setpoint((0.8,), {"e"}, profile)["yaw"] == 1.0


def test_actions_and_unknown_names_are_ignored():
    profile = {"keys": {"f1": "arm", "x": "banana+", "m": "mode:MANUAL"}}
    assert compute_setpoint((), {"f1", "x", "m"}, profile) == zeros()


def test_axis_index_beyond_the_pad_is_ignored():
    profile = {"axes": {"5": "yaw"}}
    assert compute_setpoint((0.5, 0.5), set(), profile) == zeros()


def test_neutral_setpoint_maps_to_neutral_values():
    assert to_manual_control(zeros()) == (0, 0, 500, 0)


def test_full_deflection_maps_to_extremes():
    setpoint = {"surge": 1.0, "sway": -1.0, "heave": 1.0, "yaw": 0.5}
    assert to_manual_control(setpoint) == (1000, -1000, 1000, 500)


def test_out_of_range_values_are_clamped():
    setpoint = {"surge": 5.0, "sway": 0.0, "heave": -9.0, "yaw": 0.0}
    assert to_manual_control(setpoint) == (1000, 0, 0, 0)


def test_manual_control_action_sends_values():
    action = manual_control_action({"surge": 0.5, "sway": 0.0, "heave": 0.0, "yaw": 0.0})
    conn = FakeConn()
    action(conn)
    assert conn.mav.calls == [(1, 500, 0, 500, 0, 0)]


def make_mapper(profile=PROFILE):
    bus = EventBus()
    return bus, MotionMapper(bus, profile)


def test_mapper_publishes_setpoint_only_when_it_changes():
    bus, mapper = make_mapper()
    setpoints = bus.subscribe("control.setpoint")
    bus.publish("input.gamepad", pad(0.5, 1.0))
    mapper.pump()
    bus.publish("input.gamepad", pad(0.5, 1.0))
    mapper.pump()
    events = drain(setpoints)
    assert len(events) == 1
    assert events[0].data == {"surge": 1.0, "sway": 0.5, "heave": 0.0, "yaw": 0.0}


def test_mapper_tracks_key_down_and_up():
    bus, mapper = make_mapper()
    bus.publish("input.key", {"key": "w", "pressed": True})
    assert mapper.pump()["surge"] == 1.0
    bus.publish("input.key", {"key": "w", "pressed": False})
    assert mapper.pump()["surge"] == 0.0


def test_controller_disconnect_zeroes_the_sticks():
    bus, mapper = make_mapper()
    bus.publish("input.gamepad", pad(0.0, 1.0))
    assert mapper.pump()["surge"] == 1.0
    bus.publish("controller.disconnected", {"name": "Pad"})
    assert mapper.pump()["surge"] == 0.0


def test_no_profile_gives_neutral():
    bus, mapper = make_mapper(profile=None)
    bus.publish("input.gamepad", pad(0.5, 1.0))
    assert mapper.pump() == zeros()


def test_mapper_takes_its_profile_from_the_bus():
    bus, mapper = make_mapper(profile=None)
    bus.publish("input.gamepad", pad(0.5, 1.0))
    assert mapper.pump() == zeros()
    bus.publish("profile.activated", {"profile": "p", "controller": "Pad", "data": PROFILE})
    assert mapper.pump()["surge"] == 1.0


def make_failsafe(timeout=0.5):
    bus = EventBus()
    clock = Clock()
    return bus, Failsafe(bus, timeout, clock), clock


def test_failsafe_is_idle_at_start():
    bus, failsafe, _ = make_failsafe()
    notices = bus.subscribe("operator.notice")
    assert failsafe.pump() is False
    assert drain(notices) == []


def test_input_silence_triggers_failsafe_and_alert():
    bus, failsafe, clock = make_failsafe()
    notices = bus.subscribe("operator.notice")
    bus.publish("input.gamepad", pad(0.0))
    assert failsafe.pump() is False
    clock.now = 0.3
    assert failsafe.pump() is False
    clock.now = 0.6
    assert failsafe.pump() is True
    found = alerts(notices)
    assert len(found) == 1
    assert "controller input lost" in found[0]["message"]


def test_controller_disconnect_triggers_failsafe_immediately():
    bus, failsafe, _ = make_failsafe()
    bus.publish("input.gamepad", pad(0.0))
    failsafe.pump()
    bus.publish("controller.disconnected", {"name": "Pad"})
    assert failsafe.pump() is True


def test_new_samples_clear_the_input_failsafe():
    bus, failsafe, _ = make_failsafe()
    notices = bus.subscribe("operator.notice")
    bus.publish("controller.disconnected", {"name": "Pad"})
    assert failsafe.pump() is True
    bus.publish("input.gamepad", pad(0.0))
    assert failsafe.pump() is False
    assert [e.data["level"] for e in drain(notices)] == ["alert", "info"]


def test_link_loss_triggers_failsafe_and_recovery():
    bus, failsafe, _ = make_failsafe()
    bus.publish("link.status", {"connected": False})
    assert failsafe.pump() is True
    assert failsafe.reasons() == ["vehicle link lost"]
    bus.publish("link.status", {"connected": True})
    assert failsafe.pump() is False


def test_a_second_reason_raises_a_second_alert():
    bus, failsafe, _ = make_failsafe()
    notices = bus.subscribe("operator.notice")
    bus.publish("link.status", {"connected": False})
    failsafe.pump()
    bus.publish("controller.disconnected", {"name": "Pad"})
    failsafe.pump()
    found = alerts(notices)
    assert len(found) == 2
    assert "input lost" in found[1]["message"]
    assert "link lost" in found[1]["message"]


def make_loop(rate=20):
    bus = EventBus()
    clock = Clock()
    sent = []
    loop = ControlLoop(bus, sent.append, rate_hz=rate, input_timeout_s=0.5, profile=PROFILE, clock=clock)
    return bus, loop, sent, clock


def test_nothing_is_sent_until_the_link_is_up():
    _, loop, sent, _ = make_loop()
    assert loop.tick() is None
    assert sent == []


def test_stick_input_is_sent_as_manual_control():
    bus, loop, sent, _ = make_loop()
    bus.publish("link.status", {"connected": True})
    bus.publish("input.gamepad", pad(0.5, 1.0))
    loop.tick()
    assert len(sent) == 1
    assert decode(sent[0]) == (1000, 500, 500, 0)


def test_failsafe_sends_neutral_while_input_is_lost():
    bus, loop, sent, clock = make_loop()
    bus.publish("link.status", {"connected": True})
    bus.publish("input.gamepad", pad(0.5, 1.0))
    loop.tick()
    clock.now = 1.0
    loop.tick()
    assert loop.failsafe.active is True
    assert decode(sent[-1]) == (0, 0, 500, 0)


def test_link_loss_sends_a_short_neutral_burst_then_stops():
    bus, loop, sent, _ = make_loop()
    bus.publish("link.status", {"connected": True})
    bus.publish("input.gamepad", pad(0.5, 1.0))
    loop.tick()
    bus.publish("link.status", {"connected": False})
    for _ in range(6):
        loop.tick()
    assert len(sent) == 4
    assert all(decode(action) == (0, 0, 500, 0) for action in sent[1:])


def test_loop_thread_sends_at_a_steady_rate():
    bus = EventBus()
    sent = []
    loop = ControlLoop(bus, sent.append, rate_hz=20, profile=PROFILE)
    bus.publish("link.status", {"connected": True})
    loop.start()
    time.sleep(0.5)
    loop.stop()
    assert 6 <= len(sent) <= 14


def test_invalid_rate_raises():
    with pytest.raises(ValueError):
        ControlLoop(EventBus(), lambda action: None, rate_hz=0)


def test_a_failing_send_does_not_stop_the_loop():
    bus = EventBus()

    def broken(action):
        raise RuntimeError("socket gone")

    loop = ControlLoop(bus, broken, rate_hz=50, profile=PROFILE)
    bus.publish("link.status", {"connected": True})
    loop.start()
    time.sleep(0.2)
    assert loop.is_alive()
    loop.stop()


def test_autoloader_publishes_the_profile_data(tmp_path):
    bus = EventBus()
    profiles = ProfileManager(tmp_path)
    profiles.save("padb", {"name": "padb", "controller": "Pad B", "axes": {"0": "yaw"}})
    loader = ProfileAutoLoader(bus, profiles)
    activated = bus.subscribe("profile.activated")
    bus.publish("controller.connected", {"name": "Pad B"})
    loader.pump()
    assert drain(activated)[0].data["data"]["axes"] == {"0": "yaw"}
