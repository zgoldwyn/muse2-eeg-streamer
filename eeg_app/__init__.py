"""Utilities for validating, preprocessing, and evaluating Muse EEG windows."""

from .dataset import EegWindow, LoadedSession, create_fixed_windows, load_synthetic_session
from .labels import (
    ReferenceLabelInterval,
    WindowReferenceLabel,
    join_reference_label_intervals,
)
from .metrics import compare_detectors, evaluate_predictions, format_rate
from .preprocessing import validate_eeg_window

__all__ = [
    "EegWindow",
    "LoadedSession",
    "ReferenceLabelInterval",
    "WindowReferenceLabel",
    "compare_detectors",
    "create_fixed_windows",
    "evaluate_predictions",
    "format_rate",
    "join_reference_label_intervals",
    "load_synthetic_session",
    "validate_eeg_window",
]