"""Settings and mapping-profile loading (R8, R19)."""
import copy
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "sampling_rate_hz": 50,
    "deadzone": 0.1,
    "log_level": "INFO",
    "log_file": "logs/gcs.log",
    "profiles_dir": "configs/profiles",
    "network": {"host": "127.0.0.1", "port": 5760},
}


def _merge(base, override):
    """Recursively merge override into base."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_settings(path="configs/settings.json"):
    """Load settings from file, falling back to defaults for missing keys."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    path = Path(path)
    if path.exists():
        with path.open(encoding="utf-8") as f:
            _merge(settings, json.load(f))
        logger.info("Loaded settings from %s", path)
    else:
        logger.warning("Settings file %s not found, using defaults", path)
    return settings


class ProfileManager:
    """Named mapping profiles stored as JSON files, switchable at runtime."""

    def __init__(self, profiles_dir):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.active = None

    def list_profiles(self):
        return sorted(p.stem for p in self.profiles_dir.glob("*.json"))

    def load(self, name):
        path = self.profiles_dir / f"{name}.json"
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def save(self, name, profile):
        path = self.profiles_dir / f"{name}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
        logger.info("Saved profile %s", name)

    def activate(self, name):
        """Apply a profile without restarting the program."""
        self.active = self.load(name)
        logger.info("Activated profile %s", name)
        return self.active

    def find_for_controller(self, controller_name):
        """Return the profile name matching a controller, or None."""
        for name in self.list_profiles():
            if self.load(name).get("controller") == controller_name:
                return name
        return None

    def activate_for_controller(self, controller_name):
        """Auto-load the profile for a newly connected controller."""
        name = self.find_for_controller(controller_name)
        if name is None:
            logger.warning("No profile for controller %s", controller_name)
            return None
        return self.activate(name)