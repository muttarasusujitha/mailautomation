"""Shared trainer fetch size. External searches read 240 people and keep at least 60."""

TRAINER_RESULT_TARGET = 60
TRAINER_SCAN_LIMIT = 240
TRAINER_RESULT_CEILING = 100


def trainer_keep_limit(requested=None) -> int:
    """Keep at least 60 trainer profiles, and stop once that many are qualified."""
    try:
        value = int(requested if requested is not None else TRAINER_RESULT_TARGET)
    except (TypeError, ValueError):
        value = TRAINER_RESULT_TARGET
    if value < TRAINER_RESULT_TARGET:
        value = TRAINER_RESULT_TARGET
    return min(value, TRAINER_RESULT_CEILING)
