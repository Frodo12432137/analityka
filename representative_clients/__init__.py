"""Wybór reprezentatywnych klientów na podstawie profili godzinowych."""

from .model import (
    GroupResult,
    SelectionConfig,
    SelectionData,
    SelectionResult,
)
from .solver import solve_selection

__all__ = [
    "GroupResult",
    "SelectionConfig",
    "SelectionData",
    "SelectionResult",
    "solve_selection",
]

