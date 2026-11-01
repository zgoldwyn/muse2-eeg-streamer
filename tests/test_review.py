"""Blinded review export and completed-sheet validation using real windows.

    Completed labels below are unit-test inputs, not pilot reference labels.
"""

import csv
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from eeg_app.metrics import evaluate_predictions
from eeg_app.review import (
    REVIEW_COLUMNS, _trace_segments, evaluate_review_sheet, export_review_bundle, load_windows,
    validate_review_sheet, validated_reference_records,
)
from eeg_app.review_demo import run_synthetic_dry_run


SESSION = Path(__file__).parent / "fixtures/integration/integration-demo-001"


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "review"
        self.summary = export_review_bundle(SESSION, self.bundle)
        with (self.bundle / "review.csv").open(encoding="utf-8", newline="") as stream:
            self.rows = list(csv.DictReader(stream))

    def completed_sheet(self, rows=None):
        rows = [dict(row, reviewer_id="unit-test-reviewer", label="uncertain")
                for row in (self.rows if rows is None else rows)]
        path = self.root / "completed.csv"
        self.write_sheet(path, rows)
        return path

    def write_sheet(self, path, rows):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_valid_rows_have_exact_ids_times_and_blank_human_fields(self):
        self.assertEqual(self.summary, {"total_windows": 3, "review_windows": 2,
                                        "technically_invalid_windows": 1})
        windows = [window for window in load_windows(SESSION) if window.is_valid]
        for row, window in zip(self.rows, windows):
            self.assertEqual(row["session_id"], window.session_id)
            self.assertEqual(row["window_id"], window.window_id)
            self.assertEqual(float(row["start_time_s"]), window.start_time_s)
            self.assertEqual(float(row["end_time_s"]), window.end_time_s)
            for name in ("reviewer_id", "label", "suspected_subtype", "affected_channels",
                         "evidence_notes", "uncertainty"):
                self.assertEqual(row[name], "")
            self.assertTrue((self.bundle / row["trace_file"]).is_file())

    def test_technical_exclusions_preserve_loader_reasons(self):
        with (self.bundle / "technically_invalid.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        window = next(window for window in load_windows(SESSION) if not window.is_valid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["window_id"], window.window_id)
        self.assertEqual(json.loads(rows[0]["loader_reasons"]), list(window.invalid_reasons))
        self.assertNotIn("label", rows[0])

    def test_export_never_calls_feature_or_prediction_code_and_contains_no_suggestions(self):
        with patch("eeg_app.math_pipeline.demo_peak_to_peak_prediction", side_effect=AssertionError), \
                patch("eeg_app.features.calculate_window_features", side_effect=AssertionError):
            output = self.root / "second"
            export_review_bundle(SESSION, output)
        for path in output.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for forbidden in ("peak_to_peak", "100 microvolt", '"decision"',
                                  "suggested_label", "reference_records.json"):
                    self.assertNotIn(forbidden, text)

    def test_svg_has_four_raw_channels_and_gap_is_not_connected(self):
        namespace = {"s": "http://www.w3.org/2000/svg"}
        for index, expected_paths in ((0, 4), (1, 8), (2, 4)):
            tree = ET.parse(self.bundle / f"traces/trace-{index:06d}.svg")
            paths = tree.findall(".//s:polyline", namespace)
            self.assertEqual(len(paths), expected_paths)
            self.assertEqual({path.attrib["data-channel"] for path in paths}, {"TP9", "AF7", "AF8", "TP10"})
        self.assertEqual(_trace_segments((0, 1/256, 3/256), (1, 2, 3), 256),
                         [[(0, 1), (1/256, 2)], [(3/256, 3)]])

    def test_export_refuses_to_overwrite_reviewer_work(self):
        with self.assertRaises(FileExistsError):
            export_review_bundle(SESSION, self.bundle)

    def test_blank_sheet_and_missing_rows_report_missing_labels(self):
        with self.assertRaisesRegex(ValueError, "missing required human label"):
            validate_review_sheet(SESSION, self.bundle / "review.csv")
        path = self.completed_sheet(self.rows[:1])
        with self.assertRaisesRegex(ValueError, "Missing review row and required label"):
            validate_review_sheet(SESSION, path)

    def test_unknown_duplicate_and_technical_window_ids_rejected(self):
        cases = (("unknown", "unknown window ID"),
                 (self.rows[0]["window_id"], "duplicate window ID"),
                 ("integration-demo-001:window-000001", "technically invalid window"))
        for window_id, message in cases:
            rows = [dict(row, reviewer_id="test", label="uncertain") for row in self.rows]
            rows[1]["window_id"] = window_id
            path = self.root / "bad.csv"
            self.write_sheet(path, rows)
            with self.subTest(window_id=window_id), self.assertRaisesRegex(ValueError, message):
                validate_review_sheet(SESSION, path)

    def test_unsupported_label_and_missing_reviewer_rejected(self):
        path = self.completed_sheet()
        rows = [dict(row, reviewer_id="test", label="uncertain") for row in self.rows]
        rows[0]["label"] = "probably clean"
        self.write_sheet(path, rows)
        with self.assertRaisesRegex(ValueError, "unsupported label"):
            validate_review_sheet(SESSION, path)
        rows[0]["label"], rows[0]["reviewer_id"] = "clean", ""
        self.write_sheet(path, rows)
        with self.assertRaisesRegex(ValueError, "missing required reviewer ID"):
            validate_review_sheet(SESSION, path)

    def test_all_four_labels_remain_distinct_and_notes_preserved(self):
        for label in ("clean", "artifact", "uncertain", "invalid"):
            rows = [dict(row, label=label, reviewer_id="test", uncertainty="boundary unclear",
                         evidence_notes="unit test, not pilot data", affected_channels="AF7;AF8",
                         suspected_subtype="other") for row in self.rows]
            path = self.root / "completed.csv"
            self.write_sheet(path, rows)
            records = validate_review_sheet(SESSION, path)
            self.assertEqual([record["label"] for record in records], [label, label])
            self.assertEqual(records[0]["uncertainty"], "boundary unclear")
            self.assertEqual(records[0]["affected_channels"], ["AF7", "AF8"])
            self.assertEqual(records[0]["evidence_notes"], "unit test, not pilot data")

    def test_session_times_and_channel_names_are_checked(self):
        for name, value, message in (("session_id", "another", "session ID"),
                                     ("start_time_s", "nan", "loader interval"),
                                     ("end_time_s", "3", "loader interval"),
                                     ("affected_channels", "AF9", "affected_channels")):
            rows = [dict(row, label="uncertain", reviewer_id="test") for row in self.rows]
            rows[0][name] = value
            path = self.root / "bad.csv"
            self.write_sheet(path, rows)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                validate_review_sheet(SESSION, path)

    def test_conversion_retains_exclusions_and_matches_by_id_in_different_order(self):
        path = self.completed_sheet(list(reversed(self.rows)))
        references = validated_reference_records(SESSION, path)
        self.assertEqual(references, [
            {"window_id": "integration-demo-001:window-000000", "label": "uncertain"},
            {"window_id": "integration-demo-001:window-000001", "label": "invalid"},
            {"window_id": "integration-demo-001:window-000002", "label": "uncertain"},
        ])
        result = evaluate_predictions(references, [])
        self.assertEqual(result["summary"]["invalid_windows_excluded"], 1)
        self.assertEqual(result["summary"]["uncertain_windows_excluded"], 2)
        self.assertEqual(result["summary"]["eligible_windows"], 0)

    def test_evaluation_requires_predictions_for_eligible_reviewed_windows(self):
        rows = [dict(row, reviewer_id="unit-test", label="clean") for row in self.rows]
        path = self.root / "completed.csv"
        self.write_sheet(path, rows)
        with self.assertRaisesRegex(ValueError, "Missing prediction for eligible window"):
            evaluate_review_sheet(SESSION, path, [])

    def test_uncertain_and_invalid_predictions_cannot_change_primary_metrics(self):
        # Controlled annotation inputs for evaluator behavior, not pilot labels.
        rows = [dict(row, reviewer_id="unit-test", label="uncertain") for row in self.rows]
        rows[0]["label"] = "clean"
        path = self.root / "completed.csv"
        self.write_sheet(path, rows)
        eligible_prediction = {"window_id": rows[0]["window_id"], "decision": "clean"}
        original = evaluate_review_sheet(SESSION, path, [eligible_prediction])
        self.assertEqual(original["summary"]["eligible_windows"], 1)
        self.assertEqual(original["summary"]["uncertain_windows_excluded"], 1)
        self.assertEqual(original["summary"]["invalid_windows_excluded"], 1)
        for uncertain in ("clean", "artifact"):
            for invalid in ("clean", "artifact"):
                predictions = [
                    {"window_id": rows[1]["window_id"], "decision": uncertain},
                    {"window_id": "integration-demo-001:window-000001", "decision": invalid},
                    eligible_prediction,
                ]
                self.assertEqual(evaluate_review_sheet(SESSION, path, predictions), original)

    def test_synthetic_copy_is_completed_and_validated_before_predictions(self):
        from eeg_app.math_pipeline import demo_peak_to_peak_prediction
        output = self.root / "dry-run"
        calls = []

        def check_order(record):
            sheet = output / "completed_synthetic_review.csv"
            self.assertTrue(sheet.exists())
            validated = validate_review_sheet(SESSION, sheet)
            self.assertEqual(len(validated), 2)
            self.assertTrue((output / "reference_records.json").exists())
            self.assertFalse((output / "predictions.json").exists())
            calls.append(record["window_id"])
            return demo_peak_to_peak_prediction(record)

        with patch("eeg_app.math_pipeline.demo_peak_to_peak_prediction", side_effect=check_order):
            report = run_synthetic_dry_run(output)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["evaluation"]["summary"]["eligible_windows"], 2)
        self.assertEqual(report["evaluation"]["summary"]["uncertain_windows_excluded"], 0)
        self.assertEqual(report["evaluation"]["summary"]["invalid_windows_excluded"], 1)
        self.assertEqual(len(report["missing_eligible_prediction_errors"]), 2)
        self.assertTrue(report["excluded_predictions_cannot_change_metrics"])
        with (output / "reviewer_bundle/review.csv").open(encoding="utf-8", newline="") as stream:
            self.assertTrue(all(row["label"] == "" for row in csv.DictReader(stream)))
        self.assertTrue((output / "dry_run_report.json").exists())

    def test_synthetic_dry_run_refuses_non_synthetic_metadata(self):
        # Guard the automatic example completion: it must never label pilot data.
        with patch("eeg_app.review_demo.json.loads", return_value={"data_source": "pilot"}):
            with self.assertRaisesRegex(ValueError, "restricted to the existing synthetic"):
                run_synthetic_dry_run(self.root / "not-created")
        self.assertFalse((self.root / "not-created").exists())


if __name__ == "__main__":
    unittest.main()
