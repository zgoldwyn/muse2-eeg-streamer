"""Part 3 reporting contract checks with synthetic feature records only."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from eeg_app.public_math_run import prepare_run, save_run


def record(index, participant, value, target):
    return {
        "window_id": f"{participant}:synthetic:{index}", "participant_id": participant,
        "session_id": participant + ":synthetic", "start_time_s": index * 2,
        "end_time_s": index * 2 + 2, "window_length_s": 2,
        "weak_target": target,
        "features": {f"{channel}_{name}": value
                     for channel in ("TP9", "AF7", "AF8", "TP10")
                     for name in ("peak_to_peak_uv", "max_adjacent_jump_uv")},
    }


class PublicMathRunTests(unittest.TestCase):
    def setUp(self):
        self.records = [record(0, "train", 10, "rest_period"),
                        record(1, "train", 20, "task_period"),
                        record(2, "train", 30, "rest_period"),
                        record(3, "train", 40, "task_period"),
                        record(0, "test", 5, "rest_period"),
                        record(1, "test", 100, "task_period")]

    def run_report(self, rows=None, **changes):
        options = {"training_participants": ["train"], "heldout_participants": ["test"],
                   "window_length_s": 2, "percentile": 95}
        options.update(changes)
        return prepare_run(self.records if rows is None else rows, **options)

    def test_limits_use_only_training_values_and_ignore_task_rest_labels(self):
        original = self.run_report()
        rows = copy.deepcopy(self.records)
        for row in rows:
            row["weak_target"] = "task_period" if row["weak_target"] == "rest_period" else "rest_period"
            if row["participant_id"] == "test":
                row["features"] = dict.fromkeys(row["features"], 99999)
        altered = self.run_report(rows)
        self.assertEqual(original["settings"], altered["settings"])
        self.assertEqual(original["settings"]["peak_to_peak_uv"], 38.5)
        self.assertEqual(original["settings"]["max_adjacent_jump_uv"], 38.5)
        self.assertTrue(all(wid.startswith("train:") for wid in original["selection"]["training_window_ids"]))

    def test_group_fractions_predictions_and_trace_pending_are_explicit(self):
        before = copy.deepcopy(self.records)
        result = self.run_report()
        groups = {(group["split"], group["weak_target"]): group for group in result["groups"]}
        self.assertEqual(groups["training", "task_period"]["fraction_flagged"], 0.5)
        self.assertEqual(groups["heldout", "task_period"]["fraction_flagged"], 1)
        self.assertEqual(groups["heldout", "rest_period"]["fraction_flagged"], 0)
        self.assertEqual({p["window_id"] for p in result["prediction_records"]},
                         {row["window_id"] for row in self.records})
        self.assertFalse(result["trace_backed_examples_complete"])
        self.assertTrue(all(example["trace_status"] == "pending_raw_samples_or_plots"
                            for example in result["trace_candidates"]))
        self.assertEqual(self.records, before)

    def test_overlap_duplicates_and_incomplete_records_are_not_silently_used(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            self.run_report(heldout_participants=["train"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.run_report(self.records + self.records[:1])
        rows = copy.deepcopy(self.records)
        rows[0]["features"]["AF7_peak_to_peak_uv"] = None
        result = self.run_report(rows)
        self.assertEqual(result["selection"]["training_window_count"], 3)
        self.assertEqual(len(result["excluded_windows"]), 1)
        self.assertNotIn(rows[0]["window_id"], {p["window_id"] for p in result["prediction_records"]})

    def test_saved_predictions_are_evaluator_format_and_trace_request_has_no_decisions(self):
        result = self.run_report()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            save_run(result, output)
            saved = json.loads((output / "predictions.json").read_text())
            self.assertTrue(all(set(row) == {"window_id", "decision"} for row in saved))
            text = (output / "trace-request.csv").read_text()
            self.assertNotIn("decision", text)
            self.assertNotIn("triggers", text)
            self.assertEqual(json.loads((output / "settings.json").read_text()), result["settings"])
            with self.assertRaises(FileExistsError):
                save_run(result, output)


if __name__ == "__main__":
    unittest.main()
