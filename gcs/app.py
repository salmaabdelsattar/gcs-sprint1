"""Headless application wiring (R14, R17, R18)."""
import logging
import queue
import time

from gcs.config import ProfileAutoLoader, ProfileManager, load_settings
from gcs.events import EventBus
from gcs.input import Gamepad, HotplugMonitor, Sampler, gamepad_source
from gcs.logging_setup import setup_logging

logger = logging.getLogger(__name__)


class Application:
    """Creates the modules and connects them through the event bus."""

    def __init__(self, settings_path="configs/settings.json", out=print):
        self.settings = load_settings(settings_path)
        setup_logging(self.settings)
        self._out = out
        self.bus = EventBus()
        self.profiles = ProfileManager(self.settings["profiles_dir"])
        self.autoloader = ProfileAutoLoader(self.bus, self.profiles)
        self.hotplug = HotplugMonitor()
        self.gamepad = Gamepad(self.settings["deadzone"])
        self._connected = self.bus.subscribe("controller.connected")
        self._disconnected = self.bus.subscribe("controller.disconnected")
        self._activated = self.bus.subscribe("profile.activated")
        self._everything = self.bus.subscribe("*")
        self._last_pad = None

    def step(self):
        """Handle all pending events once. Called in a loop by run()."""
        self.autoloader.pump()
        self._drain(self._connected, self._on_connected)
        self._drain(self._disconnected, self._on_disconnected)
        self._drain(self._activated, self._on_profile_activated)
        self._drain(self._everything, self._print_event)

    @staticmethod
    def _drain(sub, handler):
        while True:
            try:
                event = sub.get_nowait()
            except queue.Empty:
                return
            handler(event)

    def _on_connected(self, event):
        if not self.gamepad.is_connected:
            self.gamepad.open()

    def _on_disconnected(self, event):
        self.gamepad.close()

    def _on_profile_activated(self, event):
        profile = self.profiles.active or {}
        self.gamepad.deadzone = profile.get("deadzone", self.settings["deadzone"])
        logger.info("Dead-zone is now %s", self.gamepad.deadzone)

    def _print_event(self, event):
        line = self._describe(event)
        if line:
            self._out(line)

    def _describe(self, event):
        data = event.data
        if event.topic == "input.gamepad":
            snapshot = (data["axes"], data["buttons"], data["hats"])
            if snapshot == self._last_pad:
                return None  # unchanged, don't flood the console
            self._last_pad = snapshot
            axes = [round(a, 2) for a in data["axes"]]
            pressed = [i for i, b in enumerate(data["buttons"]) if b]
            return f"gamepad {data['name']}: axes={axes} buttons={pressed} hats={list(data['hats'])}"
        if event.topic == "input.key":
            return f"key {data['key']} {'down' if data['pressed'] else 'up'}"
        if event.topic == "operator.notice":
            return f"[{data['level'].upper()}] {data['message']}"
        return f"{event.topic} {data}"

    def run(self, duration=None):
        """Start sampling and loop until Ctrl+C (or `duration` seconds)."""
        self.hotplug.start()
        sampler = Sampler(
            self.bus,
            [self.hotplug.poll, gamepad_source(self.gamepad)],
            rate_hz=self.settings["sampling_rate_hz"],
        )
        sampler.start()
        logger.info("GCS started. Press Ctrl+C to stop.")
        end = None if duration is None else time.monotonic() + duration
        try:
            while end is None or time.monotonic() < end:
                self.step()
                time.sleep(0.02)
        except KeyboardInterrupt:
            logger.info("Interrupted by operator")
        finally:
            sampler.stop()
            self.gamepad.close()
            logger.info("GCS stopped")