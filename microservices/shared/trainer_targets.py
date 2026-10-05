"""Shared trainer fetch size. External searches read 200 people and keep 50."""

TRAINER_RESULT_TARGET = 50
TRAINER_SCAN_LIMIT = 200


def trainer_keep_limit(requested=None) -> int:
    """Return how many trainer matches a service should keep."""
    try:
        value = int(requested if requested is not None else TRAINER_RESULT_TARGET)
    except (TypeError, ValueError):
        value = TRAINER_RESULT_TARGET
    if value <= 0:
        value = TRAINER_RESULT_TARGET
    return min(value, TRAINER_RESULT_TARGET)
