"""Bounded rule selection on synthetic training and P0005 validation records."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eeg_app.math_detector import WindowExcluded
from eeg_app.preprocessing import REQUIRED_CHANNELS
from eeg_app.rule_search import derive_rule_grid, predict_policy, validate_rule_grid
from eeg_app.threshold_search import P0005_SESSIONS
from tests.test_threshold_search import prepared_rows


def add_extra_features(prepared, values):
    for record, (std, kurtosis, entropy) in zip(prepared["features"], values):
        record["units"] = {}
        for channel in REQUIRED_CHANNELS:
            record["features"].update({
                f"{channel}_standard_deviation_uv": std,
                f"{channel}_kurtosis": kurtosis,
                f"{channel}_approximate_entropy": entropy,
                f"{channel}_flatline_fraction": .01,
            })
        record["units"] = {key: "microvolts" if key.endswith("_uv") else "dimensionless"
                           for key in record["features"]}
        record["settings"] = {
            "sample_count_per_channel": 512, "continuous": True, "input_units": "microvolts",
            "flatline_tolerance_uv": .1, "entropy_m": 2,
            "entropy_tolerance_rule": "0.2 * per-channel population standard deviation",
            "entropy_convention": "natural log, self-matches, inclusive tolerance",
            "moment_convention": "population moments; Pearson kurtosis without bias correction",
        }
    return prepared


class RuleSearchTests(unittest.TestCase):
    def setUp(self):
        self.sessions = {"training": "training-person"}
        self.training = add_extra_features(
            prepared_rows([(10, 1), (20, 2), (80, 3), (100, 4)] + [(30, 1)] * 4,
                          ["clean"] * 4 + ["artifact"] * 4, list(self.sessions), "training-person"),
            [(1, 2, 1), (2, 2.5, 1.2), (3, 3, 1.4), (4, 3.5, 1.6)] + [(20, 10, .2)] * 4,
        )
        self.validation = add_extra_features(
            prepared_rows([(10, 0)] * 12, ["clean"] * 10 + ["artifact"] * 2,
                          P0005_SESSIONS, "P0005"),
            [(2, 3, 1.3)] * 9 + [(4, 3, 1.3)] + [(20, 10, .2)] * 2,
        )

    def test_training_selects_high_kurtosis_and_low_entropy(self):
        grid = derive_rule_grid(self.training, self.sessions)
        extras = {row["feature"]: row for row in grid["extra_rule_grids"]}
        self.assertEqual(extras["kurtosis"]["direction"], "high")
        self.assertEqual(extras["approximate_entropy"]["direction"], "low")
        entropy = extras["approximate_entropy"]["rules"][0]
        self.assertEqual(entropy["comparison"], "<")
        self.assertEqual(entropy["units"], "dimensionless")
        self.assertAlmostEqual(entropy["threshold"], 1.12)
        kurtosis = extras["kurtosis"]["rules"][0]
        self.assertAlmostEqual(kurtosis["threshold"], 3.2)
        self.assertEqual(len(grid["training_grid"]["candidates"]), 16)
        self.assertEqual(len(grid["original_recipe_candidates"]), 3)
        self.assertTrue(all(len(extra["rules"]) == 4 for extra in extras.values()))

    def test_low_kurtosis_is_supported_when_training_indicates_it(self):
        for record in self.training["features"][4:]:
            for channel in REQUIRED_CHANNELS:
                record["features"][f"{channel}_kurtosis"] = 1
        grid = derive_rule_grid(self.training, self.sessions)
        kurtosis = next(row for row in grid["extra_rule_grids"] if row["feature"] == "kurtosis")
        self.assertEqual(kurtosis["direction"], "low")

    def test_added_rules_can_trigger_on_each_channel_and_equality_passes(self):
        grid = derive_rule_grid(self.training, self.sessions)
        for extra in grid["extra_rule_grids"]:
            rule = extra["rules"][0]
            policy = {"settings": grid["training_grid"]["candidates"][-1]["settings"],
                      "additional_rules": [rule]}
            for channel in REQUIRED_CHANNELS:
                record = copy.deepcopy(self.validation["features"][0])
                feature = rule["feature"]
                for name in REQUIRED_CHANNELS:
                    record["features"][f"{name}_{feature}"] = rule["threshold"]
                self.assertEqual(predict_policy(record, policy)["decision"], "clean")
                record["features"][f"{channel}_{feature}"] += .01 if rule["comparison"] == ">" else -.01
                prediction = predict_policy(record, policy)
                self.assertEqual(prediction["decision"], "artifact")
                self.assertEqual(prediction["triggers"][0]["channel"], channel)

    def test_missing_added_feature_is_checked_after_a_base_trigger(self):
        grid = derive_rule_grid(self.training, self.sessions)
        policy = {"settings": grid["training_grid"]["candidates"][0]["settings"],
                  "additional_rules": [grid["extra_rule_grids"][0]["rules"][0]]}
        record = copy.deepcopy(self.validation["features"][0])
        record["features"]["TP9_peak_to_peak_uv"] = 1000
        record["features"]["TP10_standard_deviation_uv"] = None
        with self.assertRaisesRegex(WindowExcluded, "TP10_standard_deviation"):
            predict_policy(record, policy)

    def test_negative_entropy_is_valid_and_units_are_checked(self):
        grid = derive_rule_grid(self.training, self.sessions)
        entropy = next(row for row in grid["extra_rule_grids"] if row["feature"] == "approximate_entropy")
        policy = {"settings": grid["training_grid"]["candidates"][0]["settings"],
                  "additional_rules": [entropy["rules"][0]]}
        record = copy.deepcopy(self.validation["features"][0])
        record["features"]["AF8_approximate_entropy"] = -.1
        result = predict_policy(record, policy)
        self.assertEqual(result["decision"], "artifact")
        self.assertEqual(result["triggers"][0]["feature"], "approximate_entropy")
        record["units"]["AF8_approximate_entropy"] = "microvolts"
        with self.assertRaisesRegex(WindowExcluded, "expected dimensionless"):
            predict_policy(record, policy)

    def test_validation_keeps_only_the_extension_that_improves_the_objective(self):
        grid = derive_rule_grid(self.training, self.sessions)
        original_grid = copy.deepcopy(grid)
        result = validate_rule_grid(grid, self.validation)
        stages = {stage["variant"]: stage for stage in result["stages"]}
        self.assertTrue(stages["standard_deviation_uv"]["retain"])
        self.assertFalse(stages["kurtosis"]["retain"])
        self.assertFalse(stages["approximate_entropy"]["retain"])
        self.assertEqual(sum(len(stage["candidates"]) for stage in result["stages"]), 31)
        self.assertEqual(len(result["recommendation"]["policy"]["additional_rules"]), 1)
        self.assertEqual(original_grid, grid)
        self.assertEqual(result, validate_rule_grid(grid, self.validation))

    def test_unavailable_extra_disqualifies_its_candidates_and_definition_changes_fail(self):
        grid = derive_rule_grid(self.training, self.sessions)
        self.validation["features"][0]["features"]["TP9_kurtosis"] = None
        result = validate_rule_grid(grid, self.validation)
        stage = next(row for row in result["stages"] if row["variant"] == "kurtosis")
        self.assertFalse(stage["retain"])
        self.assertIsNone(stage["best"])
        self.assertTrue(all(candidate["evaluation"] is None for candidate in stage["candidates"]))
        self.validation["features"][0]["settings"]["entropy_m"] = 3
        with self.assertRaisesRegex(ValueError, "definitions"):
            validate_rule_grid(grid, self.validation)

    def test_cli_repeats_from_saved_inputs_without_public_or_reserved_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in (("training", self.training), ("sessions", self.sessions),
                                  ("validation", self.validation)):
                (root / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
            base = [sys.executable, "-m", "eeg_app.rule_search"]
            fit = subprocess.run(base + ["derive", str(root / "training.json"), str(root / "sessions.json"),
                                         str(root / "grid.json")], capture_output=True, text=True)
            self.assertEqual(fit.returncode, 0, fit.stderr)
            validate = subprocess.run(base + ["validate", str(root / "grid.json"), str(root / "validation.json"),
                                              str(root / "report.json")], capture_output=True, text=True)
            self.assertEqual(validate.returncode, 0, validate.stderr)
            self.assertEqual(json.loads((root / "report.json").read_text())["status"],
                             "awaiting_operating_point_approval")


if __name__ == "__main__":
    unittest.main()
