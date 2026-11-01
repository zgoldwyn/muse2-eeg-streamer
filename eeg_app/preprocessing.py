"""Initial validation utilities for four-channel Muse EEG windows."""

from collections.abc import Mapping, Sequence
from math import isfinite
from numbers import Real


REQUIRED_CHANNELS: tuple[str, ...] = ("TP9", "AF7", "AF8", "TP10")


def validate_eeg_window(window: Mapping[str, Sequence[Real]]) -> int:
    """Validate a four-channel EEG window and return its samples per channel.

    The window must contain nonempty, equally sized TP9, AF7, AF8, and TP10
    sample sequences. Every sample must be a finite numeric value.

    Raises:
        ValueError: If the window does not meet the initial EEG input contract.
    """
    if not isinstance(window, Mapping):
        raise ValueError("EEG window must be a mapping from channel names to samples.")

    for channel in REQUIRED_CHANNELS:
        if channel not in window:
            raise ValueError(f"EEG window is missing required channel: {channel}.")

    expected_length: int | None = None

    for channel in REQUIRED_CHANNELS:
        samples = window[channel]

        if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
            raise ValueError(f"Channel {channel} must contain a sequence of samples.")

        sample_count = len(samples)
        if sample_count == 0:
            raise ValueError(f"Channel {channel} must not be empty.")

        if expected_length is None:
            expected_length = sample_count
        elif sample_count != expected_length:
            raise ValueError(
                f"Channel {channel} has {sample_count} samples; "
                f"expected {expected_length}."
            )

        for sample_index, value in enumerate(samples):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(
                    f"Channel {channel} sample {sample_index} must be numeric."
                )
            if not isfinite(value):
                raise ValueError(
                    f"Channel {channel} sample {sample_index} must be finite."
                )

    assert expected_length is not None
    return expected_length