"""Tests for waveform-only CNN input preparation (no real participant data)."""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from eeg_app.waveform_cnn import (
    SAMPLE_COUNT,
    WaveformExample,
    _to_example,
    build_waveform_cnn,
    eligible_examples,
    fit_channel_normalizer,
    load_checkpoint,
    load_final_review_labels,
    make_rotating_participant_folds,
    normalize_waveforms,
    predict_examples,
    save_checkpoint,
    train_baseline,
    validate_split_manifest,
    write_prediction_records,
)
from eeg_app.dataset import EegWindow


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

    def test_unequal_channel_arrays_become_an_exclusion(self) -> None:
        window = EegWindow(
            "ses-a:window-000000", "ses-a", 0.0, 2.0, 256.0,
            {"TP9": (1.0,) * 512, "AF7": (1.0,) * 511, "AF8": (1.0,) * 512, "TP10": (1.0,) * 512},
            {"TP9": (), "AF7": (), "AF8": (), "TP10": ()}, False, ("incomplete",),
        )
        review = type("Review", (), {"label": "clean"})()
        example = _to_example(window, "P001", review)
        self.assertFalse(example.is_valid)
        self.assertIsNone(example.label)
        self.assertIn("unequal channel sample counts", example.exclusion_reason or "")

    def test_manifest_rejects_duplicate_ids_overlap_missing_and_empty_splits(self) -> None:
        duplicate = {"folds": [
            {"fold_id": "one", "training": ["P001"], "validation": "P002", "held_out": "P003"},
            {"fold_id": "one", "training": ["P001"], "validation": "P002", "held_out": "P003"},
        ]}
        with self.assertRaisesRegex(ValueError, "Duplicate fold ID"):
            validate_split_manifest(duplicate)
        overlap = {"folds": [{"fold_id": "one", "training": ["P001", "P002"], "validation": "P002", "held_out": "P003"}]}
        with self.assertRaisesRegex(ValueError, "overlapping"):
            validate_split_manifest(overlap)
        empty = {"folds": [{"fold_id": "one", "training": [], "validation": "P002", "held_out": "P003"}]}
        with self.assertRaisesRegex(ValueError, "empty"):
            validate_split_manifest(empty)
        missing = {"folds": [{"fold_id": "one", "training": ["P001"], "validation": "P002", "held_out": "P003"}]}
        with self.assertRaisesRegex(ValueError, "missing labeled participants"):
            validate_split_manifest(missing, available_participants={"P001", "P002", "P003", "P004"})

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch is required for the network smoke test")
    def test_network_trains_saves_reloads_and_reproduces_predictions(self) -> None:
        import torch

        model = build_waveform_cnn()
        self.assertEqual(tuple(model(torch.zeros((2, 4, SAMPLE_COUNT))).shape), (2,))
        train = [
            WaveformExample(f"train-{index}", "train", "P001", np.full((4, SAMPLE_COUNT), float(index), dtype=np.float32), index % 2, "artifact" if index % 2 else "clean", True)
            for index in range(4)
        ]
        validation = [
            WaveformExample(f"validation-{index}", "validation", "P002", np.full((4, SAMPLE_COUNT), float(index + 5), dtype=np.float32), index % 2, "artifact" if index % 2 else "clean", True)
            for index in range(2)
        ]
        result = train_baseline(train, validation, max_epochs=2, patience=1, batch_size=2, seed=3)
        before = predict_examples(validation, result, fold_id="synthetic")
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "model.pt"
            save_checkpoint(result, checkpoint)
            after = predict_examples(validation, load_checkpoint(checkpoint), fold_id="synthetic")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
