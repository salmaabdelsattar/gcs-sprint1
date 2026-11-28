"""Small helper for reading everything waiting on a subscription."""
import queue


def drain(sub):
    """Return all events currently waiting on a subscription."""
    events = []
    while True:
        try:
            events.append(sub.get_nowait())
        except queue.Empty:
            return events
