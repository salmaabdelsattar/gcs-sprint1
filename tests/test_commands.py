import queue
from types import SimpleNamespace

from gcs.control import ActionMapper, VehicleCommander, parse_action
from gcs.events import EventBus
from gcs.link import TelemetryDecoder


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeMav:
    def __init__(self):
        self.calls = []

    def command_long_send(self, *args):
        self.calls.append(args)


class FakeConn:
    target_system = 1
    target_component = 1

    def __init__(self):
        self.mav = FakeMav()


class AckMsg:
    command = 400
    result = 0

    def get_type(self):
        return "COMMAND_ACK"


def drain(sub):
    items = []
    while True:
        try:
            items.append(sub.get_nowait())
        except queue.Empty:
            return items


def make_commander(timeout=2.0):
    bus = EventBus()
    clock = Clock()
    sent = []
    commander = VehicleCommander(bus, sent.append, timeout_s=timeout, clock=clock)
    bus.publish("link.status", {"connected": True})
    commander.pump()
    return bus, commander, sent, clock


def make_mapper(buttons=None, keys=None):
    bus = EventBus()
    profiles = SimpleNamespace(active={"buttons": buttons or {}, "keys": keys or {}})
    return bus, ActionMapper(bus, profiles), profiles


def pad(*buttons):
    return {"name": "Pad", "axes": (), "buttons": tuple(buttons), "hats": ()}


def test_arm_sends_arm_command():
    bus, commander, sent, _ = make_commander()
    bus.publish("action.arm", {})
    commander.pump()
    assert len(sent) == 1
    conn = FakeConn()
    sent[0](conn)
    assert conn.mav.calls == [(1, 1, 400, 0, 1, 0, 0, 0, 0, 0, 0)]


def test_disarm_sends_disarm_command():
    bus, commander, sent, _ = make_commander()
    bus.publish("action.disarm", {})
    commander.pump()
    conn = FakeConn()
    sent[0](conn)
    assert conn.mav.calls == [(1, 1, 400, 0, 0, 0, 0, 0, 0, 0, 0)]


def test_set_mode_sends_mode_command():
    bus, commander, sent, _ = make_commander()
    bus.publish("action.set_mode", {"mode": "manual"})
    commander.pump()
    conn = FakeConn()
    sent[0](conn)
    assert conn.mav.calls == [(1, 1, 176, 0, 1, 19, 0, 0, 0, 0, 0)]


def test_ack_confirms_arm():
    bus, commander, _, _ = make_commander()
    confirmed = bus.subscribe("command.confirmed")
    bus.publish("action.arm", {})
    commander.pump()
    bus.publish("link.command_ack", {"command": 400, "result": 0})
    commander.pump()
    assert [e.data for e in drain(confirmed)] == [{"command": "arm", "via": "ack"}]


def test_denied_ack_fails_command_and_warns_operator():
    bus, commander, _, _ = make_commander()
    failed = bus.subscribe("command.failed")
    notices = bus.subscribe("operator.notice")
    bus.publish("action.arm", {})
    commander.pump()
    bus.publish("link.command_ack", {"command": 400, "result": 2})
    commander.pump()
    data = drain(failed)[0].data
    assert data["command"] == "arm"
    assert "denied" in data["reason"]
    assert drain(notices)[0].data["level"] == "warning"


def test_in_progress_ack_keeps_waiting():
    bus, commander, _, _ = make_commander()
    confirmed = bus.subscribe("command.confirmed")
    failed = bus.subscribe("command.failed")
    bus.publish("action.arm", {})
    commander.pump()
    bus.publish("link.command_ack", {"command": 400, "result": 5})
    commander.pump()
    assert drain(confirmed) == []
    assert drain(failed) == []


def test_heartbeat_mode_confirms_mode_change():
    bus, commander, _, _ = make_commander()
    confirmed = bus.subscribe("command.confirmed")
    bus.publish("action.set_mode", {"mode": "MANUAL"})
    commander.pump()
    bus.publish("link.heartbeat", {"armed": False, "mode": "MANUAL"})
    commander.pump()
    assert [e.data for e in drain(confirmed)] == [{"command": "mode MANUAL", "via": "heartbeat"}]


def test_no_response_times_out():
    bus, commander, _, clock = make_commander(timeout=2.0)
    failed = bus.subscribe("command.failed")
    bus.publish("action.arm", {})
    commander.pump()
    clock.now = 2.5
    commander.pump()
    assert "no response" in drain(failed)[0].data["reason"]


def test_commands_fail_when_vehicle_not_connected():
    bus = EventBus()
    sent = []
    commander = VehicleCommander(bus, sent.append, clock=Clock())
    failed = bus.subscribe("command.failed")
    bus.publish("action.arm", {})
    commander.pump()
    assert sent == []
    assert drain(failed)[0].data["reason"] == "vehicle not connected"


def test_unknown_mode_is_rejected():
    bus, commander, sent, _ = make_commander()
    failed = bus.subscribe("command.failed")
    bus.publish("action.set_mode", {"mode": "BANANA"})
    commander.pump()
    assert sent == []
    assert "unknown mode" in drain(failed)[0].data["reason"]


def test_link_loss_fails_pending_command():
    bus, commander, _, _ = make_commander()
    failed = bus.subscribe("command.failed")
    bus.publish("action.arm", {})
    commander.pump()
    bus.publish("link.status", {"connected": False})
    commander.pump()
    assert drain(failed)[0].data["reason"] == "link lost"


def test_unrelated_ack_is_ignored():
    bus, commander, _, _ = make_commander()
    confirmed = bus.subscribe("command.confirmed")
    failed = bus.subscribe("command.failed")
    bus.publish("action.arm", {})
    commander.pump()
    bus.publish("link.command_ack", {"command": 999, "result": 0})
    commander.pump()
    assert drain(confirmed) == []
    assert drain(failed) == []


def test_button_press_fires_action_once():
    bus, mapper, _ = make_mapper(buttons={"0": "arm"})
    arm = bus.subscribe("action.arm")
    bus.publish("input.gamepad", pad(True))
    bus.publish("input.gamepad", pad(True))
    mapper.pump()
    assert len(drain(arm)) == 1
    bus.publish("input.gamepad", pad(False))
    bus.publish("input.gamepad", pad(True))
    mapper.pump()
    assert len(drain(arm)) == 1


def test_mode_button_fires_set_mode():
    bus, mapper, _ = make_mapper(buttons={"2": "mode:alt_hold"})
    modes = bus.subscribe("action.set_mode")
    bus.publish("input.gamepad", pad(False, False, True))
    mapper.pump()
    assert drain(modes)[0].data == {"mode": "ALT_HOLD"}


def test_key_down_fires_action_but_key_up_does_not():
    bus, mapper, _ = make_mapper(keys={"f1": "arm"})
    arm = bus.subscribe("action.arm")
    bus.publish("input.key", {"key": "f1", "pressed": True})
    bus.publish("input.key", {"key": "f1", "pressed": False})
    mapper.pump()
    assert len(drain(arm)) == 1


def test_motion_mappings_are_not_actions():
    bus, mapper, _ = make_mapper(keys={"w": "surge+"})
    subs = [bus.subscribe(topic) for topic in ("action.arm", "action.disarm", "action.set_mode")]
    bus.publish("input.key", {"key": "w", "pressed": True})
    mapper.pump()
    assert all(drain(sub) == [] for sub in subs)


def test_no_active_profile_fires_nothing():
    bus, mapper, profiles = make_mapper(buttons={"0": "arm"})
    profiles.active = None
    arm = bus.subscribe("action.arm")
    bus.publish("input.gamepad", pad(True))
    mapper.pump()
    assert drain(arm) == []


def test_parse_action():
    assert parse_action("arm") == ("action.arm", {})
    assert parse_action("disarm") == ("action.disarm", {})
    assert parse_action("mode:manual") == ("action.set_mode", {"mode": "MANUAL"})
    assert parse_action("surge+") is None
    assert parse_action(None) is None


def test_decoder_publishes_command_ack():
    events = TelemetryDecoder().decode(AckMsg())
    assert events == [("link.command_ack", {"command": 400, "result": 0})]
