"""Length comparison safeguards using synthetic samples, not human labels."""

import copy
from dataclasses import dataclass, replace
import unittest

from eeg_app.math_detector import DetectorSettings, predict_records, predict_window
from eeg_app.math_pipeline import extract_window_features
from eeg_app.preprocessing import REQUIRED_CHANNELS
from eeg_app.public_math_run import prepare_run
from eeg_app.window_comparison import annotated_gaps, guard_window, training_stability
from tests.test_math_detector import make_record


@dataclass(frozen=True)
class Window:
    session_id: str
    window_id: str
    start_time_s: float
    end_time_s: float
    nominal_sample_rate_hz: float
    channel_samples: dict
    is_valid: bool = True
    invalid_reasons: tuple = ()


def window(start=0, length=2):
    return Window("synthetic", f"synthetic:w{length}:{start}", start, start + length, 8,
                  {channel: tuple(float(i) for i in range(length * 8)) for channel in REQUIRED_CHANNELS})


class WindowComparisonTests(unittest.TestCase):
    def test_gaps_exclude_overlaps_but_half_open_edges_remain_usable(self):
        gaps = annotated_gaps([{"onset": 2, "duration": 2, "description": "BAD_ACQ_SKIP"},
                               {"onset": 1, "duration": 0, "description": "task beep"}])
        self.assertTrue(guard_window(window(0), gaps).is_valid)
        rejected = guard_window(window(2), gaps)
        self.assertFalse(rejected.is_valid)
        self.assertIn("recording gap", rejected.invalid_reasons[0])
        self.assertEqual(rejected.window_id, window(2).window_id)
        self.assertEqual(rejected.channel_samples, window(2).channel_samples)
        self.assertTrue(guard_window(window(4), gaps).is_valid)
        with self.assertRaisesRegex(ValueError, "invalid"):
            extract_window_features(rejected, flatline_tolerance_uv=.1)

    def test_point_discontinuities_and_loader_boundary_reasons(self):
        gap = annotated_gaps([{"onset": 2, "duration": 0, "description": "discontinuity"}])
        self.assertTrue(guard_window(window(0), gap).is_valid)
        self.assertFalse(guard_window(window(1), gap).is_valid)
        self.assertTrue(guard_window(window(2), gap).is_valid)
        boundary = replace(window(), is_valid=False, invalid_reasons=("window crosses an event boundary",))
        self.assertEqual(guard_window(boundary, []).invalid_reasons, boundary.invalid_reasons)
        with self.assertRaisesRegex(ValueError, "Malformed"):
            annotated_gaps([{"onset": 1, "duration": -1, "description": "gap"}])

    def test_every_length_requires_all_four_complete_channels(self):
        for length in (2, 4, 8):
            for channel in REQUIRED_CHANNELS:
                original = window(length=length)
                samples = dict(original.channel_samples)
                samples[channel] = samples[channel][:-1]
                checked = guard_window(replace(original, channel_samples=samples), [])
                with self.subTest(length=length, channel=channel):
                    self.assertFalse(checked.is_valid)
                    self.assertTrue(any(channel in reason for reason in checked.invalid_reasons))
            missing = dict(original.channel_samples)
            del missing["AF8"]
            self.assertFalse(guard_window(replace(original, channel_samples=missing), []).is_valid)

    def test_features_are_calculated_on_each_lengths_samples(self):
        # A longer ramp has larger range: averaging shorter ranges is wrong.
        values = {}
        for length in (2, 4, 8):
            record = extract_window_features(guard_window(window(length=length), []), flatline_tolerance_uv=.1)
            self.assertEqual(record["settings"]["sample_count_per_channel"], length * 8)
            self.assertEqual(len(record["features"]), 24)
            values[length] = record["features"]["TP9_peak_to_peak_uv"]
        self.assertEqual(values, {2: 15, 4: 31, 8: 63})
        self.assertNotEqual(values[8], sum([values[2]] * 4) / 4)

    def test_all_lengths_boundaries_missing_features_and_repeatability(self):
        for length in (2, 4, 8):
            settings = DetectorSettings(length, 100, 50, "Synthetic tests only")
            for channel in REQUIRED_CHANNELS:
                for feature, limit in (("peak_to_peak_uv", 100), ("max_adjacent_jump_uv", 50)):
                    row = make_record()
                    row.update(window_length_s=length, end_time_s=row["start_time_s"] + length)
                    row["features"][f"{channel}_{feature}"] = limit
                    self.assertEqual(predict_window(row, settings, validity_confirmed=True)["decision"], "clean")
                    row["features"][f"{channel}_{feature}"] = limit + .01
                    self.assertEqual(predict_window(row, settings, validity_confirmed=True)["decision"], "artifact")
                    row["features"][f"{channel}_{feature}"] = None
                    checked = predict_records([row], settings, validity_confirmed=True)
                    self.assertEqual(checked["prediction_records"], [])
                    self.assertEqual(len(checked["excluded_windows"]), 1)
            first = make_record("one")
            first.update(window_length_s=length, end_time_s=1 + length)
            second = copy.deepcopy(first)
            second["window_id"] = "two"
            a = predict_records([first, second], settings, validity_confirmed=True)
            b = predict_records([second, first], settings, validity_confirmed=True)
            self.assertEqual({r["window_id"]: r for r in a["prediction_records"]},
                             {r["window_id"]: r for r in b["prediction_records"]})

    def test_selection_and_stability_do_not_use_heldout_values_or_targets(self):
        for length in (2, 4, 8):
            records = []
            for i, participant in enumerate(("train", "train", "heldout")):
                row = make_record(str(i))
                row.update(participant_id=participant, window_length_s=length,
                           start_time_s=i * length, end_time_s=(i + 1) * length)
                records.append(row)
            original = prepare_run(records, training_participants=["train"], heldout_participants=["heldout"], window_length_s=length)
            stability = training_stability(records, ["train"])
            records[-1]["features"] = dict.fromkeys(records[-1]["features"], 1e12)
            records[-1]["weak_target"] = "task_period"
            changed = prepare_run(records, training_participants=["train"], heldout_participants=["heldout"], window_length_s=length)
            self.assertEqual(original["settings"], changed["settings"])
            self.assertEqual(stability, training_stability(records, ["train"]))

    def test_stability_changes_cannot_bridge_an_excluded_window(self):
        rows = []
        for start in (0, 2, 6):
            row = make_record(str(start))
            row.update(start_time_s=start, end_time_s=start + 2)
            rows.append(row)
        report = training_stability(rows, ["synthetic-participant"])
        self.assertTrue(report["groups"])
        self.assertTrue(all(row["adjacent_pairs"] == 1 for row in report["groups"]))


if __name__ == "__main__":
    unittest.main()
