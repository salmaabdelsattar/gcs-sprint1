from gcs.config import ProfileAutoLoader, ProfileManager
from gcs.events import EventBus
from gcs.input import ControllerTracker


def topics(events):
    return [topic for topic, _ in events]


def test_connect_reports_event_and_operator_notice():
    tracker = ControllerTracker()
    out = tracker.added(1, "Pad A")
    assert topics(out) == ["controller.connected", "operator.notice"]
    assert out[0][1]["name"] == "Pad A"
    assert out[1][1]["level"] == "info"
    assert tracker.devices == {1: "Pad A"}


def test_duplicate_connect_is_ignored():
    tracker = ControllerTracker()
    tracker.added(1, "Pad A")
    assert tracker.added(1, "Pad A") == []


def test_disconnect_reports_event_and_warning():
    tracker = ControllerTracker()
    tracker.added(1, "Pad A")
    out = tracker.removed(1)
    assert topics(out) == ["controller.disconnected", "operator.notice"]
    assert out[1][1]["level"] == "warning"
    assert tracker.devices == {}


def test_disconnect_of_unknown_device_is_ignored():
    assert ControllerTracker().removed(99) == []


def test_reconnect_after_disconnect_is_reported_again():
    tracker = ControllerTracker()
    tracker.added(1, "Pad A")
    tracker.removed(1)
    assert topics(tracker.added(2, "Pad A")) == [
        "controller.connected",
        "operator.notice",
    ]


def test_autoload_activates_matching_profile(tmp_path):
    bus = EventBus()
    profiles = ProfileManager(tmp_path)
    profiles.save("padb", {"name": "padb", "controller": "Pad B"})
    loader = ProfileAutoLoader(bus, profiles)
    activated = bus.subscribe("profile.activated")

    bus.publish("controller.connected", {"name": "Pad B"})

    assert loader.pump() == 1
    assert activated.get(timeout=1).data["profile"] == "padb"
    assert profiles.active["controller"] == "Pad B"


def test_autoload_warns_operator_when_no_profile(tmp_path):
    bus = EventBus()
    loader = ProfileAutoLoader(bus, ProfileManager(tmp_path))
    notices = bus.subscribe("operator.notice")

    bus.publish("controller.connected", {"name": "Mystery Pad"})

    assert loader.pump() == 1
    assert notices.get(timeout=1).data["level"] == "warning"
