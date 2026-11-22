import queue
import threading

import pytest

from gcs.events import EventBus


def test_subscriber_receives_published_event():
    bus = EventBus()
    sub = bus.subscribe("input.button")
    bus.publish("input.button", {"id": 0, "pressed": True})
    event = sub.get(timeout=1)
    assert event.topic == "input.button"
    assert event.data["id"] == 0


def test_topics_are_isolated():
    bus = EventBus()
    sub = bus.subscribe("a")
    bus.publish("b", {})
    with pytest.raises(queue.Empty):
        sub.get(timeout=0.1)


def test_wildcard_receives_every_topic():
    bus = EventBus()
    sub = bus.subscribe("*")
    bus.publish("a", {})
    bus.publish("b", {})
    assert {sub.get(timeout=1).topic, sub.get(timeout=1).topic} == {"a", "b"}


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    sub = bus.subscribe("a")
    sub.close()
    bus.publish("a", {})
    with pytest.raises(queue.Empty):
        sub.get(timeout=0.1)


def test_full_queue_never_blocks_publisher():
    bus = EventBus()
    bus.subscribe("a", maxsize=1)
    bus.publish("a", {})
    bus.publish("a", {})  # would hang if publish blocked


def test_publish_from_many_threads():
    bus = EventBus()
    sub = bus.subscribe("a")

    def worker():
        for _ in range(100):
            bus.publish("a", {})

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sub.queue.qsize() == 400