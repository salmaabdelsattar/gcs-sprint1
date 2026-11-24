from gcs.config import ProfileManager, load_settings


def test_missing_settings_uses_defaults(tmp_path):
    s = load_settings(tmp_path / "nope.json")
    assert s["sampling_rate_hz"] == 50


def test_profile_save_load_roundtrip(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.save("a", {"controller": "Pad A", "axes": {"0": "yaw"}})
    assert pm.list_profiles() == ["a"]
    assert pm.load("a")["axes"]["0"] == "yaw"


def test_auto_load_profile_for_controller(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.save("a", {"controller": "Pad A"})
    pm.save("b", {"controller": "Pad B"})
    assert pm.activate_for_controller("Pad B")["controller"] == "Pad B"
    assert pm.activate_for_controller("Unknown") is None
