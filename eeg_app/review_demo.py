"""Synthetic-only review/evaluation rehearsal using Zack's predeclared labels.

This is an automated workflow test, not independent human annotation. The
existing example decisions are already known from last week's exercise.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .metrics import evaluate_predictions
from .review import REVIEW_COLUMNS, export_review_bundle, load_windows, validated_reference_records


REPO = Path(__file__).resolve().parents[1]
SESSION = REPO / "tests/fixtures/integration/integration-demo-001"
LABELS = REPO / "tests/fixtures/integration/reference_records.json"


def run_synthetic_dry_run(output_dir: str | Path) -> dict:
    """Complete and validate a copy using supplied labels before running the rule.

    Intentionally restricted to the known synthetic integration fixture. Pilot
    reviews use review.py and require actual independent human annotation.
    """
    metadata = json.loads((SESSION / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("data_source") != "synthetic" or metadata.get("session_id") != "integration-demo-001":
        raise ValueError("Dry-run completion is restricted to the existing synthetic integration fixture.")
    supplied = json.loads(LABELS.read_text(encoding="utf-8"))
    windows = load_windows(SESSION)
    labels_by_id = {record["window_id"]: record["label"] for record in supplied}
    if len(labels_by_id) != len(supplied) or set(labels_by_id) != {window.window_id for window in windows}:
        raise ValueError("Supplied synthetic label IDs must match the loader exactly; coordinate changes with Namit.")
    if any(not window.is_valid and labels_by_id[window.window_id] != "invalid" for window in windows):
        raise ValueError("Supplied synthetic labels disagree with a loader technical exclusion.")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / "reviewer_bundle"
    summary = export_review_bundle(SESSION, bundle)

    # The blank reviewer bundle stays unchanged. This separate copy is clearly
    # labeled as an automated synthetic example, never as pilot human review.
    with (bundle / "review.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["reviewer_id"] = "synthetic-example-only"
        row["label"] = labels_by_id[row["window_id"]]
        row["evidence_notes"] = "Zack's predeclared fixture scenario; automated rehearsal, not human pilot review."
    sheet = output / "completed_synthetic_review.csv"
    with sheet.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    references = validated_reference_records(SESSION, sheet)
    if {r["window_id"]: r["label"] for r in references} != labels_by_id:
        raise ValueError("Validated review copy differs from the predeclared synthetic labels.")
    frozen_hash = hashlib.sha256(sheet.read_bytes()).hexdigest()
    (output / "reference_records.json").write_text(json.dumps(references, indent=2), encoding="utf-8")

    # Only now run the existing demo detector. Labels never enter this API.
    from .math_pipeline import demo_peak_to_peak_prediction, extract_features_for_windows
    features = extract_features_for_windows(windows, flatline_tolerance_uv=0)
    predictions = [demo_peak_to_peak_prediction(record) for record in features["feature_records"]]
    (output / "predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    evaluation = evaluate_predictions(references, predictions)

    eligible_ids = {r["window_id"] for r in references if r["label"] in ("clean", "artifact")}
    missing_errors = {}
    for window_id in sorted(eligible_ids):
        try:
            evaluate_predictions(references, [p for p in predictions if p["window_id"] != window_id])
        except ValueError as error:
            if "Missing prediction for eligible window" not in str(error):
                raise
            missing_errors[window_id] = str(error)
        else:
            raise AssertionError(f"Missing eligible prediction was not rejected: {window_id}")
    excluded_ids = {r["window_id"] for r in references if r["label"] in ("uncertain", "invalid")}
    for decision in ("clean", "artifact"):
        supplied_predictions = predictions + [{"window_id": window_id, "decision": decision}
                                              for window_id in sorted(excluded_ids)]
        if evaluate_predictions(references, supplied_predictions) != evaluation:
            raise AssertionError("Predictions for excluded windows changed evaluation results.")
    if hashlib.sha256(sheet.read_bytes()).hexdigest() != frozen_hash:
        raise AssertionError("The synthetic review copy changed after prediction generation.")
    report = {
        "synthetic_only": True,
        "label_source": "Zack's existing scenario labels, not detector outputs or new human review",
        "label_source_sha256": hashlib.sha256(LABELS.read_bytes()).hexdigest(),
        "completed_sheet_sha256": frozen_hash,
        "stages": ["blank_template_exported", "copy_completed_from_predeclared_labels",
                   "copy_validated_and_frozen", "demo_predictions_generated", "existing_evaluator_run"],
        "template_summary": summary,
        "missing_eligible_prediction_errors": missing_errors,
        "excluded_predictions_cannot_change_metrics": True,
        "evaluation": evaluation,
    }
    (output / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    (output / "dry_run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="New local output directory, preferably under recordings/.")
    args = parser.parse_args()
    try:
        report = run_synthetic_dry_run(args.output_dir)
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(2, f"{error}\n")
    summary = report["evaluation"]["summary"]
    print("Synthetic workflow rehearsal only; no independent pilot labels created.")
    print(f"Eligible windows: {summary['eligible_windows']}")
    print(f"Uncertain windows: {summary['uncertain_windows_excluded']}")
    print(f"Invalid windows: {summary['invalid_windows_excluded']}")
    print("Counts: " + json.dumps(report["evaluation"]["counts"], sort_keys=True))
    print(f"Missing eligible predictions rejected: {len(report['missing_eligible_prediction_errors'])}")
    print("Excluded-window predictions leave metrics unchanged: PASS")
    print(f"Outputs saved under {args.output_dir}")


if __name__ == "__main__":
    main()
