"""Utilities for validating, preprocessing, and evaluating Muse EEG windows."""

from .metrics import compare_detectors, evaluate_predictions, format_rate
from .preprocessing import validate_eeg_window

__all__ = [
    "compare_detectors",
    "evaluate_predictions",
    "format_rate",
    "validate_eeg_window",
]
