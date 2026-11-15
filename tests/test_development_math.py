"""Synthetic saved-session to held-out comparison check."""

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from eeg_app.development_math import evaluate, prepare
from eeg_app.review import REVIEW_COLUMNS


FIXTURE = Path(__file__).parent / "fixtures/integration/integration-demo-001"


class DevelopmentMathTests(unittest.TestCase):
    def test_review_to_fold_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir()
            review = root / "reviews.zip"
            original = FIXTURE.name
            metadata = json.loads((FIXTURE / "metadata.json").read_text())
            samples = (FIXTURE / "eeg.csv").read_text()
            people = ["synthetic-a", "synthetic-b", "synthetic-c", "synthetic-d"]
            participants = {}
            with ZipFile(review, "w") as archive:
                for index, participant in enumerate(people):
                    session = f"test-session-{index}"
                    participants[session] = participant
                    target = sessions / session
                    target.mkdir()
                    (target / "metadata.json").write_text(json.dumps({**metadata, "session_id": session}))
                    (target / "eeg.csv").write_text(samples.replace(original, session))
                    sheet = io.StringIO(newline="")
                    writer = csv.DictWriter(sheet, fieldnames=REVIEW_COLUMNS)
                    writer.writeheader()
                    for slot, label in ((0, "clean"), (2, "artifact")):
                        writer.writerow({"session_id": session, "window_id": f"{session}:window-{slot:06d}",
                                         "start_time_s": 2 * slot, "end_time_s": 2 * slot + 2,
                                         "reviewer_id": "synthetic", "label": label,
                                         "affected_channels": "af7,tp9" if label == "artifact" else ""})
                    archive.writestr(f"{session}.csv", sheet.getvalue())
            prepared = prepare([("fixture-v1", review)], sessions, participants, .1)
            self.assertEqual(prepared["label_counts"], {"clean": 4, "artifact": 4, "invalid": 4})
            self.assertTrue(all(len(r["features"]) == 24 for r in prepared["features"]))
            folds = []
            for index, heldout in enumerate(people):
                validation = people[(index + 1) % len(people)]
                folds.append({"fold_id": f"fold-{index}", "heldout": heldout, "validation": validation,
                              "training": [person for person in people if person not in {heldout, validation}]})
            cnn = [{"window_id": r["window_id"], "decision": r["label"], "score": 0.9,
                    "fold_id": f"fold-{people.index(r['participant_id'])}"}
                   for r in prepared["references"] if r["label"] != "invalid"]
            result = evaluate(prepared, folds, cnn)
            self.assertEqual(result["label_releases"], ["fixture-v1"])
            self.assertEqual(len(result["mathematical_predictions"]), 8)
            self.assertEqual(result["comparison"]["machine_learning_detector"]["counts"]["true_positives"], 4)
            self.assertEqual(result, evaluate(prepared, folds, cnn))
            with self.assertRaisesRegex(ValueError, "Missing prediction"):
                evaluate(prepared, folds, cnn[:-1])
            with self.assertRaisesRegex(ValueError, "mismatched held-out fold"):
                evaluate(prepared, folds, [{**cnn[0], "fold_id": "wrong"}] + cnn[1:])
