"""Saved-method inference and returned-report audits using synthetic EEG only."""

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

from eeg_app.final_evaluation import (
    check_settings, object_hash, predict_sessions, score_bundle, source_versions,
)
from eeg_app.math_detector import DetectorSettings
from eeg_app.math_pipeline import extract_window_features
from eeg_app.review import REVIEW_COLUMNS, load_windows
from eeg_app.rule_search import feature_definition


FIXTURE = Path(__file__).parent / "fixtures/integration/integration-demo-001"


class FinalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        record = extract_window_features(load_windows(FIXTURE)[0], flatline_tolerance_uv=.1)
        cls.base_settings = {
            "schema_version": 1, "status": "proposed_pending_approval", "approval": {},
            "development_label_status": "preliminary", "open_items": ["Synthetic draft"],
            "channel_order": ["TP9", "AF7", "AF8", "TP10"], "nominal_sample_rate_hz": 256,
            "math_policy": {"settings": DetectorSettings(2, 123, 52, "Synthetic test limits").to_dict(),
                            "additional_rules": []},
            "feature_definition": feature_definition([record]), "source_sha256_lf": source_versions(),
            "cnn": {"cutoff": .5, "comparison": ">=", "model_version": "synthetic-cnn",
                    "preprocessing_version": "synthetic-v1", "checkpoint_sha256": None,
                    "source_sha256_lf": None},
            "training_majority_decision": "artifact", "proposed_minimum_clean_retention": .8,
        }
        cls.manifest = {FIXTURE.name: {"path": str(FIXTURE), "participant_id": "synthetic-person"}}
        cls.cnn = [{"window_id": f"{FIXTURE.name}:window-{index:06d}", "session_id": FIXTURE.name,
                    "participant_id": "synthetic-person", "decision": label, "artifact_score": score,
                    "model_version": "synthetic-cnn", "preprocessing_version": "synthetic-v1"}
                   for index, label, score in ((0, "clean", .1), (2, "artifact", .9))]
        cls.base_bundle = predict_sessions(cls.manifest, cls.base_settings, cnn_records=cls.cnn, development=True)
        rows = []
        for index, label in ((0, "clean"), (2, "artifact")):
            row = dict.fromkeys(REVIEW_COLUMNS, "")
            row.update(window_id=f"{FIXTURE.name}:window-{index:06d}", session_id=FIXTURE.name,
                       start_time_s=str(index * 2), end_time_s=str(index * 2 + 2),
                       reviewer_id="synthetic-reviewer", label=label)
            rows.append(row)
        cls.base_sheets = {FIXTURE.name: (list(REVIEW_COLUMNS), rows)}

    def setUp(self):
        self.settings = copy.deepcopy(self.base_settings)
        self.bundle = copy.deepcopy(self.base_bundle)
        self.sheets = copy.deepcopy(self.base_sheets)

    def score(self):
        return score_bundle(self.bundle, self.sheets, self.settings, "synthetic-v1", development=True)

    def test_six_features_each_channel_and_gap_remains_excluded(self):
        self.assertEqual(len(self.bundle["feature_records"]), 2)
        self.assertTrue(all(len(row["features"]) == 24 for row in self.bundle["feature_records"]))
        self.assertEqual(len(self.bundle["math"]), 2)
        self.assertEqual(len(self.bundle["windows"]), 3)
        self.assertEqual(self.bundle["excluded_windows"][0]["window_id"],
                         f"{FIXTURE.name}:window-000001")
        self.assertTrue(self.bundle["excluded_windows"][0]["reasons"])
        report = self.score()
        self.assertEqual(report["policies"]["mathematical_detector"]["counts"],
                         {"true_positives": 1, "false_positives": 0, "true_negatives": 1, "false_negatives": 0})
        self.assertEqual(report["policies"]["combined_detector"]["metrics"]["coverage"],
                         {"numerator": 1, "denominator": 2, "value": .5})

    def test_draft_source_change_and_unreconciled_labels_cannot_run_reserved(self):
        with self.assertRaisesRegex(ValueError, "approved frozen"):
            check_settings(self.settings)
        self.settings["source_sha256_lf"]["eeg_app/features.py"] = "changed"
        with self.assertRaisesRegex(ValueError, "Source version"):
            check_settings(self.settings, development=True)
        self.settings = copy.deepcopy(self.base_settings)
        self.settings.update(status="approved_frozen", approval={"approved_by": "synthetic", "approved_at": "test"})
        with self.assertRaisesRegex(ValueError, "reconciled"):
            check_settings(self.settings)

    def test_missing_eligible_predictions_are_errors_for_both_methods(self):
        for key in ("math", "cnn"):
            with self.subTest(method=key):
                self.bundle = copy.deepcopy(self.base_bundle)
                self.bundle[key] = self.bundle[key][:-1]
                with self.assertRaisesRegex(ValueError, "Missing prediction"):
                    self.score()

    def test_duplicate_unknown_and_metadata_mismatch_are_errors(self):
        for change, message in (("duplicate", "Duplicate"), ("unknown", "Unknown"),
                                ("session", "session_id mismatch"), ("participant", "participant_id mismatch")):
            self.bundle = copy.deepcopy(self.base_bundle)
            if change == "duplicate":
                self.bundle["math"].append(self.bundle["math"][0])
            elif change == "unknown":
                self.bundle["cnn"][0]["window_id"] = "unknown"
            else:
                self.bundle["cnn"][0][f"{change}_id"] = "wrong"
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                self.score()

    def test_missing_feature_or_changed_trigger_cannot_become_clean(self):
        self.bundle["feature_records"][0]["features"]["TP10_max_adjacent_jump_uv"] = None
        with self.assertRaisesRegex(ValueError, "TP10_max_adjacent_jump_uv"):
            self.score()
        self.bundle = copy.deepcopy(self.base_bundle)
        self.bundle["math"][1]["triggers"] = []
        with self.assertRaisesRegex(ValueError, "triggers changed"):
            self.score()

    def test_changed_cutoff_settings_shape_and_feature_metadata_fail(self):
        self.bundle["cnn"][0]["decision"] = "artifact"
        with self.assertRaisesRegex(ValueError, "saved cutoff"):
            self.score()
        self.bundle = copy.deepcopy(self.base_bundle)
        self.bundle["feature_records"][0]["session_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "Feature metadata"):
            self.score()
        self.settings["cnn"]["cutoff"] = .7
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.score()

    def test_uncertain_stays_distinct_and_reordering_is_repeatable(self):
        first = self.score()
        self.bundle["math"].reverse()
        self.bundle["cnn"].reverse()
        second = self.score()
        self.assertEqual(first["policies"], second["policies"])
        self.sheets[FIXTURE.name][1][0]["label"] = "uncertain"
        report = self.score()
        summary = report["policies"]["mathematical_detector"]["summary"]
        self.assertEqual(summary["eligible_windows"], 1)
        self.assertEqual(summary["uncertain_windows_excluded"], 1)
        self.assertEqual(summary["invalid_windows_excluded"], 1)

    def test_all_four_combination_cases_use_both_clean_rule(self):
        from eeg_app.metrics import compare_detectors
        refs = [{"window_id": str(i), "label": "clean"} for i in range(4)]
        math = [{"window_id": str(i), "decision": value} for i, value in
                enumerate(("clean", "artifact", "clean", "artifact"))]
        cnn = [{"window_id": str(i), "decision": value} for i, value in
               enumerate(("clean", "artifact", "artifact", "clean"))]
        result = compare_detectors(refs, math, cnn)
        self.assertEqual(result["combined_detector"]["counts"]["true_negatives"], 1)
        self.assertEqual(result["combined_detector"]["counts"]["false_positives"], 3)

    def test_cpu_checkpoint_interface_reloads_and_preserves_all_four_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "synthetic.pt"
            checkpoint.write_bytes(b"synthetic checkpoint; no real model")
            source = root / "synthetic_backend.py"
            source.write_text("# synthetic backend interface\n", encoding="utf-8")
            self.settings["cnn"]["checkpoint_sha256"] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            self.settings["cnn"]["source_sha256_lf"] = hashlib.sha256(
                source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            def infer(examples, model, *, fold_id):
                self.assertEqual(len(examples), 2)
                for example, expected in zip(examples, (0, 2)):
                    self.assertEqual(example.samples_uv.shape, (4, 512))
                    self.assertEqual(example.window_id, f"{FIXTURE.name}:window-{expected:06d}")
                    self.assertEqual(example.review_label, "inference_only")
                return copy.deepcopy(self.cnn)
            backend = SimpleNamespace(__file__=str(source), WaveformExample=SimpleNamespace,
                                      load_checkpoint=Mock(return_value=object()), predict_examples=Mock(side_effect=infer))
            self.settings.update(status="approved_frozen", development_label_status="reconciled", open_items=[],
                                 approval={"approved_by": "synthetic-test-only", "approved_at": "synthetic-test-only"})
            bundle = predict_sessions(self.manifest, self.settings, checkpoint=checkpoint,
                                      backend=backend)
            self.assertTrue(bundle["cnn_input"]["reload_reproduces_predictions"])
            self.assertEqual(backend.load_checkpoint.call_count, 2)
            report = score_bundle(bundle, self.sheets, self.settings, "synthetic-v1")
            self.assertEqual(report["data_role"], "reserved_evaluation")
            checkpoint.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checkpoint hash"):
                predict_sessions(self.manifest, self.settings, checkpoint=checkpoint,
                                 backend=backend)

    def test_cli_predict_score_verify_and_corrupt_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in (("settings", self.settings), ("manifest", self.manifest), ("cnn", self.cnn)):
                (root / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
            text = io.StringIO(newline="")
            writer = csv.DictWriter(text, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(self.sheets[FIXTURE.name][1])
            with ZipFile(root / "reviews.zip", "w") as archive:
                archive.writestr("synthetic-review.csv", text.getvalue())
            base = [sys.executable, "-m", "eeg_app.final_evaluation"]
            common = ["--settings", str(root / "settings.json"), "--development"]
            predict = base + ["predict", str(root / "manifest.json"), "--cnn-predictions", str(root / "cnn.json"),
                              "--output-dir", str(root / "predictions")] + common
            run = subprocess.run(predict, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            repeat = subprocess.run(predict, capture_output=True, text=True)
            self.assertNotEqual(repeat.returncode, 0)
            score_args = [str(root / "predictions/predictions.json"), "--labels", str(root / "reviews.zip"),
                          "--label-release", "synthetic-v1"] + common
            run = subprocess.run(base + ["score"] + score_args + ["--output-dir", str(root / "report")],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            verify = base + ["verify"] + score_args + ["--report", str(root / "report/report.json")]
            run = subprocess.run(verify, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads((root / "report/report.json").read_text())
            report["policies"]["mathematical_detector"]["metrics"]["recall"]["denominator"] += 1
            (root / "report/report.json").write_text(json.dumps(report), encoding="utf-8")
            run = subprocess.run(verify, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("denominators", run.stderr)


if __name__ == "__main__":
    unittest.main()
