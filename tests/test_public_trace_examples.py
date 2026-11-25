"""Feature verification guards; no network downloads or public recordings in tests."""

import unittest

from scratch.samuel.public_trace_examples import verify_features


class TraceFeatureVerificationTests(unittest.TestCase):
    def test_matching_values_and_roundoff_are_accepted(self):
        verify_features({"a": 100.0, "b": None}, {"a": 100.0 + 1e-10, "b": None})

    def test_different_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "feature keys"):
            verify_features({"a": 10}, {"b": 10})

    def test_value_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "differs from export"):
            verify_features({"TP9_peak_to_peak_uv": 100}, {"TP9_peak_to_peak_uv": 101})

    def test_unavailable_value_is_not_treated_as_zero(self):
        with self.assertRaisesRegex(ValueError, "differs from export"):
            verify_features({"a": None}, {"a": 0})


if __name__ == "__main__":
    unittest.main()
