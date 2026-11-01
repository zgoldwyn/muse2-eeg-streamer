from __future__ import annotations
"""Evaluate artifact-detector predictions against reference EEG-window labels."""

from collections.abc import Mapping, Sequence
from numbers import Real


VALID_REFERENCE_LABELS = frozenset({"clean", "artifact", "uncertain", "invalid"})
VALID_PREDICTIONS = frozenset({"clean", "artifact"})
ELIGIBLE_LABELS = frozenset({"clean", "artifact"})


def evaluate_predictions(
    reference_records: Sequence[Mapping[str, object]],
    prediction_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate one binary artifact detector against reference-label records.

    Each reference record must contain ``window_id`` and ``label``. Each prediction
    record must contain ``window_id`` and ``decision``. Reference labels may be
    ``clean``, ``artifact``, ``uncertain``, or ``invalid``. Only clean and artifact
    reference windows are eligible for primary metrics; artifact is the positive
    class. Eligible windows require exactly one binary prediction.

    Returns a dictionary with counts, metric values plus their numerators and
    denominators, and a summary of excluded windows.

    Raises:
        ValueError: If records are malformed, duplicate IDs appear, a prediction
            refers to an unknown window, or an eligible window lacks a prediction.
    """
    references = _index_records(
        reference_records,
        record_kind="reference",
        value_key="label",
        allowed_values=VALID_REFERENCE_LABELS,
    )
    predictions = _index_records(
        prediction_records,
        record_kind="prediction",
        value_key="decision",
        allowed_values=VALID_PREDICTIONS,
    )

    unknown_prediction_ids = [
        window_id for window_id in predictions if window_id not in references
    ]
    if unknown_prediction_ids:
        raise ValueError(
            "Prediction supplied for unknown window ID(s): "
            + ", ".join(unknown_prediction_ids)
            + "."
        )

    eligible_window_ids = [
        window_id
        for window_id, label in references.items()
        if label in ELIGIBLE_LABELS
    ]
    missing_prediction_ids = [
        window_id for window_id in eligible_window_ids if window_id not in predictions
    ]
    if missing_prediction_ids:
        raise ValueError(
            "Missing prediction for eligible window ID(s): "
            + ", ".join(missing_prediction_ids)
            + "."
        )

    counts = {
        "true_positives": 0,
        "false_negatives": 0,
        "false_positives": 0,
        "true_negatives": 0,
    }

    for window_id in eligible_window_ids:
        reference_label = references[window_id]
        decision = predictions[window_id]

        if reference_label == "artifact" and decision == "artifact":
            counts["true_positives"] += 1
        elif reference_label == "artifact" and decision == "clean":
            counts["false_negatives"] += 1
        elif reference_label == "clean" and decision == "artifact":
            counts["false_positives"] += 1
        else:
            counts["true_negatives"] += 1

    uncertain_count = sum(label == "uncertain" for label in references.values())
    invalid_count = sum(label == "invalid" for label in references.values())
    accepted_eligible_windows = counts["true_negatives"] + counts["false_negatives"]

    metrics = {
        "recall": _make_rate(
            counts["true_positives"],
            counts["true_positives"] + counts["false_negatives"],
        ),
        "precision": _make_rate(
            counts["true_positives"],
            counts["true_positives"] + counts["false_positives"],
        ),
        "clean_retention": _make_rate(
            counts["true_negatives"],
            counts["true_negatives"] + counts["false_positives"],
        ),
        "accepted_contamination": _make_rate(
            counts["false_negatives"], accepted_eligible_windows
        ),
        "coverage": _make_rate(accepted_eligible_windows, len(eligible_window_ids)),
    }

    return {
        "counts": counts,
        "metrics": metrics,
        "summary": {
            "total_reference_windows": len(references),
            "eligible_windows": len(eligible_window_ids),
            "uncertain_windows_excluded": uncertain_count,
            "invalid_windows_excluded": invalid_count,
            "accepted_eligible_windows": accepted_eligible_windows,
        },
    }


def compare_detectors(
    reference_records: Sequence[Mapping[str, object]],
    mathematical_predictions: Sequence[Mapping[str, object]],
    machine_learning_predictions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate two detectors and the rule that accepts clean only on agreement.

    The combined detector predicts clean only when both input detectors predict
    clean for an eligible window. Otherwise it predicts artifact. Agreement groups
    include eligible windows only, so uncertain and invalid reference windows do
    not affect detector comparison.
    """
    mathematical_result = evaluate_predictions(
        reference_records, mathematical_predictions
    )
    machine_learning_result = evaluate_predictions(
        reference_records, machine_learning_predictions
    )

    references = _index_records(
        reference_records,
        record_kind="reference",
        value_key="label",
        allowed_values=VALID_REFERENCE_LABELS,
    )
    mathematical_by_id = _index_records(
        mathematical_predictions,
        record_kind="prediction",
        value_key="decision",
        allowed_values=VALID_PREDICTIONS,
    )
    machine_learning_by_id = _index_records(
        machine_learning_predictions,
        record_kind="prediction",
        value_key="decision",
        allowed_values=VALID_PREDICTIONS,
    )

    eligible_window_ids = [
        window_id
        for window_id, label in references.items()
        if label in ELIGIBLE_LABELS
    ]
    combined_predictions: list[dict[str, str]] = []
    both_correct_window_ids: list[str] = []
    both_wrong_window_ids: list[str] = []
    disagreement_window_ids: list[str] = []

    for window_id in eligible_window_ids:
        reference_label = references[window_id]
        mathematical_decision = mathematical_by_id[window_id]
        machine_learning_decision = machine_learning_by_id[window_id]

        combined_decision = (
            "clean"
            if mathematical_decision == "clean"
            and machine_learning_decision == "clean"
            else "artifact"
        )
        combined_predictions.append(
            {"window_id": window_id, "decision": combined_decision}
        )

        mathematical_is_correct = mathematical_decision == reference_label
        machine_learning_is_correct = machine_learning_decision == reference_label
        if mathematical_is_correct and machine_learning_is_correct:
            both_correct_window_ids.append(window_id)
        elif not mathematical_is_correct and not machine_learning_is_correct:
            both_wrong_window_ids.append(window_id)

        if mathematical_decision != machine_learning_decision:
            disagreement_window_ids.append(window_id)

    combined_result = evaluate_predictions(reference_records, combined_predictions)

    return {
        "mathematical_detector": mathematical_result,
        "machine_learning_detector": machine_learning_result,
        "combined_detector": combined_result,
        "agreement": {
            "both_correct_window_ids": both_correct_window_ids,
            "both_wrong_window_ids": both_wrong_window_ids,
            "disagreement_window_ids": disagreement_window_ids,
        },
    }


def format_rate(rate: Mapping[str, object], decimal_places: int = 4) -> str:
    """Format a metric rate, displaying a zero-denominator result as unavailable."""
    if isinstance(decimal_places, bool) or not isinstance(decimal_places, int):
        raise ValueError("decimal_places must be an integer.")
    if decimal_places < 0:
        raise ValueError("decimal_places must not be negative.")

    value = rate.get("value")
    if value is None:
        return "unavailable"
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("rate value must be numeric or None.")
    return f"{value:.{decimal_places}f}"


def _index_records(
    records: Sequence[Mapping[str, object]],
    *,
    record_kind: str,
    value_key: str,
    allowed_values: frozenset[str],
) -> dict[str, str]:
    """Validate records and return their values indexed by window ID."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError(f"{record_kind.title()} records must be a sequence of mappings.")

    records_by_id: dict[str, str] = {}
    for record_index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(
                f"{record_kind.title()} record at position {record_index} must be a mapping."
            )

        window_id = record.get("window_id")
        if not isinstance(window_id, str) or not window_id.strip():
            raise ValueError(
                f"{record_kind.title()} record at position {record_index} needs a nonempty "
                "string window_id."
            )
        if window_id in records_by_id:
            raise ValueError(f"Duplicate {record_kind} window ID: {window_id}.")

        value = record.get(value_key)
        if not isinstance(value, str) or value not in allowed_values:
            allowed_text = ", ".join(sorted(allowed_values))
            raise ValueError(
                f"{record_kind.title()} record for window ID {window_id} has unrecognized "
                f"{value_key} {value!r}; expected one of: {allowed_text}."
            )

        records_by_id[window_id] = value

    return records_by_id


def _make_rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    """Return a metric's value and the fraction used to calculate it."""
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else numerator / denominator,
    }
