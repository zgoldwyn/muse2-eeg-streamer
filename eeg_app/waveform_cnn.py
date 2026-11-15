"""Waveform-only CNN data preparation and CPU baseline utilities.

The CNN uses only the four EEG sample sequences.  IDs, times, event markers,
reviewer notes, and any mathematical-detector result remain audit metadata and
are never inputs to the model.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

from .dataset import EegWindow, create_fixed_windows, load_synthetic_session
from .preprocessing import REQUIRED_CHANNELS

CHANNEL_ORDER = REQUIRED_CHANNELS
SAMPLE_COUNT = 512
ARTIFACT_LABEL = "artifact"
CLEAN_LABEL = "clean"
UNCERTAIN_LABELS = frozenset({"uncertain", "unsure"})
MODEL_VERSION = "waveform-cnn-v1"
PREPROCESSING_VERSION = "channel-zscore-train-only-v1"


@dataclass(frozen=True)
class ReviewLabel:
    """Final human review label retained separately from the waveform."""

    window_id: str
    session_id: str
    label: str


@dataclass(frozen=True)
class WaveformExample:
    """One eligible or excluded review window with fixed-shape EEG samples."""

    window_id: str
    session_id: str
    participant_id: str
    samples_uv: np.ndarray
    label: int | None
    review_label: str
    is_valid: bool
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class JoinReport:
    """Counts that make exclusions visible rather than silently dropping rows."""

    eligible_clean: int
    eligible_artifact: int
    uncertain: int
    technically_invalid: int
    missing_waveform: int


@dataclass(frozen=True)
class TrainingResult:
    """Saved baseline state and validation history for one participant fold."""

    model_state: Mapping[str, object]
    normalizer_mean: np.ndarray
    normalizer_std: np.ndarray
    best_epoch: int
    validation_loss: float
    training_class_counts: Mapping[str, int]
    validation_class_counts: Mapping[str, int]


def load_final_review_labels(paths: Iterable[str | Path]) -> dict[str, ReviewLabel]:
    """Read released review CSVs and reject conflicting/duplicate window IDs."""
    labels: dict[str, ReviewLabel] = {}
    for candidate in paths:
        path = Path(candidate)
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            required = {"session_id", "window_id", "label"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError(f"{path} must contain session_id, window_id, and label columns.")
            for row_number, row in enumerate(reader, start=2):
                window_id = (row.get("window_id") or "").strip()
                session_id = (row.get("session_id") or "").strip()
                label = (row.get("label") or "").strip().lower()
                if not window_id or not session_id or not label:
                    raise ValueError(f"{path}:{row_number} has a missing required review value.")
                if not window_id.startswith(f"{session_id}:"):
                    raise ValueError(f"{path}:{row_number} window_id does not belong to its session.")
                review = ReviewLabel(window_id, session_id, label)
                previous = labels.get(window_id)
                if previous is not None:
                    raise ValueError(
                        f"Duplicate reviewed window {window_id!r} in {path}; "
                        "keep one final label release only."
                    )
                labels[window_id] = review
    return labels


def join_reviewed_waveforms(
    sessions_dir: str | Path, labels: Mapping[str, ReviewLabel]
) -> tuple[list[WaveformExample], JoinReport]:
    """Join review labels to complete local two-second waveform windows.

    Only a 4 x 512 microvolt array reaches ``WaveformExample.samples_uv``.
    ``uncertain``/``unsure`` and technically invalid windows are retained as
    exclusion records, never converted into a clean/artifact target.
    """
    root = Path(sessions_dir)
    labels_by_session: dict[str, list[ReviewLabel]] = {}
    for review in labels.values():
        labels_by_session.setdefault(review.session_id, []).append(review)

    examples: list[WaveformExample] = []
    missing_waveform = 0
    counts: Counter[str] = Counter()
    for session_id, session_labels in sorted(labels_by_session.items()):
        session_path = root / session_id
        eeg_path = session_path / "eeg.csv"
        metadata_path = session_path / "metadata.json"
        participant_path = session_path / "session.json"
        if not (eeg_path.is_file() and metadata_path.is_file() and participant_path.is_file()):
            missing_waveform += len(session_labels)
            continue
        participant_id = _participant_id(participant_path)
        windows = {
            window.window_id: window
            for window in create_fixed_windows(load_synthetic_session(eeg_path, metadata_path))
        }
        for review in session_labels:
            window = windows.get(review.window_id)
            if window is None:
                missing_waveform += 1
                continue
            example = _to_example(window, participant_id, review)
            examples.append(example)
            if example.label is not None:
                counts[review.label] += 1
            elif review.label in UNCERTAIN_LABELS:
                counts["uncertain"] += 1
            elif not window.is_valid:
                counts["technically_invalid"] += 1
            else:
                raise ValueError(f"Unsupported review label {review.label!r} for {review.window_id}.")
    return examples, JoinReport(
        eligible_clean=counts[CLEAN_LABEL],
        eligible_artifact=counts[ARTIFACT_LABEL],
        uncertain=counts["uncertain"],
        technically_invalid=counts["technically_invalid"],
        missing_waveform=missing_waveform,
    )


def _participant_id(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read participant metadata {path}: {error}") from error
    participant_id = data.get("participant_code")
    if not isinstance(participant_id, str) or not participant_id.strip():
        raise ValueError(f"{path} has no nonempty participant_code.")
    return participant_id.strip()


def _to_example(window: EegWindow, participant_id: str, review: ReviewLabel) -> WaveformExample:
    samples = np.asarray([window.channel_samples[channel] for channel in CHANNEL_ORDER], dtype=np.float32)
    if samples.shape != (len(CHANNEL_ORDER), SAMPLE_COUNT):
        return WaveformExample(
            window.window_id, window.session_id, participant_id, samples, None,
            review.label, False, f"unexpected waveform shape {samples.shape!r}",
        )
    if not np.isfinite(samples).all():
        return WaveformExample(
            window.window_id, window.session_id, participant_id, samples, None,
            review.label, False, "nonfinite waveform sample",
        )
    if not window.is_valid:
        return WaveformExample(
            window.window_id, window.session_id, participant_id, samples, None,
            review.label, False, "; ".join(window.invalid_reasons),
        )
    if review.label == CLEAN_LABEL:
        label = 0
    elif review.label == ARTIFACT_LABEL:
        label = 1
    elif review.label in UNCERTAIN_LABELS:
        return WaveformExample(
            window.window_id, window.session_id, participant_id, samples, None,
            review.label, True, "uncertain review label",
        )
    else:
        raise ValueError(f"Unsupported review label {review.label!r} for {review.window_id}.")
    return WaveformExample(window.window_id, window.session_id, participant_id, samples, label, review.label, True)


def eligible_examples(examples: Iterable[WaveformExample]) -> list[WaveformExample]:
    """Return only human-labeled clean/artifact, technically valid windows."""
    return [example for example in examples if example.is_valid and example.label in (0, 1)]


def fit_channel_normalizer(examples: Sequence[WaveformExample]) -> tuple[np.ndarray, np.ndarray]:
    """Estimate channel-wise normalization from training samples only."""
    if not examples:
        raise ValueError("Cannot fit a normalizer without training examples.")
    waveforms = np.stack([example.samples_uv for example in examples])
    mean = waveforms.mean(axis=(0, 2), dtype=np.float64).astype(np.float32)
    std = waveforms.std(axis=(0, 2), dtype=np.float64).astype(np.float32)
    if np.any(std <= 0) or not np.isfinite(mean).all() or not np.isfinite(std).all():
        raise ValueError("Training samples do not produce a finite, nonzero channel scale.")
    return mean, std


def normalize_waveforms(examples: Sequence[WaveformExample], mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """Apply training-only channel normalization without per-window scaling."""
    if tuple(mean.shape) != (4,) or tuple(std.shape) != (4,):
        raise ValueError("Normalizer mean and std must each have one value per required channel.")
    if not examples:
        return np.empty((0, 4, SAMPLE_COUNT), dtype=np.float32)
    result = (np.stack([example.samples_uv for example in examples]) - mean[None, :, None]) / std[None, :, None]
    if result.shape[1:] != (4, SAMPLE_COUNT) or not np.isfinite(result).all():
        raise ValueError("Normalization produced an invalid waveform batch.")
    return result.astype(np.float32)


def make_rotating_participant_folds(participant_ids: Sequence[str]) -> list[dict[str, tuple[str, ...] | str]]:
    """Return four-fold group splits: held-out, validation, and two train people."""
    unique = tuple(sorted(set(participant_ids)))
    if len(unique) != 4:
        raise ValueError("Exactly four development participants are required for rotating folds.")
    folds: list[dict[str, tuple[str, ...] | str]] = []
    for index, held_out in enumerate(unique):
        remaining = [candidate for candidate in unique if candidate != held_out]
        validation = remaining[index % len(remaining)]
        training = tuple(candidate for candidate in remaining if candidate != validation)
        folds.append({"fold_id": f"fold-{index + 1}-{held_out}", "held_out": held_out, "validation": validation, "training": training})
    return folds


def class_counts(examples: Sequence[WaveformExample]) -> dict[str, int]:
    """Count the eligible clean/artifact targets without treating exclusions as clean."""
    result = {CLEAN_LABEL: 0, ARTIFACT_LABEL: 0}
    for example in examples:
        if example.label == 0:
            result[CLEAN_LABEL] += 1
        elif example.label == 1:
            result[ARTIFACT_LABEL] += 1
    return result


def select_participants(
    examples: Sequence[WaveformExample], participant_ids: Iterable[str]
) -> list[WaveformExample]:
    """Select eligible windows while keeping participant identity outside model inputs."""
    allowed = set(participant_ids)
    return [example for example in eligible_examples(examples) if example.participant_id in allowed]


def train_baseline(
    training_examples: Sequence[WaveformExample],
    validation_examples: Sequence[WaveformExample],
    *,
    learning_rate: float = 1e-3,
    batch_size: int = 16,
    max_epochs: int = 40,
    patience: int = 6,
    seed: int = 17,
) -> TrainingResult:
    """Train a CPU CNN with train-only normalization and validation early stopping."""
    if min(batch_size, max_epochs, patience) <= 0 or learning_rate <= 0:
        raise ValueError("learning_rate, batch_size, max_epochs, and patience must be positive.")
    training_examples = eligible_examples(training_examples)
    validation_examples = eligible_examples(validation_examples)
    train_counts = class_counts(training_examples)
    validation_counts = class_counts(validation_examples)
    if not training_examples or not validation_examples:
        raise ValueError("Training and validation splits must both contain eligible reviewed windows.")
    if 0 in train_counts.values():
        raise ValueError(f"Training split lacks a required class: {train_counts}.")
    if 0 in validation_counts.values():
        raise ValueError(f"Validation split lacks a required class: {validation_counts}.")

    torch, _ = _torch()
    set_reproducible_seed(seed)
    mean, std = fit_channel_normalizer(training_examples)
    train_x = torch.from_numpy(normalize_waveforms(training_examples, mean, std))
    train_y = torch.tensor([example.label for example in training_examples], dtype=torch.float32)
    val_x = torch.from_numpy(normalize_waveforms(validation_examples, mean, std))
    val_y = torch.tensor([example.label for example in validation_examples], dtype=torch.float32)

    model = build_waveform_cnn()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    criterion = torch.nn.BCEWithLogitsLoss()
    best_state = None
    best_loss = float("inf")
    best_epoch = 0
    epochs_without_improvement = 0
    generator = torch.Generator().manual_seed(seed)

    for epoch in range(1, max_epochs + 1):
        model.train()
        for indices in torch.randperm(len(train_x), generator=generator).split(batch_size):
            optimizer.zero_grad()
            loss = criterion(model(train_x[indices]), train_y[indices])
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            validation_loss = float(criterion(model(val_x), val_y).item())
        if validation_loss < best_loss - 1e-8:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break
    assert best_state is not None
    return TrainingResult(best_state, mean, std, best_epoch, best_loss, train_counts, validation_counts)


def predict_examples(
    examples: Sequence[WaveformExample], result: TrainingResult, *, fold_id: str
) -> list[dict[str, object]]:
    """Return held-out prediction records using the saved evaluation-mode model."""
    examples = eligible_examples(examples)
    torch, _ = _torch()
    model = build_waveform_cnn()
    model.load_state_dict(result.model_state)
    model.eval()
    batch = torch.from_numpy(normalize_waveforms(examples, result.normalizer_mean, result.normalizer_std))
    with torch.no_grad():
        scores = torch.sigmoid(model(batch)).cpu().numpy()
    return [
        {
            "window_id": example.window_id,
            "decision": ARTIFACT_LABEL if float(score) >= 0.5 else CLEAN_LABEL,
            "artifact_score": float(score),
            "model_version": MODEL_VERSION,
            "preprocessing_version": PREPROCESSING_VERSION,
            "fold_id": fold_id,
            # Audit metadata, never model input:
            "session_id": example.session_id,
            "participant_id": example.participant_id,
        }
        for example, score in zip(examples, scores, strict=True)
    ]


def majority_class_predictions(examples: Sequence[WaveformExample], held_out: Sequence[WaveformExample]) -> list[dict[str, object]]:
    """Produce the documented majority-class comparator for a held-out fold."""
    counts = class_counts(eligible_examples(examples))
    if counts[CLEAN_LABEL] == counts[ARTIFACT_LABEL]:
        majority = CLEAN_LABEL
    else:
        majority = max(counts, key=counts.__getitem__)
    score = 1.0 if majority == ARTIFACT_LABEL else 0.0
    return [
        {"window_id": example.window_id, "decision": majority, "artifact_score": score, "model_version": "majority-class-v1"}
        for example in eligible_examples(held_out)
    ]


def write_prediction_records(records: Iterable[Mapping[str, object]], path: str | Path) -> None:
    """Write JSONL predictions and refuse duplicate output window IDs."""
    target = Path(path)
    seen: set[str] = set()
    lines: list[str] = []
    for record in records:
        window_id = record.get("window_id")
        if not isinstance(window_id, str) or not window_id:
            raise ValueError("Every prediction record must contain a nonempty window_id.")
        if window_id in seen:
            raise ValueError(f"Duplicate prediction window ID {window_id!r}.")
        seen.add(window_id)
        lines.append(json.dumps(dict(record), sort_keys=True))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def save_checkpoint(result: TrainingResult, path: str | Path) -> None:
    """Save one fold's model and training-only normalizer for later evaluation."""
    torch, _ = _torch()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state": dict(result.model_state),
            "normalizer_mean": result.normalizer_mean,
            "normalizer_std": result.normalizer_std,
            "best_epoch": result.best_epoch,
            "validation_loss": result.validation_loss,
            "training_class_counts": dict(result.training_class_counts),
            "validation_class_counts": dict(result.validation_class_counts),
        },
        target,
    )


def load_checkpoint(path: str | Path) -> TrainingResult:
    """Load a CPU evaluation checkpoint without retraining or changing settings."""
    torch, _ = _torch()
    try:
        saved = torch.load(Path(path), map_location="cpu", weights_only=False)
        return TrainingResult(
            saved["model_state"],
            np.asarray(saved["normalizer_mean"], dtype=np.float32),
            np.asarray(saved["normalizer_std"], dtype=np.float32),
            int(saved["best_epoch"]),
            float(saved["validation_loss"]),
            dict(saved["training_class_counts"]),
            dict(saved["validation_class_counts"]),
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise ValueError(f"Could not load waveform CNN checkpoint {path}: {error}") from error


def _torch():
    try:
        import torch
        from torch import nn
    except ImportError as error:  # pragma: no cover - installation check
        raise RuntimeError("PyTorch is required; install the project's dependencies.") from error
    return torch, nn


def build_waveform_cnn(dropout: float = 0.25):
    """Construct the specified small CPU-friendly 1D waveform CNN."""
    _, nn = _torch()

    class WaveformCNN(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = nn.Sequential(
                nn.Conv1d(4, 16, kernel_size=7, padding=3),
                nn.ReLU(),
                nn.AvgPool1d(2),
                nn.Conv1d(16, 32, kernel_size=7, padding=3),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Dropout(dropout),
                nn.Linear(32, 1),
            )

        def forward(self, batch):
            if batch.ndim != 3 or tuple(batch.shape[1:]) != (4, SAMPLE_COUNT):
                raise ValueError("CNN input must have shape [batch_size, 4, 512].")
            return self.layers(batch).squeeze(1)

    return WaveformCNN()


def set_reproducible_seed(seed: int) -> None:
    """Set Python, NumPy, and PyTorch CPU random seeds."""
    random.seed(seed)
    np.random.seed(seed)
    torch, _ = _torch()
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)

