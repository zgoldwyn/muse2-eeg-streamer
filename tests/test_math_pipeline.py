"""Feature handoff, validity, and illustrative prediction tests."""

import copy
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from eeg_app.math_pipeline import (
    demo_peak_to_peak_prediction, extract_features_for_windows, extract_window_features,
)
from eeg_app.metrics import evaluate_predictions
from eeg_app.preprocessing import REQUIRED_CHANNELS


def make_window():
    # Two seconds at 256 Hz, with deliberately different channel amplitudes.
    times = tuple(i / 256 for i in range(512))
    return SimpleNamespace(
        session_id="adapter-example",
        window_id="adapter-example:window-0",
        start_time_s=0.0,
        end_time_s=2.0,
        nominal_sample_rate_hz=256,
        channel_samples={
            channel: [float(i % 2) * amplitude for i in range(512)]
            for channel, amplitude in zip(REQUIRED_CHANNELS, (2, 10, 0, 5))
        },
        channel_times_s=dict.fromkeys(REQUIRED_CHANNELS, times),
        is_valid=True,
        invalid_reasons=(),
    )


class MathPipelineTests(unittest.TestCase):
    def test_one_record_with_six_features_per_channel_and_separate_metadata(self):
        window = make_window()
        record = extract_window_features(window, flatline_tolerance_uv=0)
        names = (
            "peak_to_peak_uv", "max_adjacent_jump_uv", "flatline_fraction",
            "standard_deviation_uv", "kurtosis", "approximate_entropy",
        )
        self.assertEqual(set(record["features"]), {
            f"{channel}_{name}" for channel in REQUIRED_CHANNELS for name in names
        })
        for name in ("session_id", "window_id", "start_time_s", "end_time_s",
                     "nominal_sample_rate_hz"):
            self.assertEqual(record[name], getattr(window, name))
            self.assertNotIn(name, record["features"])
        for channel, amplitude in zip(REQUIRED_CHANNELS, (2, 10, 0, 5)):
            self.assertEqual(record["features"][f"{channel}_peak_to_peak_uv"], amplitude)
            self.assertEqual(record["features"][f"{channel}_max_adjacent_jump_uv"], amplitude)
            self.assertEqual(record["features"][f"{channel}_standard_deviation_uv"], amplitude / 2)
            self.assertEqual(record["features"][f"{channel}_flatline_fraction"], int(amplitude == 0))
            self.assertAlmostEqual(record["features"][f"{channel}_approximate_entropy"], 0, places=5)
            if amplitude:
                self.assertEqual(record["features"][f"{channel}_kurtosis"], 1)

    def test_units_settings_and_unavailable_reason_survive(self):
        record = extract_window_features(
            make_window(), flatline_tolerance_uv=0.1,
            entropy_m=3, entropy_tolerance_uv=0.25,
        )
        self.assertEqual(record["settings"]["flatline_tolerance_uv"], 0.1)
        self.assertEqual(record["settings"]["entropy_m"], 3)
        self.assertEqual(record["settings"]["entropy_tolerance_uv"],
                         dict.fromkeys(REQUIRED_CHANNELS, 0.25))
        self.assertEqual(record["settings"]["sample_count_per_channel"], 512)
        self.assertIn("population", record["settings"]["moment_convention"])
        self.assertIsNone(record["features"]["AF8_kurtosis"])
        self.assertIn("variance is zero", record["unavailable_reasons"]["AF8_kurtosis"])
        self.assertEqual(set(record["units"]), set(record["features"]))
        for channel in REQUIRED_CHANNELS:
            for name in ("peak_to_peak_uv", "max_adjacent_jump_uv", "standard_deviation_uv"):
                self.assertEqual(record["units"][f"{channel}_{name}"], "microvolts")
            for name in ("flatline_fraction", "kurtosis", "approximate_entropy"):
                self.assertEqual(record["units"][f"{channel}_{name}"], "dimensionless")

    def test_derived_entropy_tolerances_preserved(self):
        record = extract_window_features(make_window(), flatline_tolerance_uv=0)
        self.assertEqual(record["settings"]["entropy_tolerance_uv"],
                         dict(zip(REQUIRED_CHANNELS, (0.2, 1.0, 0.0, 0.5))))

    def test_invalid_or_inconsistent_validity_rejected_before_calculation(self):
        for flag, reasons in ((False, ("Missing packet 50",)), (None, ()),
                              (1, ()), (True, ("Missing channel",))):
            window = make_window()
            window.is_valid, window.invalid_reasons = flag, reasons
            with self.subTest(flag=flag, reasons=reasons):
                with patch("eeg_app.math_pipeline.calculate_window_features") as calculate:
                    with self.assertRaisesRegex(ValueError, "invalid"):
                        extract_window_features(window, flatline_tolerance_uv=0)
                    calculate.assert_not_called()

    def test_invalid_metadata_rejected(self):
        for name, value in (("session_id", ""), ("window_id", " "),
                            ("start_time_s", -1), ("end_time_s", 0),
                            ("end_time_s", math.inf), ("nominal_sample_rate_hz", 0),
                            ("nominal_sample_rate_hz", True)):
            window = make_window()
            setattr(window, name, value)
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                extract_window_features(window, flatline_tolerance_uv=0)

    def test_malformed_samples_and_invalid_parameters_rejected(self):
        window = make_window()
        window.channel_samples["AF7"][0] = math.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            extract_window_features(window, flatline_tolerance_uv=0)
        with self.assertRaises(ValueError):
            extract_window_features(make_window(), flatline_tolerance_uv=-1)

    def test_input_arrays_and_metadata_unchanged(self):
        window = make_window()
        before = copy.deepcopy(window)
        extract_window_features(window, flatline_tolerance_uv=0)
        self.assertEqual(window, before)

    def test_batch_skips_gap_without_calculating_or_mutating_it(self):
        first, middle, last = (make_window() for _ in range(3))
        for i, window in enumerate((first, middle, last)):
            window.window_id = f"adapter-example:window-{i}"
            window.start_time_s, window.end_time_s = i * 2, (i + 1) * 2
        middle.is_valid = False
        middle.invalid_reasons = ("Missing packet 50",)
        middle.channel_samples = {c: values[:500] for c, values in middle.channel_samples.items()}
        windows = [first, middle, last]
        before = copy.deepcopy(windows)
        with patch("eeg_app.math_pipeline.extract_window_features",
                   wraps=extract_window_features) as extract:
            result = extract_features_for_windows(iter(windows), flatline_tolerance_uv=0.1)
        self.assertEqual([call.args[0].window_id for call in extract.call_args_list],
                         [first.window_id, last.window_id])
        self.assertEqual(result["summary"], {
            "total_windows": 3, "valid_windows_processed": 2, "invalid_windows_skipped": 1,
        })
        self.assertEqual([r["window_id"] for r in result["feature_records"]],
                         [first.window_id, last.window_id])
        self.assertEqual(result["skipped_windows"][0]["invalid_reasons"], ["Missing packet 50"])
        self.assertEqual(result["skipped_windows"][0]["start_time_s"], 2)
        self.assertEqual(windows, before)

    def test_batch_empty_and_all_invalid(self):
        empty = extract_features_for_windows([], flatline_tolerance_uv=0)
        self.assertEqual(empty["summary"]["total_windows"], 0)
        window = make_window()
        window.is_valid = False
        result = extract_features_for_windows([window], flatline_tolerance_uv=0)
        self.assertEqual(result["feature_records"], [])
        self.assertEqual(result["summary"]["invalid_windows_skipped"], 1)
        self.assertTrue(result["skipped_windows"][0]["invalid_reasons"])

    def test_errors_in_valid_windows_are_not_silently_skipped(self):
        window = make_window()
        del window.channel_samples["AF7"]
        with self.assertRaisesRegex(ValueError, "missing required channel"):
            extract_features_for_windows([window], flatline_tolerance_uv=0)


class DemoPredictionTests(unittest.TestCase):
    def make_record(self):
        # Feature inputs for a rule unit test, not reference labels.
        return {
            "window_id": "rule-unit-test:window-0",
            "features": {f"{c}_peak_to_peak_uv": 10.0 for c in REQUIRED_CHANNELS},
            "units": {f"{c}_peak_to_peak_uv": "microvolts" for c in REQUIRED_CHANNELS},
            "unavailable_reasons": {},
        }

    def test_strict_threshold_and_each_channel_can_trigger_artifact(self):
        for channel in REQUIRED_CHANNELS:
            record = self.make_record()
            record["features"][f"{channel}_peak_to_peak_uv"] = 100
            self.assertEqual(demo_peak_to_peak_prediction(record)["decision"], "clean")
            record["features"][f"{channel}_peak_to_peak_uv"] = 100.01
            self.assertEqual(demo_peak_to_peak_prediction(record)["decision"], "artifact")

    def test_two_valid_windows_produce_two_predictions_with_distinct_original_ids(self):
        first, last = make_window(), make_window()
        last.window_id = "adapter-example:window-2"
        last.start_time_s, last.end_time_s = 4.0, 6.0
        last.channel_samples["AF7"][256] = 200.0
        windows = [first, last]
        before = copy.deepcopy(windows)
        result = extract_features_for_windows(windows, flatline_tolerance_uv=0)
        predictions = [demo_peak_to_peak_prediction(record) for record in result["feature_records"]]
        self.assertEqual(len(predictions), 2)
        self.assertEqual(len({record["window_id"] for record in predictions}), 2)
        self.assertEqual([record["window_id"] for record in predictions],
                         [first.window_id, last.window_id])
        self.assertEqual([record["decision"] for record in predictions], ["clean", "artifact"])
        self.assertEqual(windows, before)

    def test_unavailable_required_feature_reports_window_key_and_reason(self):
        record = self.make_record()
        record["features"]["AF7_peak_to_peak_uv"] = None
        record["unavailable_reasons"]["AF7_peak_to_peak_uv"] = "Calculation unavailable"
        with self.assertRaisesRegex(ValueError, "rule-unit-test:window-0.*AF7_peak_to_peak_uv.*Calculation unavailable"):
            demo_peak_to_peak_prediction(record)
        self.assertIsNone(record["features"]["AF7_peak_to_peak_uv"])

    def test_all_required_values_checked_even_when_another_channel_is_artifact(self):
        for value in (None, math.nan, math.inf, -1, True, "10"):
            record = self.make_record()
            record["features"]["TP9_peak_to_peak_uv"] = 200
            record["features"]["TP10_peak_to_peak_uv"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "TP10_peak_to_peak_uv"):
                demo_peak_to_peak_prediction(record)
        record = self.make_record()
        del record["features"]["AF7_peak_to_peak_uv"]
        with self.assertRaisesRegex(ValueError, "AF7_peak_to_peak_uv"):
            demo_peak_to_peak_prediction(record)

    def test_units_and_record_id_are_required(self):
        record = self.make_record()
        record["units"]["AF7_peak_to_peak_uv"] = "volts"
        with self.assertRaisesRegex(ValueError, "microvolts"):
            demo_peak_to_peak_prediction(record)
        record = self.make_record()
        record["window_id"] = ""
        with self.assertRaisesRegex(ValueError, "window_id"):
            demo_peak_to_peak_prediction(record)

    def test_unused_unavailable_kurtosis_does_not_prevent_prediction(self):
        record = self.make_record()
        record["features"]["AF7_kurtosis"] = None
        record["unavailable_reasons"]["AF7_kurtosis"] = "Zero variance"
        before = copy.deepcopy(record)
        self.assertEqual(demo_peak_to_peak_prediction(record), {
            "window_id": record["window_id"], "decision": "clean",
        })
        self.assertEqual(record, before)

    def test_prediction_schema_passes_evaluator_validation_without_inventing_labels(self):
        predictions = [demo_peak_to_peak_prediction(self.make_record())]
        # The evaluator validates prediction records before checking reference IDs.
        # Empty references deliberately prevent scoring; no labels are fabricated.
        with self.assertRaisesRegex(ValueError, "Prediction supplied for unknown window ID"):
            evaluate_predictions([], predictions)


if __name__ == "__main__":
    unittest.main()
