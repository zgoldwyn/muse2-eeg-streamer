"""Part 2 detector contract tests; numeric limits here are synthetic test inputs."""

import copy
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eeg_app.math_detector import DetectorSettings, WindowExcluded, predict_records, predict_window
from eeg_app.preprocessing import REQUIRED_CHANNELS


def make_record(window_id="synthetic:window-0"):
    # Same field names as Namit's public exports, with made-up numeric inputs.
    return {
        "window_id": window_id, "participant_id": "synthetic-participant",
        "session_id": "synthetic", "start_time_s": 1.0, "end_time_s": 3.0,
        "window_length_s": 2.0, "sample_rate_hz": 256.0,
        "weak_target": "rest_period", "target_provenance": {"source": "test_only"},
        "features": {f"{channel}_{feature}": 10.0 for channel in REQUIRED_CHANNELS
                     for feature in ("peak_to_peak_uv", "max_adjacent_jump_uv")},
    }


class MathDetectorTests(unittest.TestCase):
    def setUp(self):
        self.settings = DetectorSettings(
            window_length_s=2, peak_to_peak_uv=100, max_adjacent_jump_uv=50,
            selection_note="Synthetic boundary-test inputs only; not research thresholds.",
        )

    def predict(self, record):
        return predict_window(record, self.settings, validity_confirmed=True)

    def test_each_channel_and_feature_can_trigger_and_equality_does_not(self):
        for channel in REQUIRED_CHANNELS:
            for feature, threshold in (("peak_to_peak_uv", 100), ("max_adjacent_jump_uv", 50)):
                row = make_record()
                key = f"{channel}_{feature}"
                row["features"][key] = threshold
                self.assertEqual(self.predict(row)["decision"], "clean")
                row["features"][key] = threshold + 0.01
                result = self.predict(row)
                self.assertEqual(result["decision"], "artifact")
                self.assertEqual(result["triggers"], [{
                    "channel": channel, "feature": feature, "feature_key": key,
                    "value_uv": threshold + 0.01, "threshold_uv": threshold, "comparison": ">",
                }])

    def test_all_triggers_preserved_and_input_unchanged(self):
        row = make_record()
        row["features"]["AF7_peak_to_peak_uv"] = 130
        row["features"]["TP10_max_adjacent_jump_uv"] = 80
        before = copy.deepcopy(row)
        result = self.predict(row)
        self.assertEqual(result["window_id"], row["window_id"])
        self.assertEqual(len(result["triggers"]), 2)
        self.assertEqual(result["settings"], self.settings.to_dict())
        self.assertEqual(row, before)

    def test_every_required_feature_checked_even_after_an_artifact_trigger(self):
        for value in (None, math.nan, math.inf, -1, True, "10"):
            row = make_record()
            row["features"]["TP9_peak_to_peak_uv"] = 200
            row["features"]["TP10_max_adjacent_jump_uv"] = value
            with self.subTest(value=value), self.assertRaisesRegex(WindowExcluded, "TP10_max_adjacent_jump_uv"):
                self.predict(row)
        for channel in REQUIRED_CHANNELS:
            row = make_record()
            del row["features"][f"{channel}_peak_to_peak_uv"]
            with self.subTest(channel=channel), self.assertRaisesRegex(WindowExcluded, channel):
                self.predict(row)

    def test_unavailable_reason_and_units_checked(self):
        row = make_record()
        row["unavailable_reasons"] = {"AF7_peak_to_peak_uv": "Unavailable calculation"}
        with self.assertRaisesRegex(WindowExcluded, "Unavailable calculation"):
            self.predict(row)
        row = make_record()
        row["units"] = dict.fromkeys(row["features"], "microvolts")
        row["units"]["AF7_peak_to_peak_uv"] = "volts"
        with self.assertRaisesRegex(WindowExcluded, "units must be microvolts"):
            self.predict(row)

    def test_explicit_invalidity_overrides_confirmation_and_reasons_are_retained(self):
        row = make_record()
        row.update(is_valid=False, invalid_reasons=["Missing packet 50"])
        result = predict_records([row], self.settings, validity_confirmed=True)
        self.assertEqual(result["prediction_records"], [])
        excluded = result["excluded_windows"][0]
        self.assertNotIn("decision", excluded)
        self.assertIn("Missing packet 50", excluded["reasons"])
        row["is_valid"] = True
        with self.assertRaisesRegex(WindowExcluded, "Missing packet 50"):
            self.predict(row)

    def test_unknown_validity_requires_explicit_upstream_confirmation(self):
        row = make_record()
        with self.assertRaisesRegex(WindowExcluded, "Validity is unknown"):
            predict_window(row, self.settings)
        row["is_valid"] = True
        self.assertEqual(predict_window(row, self.settings)["decision"], "clean")
        row["is_valid"] = 1
        with self.assertRaises(WindowExcluded):
            self.predict(row)

    def test_window_length_and_interval_must_match_saved_settings(self):
        for changes in ({"window_length_s": 4}, {"end_time_s": 4}, {"start_time_s": math.nan}):
            row = make_record()
            row.update(changes)
            with self.subTest(changes=changes), self.assertRaises(WindowExcluded):
                self.predict(row)
        row = make_record()
        del row["window_length_s"]  # Existing math adapter supplies start/end instead.
        self.assertEqual(self.predict(row)["decision"], "clean")

    def test_unused_features_and_weak_target_do_not_affect_decision(self):
        row = make_record()
        original = self.predict(row)
        row.update(participant_id="another", weak_target="task_period",
                   target_provenance={"event_codes": [2, 4]})
        row["features"].update(AF7_kurtosis=None, AF8_approximate_entropy=999)
        row["unavailable_reasons"] = {"AF7_kurtosis": "Zero variance"}
        self.assertEqual(self.predict(row), original)

    def test_repeatable_batch_excludes_missing_values_and_rejects_duplicate_ids(self):
        first, second = make_record(), make_record("synthetic:window-1")
        second["features"]["AF7_peak_to_peak_uv"] = None
        rows = [first, second]
        result = predict_records(rows, self.settings, validity_confirmed=True)
        self.assertEqual(result["summary"], {"total_records": 2, "predicted": 1, "excluded": 1})
        self.assertEqual(result, predict_records(rows, self.settings, validity_confirmed=True))
        with self.assertRaisesRegex(ValueError, "Duplicate window_id"):
            predict_records([first, first], self.settings, validity_confirmed=True)

    def test_settings_are_explicit_immutable_and_serializable(self):
        saved = json.loads(json.dumps(self.settings.to_dict()))
        self.assertEqual(DetectorSettings.from_dict(saved), self.settings)
        with self.assertRaises(FrozenInstanceError):
            self.settings.peak_to_peak_uv = 5
        with self.assertRaises(TypeError):
            DetectorSettings(window_length_s=2, selection_note="No limits provided")
        for value in (-1, math.inf, True, "100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                DetectorSettings(2, value, 50, "Unit test")
        with self.assertRaises(ValueError):
            DetectorSettings(2, 100, 50, "")
        saved["status"] = "validated"
        with self.assertRaisesRegex(ValueError, "Unsupported detector setting"):
            DetectorSettings.from_dict(saved)

    def test_cli_uses_saved_settings_on_synthetic_record_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "records.jsonl").write_text(json.dumps(make_record()) + "\n", encoding="utf-8")
            (root / "settings.json").write_text(json.dumps(self.settings.to_dict()), encoding="utf-8")
            command = [sys.executable, "-m", "eeg_app.math_detector", str(root / "records.jsonl"),
                       "--settings", str(root / "settings.json"), "--valid-windows-confirmed",
                       "--output", str(root / "predictions.json")]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads((root / "predictions.json").read_text())
            self.assertEqual(result["prediction_records"][0]["window_id"], make_record()["window_id"])
            self.assertEqual(result["summary"]["predicted"], 1)
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)


if __name__ == "__main__":
    unittest.main()
