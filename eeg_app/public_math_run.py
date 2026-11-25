"""One provisional public-subset detector run, with task/rest flagging fractions.

This is not an artifact-accuracy evaluation and never creates human labels.
Raw trace examples require separately supplied samples, not feature exports.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from math import isclose, isfinite
from numbers import Real
from pathlib import Path

from .math_detector import DetectorSettings, REQUIRED_FEATURES, predict_records
from .preprocessing import REQUIRED_CHANNELS


def prepare_run(records, *, training_participants, heldout_participants, window_length_s=2, percentile=95):
    """Select one label-blind training-only setting, then apply it unchanged.

    Selection uses the requested percentile (inclusive interpolation) of each
    training window's maximum across channels. Task/rest and heldout values
    play no role in selecting limits. This is an explicit provisional heuristic,
    not a specificity/false-positive guarantee or a search for an optimal rule.
    """
    training, heldout = set(training_participants), set(heldout_participants)
    if not training or not heldout or training & heldout:
        raise ValueError("Training and heldout participants must be nonempty and disjoint.")
    if isinstance(percentile, bool) or not isinstance(percentile, Real) or not isfinite(percentile) or not 0 < percentile < 100:
        raise ValueError("percentile must be strictly between 0 and 100.")
    seen, present, valid_training, selection_exclusions = set(), set(), [], []
    for record in records:
        window_id = record.get("window_id")
        if not isinstance(window_id, str) or not window_id or window_id in seen:
            raise ValueError(f"Missing or duplicate window ID: {window_id!r}")
        seen.add(window_id)
        participant = record.get("participant_id")
        if participant not in training | heldout:
            raise ValueError(f"{window_id}: participant is outside the specified split.")
        present.add(participant)
        if record.get("weak_target") not in ("task_period", "rest_period"):
            raise ValueError(f"{window_id}: weak target must be task_period or rest_period.")
        for name in ("window_length_s", "start_time_s", "end_time_s"):
            value = record.get(name)
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
                raise ValueError(f"{window_id}: invalid {name}.")
        if (record["start_time_s"] < 0 or not isclose(record["window_length_s"], window_length_s)
                or not isclose(record["end_time_s"] - record["start_time_s"], window_length_s)):
            raise ValueError(f"{window_id}: window interval must match the selected length.")
        if participant not in training:
            continue
        # Check eligibility using the same detector validation rather than
        # interpreting any missing numeric value as zero during calibration.
        from sys import float_info
        check_settings = DetectorSettings(window_length_s, float_info.max, float_info.max,
                                          "Completeness check only; not selected decision limits.")
        checked = predict_records([record], check_settings, validity_confirmed=True)
        if checked["excluded_windows"]:
            selection_exclusions.extend(checked["excluded_windows"])
        else:
            valid_training.append(record)
    if present != training | heldout:
        raise ValueError("The export does not contain all participants in the specified split.")
    if len(valid_training) < 2:
        raise ValueError("At least two complete training windows are needed for percentile selection.")

    limits = {}
    for feature in REQUIRED_FEATURES:
        maxima = [max(record["features"][f"{channel}_{feature}"] for channel in REQUIRED_CHANNELS)
                  for record in valid_training]
        # Inclusive linear interpolation also supports fractional percentiles.
        ordered = sorted(maxima)
        position = (len(ordered) - 1) * percentile / 100
        left = int(position)
        right = min(left + 1, len(ordered) - 1)
        limits[feature] = ordered[left] + (position - left) * (ordered[right] - ordered[left])
    note = (f"Provisional {percentile:g}th percentile of training-window channel maxima; "
            f"inclusive interpolation; participants {', '.join(sorted(training))}; "
            "task/rest labels and heldout values unused in selection; no artifact labels available.")
    settings = DetectorSettings(window_length_s, selection_note=note, **limits)
    # The settings object is immutable and selected before any heldout prediction.
    result = predict_records(records, settings, validity_confirmed=True)
    by_id = {record["window_id"]: record for record in records}
    predicted = {record["window_id"]: record for record in result["prediction_records"]}
    groups = []
    examples = []
    for split, participants in (("training", training), ("heldout", heldout)):
        for target in ("rest_period", "task_period"):
            group_ids = [record["window_id"] for record in records
                         if record["participant_id"] in participants and record["weak_target"] == target]
            eligible = [predicted[wid] for wid in group_ids if wid in predicted]
            flagged = sum(prediction["decision"] == "artifact" for prediction in eligible)
            groups.append({"split": split, "weak_target": target, "input_windows": len(group_ids),
                           "predicted_windows": len(eligible), "excluded_windows": len(group_ids) - len(eligible),
                           "flagged": flagged, "fraction_flagged": flagged / len(eligible) if eligible else None})
        for decision in ("artifact", "clean"):
            candidates = [prediction for prediction in predicted.values()
                          if by_id[prediction["window_id"]]["participant_id"] in participants
                          and prediction["decision"] == decision]
            if candidates:
                selected = sorted(candidates, key=lambda prediction: prediction["window_id"])[0]
                source = by_id[selected["window_id"]]
                examples.append({"window_id": source["window_id"], "participant_id": source["participant_id"],
                                 "session_id": source["session_id"], "start_time_s": source["start_time_s"],
                                 "end_time_s": source["end_time_s"], "weak_target": source["weak_target"],
                                 "split": split, "proposed_decision": decision,
                                 "triggers": selected["triggers"], "trace_status": "pending_raw_samples_or_plots"})
    return {
        "interpretation": "Task/rest flagging fractions only; not artifact-detection accuracy.",
        "settings": settings.to_dict(), "training_participants": sorted(training),
        "heldout_participants": sorted(heldout),
        "selection": {"method": "training_window_channel_maximum_percentile", "percentile": percentile,
                      "training_window_ids": [record["window_id"] for record in valid_training],
                      "training_window_count": len(valid_training), "exclusions": selection_exclusions},
        "groups": groups, "prediction_records": result["prediction_records"],
        "excluded_windows": result["excluded_windows"], "trace_candidates": examples,
        "trace_backed_examples_complete": False,
    }


def save_run(report, output_dir):
    """Write analyst-only outputs outside every blinded reviewer bundle."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "settings.json").write_text(json.dumps(report["settings"], indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    # Exact evaluator schema; triggers and settings remain in report.json.
    predictions = [{"window_id": prediction["window_id"], "decision": prediction["decision"]}
                   for prediction in report["prediction_records"]]
    (output / "predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    with (output / "trace-request.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("participant_id", "session_id", "window_id",
                                                   "start_time_s", "end_time_s"))
        writer.writeheader()
        for example in report["trace_candidates"]:
            writer.writerow({key: example[key] for key in writer.fieldnames})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    parser.add_argument("--training-participants", nargs="+", required=True)
    parser.add_argument("--heldout-participants", nargs="+", required=True)
    parser.add_argument("--window-length-s", type=int, choices=(2, 4, 8), required=True)
    parser.add_argument("--percentile", type=float, default=95)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        content = args.records.read_bytes()
        records = [json.loads(line) for line in content.decode("utf-8-sig").splitlines() if line.strip()]
        report = prepare_run(records, training_participants=args.training_participants,
                             heldout_participants=args.heldout_participants,
                             window_length_s=args.window_length_s, percentile=args.percentile)
        report["source_export_sha256"] = hashlib.sha256(content).hexdigest()
        save_run(report, args.output_dir)
        print("Limits (microvolts): " + json.dumps({key: report["settings"][key] for key in REQUIRED_FEATURES}))
        for group in report["groups"]:
            fraction = group["fraction_flagged"]
            display = f"{fraction:.2%}" if fraction is not None else "unavailable"
            print(f"{group['split']} / {group['weak_target']}: {group['flagged']}/{group['predicted_windows']} flagged ({display})")
        print("Trace-backed examples: PENDING raw samples or plots. See trace-request.csv.")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
