"""Thread-safe publish-subscribe event bus (R15, R18)."""
import logging
import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

WILDCARD = "*"


@dataclass(frozen=True)
class Event:
    """An immutable message published on the bus."""

    topic: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


class Subscription:
    """A subscriber's private queue of events for one topic."""

    def __init__(self, bus, topic, maxsize):
        self._bus = bus
        self.topic = topic
        self.queue = queue.Queue(maxsize=maxsize)

    def get(self, timeout=None):
        """Wait for the next event. Raises queue.Empty on timeout."""
        return self.queue.get(timeout=timeout)

    def get_nowait(self):
        """Return the next event now. Raises queue.Empty if none."""
        return self.queue.get_nowait()

    def close(self):
        self._bus.unsubscribe(self)


class EventBus:
    """Modules publish by topic; subscribers read from their own queue."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = defaultdict(list)

    def subscribe(self, topic, maxsize=1000):
        """Subscribe to a topic, or to WILDCARD ("*") for every topic."""
        sub = Subscription(self, topic, maxsize)
        with self._lock:
            self._subscribers[topic].append(sub)
        logger.debug("Subscribed to %s", topic)
        return sub

    def unsubscribe(self, sub):
        with self._lock:
            subs = self._subscribers.get(sub.topic, [])
            if sub in subs:
                subs.remove(sub)

    def publish(self, topic, data=None):
        """Deliver an event to all subscribers without ever blocking."""
        event = Event(topic, dict(data or {}))
        with self._lock:
            targets = list(self._subscribers.get(topic, []))
            if topic != WILDCARD:
                targets += self._subscribers.get(WILDCARD, [])
        for sub in targets:
            try:
                sub.queue.put_nowait(event)
            except queue.Full:
                logger.warning("Subscriber queue full, dropped event on %s", topic)
        return event