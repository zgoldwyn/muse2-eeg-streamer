"""P0005 comparator, agreement, and score-cutoff checks with synthetic data."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eeg_app.rule_search import derive_rule_grid
from eeg_app.threshold_search import P0005_SESSIONS
from eeg_app.validation_comparison import build_comparison
from tests.test_rule_search import add_extra_features
from tests.test_threshold_search import prepared_rows


class ValidationComparisonTests(unittest.TestCase):
    def setUp(self):
        self.training = add_extra_features(
            prepared_rows([(10, 1), (20, 2), (80, 3), (100, 4)] + [(30, 1)] * 5,
                          ["clean"] * 4 + ["artifact"] * 5, ["training"], "training-person"),
            [(1, 2, 1), (2, 2.5, 1.2), (3, 3, 1.4), (4, 3.5, 1.6)] + [(20, 10, .2)] * 5,
        )
        self.grid = derive_rule_grid(self.training, {"training": "training-person"})
        self.validation = add_extra_features(
            prepared_rows([(10, 0)] * 12, ["clean"] * 10 + ["artifact"] * 2, P0005_SESSIONS, "P0005"),
            [(2, 3, 1.3)] * 9 + [(4, 3, 1.3)] + [(20, 10, .2)] * 2,
        )
        self.cnn = []
        for index, reference in enumerate(self.validation["references"]):
            decision = "artifact" if index in (0, 10) else "clean"
            self.cnn.append({
                "window_id": reference["window_id"], "session_id": reference["session_id"],
                "participant_id": "P0005", "decision": decision,
                "artifact_score": .9 if decision == "artifact" else .1,
                "model_version": "synthetic-cnn", "preprocessing_version": "synthetic-v1",
            })

    def test_reference_policies_use_training_majority(self):
        report, predictions = build_comparison(self.training, self.validation, self.grid)
        self.assertEqual(report["status"], "pending_CNN_validation_export")
        self.assertNotIn("cnn", report["policies"])
        self.assertEqual(report["majority_decision"], "artifact")
        self.assertEqual(report["policies"]["majority_class"]["counts"],
                         {"true_positives": 2, "false_negatives": 0, "false_positives": 10, "true_negatives": 0})
        self.assertEqual(report["policies"]["always_clean"]["counts"],
                         {"true_positives": 0, "false_negatives": 2, "false_positives": 0, "true_negatives": 10})
        self.assertEqual(len(predictions["math"]), 12)

    def test_all_agreement_combinations_and_matched_coverage(self):
        report, predictions = build_comparison(self.training, self.validation, self.grid, self.cnn)
        self.assertEqual(report["policies"]["agreement"]["counts"],
                         {"true_positives": 2, "false_negatives": 0, "false_positives": 2, "true_negatives": 8})
        self.assertEqual(report["policies"]["cnn"]["counts"],
                         {"true_positives": 1, "false_negatives": 1, "false_positives": 1, "true_negatives": 9})
        self.assertAlmostEqual(report["similar_acceptance"]["cnn_coverage_minus_math"], 1 / 12)
        self.assertEqual(report["similar_acceptance"]["cnn_cutoff"], .9)
        matched = predictions["cnn_similar_acceptance"]
        self.assertEqual(sum(row["decision"] == "artifact" for row in matched), 2)
        self.assertEqual(sorted(self.cnn, key=lambda row: row["window_id"]), predictions["cnn"])

    def test_missing_duplicate_unknown_and_mismatched_cnn_records(self):
        cases = [(self.cnn[:-1], "Missing prediction"),
                 (self.cnn + self.cnn[:1], "duplicate"),
                 ([{**self.cnn[0], "window_id": "unknown"}] + self.cnn[1:], "Unknown"),
                 ([{**self.cnn[0], "session_id": "wrong"}] + self.cnn[1:], "session_id mismatch")]
        for records, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                build_comparison(self.training, self.validation, self.grid, records)

    def test_score_and_version_errors(self):
        for value in (None, True, float("nan"), float("inf"), -1, 2):
            rows = copy.deepcopy(self.cnn)
            rows[0]["artifact_score"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "artifact_score"):
                build_comparison(self.training, self.validation, self.grid, rows)
        rows = copy.deepcopy(self.cnn)
        del rows[0]["preprocessing_version"]
        with self.assertRaisesRegex(ValueError, "preprocessing_version"):
            build_comparison(self.training, self.validation, self.grid, rows)

    def test_excluded_window_predictions_cannot_change_cutoff_or_metrics(self):
        first, _ = build_comparison(self.training, self.validation, self.grid, self.cnn)
        validation = copy.deepcopy(self.validation)
        excluded = {**validation["references"][0], "window_id": "excluded", "label": "uncertain"}
        validation["references"].append(excluded)
        prediction = {**self.cnn[0], "window_id": "excluded", "artifact_score": .123456}
        second, _ = build_comparison(self.training, validation, self.grid, self.cnn + [prediction])
        self.assertEqual(first["policies"]["agreement"]["metrics"], second["policies"]["agreement"]["metrics"])
        self.assertEqual(first["similar_acceptance"]["cnn_cutoff"], second["similar_acceptance"]["cnn_cutoff"])
        self.assertEqual(len(first["similar_acceptance"]["cnn_cutoff_curve"]),
                         len(second["similar_acceptance"]["cnn_cutoff_curve"]))

    def test_reordered_cnn_scores_are_repeatable(self):
        first = build_comparison(self.training, self.validation, self.grid, self.cnn)
        self.assertEqual(first, build_comparison(self.training, self.validation, self.grid, list(reversed(self.cnn))))

    def test_preliminary_labels_remain_visible_with_or_without_cnn(self):
        original, _ = build_comparison(self.training, self.validation, self.grid, self.cnn)
        self.validation["label_review_status"] = "preliminary"
        report, _ = build_comparison(self.training, self.validation, self.grid, self.cnn)
        self.assertEqual(report["status"], "preliminary_pending_label_reconciliation")
        self.assertEqual(report["label_review_status"], "preliminary")
        self.assertEqual(original["policies"], report["policies"])
        pending, _ = build_comparison(self.training, self.validation, self.grid)
        self.assertEqual(pending["status"], "pending_CNN_validation_export")
        self.assertEqual(pending["label_review_status"], "preliminary")

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Plot output requires matplotlib")
    def test_cli_accepts_jsonl_and_writes_complete_output_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("training", self.training), ("grid", self.grid), ("validation", self.validation)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            (root / "cnn.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.cnn), encoding="utf-8")
            command = [sys.executable, "-m", "eeg_app.validation_comparison", str(root / "training.json"),
                       str(root / "grid.json"), str(root / "validation.json"), str(root / "output"),
                       "--cnn-predictions", str(root / "cnn.jsonl")]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual({p.name for p in (root / "output").iterdir()},
                             {"comparison.json", "predictions.json", "summary.md", "tradeoff.png"})
            self.assertGreater((root / "output/tradeoff.png").stat().st_size, 1000)
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)


if __name__ == "__main__":
    unittest.main()
