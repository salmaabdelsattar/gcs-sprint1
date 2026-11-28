"""Arm/disarm and flight-mode commands, confirmed by the vehicle (R21)."""
import logging
import queue
import time
from dataclasses import dataclass

from gcs.link import MODE_NUMBERS

logger = logging.getLogger(__name__)

CMD_DO_SET_MODE = 176
CMD_ARM_DISARM = 400

ACCEPTED = 0
IN_PROGRESS = 5
RESULT_NAMES = {
    0: "accepted",
    1: "temporarily rejected",
    2: "denied",
    3: "unsupported",
    4: "failed",
    5: "in progress",
    6: "cancelled",
}


def arm_disarm_action(arm):
    """Build a link action that sends MAV_CMD_COMPONENT_ARM_DISARM."""

    def action(conn):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component, CMD_ARM_DISARM, 0, 1 if arm else 0, 0, 0, 0, 0, 0, 0
        )

    return action


def set_mode_action(mode_number):
    """Build a link action that sends MAV_CMD_DO_SET_MODE."""

    def action(conn):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component, CMD_DO_SET_MODE, 0, 1, mode_number, 0, 0, 0, 0, 0
        )

    return action


@dataclass
class Pending:
    """A command sent to the vehicle that has not been confirmed yet."""

    name: str
    command_id: int
    deadline: float
    armed: object = None
    mode: object = None


class VehicleCommander:
    """Turns action.* events into MAVLink commands and confirms each one.

    A command is confirmed by an accepted COMMAND_ACK or by a heartbeat
    that shows the new armed state or flight mode. If the vehicle refuses,
    or neither arrives in time, the operator is told.
    """

    def __init__(self, bus, send, timeout_s=2.0, clock=time.monotonic):
        self._bus = bus
        self._send = send
        self._timeout = timeout_s
        self._clock = clock
        self._pending = {}
        self._connected = False
        topics = {
            "status": "link.status",
            "arm": "action.arm",
            "disarm": "action.disarm",
            "mode": "action.set_mode",
            "ack": "link.command_ack",
            "heartbeat": "link.heartbeat",
        }
        self._subs = {name: bus.subscribe(topic) for name, topic in topics.items()}

    def pump(self):
        """Handle all pending events and expire overdue commands."""
        self._drain("status", self._on_status)
        self._drain("arm", lambda event: self._request_arm(True))
        self._drain("disarm", lambda event: self._request_arm(False))
        self._drain("mode", self._on_mode_request)
        self._drain("ack", self._on_ack)
        self._drain("heartbeat", self._on_heartbeat)
        self._expire()

    def _drain(self, name, handler):
        sub = self._subs[name]
        while True:
            try:
                event = sub.get_nowait()
            except queue.Empty:
                return
            handler(event)

    def _deadline(self):
        return self._clock() + self._timeout

    def _on_status(self, event):
        self._connected = bool(event.data.get("connected"))
        if not self._connected:
            for pending in list(self._pending.values()):
                self._fail(pending, "link lost")

    def _request_arm(self, arm):
        name = "arm" if arm else "disarm"
        pending = Pending(name, CMD_ARM_DISARM, self._deadline(), armed=arm)
        self._start(pending, arm_disarm_action(arm))

    def _on_mode_request(self, event):
        mode = str(event.data.get("mode", "")).upper()
        if mode not in MODE_NUMBERS:
            self._fail(Pending(f"mode {mode}", CMD_DO_SET_MODE, 0.0), f"unknown mode {mode!r}")
            return
        pending = Pending(f"mode {mode}", CMD_DO_SET_MODE, self._deadline(), mode=mode)
        self._start(pending, set_mode_action(MODE_NUMBERS[mode]))

    def _start(self, pending, action):
        if not self._connected:
            self._fail(pending, "vehicle not connected")
            return
        self._pending[pending.command_id] = pending
        self._send(action)
        self._bus.publish("command.sent", {"command": pending.name})
        logger.info("Sent command: %s", pending.name)

    def _on_ack(self, event):
        pending = self._pending.get(event.data.get("command"))
        if pending is None:
            return
        result = event.data.get("result")
        if result == ACCEPTED:
            self._confirm(pending, "ack")
        elif result == IN_PROGRESS:
            pending.deadline = self._deadline()
        else:
            self._fail(pending, RESULT_NAMES.get(result, f"result {result}"))

    def _on_heartbeat(self, event):
        for pending in list(self._pending.values()):
            if pending.armed is not None and event.data.get("armed") == pending.armed:
                self._confirm(pending, "heartbeat")
            elif pending.mode is not None and event.data.get("mode") == pending.mode:
                self._confirm(pending, "heartbeat")

    def _expire(self):
        now = self._clock()
        for pending in list(self._pending.values()):
            if now >= pending.deadline:
                self._fail(pending, "no response from vehicle")

    def _confirm(self, pending, via):
        self._pending.pop(pending.command_id, None)
        logger.info("Command confirmed (%s): %s", via, pending.name)
        self._bus.publish("command.confirmed", {"command": pending.name, "via": via})
        message = f"Vehicle confirmed: {pending.name}"
        self._bus.publish("operator.notice", {"level": "info", "message": message})

    def _fail(self, pending, reason):
        self._pending.pop(pending.command_id, None)
        logger.warning("Command failed (%s): %s", pending.name, reason)
        self._bus.publish("command.failed", {"command": pending.name, "reason": reason})
        message = f"Command failed ({pending.name}): {reason}"
        self._bus.publish("operator.notice", {"level": "warning", "message": message})
