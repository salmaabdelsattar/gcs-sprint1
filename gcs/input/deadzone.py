"""Dead-zone filtering for analogue axes (R5)."""
import math


def apply_deadzone(value, deadzone):
    """Zero out small values so stick drift doesn't move the vehicle.

    Values outside the dead-zone are rescaled so the output still
    spans the full range (-1.0 to 1.0) with no jump at the edge.
    """
    if not 0.0 <= deadzone < 1.0:
        raise ValueError("deadzone must be in [0.0, 1.0)")
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    scaled = (magnitude - deadzone) / (1.0 - deadzone)
    return math.copysign(min(scaled, 1.0), value)
