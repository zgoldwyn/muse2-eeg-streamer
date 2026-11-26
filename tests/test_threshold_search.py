"""Clean-only calibration and P0005 validation with synthetic feature values."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eeg_app.threshold_search import P0005_SESSIONS, derive_candidates, validate_candidates
from tests.test_math_detector import make_record


def prepared_rows(values, labels, sessions, participant):
    references, features = [], []
    for index, ((peak, jump), label) in enumerate(zip(values, labels)):
        session = sessions[index % len(sessions)]
        record = make_record(f"{session}:window-{index:06d}")
        record.update(session_id=session, participant_id=participant)
        for key in record["features"]:
            record["features"][key] = jump if key.endswith("max_adjacent_jump_uv") else peak
        features.append(record)
        references.append({"window_id": record["window_id"], "session_id": session,
                           "participant_id": participant, "label": label, "label_release": "synthetic-v1"})
    return {"references": references, "features": features}


class ThresholdSearchTests(unittest.TestCase):
    def setUp(self):
        self.sessions = {"training-session": "training-person"}
        self.training = prepared_rows([(10, 1), (20, 2), (80, 3), (100, 4), (10000, 10000)],
                                      ["clean"] * 4 + ["artifact"], list(self.sessions), "training-person")

    def validation(self):
        return prepared_rows([(10 * n, 0) for n in range(1, 11)] + [(120, 0), (130, 0)],
                             ["clean"] * 10 + ["artifact"] * 2, P0005_SESSIONS, "P0005")

    def test_grid_is_clean_only_and_has_independent_percentiles(self):
        grid = derive_candidates(self.training, self.sessions)
        self.assertEqual(len(grid["candidates"]), 16)
        self.assertEqual(grid["clean_windows_used"], 4)
        self.assertAlmostEqual(grid["thresholds_uv"]["peak_to_peak_uv"]["80"], 88)
        self.assertAlmostEqual(grid["thresholds_uv"]["max_adjacent_jump_uv"]["99"], 3.97)
        candidate = next(row for row in grid["candidates"] if row["candidate_id"] == "p2p-p80-jump-p99")
        self.assertEqual(candidate["settings"]["peak_to_peak_uv"], 88)
        self.assertAlmostEqual(candidate["settings"]["max_adjacent_jump_uv"], 3.97)
        # Even malformed artifact values cannot influence calibration.
        self.training["features"][-1]["features"] = dict.fromkeys(self.training["features"][-1]["features"], None)
        self.assertEqual(grid, derive_candidates(self.training, self.sessions))

    def test_maximum_uses_every_channel_and_missing_clean_values_are_reported(self):
        self.training["features"][0]["features"]["TP10_peak_to_peak_uv"] = 200
        changed = derive_candidates(self.training, self.sessions)
        self.assertGreater(changed["thresholds_uv"]["peak_to_peak_uv"]["99"], 100)
        self.training["features"][0]["features"]["AF8_max_adjacent_jump_uv"] = None
        changed = derive_candidates(self.training, self.sessions)
        self.assertEqual(changed["clean_windows_used"], 3)
        self.assertIn("AF8_max_adjacent_jump_uv", str(changed["clean_input_exclusions"]))

    def test_validation_reports_nearest_80_and_90_percent_options(self):
        grid = derive_candidates(self.training, self.sessions)
        before = copy.deepcopy(grid)
        result = validate_candidates(grid, self.validation())
        self.assertEqual([row["achieved_clean_retention"] for row in result["retention_options"]], [.8, .9])
        self.assertTrue(all(row["evaluation"]["metrics"]["recall"]["value"] == 1 for row in result["candidates"]))
        self.assertEqual(before, grid)
        self.assertEqual(result, validate_candidates(grid, self.validation()))

    def test_equality_does_not_trigger_and_uncertain_stays_excluded(self):
        grid = derive_candidates(self.training, self.sessions)
        validation = self.validation()
        validation["features"][0]["features"]["TP9_peak_to_peak_uv"] = 88
        validation["references"][-1]["label"] = "uncertain"
        result = validate_candidates(grid, validation)
        candidate = next(row for row in result["candidates"] if row["candidate_id"] == "p2p-p80-jump-p80")
        self.assertEqual(candidate["evaluation"]["counts"]["true_negatives"], 8)
        self.assertEqual(candidate["evaluation"]["summary"]["uncertain_windows_excluded"], 1)

    def test_scope_ids_and_validation_completeness(self):
        reserved = copy.deepcopy(self.training)
        reserved["references"][0]["session_id"] = "reserved-repeat"
        with self.assertRaisesRegex(ValueError, "outside the approved"):
            derive_candidates(reserved, self.sessions)
        duplicate = copy.deepcopy(self.training)
        duplicate["features"].append(duplicate["features"][0])
        with self.assertRaisesRegex(ValueError, "duplicate feature"):
            derive_candidates(duplicate, self.sessions)
        grid = derive_candidates(self.training, self.sessions)
        validation = self.validation()
        validation["features"][0]["features"]["TP9_peak_to_peak_uv"] = None
        with self.assertRaisesRegex(ValueError, "Missing/unavailable"):
            validate_candidates(grid, validation)
        with self.assertRaisesRegex(ValueError, "outside the approved"):
            validate_candidates(grid, self.training)
        with self.assertRaisesRegex(ValueError, "reserved for development validation"):
            derive_candidates(self.validation(), dict.fromkeys(P0005_SESSIONS, "P0005"))

    def test_cli_derives_and_validates_saved_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in (("training", self.training), ("sessions", self.sessions),
                                  ("validation", self.validation())):
                (root / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
            base = [sys.executable, "-m", "eeg_app.threshold_search"]
            command = base + ["derive", str(root / "training.json"), str(root / "sessions.json"), str(root / "grid.json")]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = subprocess.run(base + ["validate", str(root / "grid.json"), str(root / "validation.json"),
                                           str(root / "report.json")], capture_output=True, text=True)
            self.assertEqual(report.returncode, 0, report.stderr)
            saved = json.loads((root / "report.json").read_text())
            self.assertEqual(len(saved["candidates"]), 16)
            self.assertIn("candidate_grid_sha256", saved)
            repeat = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeat.returncode, 0)


if __name__ == "__main__":
    unittest.main()
