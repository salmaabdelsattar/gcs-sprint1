"""Fixed-rate input sampling thread (R3, R14)."""
import logging
import threading
import time

logger = logging.getLogger(__name__)


class Sampler(threading.Thread):
    """Polls input sources at a fixed rate and publishes to the event bus.

    A source is any function that returns a list of (topic, data) pairs.
    The loop is never blocked by slow subscribers (publish never waits)
    and a failing source is logged without stopping the thread.
    """

    def __init__(self, bus, sources, rate_hz=50, name="input-sampler"):
        super().__init__(name=name, daemon=True)
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self._bus = bus
        self._sources = list(sources)
        self._period = 1.0 / rate_hz
        self.rate_hz = rate_hz
        self._stop_event = threading.Event()
        self.ticks = 0
        self.overruns = 0

    def run(self):
        logger.info("Sampler started at %s Hz", self.rate_hz)
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            self._tick()
            next_tick += self._period
            delay = next_tick - time.monotonic()
            if delay > 0:
                self._stop_event.wait(delay)
            else:
                # Running late: count it and resync instead of bursting.
                self.overruns += 1
                next_tick = time.monotonic()
        logger.info("Sampler stopped after %d ticks", self.ticks)

    def _tick(self):
        for source in self._sources:
            try:
                for topic, data in source():
                    self._bus.publish(topic, data)
            except Exception:
                logger.exception("Input source failed; continuing")
        self.ticks += 1

    def stop(self, timeout=1.0):
        """Ask the thread to finish and wait for it."""
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)


def gamepad_source(gamepad):
    """Adapt a Gamepad into a sampler source."""

    def source():
        state = gamepad.read()
        if state is None:
            return []
        return [
            (
                "input.gamepad",
                {
                    "name": state.name,
                    "axes": state.axes,
                    "buttons": state.buttons,
                    "hats": state.hats,
                },
            )
        ]

    return source


def keyboard_source(keyboard):
    """Adapt a Keyboard into a sampler source."""

    def source():
        return [
            ("input.key", {"key": e.key, "pressed": e.pressed})
            for e in keyboard.poll()
        ]

    return source