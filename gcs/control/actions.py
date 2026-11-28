"""Turns controller buttons and keys into named actions (R21)."""
import queue


def parse_action(value):
    """Return (topic, data) for a profile action name, or None if it is not an action."""
    if value == "arm":
        return "action.arm", {}
    if value == "disarm":
        return "action.disarm", {}
    if isinstance(value, str) and value.startswith("mode:"):
        return "action.set_mode", {"mode": value.split(":", 1)[1].strip().upper()}
    return None


class ActionMapper:
    """Publishes action.* events on button presses and key-downs.

    Uses the buttons and keys of the active profile. Holding a button
    fires once, not on every sample.
    """

    def __init__(self, bus, profiles):
        self._bus = bus
        self._profiles = profiles
        self._gamepad = bus.subscribe("input.gamepad")
        self._keys = bus.subscribe("input.key")
        self._last_buttons = ()

    def pump(self):
        """Handle all pending input events."""
        profile = self._profiles.active or {}
        for event in self._drain(self._gamepad):
            self._on_gamepad(event.data, profile.get("buttons", {}))
        for event in self._drain(self._keys):
            self._on_key(event.data, profile.get("keys", {}))

    @staticmethod
    def _drain(sub):
        events = []
        while True:
            try:
                events.append(sub.get_nowait())
            except queue.Empty:
                return events

    def _on_gamepad(self, data, mapping):
        buttons = data.get("buttons", ())
        for index, pressed in enumerate(buttons):
            was_pressed = index < len(self._last_buttons) and self._last_buttons[index]
            if pressed and not was_pressed:
                self._fire(mapping.get(str(index)))
        self._last_buttons = buttons

    def _on_key(self, data, mapping):
        if data.get("pressed"):
            self._fire(mapping.get(data.get("key")))

    def _fire(self, value):
        parsed = parse_action(value)
        if parsed is not None:
            topic, data = parsed
            self._bus.publish(topic, data)
