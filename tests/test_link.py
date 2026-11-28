import time

import pytest

from gcs.events import EventBus
from gcs.link import HeartbeatMonitor, MavlinkLink, TelemetryDecoder


class Msg:
    """A stand-in for a pymavlink message."""

    def __init__(self, kind, **fields):
        self._kind = kind
        self.__dict__.update(fields)

    def get_type(self):
        return self._kind


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeConn:
    def __init__(self, messages=()):
        self._messages = list(messages)
        self.mav = self
        self.heartbeats_sent = 0

    def recv_match(self, blocking=True, timeout=None):
        if self._messages:
            return self._messages.pop(0)
        time.sleep(timeout or 0.01)
        return None

    def heartbeat_send(self, *args, **kwargs):
        self.heartbeats_sent += 1


def wait_for(condition, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def heartbeat(mode=19, armed=True, kind=12):
    base_mode = 128 if armed else 0
    return Msg("HEARTBEAT", type=kind, autopilot=3, base_mode=base_mode, custom_mode=mode, system_status=4)


def test_first_heartbeat_reports_connected():
    monitor = HeartbeatMonitor(3.0, Clock())
    events = monitor.beat()
    assert [topic for topic, _ in events] == ["link.status", "operator.notice"]
    assert events[0][1]["connected"] is True
    assert monitor.beat() == []


def test_heartbeat_lost_after_timeout_then_recovered():
    clock = Clock()
    monitor = HeartbeatMonitor(3.0, clock)
    monitor.beat()
    clock.now = 2.9
    assert monitor.check() == []
    clock.now = 3.5
    lost = monitor.check()
    assert lost[0][1]["connected"] is False
    assert lost[1][1]["level"] == "warning"
    assert monitor.check() == []
    assert monitor.beat()[0][1]["connected"] is True


def test_check_before_any_heartbeat_reports_nothing():
    assert HeartbeatMonitor(3.0, Clock()).check() == []


def test_heartbeat_decodes_armed_and_mode():
    events = TelemetryDecoder().decode(heartbeat(mode=19, armed=True))
    assert [topic for topic, _ in events] == ["link.heartbeat", "telemetry.update"]
    assert events[0][1] == {"armed": True, "mode": "MANUAL"}
    assert events[1][1]["armed"] is True


def test_repeated_heartbeat_does_not_repeat_telemetry_update():
    decoder = TelemetryDecoder()
    decoder.decode(heartbeat())
    assert [topic for topic, _ in decoder.decode(heartbeat())] == ["link.heartbeat"]


def test_unknown_mode_number_gets_a_readable_name():
    events = TelemetryDecoder().decode(heartbeat(mode=99))
    assert events[0][1]["mode"] == "MODE_99"


def test_ground_station_heartbeats_are_ignored():
    assert TelemetryDecoder().decode(heartbeat(kind=6)) == []


def test_vfr_hud_gives_altitude_and_depth():
    events = TelemetryDecoder().decode(Msg("VFR_HUD", alt=-2.5))
    assert events[0][0] == "telemetry.update"
    assert events[0][1]["altitude_m"] == pytest.approx(-2.5)
    assert events[0][1]["depth_m"] == pytest.approx(2.5)


def test_other_messages_are_ignored():
    assert TelemetryDecoder().decode(Msg("ATTITUDE", roll=0.1)) == []


def test_link_publishes_status_and_telemetry():
    bus = EventBus()
    status = bus.subscribe("link.status")
    telemetry = bus.subscribe("telemetry.update")
    conn = FakeConn([heartbeat(), Msg("VFR_HUD", alt=-1.5)])
    link = MavlinkLink(bus, "fake", connect=lambda: conn)
    link.start()
    try:
        assert status.get(timeout=2).data["connected"] is True
        first = telemetry.get(timeout=2).data
        second = telemetry.get(timeout=2).data
    finally:
        link.stop()
    assert first["armed"] is True
    assert first["mode"] == "MANUAL"
    assert second["depth_m"] == pytest.approx(1.5)


def test_link_sends_its_own_heartbeat():
    conn = FakeConn()
    link = MavlinkLink(EventBus(), "fake", connect=lambda: conn)
    link.start()
    try:
        assert wait_for(lambda: conn.heartbeats_sent >= 1)
    finally:
        link.stop()


def test_queued_actions_run_on_the_link_thread():
    conn = FakeConn()
    seen = []
    link = MavlinkLink(EventBus(), "fake", connect=lambda: conn)
    link.start()
    try:
        link.send(lambda c: seen.append(c))
        assert wait_for(lambda: seen)
    finally:
        link.stop()
    assert seen == [conn]


def test_failing_action_does_not_stop_the_link():
    conn = FakeConn()
    seen = []
    link = MavlinkLink(EventBus(), "fake", connect=lambda: conn)
    link.start()
    try:
        link.send(lambda c: 1 / 0)
        link.send(lambda c: seen.append("ok"))
        assert wait_for(lambda: seen)
    finally:
        link.stop()
