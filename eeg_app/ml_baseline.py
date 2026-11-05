"""Reproducible participant-held-out baseline for public Muse feature records."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import joblib
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


TARGETS = ("rest_period", "task_period")


@dataclass(frozen=True)
class BaselineResult:
    """Trained pipeline, holdout probabilities, and an auditable summary."""

    pipeline: Pipeline
    feature_names: tuple[str, ...]
    predictions: tuple[dict[str, Any], ...]
    summary: Mapping[str, Any]


def _validate_records(records: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    if not records:
        raise ValueError("Cannot train: no feature records were supplied.")
    seen_ids: set[str] = set()
    feature_names: set[str] = set()
    for index, record in enumerate(records):
        window_id = record.get("window_id")
        if not isinstance(window_id, str) or not window_id:
            raise ValueError(f"Record {index} has a missing window_id.")
        if window_id in seen_ids:
            raise ValueError(f"Duplicate window_id {window_id!r}.")
        seen_ids.add(window_id)
        if not isinstance(record.get("participant_id"), str) or not record["participant_id"]:
            raise ValueError(f"Record {window_id!r} has a missing participant_id.")
        if record.get("weak_target") not in TARGETS:
            raise ValueError(f"Record {window_id!r} has missing or invalid weak_target.")
        features = record.get("features")
        if not isinstance(features, Mapping) or not features:
            raise ValueError(f"Record {window_id!r} has missing features.")
        feature_names.update(str(name) for name in features)
    if not feature_names:
        raise ValueError("Cannot train: no numeric feature names were found.")
    return tuple(sorted(feature_names))


def _matrix(records: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> np.ndarray:
    matrix = np.full((len(records), len(feature_names)), np.nan, dtype=float)
    for row, record in enumerate(records):
        features = record["features"]
        for column, name in enumerate(feature_names):
            value = features.get(name)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"Feature {name!r} in {record['window_id']!r} is not numeric.")
            try:
                value = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Feature {name!r} in {record['window_id']!r} is not numeric.") from error
            if isfinite(value):
                matrix[row, column] = value
    return matrix


def check_no_participant_overlap(
    training_records: Sequence[Mapping[str, Any]], holdout_records: Sequence[Mapping[str, Any]]
) -> None:
    """Raise when a person appears in both sides of a proposed evaluation split."""

    training_people = {record.get("participant_id") for record in training_records}
    holdout_people = {record.get("participant_id") for record in holdout_records}
    overlap = training_people & holdout_people
    if overlap:
        raise ValueError(f"Participant overlap detected between training and holdout sets: {sorted(overlap)}.")


def train_participant_baseline(
    records: Sequence[Mapping[str, Any]],
    *,
    holdout_participants: Sequence[str],
    random_seed: int = 17,
) -> BaselineResult:
    """Train only on non-holdout participants and score the held-out people.

    This evaluates weak task-period versus rest-period targets, not artifact
    detection accuracy.
    """

    feature_names = _validate_records(records)
    holdout = set(holdout_participants)
    if not holdout:
        raise ValueError("Choose at least one held-out participant.")
    train = [record for record in records if record["participant_id"] not in holdout]
    test = [record for record in records if record["participant_id"] in holdout]
    if not train or not test:
        raise ValueError("Participant split left an empty training or holdout set.")
    check_no_participant_overlap(train, test)
    train_people = {record["participant_id"] for record in train}
    test_people = {record["participant_id"] for record in test}
    train_targets = [record["weak_target"] for record in train]
    test_targets = [record["weak_target"] for record in test]
    if set(train_targets) != set(TARGETS) or set(test_targets) != set(TARGETS):
        raise ValueError("Both weak targets must be present in both training and holdout sets.")

    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=random_seed)),
    ])
    train_matrix = _matrix(train, feature_names)
    test_matrix = _matrix(test, feature_names)
    pipeline.fit(train_matrix, train_targets)
    task_index = list(pipeline.named_steps["classifier"].classes_).index("task_period")
    task_probabilities = pipeline.predict_proba(test_matrix)[:, task_index]
    predicted = pipeline.predict(test_matrix)
    encoded_test = np.asarray([target == "task_period" for target in test_targets], dtype=int)

    predictions = tuple({
        "window_id": record["window_id"],
        "participant_id": record["participant_id"],
        "weak_target": record["weak_target"],
        "task_period_probability": float(probability),
    } for record, probability in zip(test, task_probabilities))
    summary = {
        "evaluation": "weak task-period vs rest-period check; not artifact accuracy",
        "random_seed": random_seed,
        "feature_count": len(feature_names),
        "training_participants": sorted(train_people),
        "holdout_participants": sorted(test_people),
        "training_windows": len(train),
        "holdout_windows": len(test),
        "training_class_balance": dict(Counter(train_targets)),
        "holdout_class_balance": dict(Counter(test_targets)),
        "features_with_missing_values": int(np.isnan(np.vstack((train_matrix, test_matrix))).any(axis=0).sum()),
        "holdout_accuracy": float(accuracy_score(test_targets, predicted)),
        "holdout_balanced_accuracy": float(balanced_accuracy_score(test_targets, predicted)),
        "holdout_task_period_roc_auc": float(roc_auc_score(encoded_test, task_probabilities)),
    }
    return BaselineResult(pipeline, feature_names, predictions, summary)


def load_feature_records(path: str | Path) -> list[dict[str, Any]]:
    """Read JSON Lines feature records produced by ``write_feature_records``."""

    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def save_baseline(result: BaselineResult, output_dir: str | Path) -> None:
    """Save the fitted pipeline, holdout window IDs/probabilities, and report."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": result.pipeline, "feature_names": result.feature_names}, output / "pipeline.joblib")
    with (output / "holdout_predictions.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["window_id", "participant_id", "weak_target", "task_period_probability"])
        writer.writeheader()
        writer.writerows(result.predictions)
    (output / "summary.json").write_text(json.dumps(result.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
