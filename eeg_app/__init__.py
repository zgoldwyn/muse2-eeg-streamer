"""Utilities for loading, validating, and preprocessing Muse EEG windows."""

from .dataset import EegWindow, LoadedSession, create_fixed_windows, load_synthetic_session
from .labels import (
    ReferenceLabelInterval,
    WindowReferenceLabel,
    join_reference_label_intervals,
)
from .preprocessing import validate_eeg_window

__all__ = [
    "EegWindow",
    "LoadedSession",
    "ReferenceLabelInterval",
    "WindowReferenceLabel",
    "create_fixed_windows",
    "join_reference_label_intervals",
    "load_synthetic_session",
    "validate_eeg_window",
]