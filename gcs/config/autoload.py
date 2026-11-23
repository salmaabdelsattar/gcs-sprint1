"""Auto-load mapping profiles when a controller connects (R8, R18)."""
import logging
import queue

logger = logging.getLogger(__name__)


class ProfileAutoLoader:
    """Listens on the event bus and activates the profile for a new controller.

    Call pump() regularly (or from a thread) to handle pending events.
    """

    def __init__(self, bus, profiles):
        self._bus = bus
        self._profiles = profiles
        self._sub = bus.subscribe("controller.connected")

    def pump(self):
        """Handle all pending connect events. Returns how many were handled."""
        handled = 0
        while True:
            try:
                event = self._sub.get_nowait()
            except queue.Empty:
                return handled
            self._handle(event)
            handled += 1

    def _handle(self, event):
        controller = event.data.get("name", "")
        profile = self._profiles.activate_for_controller(controller)
        if profile is None:
            self._bus.publish(
                "operator.notice",
                {
                    "level": "warning",
                    "message": f"No profile found for controller: {controller}",
                },
            )
            return
        profile_name = profile.get("name", controller)
        logger.info("Auto-loaded profile %s for %s", profile_name, controller)
        self._bus.publish(
            "profile.activated",
            {"profile": profile_name, "controller": controller},
        )
        self._bus.publish(
            "operator.notice",
            {"level": "info", "message": f"Loaded profile: {profile_name}"},
        )