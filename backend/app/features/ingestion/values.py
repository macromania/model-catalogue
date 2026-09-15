import math
from typing import Any


def object_value(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def number(value: Any, context: str, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number or null")
    if not math.isfinite(value) or value < 0 or (integer and int(value) != value):
        raise ValueError(f"{context} must be a finite, non-negative number")
    return int(value) if integer else value


def boolean(value: Any, context: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean or null")
    return value
