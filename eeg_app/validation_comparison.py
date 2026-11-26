"""Compare P0005 screening policies and write a compact validation handoff."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import isfinite, nextafter, inf
from numbers import Real
from pathlib import Path
import tempfile

from .development_math import read_cnn_predictions
from .metrics import ELIGIBLE_LABELS, compare_detectors, evaluate_predictions
from .rule_search import predict_policy, validate_rule_grid
from .threshold_search import P0005_SESSIONS, _checked_prepared


def _checked_cnn(records, references):
    by_id = {row["window_id"]: row for row in references}
    seen = set()
    versions = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("CNN prediction records must be JSON objects")
        window_id = row.get("window_id")
        if window_id not in by_id or window_id in seen:
            raise ValueError(f"Unknown or duplicate CNN window ID: {window_id!r}")
        seen.add(window_id)
        reference = by_id[window_id]
        for field in ("session_id", "participant_id"):
            if field in row and row[field] != reference[field]:
                raise ValueError(f"CNN {field} mismatch for {window_id}")
        score = row.get("artifact_score")
        if isinstance(score, bool) or not isinstance(score, Real) or not isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"{window_id}: artifact_score must be finite and between 0 and 1")
        for field in ("model_version", "preprocessing_version"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"{window_id}: missing {field}")
        versions.add((row["model_version"], row["preprocessing_version"]))
    if len(versions) != 1:
        raise ValueError("Provide predictions from one final development model and preprocessing version")
    return sorted(records, key=lambda row: row["window_id"]), list(next(iter(versions)))


def _cnn_curve(references, records):
    eligible = {row["window_id"] for row in references if row["label"] in ELIGIBLE_LABELS}
    rows = [row for row in records if row["window_id"] in eligible]
    scores = {float(row["artifact_score"]) for row in rows}
    cutoffs = sorted(scores | {0.0, 1.0, nextafter(max(scores), inf)})
    return [{"cutoff": cutoff, "evaluation": evaluate_predictions(references, [
        {"window_id": row["window_id"],
         "decision": "artifact" if row["artifact_score"] >= cutoff else "clean"} for row in rows
    ])} for cutoff in cutoffs]


def build_comparison(training, validation, grid, cnn=None, historical=None):
    train_refs, _ = _checked_prepared(training, grid["training_grid"]["training_sessions"])
    validation_refs, features = _checked_prepared(validation, dict.fromkeys(P0005_SESSIONS, "P0005"))
    references = sorted(validation_refs.values(), key=lambda row: row["window_id"])
    rule_report = validate_rule_grid(grid, validation)
    policy = rule_report["recommendation"]["policy"]
    math = [predict_policy(features[row["window_id"]], policy)
            for row in references if row["label"] in ELIGIBLE_LABELS]
    training_counts = Counter(row["label"] for row in train_refs.values() if row["label"] in ELIGIBLE_LABELS)
    majority_label = "artifact" if training_counts["artifact"] > training_counts["clean"] else "clean"
    policies = {}
    predictions = {"math": math}
    policies["math"] = evaluate_predictions(references, math)
    for name, decision in (("majority_class", majority_label), ("always_clean", "clean")):
        predictions[name] = [{"window_id": row["window_id"], "decision": decision}
                             for row in references if row["label"] in ELIGIBLE_LABELS]
        policies[name] = evaluate_predictions(references, predictions[name])
    report = {
        "data_role": "P0005 development validation",
        "status": "pending_CNN_validation_export" if cnn is None else rule_report["status"],
        "label_review_status": rule_report["label_review_status"],
        "label_releases": rule_report["validation_label_releases"],
        "training_label_releases": rule_report["training_label_releases"],
        "training_label_counts": dict(training_counts), "majority_decision": majority_label,
        "majority_tie_rule": "clean",
        "math_policy": policy, "policies": policies,
        "math_rule_comparison": rule_report["stages"],
        "reference_summary": policies["math"]["summary"],
    }
    if historical is not None:
        report["historical_participant_held_out_development"] = {
            name: result for name, result in historical["comparison"].items() if "metrics" in result
        }
    if cnn is not None:
        cnn, versions = _checked_cnn(cnn, references)
        # Existing scorer checks supported decisions and missing eligible IDs.
        comparison = compare_detectors(references, math, cnn)
        policies["cnn"] = comparison["machine_learning_detector"]
        policies["agreement"] = comparison["combined_detector"]
        predictions["cnn"] = cnn
        cnn_by_id = {row["window_id"]: row for row in cnn}
        predictions["agreement"] = [
            {"window_id": row["window_id"], "decision": "clean" if row["decision"] == "clean"
             and cnn_by_id[row["window_id"]]["decision"] == "clean" else "artifact"}
            for row in math
        ]
        report["cnn_versions"] = {"model_version": versions[0], "preprocessing_version": versions[1]}
        curve = _cnn_curve(references, cnn)
        target = policies["math"]["metrics"]["coverage"]["value"]
        matched = min(curve, key=lambda row: (
            abs(row["evaluation"]["metrics"]["coverage"]["value"] - target),
            -row["evaluation"]["metrics"]["recall"]["value"],
            -row["evaluation"]["metrics"]["clean_retention"]["value"], row["cutoff"],
        ))
        matched_predictions = [{**row, "decision": "artifact" if row["artifact_score"] >= matched["cutoff"]
                                else "clean", "decision_cutoff": matched["cutoff"]} for row in cnn]
        matched_comparison = compare_detectors(references, math, matched_predictions)
        report["similar_acceptance"] = {
            "target_math_coverage": target, "cnn_cutoff": matched["cutoff"],
            "comparison": {name: value for name, value in matched_comparison.items() if "metrics" in value},
            "cnn_coverage_minus_math": matched["evaluation"]["metrics"]["coverage"]["value"] - target,
            "selection": "Nearest validation coverage; ties prefer higher recall, then clean retention, then lower cutoff.",
            "inequality": "artifact_score >= cutoff",
            "cnn_cutoff_curve": curve,
        }
        predictions["cnn_similar_acceptance"] = matched_predictions
    return report, predictions


def _rate(rate):
    value = rate["value"]
    return f"{rate['numerator']}/{rate['denominator']} " + (f"({value:.1%})" if value is not None else "(unavailable)")


def _table(results):
    lines = ["| Policy | TP/FP/TN/FN | Recall | Precision | Clean retention | Accepted contamination | Coverage |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, result in results.items():
        counts, metrics = result["counts"], result["metrics"]
        count_text = "/".join(str(counts[key]) for key in
                              ("true_positives", "false_positives", "true_negatives", "false_negatives"))
        lines.append("| " + " | ".join([name, count_text] + [_rate(metrics[key]) for key in
                     ("recall", "precision", "clean_retention", "accepted_contamination", "coverage")]) + " |")
    return lines


def write_summary(report, path):
    summary = report["reference_summary"]
    lines = ["# P0005 development-validation comparison", "",
             f"{summary['eligible_windows']} eligible windows. "
             f"{summary['uncertain_windows_excluded']} uncertain and "
             f"{summary['invalid_windows_excluded']} technically invalid windows excluded.", ""]
    if report["label_review_status"] == "preliminary":
        lines += ["Preliminary labels await Ben and Rushil's independent-review reconciliation.", ""]
    lines += _table(report["policies"])
    lines += ["", f"Majority reference predicts {report['majority_decision']}, based on eligible training labels.",
              "", "Math settings", "", "```json", json.dumps(report["math_policy"], indent=2), "```", ""]
    if report["status"] == "pending_CNN_validation_export":
        lines += ["CNN and agreement rows await the P0005 validation-score export.", ""]
    else:
        matched = report["similar_acceptance"]
        lines += [f"Validation-selected CNN cutoff for similar acceptance: {matched['cnn_cutoff']:.12g}.",
                  f"Remaining CNN-minus-math coverage difference: {matched['cnn_coverage_minus_math']:.2%}.", ""]
        lines += _table(matched["comparison"]) + [""]
    if "historical_participant_held_out_development" in report:
        lines += ["Earlier four-participant held-out development results", ""]
        lines += _table(report["historical_participant_held_out_development"]) + [""]
    path.write_text("\n".join(lines), encoding="utf-8")


def draw_tradeoff(report, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    fig, axis = plt.subplots(figsize=(10, 7))
    labels = ("Original recipe", "Retuned pair", "Add standard deviation", "Add kurtosis", "Add entropy")
    for stage, label in zip(report["math_rule_comparison"], labels):
        available = [candidate["evaluation"] for candidate in stage["candidates"]
                     if candidate["evaluation"] is not None]
        axis.scatter([row["metrics"]["clean_retention"]["value"] for row in available],
                     [row["metrics"]["recall"]["value"] for row in available],
                     s=45, alpha=.7, label=f"{label} ({len(available)})")
    for name, marker, title in (("math", "*", "Selected math"), ("majority_class", "x", "Training majority"),
                                ("always_clean", "+", "Always clean"), ("cnn", "^", "Exported CNN"),
                                ("agreement", "D", "Both clean")):
        if name in report["policies"]:
            metrics = report["policies"][name]["metrics"]
            axis.scatter([metrics["clean_retention"]["value"]], [metrics["recall"]["value"]],
                         s=150 if name == "math" else 75, marker=marker, label=title)
    if "similar_acceptance" in report:
        curve = report["similar_acceptance"]["cnn_cutoff_curve"]
        axis.plot([row["evaluation"]["metrics"]["clean_retention"]["value"] for row in curve],
                  [row["evaluation"]["metrics"]["recall"]["value"] for row in curve],
                  color="gray", linewidth=1, alpha=.6, label="CNN validation cutoffs")
    axis.set(xlabel="Clean retention", ylabel="Artifact recall", xlim=(-.03, 1.03), ylim=(-.03, 1.03),
             title="P0005 development validation — screening tradeoff")
    axis.xaxis.set_major_formatter(PercentFormatter(1))
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.grid(alpha=.2)
    axis.legend(loc="lower left", fontsize=9)
    pending = " • CNN validation scores pending" if report["status"] == "pending_CNN_validation_export" else ""
    if report["label_review_status"] == "preliminary":
        pending = " • preliminary labels await reconciliation" + pending
    count = report["reference_summary"]["eligible_windows"]
    fig.text(.5, .015, f"{count} eligible windows; operating point awaits approval" + pending,
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .035, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training", type=Path)
    parser.add_argument("grid", type=Path)
    parser.add_argument("validation", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--cnn-predictions", type=Path)
    parser.add_argument("--historical-report", type=Path)
    args = parser.parse_args()
    try:
        if args.output_dir.exists():
            raise FileExistsError(f"Output directory already exists: {args.output_dir}")
        sources = {name: path.read_bytes() for name, path in
                   (("training", args.training), ("grid", args.grid), ("validation", args.validation))}
        read = lambda name: json.loads(sources[name].decode("utf-8-sig"))
        cnn = read_cnn_predictions(args.cnn_predictions) if args.cnn_predictions else None
        historical = (json.loads(args.historical_report.read_text(encoding="utf-8-sig"))
                      if args.historical_report else None)
        report, predictions = build_comparison(read("training"), read("validation"), read("grid"), cnn, historical)
        report["source_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}
        for name, path in (("cnn_predictions", args.cnn_predictions), ("historical_report", args.historical_report)):
            if path:
                report["source_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        report["comparison_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{args.output_dir.name}-", dir=args.output_dir.parent) as temporary:
            staging = Path(temporary)
            for name, value in (("comparison.json", report), ("predictions.json", predictions)):
                (staging / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            write_summary(report, staging / "summary.md")
            draw_tradeoff(report, staging / "tradeoff.png")
            if args.output_dir.exists():
                raise FileExistsError(f"Output directory already exists: {args.output_dir}")
            staging.rename(args.output_dir)
        print(f"{report['status']}: {args.output_dir}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
