"""Controller hot-plug detection (R4)."""
import logging
import os

logger = logging.getLogger(__name__)


class ControllerTracker:
    """Tracks which controllers are connected and reports changes.

    Pure logic with no pygame, so it is easy to test. Each method returns
    a list of (topic, data) pairs ready to publish on the event bus.
    """

    def __init__(self):
        self._devices = {}

    @property
    def devices(self):
        return dict(self._devices)

    def added(self, device_id, name):
        if device_id in self._devices:
            return []
        self._devices[device_id] = name
        logger.info("Controller connected: %s", name)
        return [
            ("controller.connected", {"device_id": device_id, "name": name}),
            (
                "operator.notice",
                {"level": "info", "message": f"Controller connected: {name}"},
            ),
        ]

    def removed(self, device_id):
        name = self._devices.pop(device_id, None)
        if name is None:
            return []
        logger.warning("Controller disconnected: %s", name)
        return [
            ("controller.disconnected", {"device_id": device_id, "name": name}),
            (
                "operator.notice",
                {"level": "warning", "message": f"Controller disconnected: {name}"},
            ),
        ]


class HotplugMonitor:
    """Watches pygame for controllers being plugged in or removed.

    Use `monitor.poll` as a source for the Sampler.
    """

    def __init__(self, tracker=None):
        self.tracker = tracker or ControllerTracker()
        self._joysticks = {}  # keep references so pygame keeps devices open
        self._started = False

    def start(self):
        # A dummy video driver lets pygame run without opening a window.
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        pygame.display.init()
        pygame.joystick.init()
        self._started = True

    def poll(self):
        """Return (topic, data) pairs for any connect/disconnect since last call."""
        if not self._started:
            self.start()
        import pygame

        results = []
        events = pygame.event.get([pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED])
        for event in events:
            if event.type == pygame.JOYDEVICEADDED:
                try:
                    joy = pygame.joystick.Joystick(event.device_index)
                except pygame.error:
                    logger.exception("Could not open new controller")
                    continue
                device_id = joy.get_instance_id()
                self._joysticks[device_id] = joy
                results += self.tracker.added(device_id, joy.get_name())
            else:
                self._joysticks.pop(event.instance_id, None)
                results += self.tracker.removed(event.instance_id)
        return results
