"""Feature verification guards; no network downloads or public recordings in tests."""

import unittest

from scratch.samuel.public_trace_examples import edf_event_times, verify_features


class EdfMarkerTests(unittest.TestCase):
    def setUp(self):
        self.annotations = [{"description": f"OVTK_StimulationId_Number_{code:02}", "onset": onset}
                            for code, onset in [(0, 6), (1, 66), (2, 69), (2, 72), (3, 129), (4, 189)]]

    def test_embedded_boundary_times_ignore_repeated_beeps(self):
        self.assertEqual(edf_event_times(self.annotations, first_time=5), {1: 1, 2: 61, 4: 124, 5: 184})

    def test_missing_duplicate_and_out_of_order_boundaries_fail(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            edf_event_times(self.annotations[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            edf_event_times(self.annotations + [self.annotations[1]])
        self.annotations[-1]["onset"] = 100
        with self.assertRaisesRegex(ValueError, "out of order"):
            edf_event_times(self.annotations)


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
