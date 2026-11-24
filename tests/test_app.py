import json

from gcs.app import Application


def make_app(tmp_path, out=print):
    settings = {
        "sampling_rate_hz": 50,
        "deadzone": 0.1,
        "log_level": "INFO",
        "log_file": str(tmp_path / "logs" / "t.log"),
        "profiles_dir": str(tmp_path / "profiles"),
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    return Application(str(path), out=out)


def test_profile_sets_gamepad_deadzone(tmp_path):
    app = make_app(tmp_path)
    app.profiles.save("padb", {"name": "padb", "controller": "Pad B", "deadzone": 0.25})
    app.bus.publish("controller.connected", {"name": "Pad B"})
    app.step()
    assert app.gamepad.deadzone == 0.25


def test_disconnect_closes_gamepad(tmp_path):
    app = make_app(tmp_path)
    app.gamepad._joystick = object()  # pretend a controller is open
    assert app.gamepad.is_connected
    app.bus.publish("controller.disconnected", {"name": "Pad"})
    app.step()
    assert not app.gamepad.is_connected


def test_operator_notices_are_printed(tmp_path):
    lines = []
    app = make_app(tmp_path, out=lines.append)
    app.bus.publish(
        "operator.notice",
        {"level": "warning", "message": "Controller disconnected: Pad"},
    )
    app.step()
    assert lines == ["[WARNING] Controller disconnected: Pad"]


def test_unchanged_gamepad_state_is_not_reprinted(tmp_path):
    lines = []
    app = make_app(tmp_path, out=lines.append)
    data = {"name": "Pad", "axes": (0.0, 0.5), "buttons": (True,), "hats": ((0, 0),)}
    app.bus.publish("input.gamepad", data)
    app.bus.publish("input.gamepad", data)
    app.step()
    assert len(lines) == 1
    assert "buttons=[0]" in lines[0]
