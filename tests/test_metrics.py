"""Tests for synthetic artifact-detector evaluation metrics."""

import unittest

from eeg_app.metrics import compare_detectors, evaluate_predictions, format_rate
from eeg_app.math_pipeline import demo_peak_to_peak_prediction
from eeg_app.preprocessing import REQUIRED_CHANNELS


REFERENCE_RECORDS = [
    {"window_id": "demo-001-w01", "label": "artifact"},
    {"window_id": "demo-001-w02", "label": "artifact"},
    {"window_id": "demo-001-w03", "label": "artifact"},
    {"window_id": "demo-001-w04", "label": "artifact"},
    {"window_id": "demo-001-w05", "label": "clean"},
    {"window_id": "demo-001-w06", "label": "clean"},
    {"window_id": "demo-001-w07", "label": "clean"},
    {"window_id": "demo-001-w08", "label": "clean"},
    {"window_id": "demo-001-w09", "label": "clean"},
    {"window_id": "demo-001-w10", "label": "clean"},
]

MATHEMATICAL_PREDICTIONS = [
    {"window_id": "demo-001-w01", "decision": "artifact"},
    {"window_id": "demo-001-w02", "decision": "artifact"},
    {"window_id": "demo-001-w03", "decision": "artifact"},
    {"window_id": "demo-001-w04", "decision": "clean"},
    {"window_id": "demo-001-w05", "decision": "artifact"},
    {"window_id": "demo-001-w06", "decision": "clean"},
    {"window_id": "demo-001-w07", "decision": "clean"},
    {"window_id": "demo-001-w08", "decision": "clean"},
    {"window_id": "demo-001-w09", "decision": "clean"},
    {"window_id": "demo-001-w10", "decision": "clean"},
]

MACHINE_LEARNING_PREDICTIONS = [
    {"window_id": "demo-001-w01", "decision": "artifact"},
    {"window_id": "demo-001-w02", "decision": "artifact"},
    {"window_id": "demo-001-w03", "decision": "artifact"},
    {"window_id": "demo-001-w04", "decision": "clean"},
    {"window_id": "demo-001-w05", "decision": "clean"},
    {"window_id": "demo-001-w06", "decision": "artifact"},
    {"window_id": "demo-001-w07", "decision": "clean"},
    {"window_id": "demo-001-w08", "decision": "clean"},
    {"window_id": "demo-001-w09", "decision": "clean"},
    {"window_id": "demo-001-w10", "decision": "clean"},
]


class EvaluationMetricsTests(unittest.TestCase):
    """Check reference-label validation and binary detector evaluation."""

    def test_demo_rule_predictions_match_existing_references_by_id_when_reordered(self):
        # Reuse the existing ten-window reference data above unchanged.
        # These feature inputs test matching only; they are not Ben's fixture.
        predictions = []
        for index, reference in enumerate(REFERENCE_RECORDS):
            peak_to_peak = 200.0 if index % 2 == 0 else 10.0
            predictions.append(demo_peak_to_peak_prediction({
                "window_id": reference["window_id"],
                "features": {f"{c}_peak_to_peak_uv": peak_to_peak for c in REQUIRED_CHANNELS},
                "units": {f"{c}_peak_to_peak_uv": "microvolts" for c in REQUIRED_CHANNELS},
                "unavailable_reasons": {},
            }))
        ordered = evaluate_predictions(REFERENCE_RECORDS, predictions)
        reversed_result = evaluate_predictions(REFERENCE_RECORDS, list(reversed(predictions)))
        both_reordered = evaluate_predictions(
            REFERENCE_RECORDS[3:] + REFERENCE_RECORDS[:3], predictions[1::2] + predictions[::2],
        )
        self.assertEqual(ordered["counts"], {
            "true_positives": 2, "false_negatives": 2,
            "false_positives": 3, "true_negatives": 3,
        })
        self.assertEqual(reversed_result, ordered)
        self.assertEqual(both_reordered, ordered)

    def assert_rate(
        self,
        result: dict[str, object],
        metric_name: str,
        numerator: int,
        denominator: int,
        value: float | None,
    ) -> None:
        metrics = result["metrics"]
        self.assertIsInstance(metrics, dict)
        rate = metrics[metric_name]
        self.assertIsInstance(rate, dict)
        self.assertEqual(rate["numerator"], numerator)
        self.assertEqual(rate["denominator"], denominator)
        if value is None:
            self.assertIsNone(rate["value"])
        else:
            self.assertAlmostEqual(rate["value"], value)

    def test_original_ten_window_example(self) -> None:
        result = evaluate_predictions(REFERENCE_RECORDS, MATHEMATICAL_PREDICTIONS)

        self.assertEqual(
            result["counts"],
            {
                "true_positives": 3,
                "false_negatives": 1,
                "false_positives": 1,
                "true_negatives": 5,
            },
        )
        self.assertEqual(
            result["summary"],
            {
                "total_reference_windows": 10,
                "eligible_windows": 10,
                "uncertain_windows_excluded": 0,
                "invalid_windows_excluded": 0,
                "accepted_eligible_windows": 6,
            },
        )
        self.assert_rate(result, "recall", 3, 4, 0.75)
        self.assert_rate(result, "precision", 3, 4, 0.75)
        self.assert_rate(result, "clean_retention", 5, 6, 5 / 6)
        self.assert_rate(result, "accepted_contamination", 1, 6, 1 / 6)
        self.assert_rate(result, "coverage", 6, 10, 0.60)

    def test_excluded_windows_are_reported_without_changing_primary_metrics(self) -> None:
        expanded_references = REFERENCE_RECORDS + [
            {"window_id": "demo-001-w11", "label": "uncertain"},
            {"window_id": "demo-001-w12", "label": "uncertain"},
            {"window_id": "demo-001-w13", "label": "invalid"},
        ]
        expanded_predictions = MATHEMATICAL_PREDICTIONS + [
            {"window_id": "demo-001-w11", "decision": "artifact"},
            {"window_id": "demo-001-w13", "decision": "clean"},
        ]

        original_result = evaluate_predictions(REFERENCE_RECORDS, MATHEMATICAL_PREDICTIONS)
        expanded_result = evaluate_predictions(expanded_references, expanded_predictions)

        self.assertEqual(expanded_result["counts"], original_result["counts"])
        self.assertEqual(expanded_result["metrics"], original_result["metrics"])
        self.assertEqual(
            expanded_result["summary"],
            {
                "total_reference_windows": 13,
                "eligible_windows": 10,
                "uncertain_windows_excluded": 2,
                "invalid_windows_excluded": 1,
                "accepted_eligible_windows": 6,
            },
        )

    def test_no_windows_accepted_as_clean(self) -> None:
        references = [
            {"window_id": "w01", "label": "artifact"},
            {"window_id": "w02", "label": "clean"},
        ]
        predictions = [
            {"window_id": "w01", "decision": "artifact"},
            {"window_id": "w02", "decision": "artifact"},
        ]

        result = evaluate_predictions(references, predictions)

        self.assertEqual(result["summary"]["accepted_eligible_windows"], 0)
        self.assert_rate(result, "accepted_contamination", 0, 0, None)
        self.assert_rate(result, "coverage", 0, 2, 0.0)
        metrics = result["metrics"]
        self.assertIsInstance(metrics, dict)
        self.assertEqual(format_rate(metrics["accepted_contamination"]), "unavailable")

    def test_no_reference_artifacts_make_recall_unavailable(self) -> None:
        references = [
            {"window_id": "w01", "label": "clean"},
            {"window_id": "w02", "label": "clean"},
        ]
        predictions = [
            {"window_id": "w01", "decision": "clean"},
            {"window_id": "w02", "decision": "artifact"},
        ]

        result = evaluate_predictions(references, predictions)

        self.assert_rate(result, "recall", 0, 0, None)
        self.assert_rate(result, "precision", 0, 1, 0.0)

    def test_no_eligible_windows_make_all_primary_rates_unavailable(self) -> None:
        references = [
            {"window_id": "w01", "label": "uncertain"},
            {"window_id": "w02", "label": "invalid"},
        ]

        result = evaluate_predictions(references, [])

        self.assertEqual(result["counts"], {
            "true_positives": 0,
            "false_negatives": 0,
            "false_positives": 0,
            "true_negatives": 0,
        })
        self.assertEqual(result["summary"]["eligible_windows"], 0)
        for metric_name in (
            "recall",
            "precision",
            "clean_retention",
            "accepted_contamination",
            "coverage",
        ):
            self.assert_rate(result, metric_name, 0, 0, None)

    def test_records_can_arrive_in_different_orders(self) -> None:
        result = evaluate_predictions(
            list(reversed(REFERENCE_RECORDS)),
            list(reversed(MATHEMATICAL_PREDICTIONS)),
        )

        self.assertEqual(
            result["counts"],
            {
                "true_positives": 3,
                "false_negatives": 1,
                "false_positives": 1,
                "true_negatives": 5,
            },
        )

    def test_duplicate_reference_window_id_raises_helpful_error(self) -> None:
        duplicate_references = REFERENCE_RECORDS + [REFERENCE_RECORDS[0]]

        with self.assertRaisesRegex(ValueError, "Duplicate reference window ID"):
            evaluate_predictions(duplicate_references, MATHEMATICAL_PREDICTIONS)

    def test_duplicate_prediction_window_id_raises_helpful_error(self) -> None:
        duplicate_predictions = MATHEMATICAL_PREDICTIONS + [MATHEMATICAL_PREDICTIONS[0]]

        with self.assertRaisesRegex(ValueError, "Duplicate prediction window ID"):
            evaluate_predictions(REFERENCE_RECORDS, duplicate_predictions)

    def test_missing_prediction_for_eligible_window_raises_helpful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing prediction.*demo-001-w10"):
            evaluate_predictions(REFERENCE_RECORDS, MATHEMATICAL_PREDICTIONS[:-1])

    def test_unknown_prediction_window_id_raises_helpful_error(self) -> None:
        unknown_prediction = {"window_id": "unknown-window", "decision": "clean"}

        with self.assertRaisesRegex(ValueError, "unknown window ID.*unknown-window"):
            evaluate_predictions(REFERENCE_RECORDS, MATHEMATICAL_PREDICTIONS + [unknown_prediction])

    def test_unrecognized_label_or_prediction_raises_helpful_error(self) -> None:
        bad_reference = REFERENCE_RECORDS.copy()
        bad_reference[0] = {"window_id": "demo-001-w01", "label": "maybe"}
        bad_prediction = MATHEMATICAL_PREDICTIONS.copy()
        bad_prediction[0] = {"window_id": "demo-001-w01", "decision": "maybe"}

        with self.assertRaisesRegex(ValueError, "unrecognized label"):
            evaluate_predictions(bad_reference, MATHEMATICAL_PREDICTIONS)
        with self.assertRaisesRegex(ValueError, "unrecognized decision"):
            evaluate_predictions(REFERENCE_RECORDS, bad_prediction)

    def test_malformed_prediction_record_raises_helpful_error(self) -> None:
        malformed_predictions = MATHEMATICAL_PREDICTIONS.copy()
        malformed_predictions[0] = {"window_id": "demo-001-w01"}

        with self.assertRaisesRegex(ValueError, "unrecognized decision"):
            evaluate_predictions(REFERENCE_RECORDS, malformed_predictions)

    def test_second_detector_and_combined_rule(self) -> None:
        result = compare_detectors(
            REFERENCE_RECORDS,
            MATHEMATICAL_PREDICTIONS,
            MACHINE_LEARNING_PREDICTIONS,
        )

        machine_learning_result = result["machine_learning_detector"]
        self.assertIsInstance(machine_learning_result, dict)
        self.assertEqual(
            machine_learning_result["counts"],
            {
                "true_positives": 3,
                "false_negatives": 1,
                "false_positives": 1,
                "true_negatives": 5,
            },
        )

        combined_result = result["combined_detector"]
        self.assertIsInstance(combined_result, dict)
        self.assertEqual(
            combined_result["counts"],
            {
                "true_positives": 3,
                "false_negatives": 1,
                "false_positives": 2,
                "true_negatives": 4,
            },
        )
        self.assert_rate(combined_result, "recall", 3, 4, 0.75)
        self.assert_rate(combined_result, "precision", 3, 5, 0.60)
        self.assert_rate(combined_result, "clean_retention", 4, 6, 4 / 6)
        self.assert_rate(combined_result, "accepted_contamination", 1, 5, 0.20)
        self.assert_rate(combined_result, "coverage", 5, 10, 0.50)

        self.assertEqual(
            result["agreement"],
            {
                "both_correct_window_ids": [
                    "demo-001-w01",
                    "demo-001-w02",
                    "demo-001-w03",
                    "demo-001-w07",
                    "demo-001-w08",
                    "demo-001-w09",
                    "demo-001-w10",
                ],
                "both_wrong_window_ids": ["demo-001-w04"],
                "disagreement_window_ids": ["demo-001-w05", "demo-001-w06"],
            },
        )

    def test_detector_comparison_works_with_different_prediction_orders(self) -> None:
        ordered = compare_detectors(
            REFERENCE_RECORDS,
            MATHEMATICAL_PREDICTIONS,
            MACHINE_LEARNING_PREDICTIONS,
        )
        reordered = compare_detectors(
            REFERENCE_RECORDS,
            list(reversed(MATHEMATICAL_PREDICTIONS)),
            list(reversed(MACHINE_LEARNING_PREDICTIONS)),
        )

        self.assertEqual(reordered, ordered)

    def test_missing_or_duplicate_predictions_for_either_detector_raise_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing prediction.*demo-001-w10"):
            compare_detectors(
                REFERENCE_RECORDS,
                MATHEMATICAL_PREDICTIONS[:-1],
                MACHINE_LEARNING_PREDICTIONS,
            )
        with self.assertRaisesRegex(ValueError, "Missing prediction.*demo-001-w10"):
            compare_detectors(
                REFERENCE_RECORDS,
                MATHEMATICAL_PREDICTIONS,
                MACHINE_LEARNING_PREDICTIONS[:-1],
            )
        with self.assertRaisesRegex(ValueError, "Duplicate prediction window ID"):
            compare_detectors(
                REFERENCE_RECORDS,
                MATHEMATICAL_PREDICTIONS + [MATHEMATICAL_PREDICTIONS[0]],
                MACHINE_LEARNING_PREDICTIONS,
            )
        with self.assertRaisesRegex(ValueError, "Duplicate prediction window ID"):
            compare_detectors(
                REFERENCE_RECORDS,
                MATHEMATICAL_PREDICTIONS,
                MACHINE_LEARNING_PREDICTIONS + [MACHINE_LEARNING_PREDICTIONS[0]],
            )


if __name__ == "__main__":
    unittest.main()
