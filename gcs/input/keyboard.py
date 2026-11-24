"""Keyboard input: key down and key up events (R2)."""
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyEvent:
    """One key press or release."""

    key: str
    pressed: bool
    timestamp: float = field(default_factory=time.monotonic)


class Keyboard:
    """Turns pygame key events into KeyEvents and tracks held keys."""

    def __init__(self, name_func=None):
        # name_func maps a pygame key code to a name like "w".
        # Defaults to pygame.key.name; tests pass a fake.
        self._name_func = name_func
        self._held = set()

    def _name(self, code):
        if self._name_func is not None:
            return self._name_func(code)
        import pygame

        return pygame.key.name(code)

    def process(self, event):
        """Convert one pygame event. Returns a KeyEvent, or None to ignore."""
        import pygame

        if event.type == pygame.KEYDOWN:
            pressed = True
        elif event.type == pygame.KEYUP:
            pressed = False
        else:
            return None

        key = self._name(event.key)
        if pressed:
            if key in self._held:  # OS auto-repeat, not a new press
                return None
            self._held.add(key)
        else:
            if key not in self._held:
                return None
            self._held.discard(key)
        return KeyEvent(key, pressed)

    def poll(self):
        """Collect all pending key events from pygame's queue."""
        import pygame

        events = pygame.event.get([pygame.KEYDOWN, pygame.KEYUP])
        results = (self.process(e) for e in events)
        return [r for r in results if r is not None]

    def held_keys(self):
        return frozenset(self._held)

    def held_actions(self, mapping):
        """Actions for the keys now held, using a profile's "keys" mapping."""
        return {mapping[k] for k in self._held if k in mapping}
