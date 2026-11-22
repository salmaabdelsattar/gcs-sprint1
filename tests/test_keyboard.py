import pygame

from gcs.input import Keyboard

NAMES = {pygame.K_w: "w", pygame.K_s: "s"}


class FakeEvent:
    def __init__(self, type, key=0):
        self.type = type
        self.key = key


def make_keyboard():
    return Keyboard(name_func=NAMES.get)


def test_key_down_then_key_up():
    kb = make_keyboard()
    down = kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_w))
    assert down.key == "w" and down.pressed is True
    up = kb.process(FakeEvent(pygame.KEYUP, pygame.K_w))
    assert up.key == "w" and up.pressed is False


def test_multiple_keys_held_at_once():
    kb = make_keyboard()
    kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_w))
    kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_s))
    assert kb.held_keys() == {"w", "s"}
    kb.process(FakeEvent(pygame.KEYUP, pygame.K_w))
    assert kb.held_keys() == {"s"}


def test_auto_repeat_is_ignored():
    kb = make_keyboard()
    assert kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_w)) is not None
    assert kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_w)) is None


def test_key_up_without_key_down_is_ignored():
    kb = make_keyboard()
    assert kb.process(FakeEvent(pygame.KEYUP, pygame.K_w)) is None


def test_other_event_types_are_ignored():
    kb = make_keyboard()
    assert kb.process(FakeEvent(pygame.MOUSEMOTION)) is None


def test_held_actions_use_profile_mapping():
    kb = make_keyboard()
    kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_w))
    kb.process(FakeEvent(pygame.KEYDOWN, pygame.K_s))
    mapping = {"w": "forward", "s": "backward", "x": "unused"}
    assert kb.held_actions(mapping) == {"forward", "backward"}
    