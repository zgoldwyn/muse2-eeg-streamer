"""Tests for waveform-only CNN input preparation (no real participant data)."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from eeg_app.waveform_cnn import (
    SAMPLE_COUNT,
    WaveformExample,
    eligible_examples,
    fit_channel_normalizer,
    load_final_review_labels,
    make_rotating_participant_folds,
    normalize_waveforms,
    write_prediction_records,
)


class WaveformCnnDataTests(unittest.TestCase):
    def example(self, label: int | None = 0, participant: str = "P001") -> WaveformExample:
        return WaveformExample("ses-a:window-000000", "ses-a", participant, np.ones((4, 512), dtype=np.float32), label, "clean", True)

    def test_normalizer_uses_training_examples_and_preserves_batch_shape(self) -> None:
        train = [
            WaveformExample("a", "ses-a", "P001", np.full((4, 512), 2.0, dtype=np.float32), 0, "clean", True),
            WaveformExample("b", "ses-b", "P002", np.full((4, 512), 6.0, dtype=np.float32), 1, "artifact", True),
        ]
        mean, std = fit_channel_normalizer(train)
        normalized = normalize_waveforms(train, mean, std)
        self.assertEqual(normalized.shape, (2, 4, SAMPLE_COUNT))
        self.assertTrue(np.allclose(mean, 4.0))
        self.assertTrue(np.allclose(std, 2.0))

    def test_uncertain_windows_are_not_eligible(self) -> None:
        eligible = eligible_examples([self.example(0), self.example(None)])
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].label, 0)

    def test_rotating_folds_keep_people_disjoint(self) -> None:
        folds = make_rotating_participant_folds(["P001", "P0002", "P0003", "P0004"])
        self.assertEqual(len(folds), 4)
        self.assertEqual({fold["held_out"] for fold in folds}, {"P001", "P0002", "P0003", "P0004"})
        for fold in folds:
            members = set(fold["training"]) | {fold["validation"], fold["held_out"]}
            self.assertEqual(len(members), 4)

    def test_duplicate_label_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["session_id", "window_id", "label"])
                writer.writeheader()
                writer.writerow({"session_id": "ses-a", "window_id": "ses-a:window-000000", "label": "clean"})
                writer.writerow({"session_id": "ses-a", "window_id": "ses-a:window-000000", "label": "artifact"})
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_final_review_labels([path])

    def test_duplicate_prediction_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            records = [{"window_id": "w-1"}, {"window_id": "w-1"}]
            with self.assertRaisesRegex(ValueError, "Duplicate prediction"):
                write_prediction_records(records, Path(directory) / "predictions.jsonl")


if __name__ == "__main__":
    unittest.main()
