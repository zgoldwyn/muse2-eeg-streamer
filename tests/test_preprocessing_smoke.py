"""Smoke tests for synthetic EEG-window validation."""

import math
import unittest

from eeg_app import validate_eeg_window


class ValidateEegWindowSmokeTests(unittest.TestCase):
    """Check the initial EEG input contract with synthetic data only."""

    def test_valid_four_channel_window_returns_sample_count(self) -> None:
        window = {
            "TP9": [1.2, 1.0, 0.9],
            "AF7": [-0.4, -0.3, -0.5],
            "AF8": [0.2, 0.3, 0.1],
            "TP10": [1.5, 1.4, 1.6],
        }

        self.assertEqual(validate_eeg_window(window), 3)

    def test_missing_required_channel_raises_helpful_error(self) -> None:
        window = {
            "TP9": [1.0, 2.0],
            "AF7": [1.0, 2.0],
            "AF8": [1.0, 2.0],
        }

        with self.assertRaisesRegex(ValueError, "missing required channel: TP10"):
            validate_eeg_window(window)

    def test_channels_with_different_lengths_raise_helpful_error(self) -> None:
        window = {
            "TP9": [1.0, 2.0, 3.0],
            "AF7": [1.0, 2.0],
            "AF8": [1.0, 2.0, 3.0],
            "TP10": [1.0, 2.0, 3.0],
        }

        with self.assertRaisesRegex(ValueError, "AF7 has 2 samples; expected 3"):
            validate_eeg_window(window)

    def test_nonnumeric_or_nonfinite_value_raises_helpful_error(self) -> None:
        nonnumeric_window = {
            "TP9": [1.0, "not a measurement"],
            "AF7": [1.0, 2.0],
            "AF8": [1.0, 2.0],
            "TP10": [1.0, 2.0],
        }
        nonfinite_window = {
            "TP9": [1.0, math.nan],
            "AF7": [1.0, 2.0],
            "AF8": [1.0, 2.0],
            "TP10": [1.0, 2.0],
        }

        with self.assertRaisesRegex(ValueError, "TP9 sample 1 must be numeric"):
            validate_eeg_window(nonnumeric_window)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "TP9 sample 1 must be finite"):
            validate_eeg_window(nonfinite_window)

    def test_empty_channel_raises_helpful_error(self) -> None:
        window = {
            "TP9": [1.0, 2.0],
            "AF7": [],
            "AF8": [1.0, 2.0],
            "TP10": [1.0, 2.0],
        }

        with self.assertRaisesRegex(ValueError, "Channel AF7 must not be empty"):
            validate_eeg_window(window)


if __name__ == "__main__":
    unittest.main()