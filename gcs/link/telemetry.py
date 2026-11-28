"""Heartbeat monitoring and telemetry decoding (R20, R23)."""
import time

GCS_TYPE = 6  # MAV_TYPE_GCS: heartbeats from other ground stations are ignored
ARMED_FLAG = 128  # MAV_MODE_FLAG_SAFETY_ARMED

# ArduSub flight modes: custom_mode number -> name
ARDUSUB_MODES = {
    0: "STABILIZE",
    1: "ACRO",
    2: "ALT_HOLD",
    3: "AUTO",
    4: "GUIDED",
    7: "CIRCLE",
    9: "SURFACE",
    16: "POSHOLD",
    19: "MANUAL",
}
MODE_NUMBERS = {name: number for number, name in ARDUSUB_MODES.items()}


class HeartbeatMonitor:
    """Detects when the vehicle's heartbeat starts and when it is lost.

    Each method returns (topic, data) pairs ready to publish on the bus.
    """

    def __init__(self, timeout_s=3.0, clock=time.monotonic):
        self._timeout = timeout_s
        self._clock = clock
        self._last = None
        self.connected = False

    def beat(self):
        """Call whenever a vehicle heartbeat arrives."""
        self._last = self._clock()
        if self.connected:
            return []
        self.connected = True
        return [
            ("link.status", {"connected": True}),
            ("operator.notice", {"level": "info", "message": "Vehicle heartbeat received"}),
        ]

    def check(self):
        """Call regularly. Reports once when the heartbeat goes missing."""
        if not self.connected:
            return []
        if self._clock() - self._last <= self._timeout:
            return []
        self.connected = False
        return [
            ("link.status", {"connected": False}),
            ("operator.notice", {"level": "warning", "message": "Vehicle heartbeat lost"}),
        ]


class TelemetryDecoder:
    """Turns MAVLink messages into bus events and keeps the latest state."""

    def __init__(self):
        self.state = {"armed": None, "mode": None, "altitude_m": None, "depth_m": None}

    def decode(self, msg):
        kind = msg.get_type()
        if kind == "HEARTBEAT":
            if msg.type == GCS_TYPE:
                return []
            armed = bool(msg.base_mode & ARMED_FLAG)
            mode = ARDUSUB_MODES.get(msg.custom_mode, f"MODE_{msg.custom_mode}")
            beat = ("link.heartbeat", {"armed": armed, "mode": mode})
            return [beat] + self._update({"armed": armed, "mode": mode})
        if kind == "VFR_HUD":
            altitude = float(msg.alt)
            return self._update({"altitude_m": altitude, "depth_m": -altitude})
        return []

    def _update(self, changes):
        if all(self.state[key] == value for key, value in changes.items()):
            return []
        self.state.update(changes)
        return [("telemetry.update", dict(self.state))]
