"""Game controller reading via pygame (R1, R5)."""
import logging
import os
from dataclasses import dataclass

from .deadzone import apply_deadzone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GamepadState:
    """A snapshot of one controller at one moment."""

    name: str
    axes: tuple
    buttons: tuple
    hats: tuple


def read_state(joystick, deadzone, name=""):
    """Build a GamepadState from any joystick-like object."""
    axes = tuple(
        apply_deadzone(joystick.get_axis(i), deadzone)
        for i in range(joystick.get_numaxes())
    )
    buttons = tuple(
        bool(joystick.get_button(i)) for i in range(joystick.get_numbuttons())
    )
    hats = tuple(joystick.get_hat(i) for i in range(joystick.get_numhats()))
    return GamepadState(name, axes, buttons, hats)


class Gamepad:
    """Wraps pygame's joystick API. Call open(), then read() repeatedly."""

    def __init__(self, deadzone=0.1):
        self.deadzone = deadzone
        self._joystick = None
        self.name = ""

    @property
    def is_connected(self):
        return self._joystick is not None

    def open(self, index=0):
        """Connect to controller number `index`. Returns True on success."""
        # A dummy video driver lets pygame pump events without a window.
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame

        pygame.display.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() <= index:
            logger.warning("No controller found at index %d", index)
            return False
        self._joystick = pygame.joystick.Joystick(index)
        self.name = self._joystick.get_name()
        logger.info("Connected to controller: %s", self.name)
        return True

    def read(self):
        """Return the current GamepadState, or None if not connected."""
        if self._joystick is None:
            return None
        import pygame

        pygame.event.pump()
        return read_state(self._joystick, self.deadzone, self.name)

    def close(self):
        self._joystick = None
        logger.info("Controller closed")