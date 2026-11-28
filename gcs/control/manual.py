"""Steady-rate MANUAL_CONTROL sending with failsafe (R14, R22, R24)."""
import logging
import threading
import time

from .failsafe import Failsafe
from .motion import MotionMapper
from .queues import drain

logger = logging.getLogger(__name__)

NEUTRAL = {"surge": 0.0, "sway": 0.0, "heave": 0.0, "yaw": 0.0}
LOSS_BURST = 3  # neutral commands sent when the link first drops


def _to_int(value, low, high):
    return max(low, min(high, int(round(value))))


def to_manual_control(setpoint):
    """Convert a -1..1 setpoint to MANUAL_CONTROL x, y, z, r values.

    x = surge, y = sway, z = heave (0..1000, where 500 is neutral), r = yaw.
    """
    x = _to_int(setpoint["surge"] * 1000, -1000, 1000)
    y = _to_int(setpoint["sway"] * 1000, -1000, 1000)
    z = _to_int(500 + setpoint["heave"] * 500, 0, 1000)
    r = _to_int(setpoint["yaw"] * 1000, -1000, 1000)
    return x, y, z, r


def manual_control_action(setpoint):
    """Build a link action that sends one MANUAL_CONTROL message."""
    x, y, z, r = to_manual_control(setpoint)

    def action(conn):
        conn.mav.manual_control_send(conn.target_system, x, y, z, r, 0)

    return action


class ControlLoop(threading.Thread):
    """Turns input into MANUAL_CONTROL at a steady rate, with a failsafe.

    Every tick it handles pending input events, checks the failsafe, and
    sends the operator's setpoint, or neutral while the failsafe is active.
    Nothing is sent while the vehicle link is down, apart from a short burst
    of neutral commands when it first drops (so the send queue cannot grow).
    All its state is private to this thread. It talks to the rest of the
    program only through bus queues and the `send` function.
    """

    def __init__(self, bus, send, rate_hz=20, input_timeout_s=0.5, profile=None, clock=time.monotonic):
        super().__init__(name="control-loop", daemon=True)
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self.motion = MotionMapper(bus, profile)
        self.failsafe = Failsafe(bus, input_timeout_s, clock)
        self._send = send
        self._link = bus.subscribe("link.status")
        self._period = 1.0 / rate_hz
        self._clock = clock
        self._stop_event = threading.Event()
        self._link_up = False
        self._burst = 0
        self.sent = 0

    def tick(self):
        """One control step. Returns the setpoint that was sent, or None."""
        setpoint = self.motion.pump()
        failsafe_active = self.failsafe.pump()
        for event in drain(self._link):
            up = bool(event.data.get("connected"))
            if self._link_up and not up:
                self._burst = LOSS_BURST
            self._link_up = up
        if self._link_up:
            to_send = NEUTRAL if failsafe_active else setpoint
        elif self._burst > 0:
            self._burst -= 1
            to_send = NEUTRAL
        else:
            return None
        self._send(manual_control_action(to_send))
        self.sent += 1
        return to_send

    def run(self):
        logger.info("Control loop started at %.0f Hz", 1.0 / self._period)
        next_tick = self._clock()
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Control tick failed; sending neutral")
                self._safe_neutral()
            next_tick += self._period
            delay = next_tick - self._clock()
            if delay > 0:
                self._stop_event.wait(delay)
            else:
                next_tick = self._clock()
        self._safe_neutral()
        logger.info("Control loop stopped")

    def _safe_neutral(self):
        if not self._link_up:
            return
        try:
            self._send(manual_control_action(NEUTRAL))
        except Exception:
            logger.exception("Could not send neutral command")

    def stop(self, timeout=1.0):
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)
