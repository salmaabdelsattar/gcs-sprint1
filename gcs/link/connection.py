"""MAVLink I/O thread (R14, R20, R23)."""
import logging
import queue
import threading
import time

from .telemetry import HeartbeatMonitor, TelemetryDecoder

logger = logging.getLogger(__name__)

GCS_TYPE = 6
AUTOPILOT_INVALID = 8


def default_connect(url):
    from pymavlink import mavutil

    return mavutil.mavlink_connection(url, source_system=255)


class MavlinkLink(threading.Thread):
    """Receives MAVLink, publishes events on the bus, and sends queued actions.

    Other modules never touch the connection. They call link.send(action),
    where action(conn) runs on this thread, so the socket is never shared.
    """

    def __init__(self, bus, url, heartbeat_timeout_s=3.0, connect=None, clock=time.monotonic):
        super().__init__(name="mavlink-link", daemon=True)
        self._bus = bus
        self._url = url
        self._connect = connect or (lambda: default_connect(url))
        self._clock = clock
        self._monitor = HeartbeatMonitor(heartbeat_timeout_s, clock)
        self._decoder = TelemetryDecoder()
        self._outgoing = queue.Queue()
        self._stop_event = threading.Event()
        self._conn = None
        self._last_gcs_beat = float("-inf")
        self.messages = 0

    @property
    def connected(self):
        return self._monitor.connected

    def send(self, action):
        """Queue action(conn) to run on the link thread. Safe from any thread."""
        self._outgoing.put(action)

    def stop(self, timeout=1.0):
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)

    def run(self):
        logger.info("MAVLink link started (%s)", self._url)
        while not self._stop_event.is_set():
            if self._conn is None and not self._open():
                self._stop_event.wait(2.0)
                continue
            try:
                self._cycle()
            except Exception:
                logger.exception("MAVLink link error; reconnecting")
                self._conn = None
                self._stop_event.wait(1.0)
        logger.info("MAVLink link stopped")

    def _open(self):
        try:
            self._conn = self._connect()
        except Exception as exc:
            logger.warning("Could not open MAVLink connection %s: %s", self._url, exc)
            return False
        logger.info("MAVLink connection open: %s", self._url)
        return True

    def _cycle(self):
        self._send_pending()
        self._send_gcs_heartbeat()
        msg = self._conn.recv_match(blocking=True, timeout=0.05)
        if msg is not None:
            self.messages += 1
            events = self._decoder.decode(msg)
            if events and msg.get_type() == "HEARTBEAT":
                events = self._monitor.beat() + events
            self._publish(events)
        self._publish(self._monitor.check())

    def _send_pending(self):
        while True:
            try:
                action = self._outgoing.get_nowait()
            except queue.Empty:
                return
            try:
                action(self._conn)
            except Exception:
                logger.exception("Failed to send MAVLink message")

    def _send_gcs_heartbeat(self):
        now = self._clock()
        if now - self._last_gcs_beat >= 1.0:
            self._last_gcs_beat = now
            self._conn.mav.heartbeat_send(GCS_TYPE, AUTOPILOT_INVALID, 0, 0, 0)

    def _publish(self, events):
        for topic, data in events:
            self._bus.publish(topic, data)
