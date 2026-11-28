"""Turns controller and keyboard input into a motion setpoint (R22)."""
from .queues import drain

AXIS_NAMES = ("surge", "sway", "heave", "yaw")


def clamp(value):
    return max(-1.0, min(1.0, value))


def compute_setpoint(axes, held_keys, profile):
    """Combine stick axes and held keys into surge/sway/heave/yaw, each -1.0 to 1.0.

    The profile says which axis index drives which motion ("axes"), which
    motions to flip ("invert"), and which keys push a motion ("keys").
    """
    result = dict.fromkeys(AXIS_NAMES, 0.0)
    invert = set(profile.get("invert", []))
    for index, name in profile.get("axes", {}).items():
        try:
            position = int(index)
        except ValueError:
            continue
        if name in result and position < len(axes):
            result[name] += -axes[position] if name in invert else axes[position]
    for key, action in profile.get("keys", {}).items():
        if key not in held_keys or not isinstance(action, str) or len(action) < 2:
            continue
        name, sign = action[:-1], action[-1]
        if name in result and sign in "+-":
            result[name] += 1.0 if sign == "+" else -1.0
    return {name: clamp(value) for name, value in result.items()}


class MotionMapper:
    """Keeps the latest input state and publishes control.setpoint when it changes.

    The active profile arrives on the bus (profile.activated), so this can
    run in its own thread without sharing objects with the rest of the app.
    """

    def __init__(self, bus, profile=None):
        self._bus = bus
        self._profile = profile or {}
        self._profile_events = bus.subscribe("profile.activated")
        self._gamepad = bus.subscribe("input.gamepad")
        self._keys = bus.subscribe("input.key")
        self._disconnected = bus.subscribe("controller.disconnected")
        self._axes = ()
        self._held = set()
        self.setpoint = dict.fromkeys(AXIS_NAMES, 0.0)

    def pump(self):
        """Handle pending events. Returns the current setpoint."""
        for event in drain(self._profile_events):
            self._profile = event.data.get("data") or {}
        for event in drain(self._gamepad):
            self._axes = tuple(event.data.get("axes", ()))
        for event in drain(self._keys):
            key = event.data.get("key")
            if event.data.get("pressed"):
                self._held.add(key)
            else:
                self._held.discard(key)
        if drain(self._disconnected):
            self._axes = ()
        setpoint = compute_setpoint(self._axes, self._held, self._profile)
        if setpoint != self.setpoint:
            self.setpoint = setpoint
            self._bus.publish("control.setpoint", dict(setpoint))
        return self.setpoint
