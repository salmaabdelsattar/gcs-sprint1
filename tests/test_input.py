import pytest

from gcs.input import apply_deadzone, read_state


class FakeJoystick:
    def __init__(self, axes=(), buttons=(), hats=()):
        self._axes, self._buttons, self._hats = axes, buttons, hats

    def get_numaxes(self):
        return len(self._axes)

    def get_axis(self, i):
        return self._axes[i]

    def get_numbuttons(self):
        return len(self._buttons)

    def get_button(self, i):
        return self._buttons[i]

    def get_numhats(self):
        return len(self._hats)

    def get_hat(self, i):
        return self._hats[i]


def test_inside_deadzone_is_zero():
    assert apply_deadzone(0.05, 0.1) == 0.0
    assert apply_deadzone(-0.1, 0.1) == 0.0


def test_full_deflection_stays_full():
    assert apply_deadzone(1.0, 0.2) == 1.0
    assert apply_deadzone(-1.0, 0.2) == -1.0


def test_sign_is_preserved_and_rescaled():
    assert apply_deadzone(0.55, 0.1) == pytest.approx(0.5)
    assert apply_deadzone(-0.55, 0.1) == pytest.approx(-0.5)


def test_invalid_deadzone_raises():
    with pytest.raises(ValueError):
        apply_deadzone(0.5, 1.0)
    with pytest.raises(ValueError):
        apply_deadzone(0.5, -0.1)


def test_read_state_applies_deadzone_to_axes():
    joy = FakeJoystick(axes=[0.05, -0.5, 1.0])
    state = read_state(joy, 0.1, "Pad")
    assert state.name == "Pad"
    assert state.axes[0] == 0.0
    assert state.axes[1] == pytest.approx(-0.4 / 0.9)
    assert state.axes[2] == 1.0


def test_read_state_buttons_and_hats():
    joy = FakeJoystick(buttons=[1, 0], hats=[(0, 1)])
    state = read_state(joy, 0.1)
    assert state.buttons == (True, False)
    assert state.hats == ((0, 1),)