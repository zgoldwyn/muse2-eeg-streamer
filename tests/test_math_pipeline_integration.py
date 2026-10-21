"""Real PR #12 loader + unchanged PR #17 fixture; see the verification runner."""

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from eeg_app.math_pipeline import (
    demo_peak_to_peak_prediction, extract_features_for_windows, extract_window_features,
)
from eeg_app.metrics import evaluate_predictions
from eeg_app.preprocessing import REQUIRED_CHANNELS

try:
    from eeg_app.dataset import create_fixed_windows, load_synthetic_session
except ModuleNotFoundError as error:
    if error.name != "eeg_app.dataset":
        raise
    load_synthetic_session = None

FIXTURE = Path(__file__).parent / "fixtures/integration/integration-demo-001"


@unittest.skipUnless(load_synthetic_session and (FIXTURE / "eeg.csv").exists(),
                     "Run scratch/samuel/verify_math_handoff.py to supply upstream PRs.")
class MathPipelineIntegrationTests(unittest.TestCase):
    def test_actual_loader_gap_exclusion_and_unchanged_samples(self):
        session = load_synthetic_session(FIXTURE / "eeg.csv", FIXTURE / "metadata.json")
        self.assertEqual(len(session.samples), 6096)
        self.assertFalse(any(sample.packet_index == 50 for sample in session.samples))
        windows = create_fixed_windows(session)
        before = copy.deepcopy(windows)
        self.assertEqual([(w.start_time_s, w.end_time_s, w.is_valid) for w in windows],
                         [(0, 2, True), (2, 4, False), (4, 6, True)])
        for window, count in zip(windows, (512, 500, 512)):
            for channel in REQUIRED_CHANNELS:
                self.assertEqual(len(window.channel_samples[channel]), count)
        self.assertTrue(any("missing packet/sample" in reason for reason in windows[1].invalid_reasons))
        with patch("eeg_app.math_pipeline.extract_window_features",
                   wraps=extract_window_features) as extract:
            result = extract_features_for_windows(windows, flatline_tolerance_uv=0)
        self.assertEqual([call.args[0].window_id for call in extract.call_args_list],
                         [windows[0].window_id, windows[2].window_id])
        self.assertEqual(result["summary"], {
            "total_windows": 3, "valid_windows_processed": 2, "invalid_windows_skipped": 1,
        })
        self.assertEqual([r["window_id"] for r in result["feature_records"]],
                         [windows[0].window_id, windows[2].window_id])
        for record in result["feature_records"]:
            self.assertEqual(len(record["features"]), 24)
            self.assertEqual(record["settings"]["sample_count_per_channel"], 512)
            self.assertEqual(record["session_id"], "integration-demo-001")
        self.assertEqual(result["skipped_windows"][0]["window_id"], windows[1].window_id)
        self.assertEqual(result["skipped_windows"][0]["invalid_reasons"], list(windows[1].invalid_reasons))
        self.assertEqual(windows, before)

    def test_two_real_window_predictions_preserve_ids_and_exclude_invalid_middle(self):
        session = load_synthetic_session(FIXTURE / "eeg.csv", FIXTURE / "metadata.json")
        windows = create_fixed_windows(session)
        result = extract_features_for_windows(windows, flatline_tolerance_uv=0)
        predictions = [demo_peak_to_peak_prediction(record) for record in result["feature_records"]]
        # These are assertions about the fixed rule's output, not reference labels.
        self.assertEqual([p["window_id"] for p in predictions],
                         [windows[0].window_id, windows[2].window_id])
        self.assertEqual([p["decision"] for p in predictions], ["clean", "artifact"])
        self.assertNotIn(windows[1].window_id, [p["window_id"] for p in predictions])
        self.assertTrue(all(set(p) == {"window_id", "decision"} for p in predictions))
        # Check the actual evaluator's schema acceptance without inventing truth.
        with self.assertRaisesRegex(ValueError, "Prediction supplied for unknown window ID"):
            evaluate_predictions([], predictions)


if __name__ == "__main__":
    unittest.main()
