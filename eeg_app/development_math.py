"""Prepare reviewed EEG features and evaluate participant-held-out detectors."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
from math import isfinite
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

from .math_detector import DetectorSettings, REQUIRED_FEATURES, predict_records
from .math_pipeline import extract_features_for_windows
from .metrics import ELIGIBLE_LABELS, VALID_REFERENCE_LABELS, compare_detectors, evaluate_predictions
from .preprocessing import REQUIRED_CHANNELS
from .review import _validate_review_rows, load_windows
from .window_comparison import quantile


def read_release(path):
    """Read a ZIP of review CSVs without extracting or changing the originals."""
    sheets, seen = {}, set()
    with ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".csv"):
                continue
            reader = csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"), newline=""))
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)):
                raise ValueError(f"{member.filename}: duplicate CSV column")
            rows = []
            for line, row in enumerate(reader, 2):
                prefix = f"{member.filename}:{line}"
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{prefix}: wrong number of CSV fields")
                row = {key: value.strip() for key, value in row.items()}
                session, window = row.get("session_id"), row.get("window_id")
                if not session or not window or window in seen:
                    raise ValueError(f"{prefix}: missing session/window ID or duplicate window ID {window!r}")
                seen.add(window)
                label = row.get("label", "").lower()
                row["label"] = "uncertain" if label == "unsure" else label
                if row["label"] not in VALID_REFERENCE_LABELS:
                    raise ValueError(f"{prefix}: unsupported label {label!r}")
                if "affected_channels" in row:
                    channels = re.split(r"[,;]", row["affected_channels"])
                    row["affected_channels"] = ";".join(channel.strip().upper() for channel in channels if channel.strip())
                rows.append(row)
            if not rows:
                raise ValueError(f"{member.filename}: no review rows")
            sessions = {row["session_id"] for row in rows}
            if len(sessions) != 1 or rows[0]["session_id"] in sheets:
                raise ValueError(f"{member.filename}: expected one distinct session per review sheet")
            sheets[rows[0]["session_id"]] = (fields, rows)
    if not sheets:
        raise ValueError(f"{path}: no review CSVs")
    return sheets


def prepare(releases, session_root, participants, flatline_tolerance_uv):
    sheets = {}
    for release_name, path in releases:
        for session, sheet in read_release(path).items():
            if session in sheets:
                raise ValueError(f"Session {session!r} occurs in more than one release")
            sheets[session] = (release_name, *sheet)
    if set(participants) != set(sheets) or any(not isinstance(p, str) or not p.strip() for p in participants.values()):
        raise ValueError("Provide one participant ID per reviewed session, grouping refits under the same person")

    paths = {}
    for path in Path(session_root).rglob("metadata.json"):
        if not (path.parent / "eeg.csv").is_file():
            continue
        session = json.loads(path.read_text(encoding="utf-8-sig")).get("session_id")
        if session in sheets:
            if session in paths:
                raise ValueError(f"Multiple recordings for session {session!r}")
            paths[session] = path.parent
    if missing := set(sheets) - set(paths):
        raise ValueError("Missing saved sessions: " + ", ".join(sorted(missing)))

    references, features, exclusions = [], [], []
    for session, (release_name, fields, rows) in sheets.items():
        print(f"Preparing {session}", flush=True)
        windows = load_windows(paths[session])
        normalized = io.StringIO(newline="")
        writer = csv.DictWriter(normalized, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        normalized.seek(0)
        checked = _validate_review_rows(windows, csv.DictReader(normalized))
        by_id = {row["window_id"]: row for row in checked}
        participant = participants[session]
        for window in windows:
            reference = by_id.get(window.window_id, {"label": "invalid"})
            references.append({**reference, "window_id": window.window_id, "session_id": session,
                               "participant_id": participant, "label_release": release_name})
        extracted = extract_features_for_windows(windows, flatline_tolerance_uv=flatline_tolerance_uv)
        features.extend({**record, "participant_id": participant} for record in extracted["feature_records"])
        exclusions.extend(extracted["skipped_windows"])
    return {"references": references, "features": features, "loader_exclusions": exclusions,
            "label_counts": dict(Counter(row["label"] for row in references))}


def _selection(training, validation, features):
    maxima = {key: [] for key in REQUIRED_FEATURES}
    for row in training:
        record = features[row["window_id"]]
        for key in maxima:
            maxima[key].append(max(record["features"][f"{channel}_{key}"] for channel in REQUIRED_CHANNELS))
    candidates = []
    for percentile in (90, 95, 99):
        settings = DetectorSettings(2, **{key: quantile(values, percentile / 100) for key, values in maxima.items()},
                                    selection_note=f"Training channel maxima percentile {percentile}.")
        decisions = predict_records((features[r["window_id"]] for r in validation), settings, validity_confirmed=True)
        result = evaluate_predictions(validation, decisions["prediction_records"])
        metrics = result["metrics"]
        score = (metrics["clean_retention"]["value"] + metrics["recall"]["value"]) / 2
        candidates.append({"percentile": percentile, "settings": settings.to_dict(),
                           "balanced_accuracy": score, "validation": result})
    # Prefer higher artifact recall when balanced accuracy ties.
    selected = max(candidates, key=lambda r: (r["balanced_accuracy"], r["validation"]["metrics"]["recall"]["value"]))
    return selected, candidates


def evaluate(prepared, folds, cnn_predictions=None):
    if isinstance(folds, dict):
        if folds.get("status") != "approved":
            raise ValueError("Shared split manifest must be approved")
        folds = [{**row, "heldout": row["held_out"]} for row in folds["folds"]]
    references = prepared["references"]
    references_by_id = {r["window_id"]: r for r in references}
    features = {r["window_id"]: r for r in prepared["features"]}
    if len(features) != len(prepared["features"]) or len(references) != len({r["window_id"] for r in references}):
        raise ValueError("Duplicate prepared window ID")
    people = {row["participant_id"] for row in references}
    if len(people) != 4:
        raise ValueError("The shared evaluation requires four development participants")
    heldouts = set()
    fold_ids = set()
    for fold in folds:
        train, validation, heldout = fold["training"], fold["validation"], fold["heldout"]
        if (len(train) != 2 or len(set(train) | {validation, heldout}) != 4
                or set(train) | {validation, heldout} != people or heldout in heldouts
                or fold["fold_id"] in fold_ids):
            raise ValueError("Each fold needs two training, one validation, and one unique held-out participant")
        heldouts.add(heldout)
        fold_ids.add(fold["fold_id"])
    if heldouts != people:
        raise ValueError("Exactly one held-out fold is required per participant")

    eligible = [r for r in references if r["label"] in ELIGIBLE_LABELS]
    completeness_settings = DetectorSettings(2, 0, 0, "Feature completeness check only")
    if missing := [r["window_id"] for r in eligible if r["window_id"] not in features]:
        raise ValueError("Missing features for eligible windows: " + ", ".join(missing))
    checked = predict_records((features[r["window_id"]] for r in eligible), completeness_settings,
                              validity_confirmed=True)
    if checked["excluded_windows"]:
        raise ValueError(f"Eligible windows have unavailable detector inputs: {checked['excluded_windows']}")

    all_predictions, reports, expected_fold = [], [], {}
    for fold in folds:
        training = [r for r in eligible if r["participant_id"] in fold["training"]]
        validation = [r for r in eligible if r["participant_id"] == fold["validation"]]
        for name, group in (("training", training), ("validation", validation)):
            if {row["label"] for row in group} != ELIGIBLE_LABELS:
                raise ValueError(f"{fold['fold_id']}: {name} needs clean and artifact examples")
        selected, candidates = _selection(training, validation, features)
        heldout = [r for r in references if r["participant_id"] == fold["heldout"]]
        expected_fold.update({r["window_id"]: fold["fold_id"] for r in heldout})
        records = (features[r["window_id"]] for r in heldout if r["label"] in ELIGIBLE_LABELS)
        result = predict_records(records, DetectorSettings.from_dict(selected["settings"]), validity_confirmed=True)
        predictions = [{**r, "fold_id": fold["fold_id"]} for r in result["prediction_records"]]
        all_predictions.extend(predictions)
        reports.append({"fold": fold, "selected": selected, "candidates": candidates,
                        "heldout": evaluate_predictions(heldout, predictions)})

    report = {"label_releases": sorted({r["label_release"] for r in references}),
              "folds": reports, "mathematical_predictions": all_predictions,
              "mathematical_evaluation": evaluate_predictions(references, all_predictions)}
    if cnn_predictions is not None:
        for prediction in cnn_predictions:
            window_id = prediction.get("window_id")
            if window_id not in expected_fold or prediction.get("fold_id") != expected_fold[window_id]:
                raise ValueError(f"CNN prediction has an unknown window or mismatched held-out fold: {window_id!r}")
            reference = references_by_id[window_id]
            for field in ("participant_id", "session_id"):
                if field in prediction and prediction[field] != reference.get(field):
                    raise ValueError(f"CNN prediction has mismatched {field}: {window_id!r}")
        report["comparison"] = compare_detectors(references, all_predictions, cnn_predictions)
    return report


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def investigate_rules(prepared, evaluation):
    """Compare two extra triggers against each saved math setting on validation."""
    features = {record["window_id"]: record for record in prepared["features"]}
    eligible = [row for row in prepared["references"] if row["label"] in ELIGIBLE_LABELS]
    reports = []
    for report in evaluation["folds"]:
        fold = report["fold"]
        settings = DetectorSettings.from_dict(report["selected"]["settings"])
        training_clean = [row for row in eligible
                          if row["participant_id"] in fold["training"] and row["label"] == "clean"]
        validation = [row for row in eligible if row["participant_id"] == fold["validation"]]
        baseline = predict_records([features[row["window_id"]] for row in validation], settings,
                                   validity_confirmed=True)["prediction_records"]
        baseline_metrics = evaluate_predictions(validation, baseline)
        candidates = []
        for name in ("standard_deviation_uv", "flatline_fraction"):
            maxima = {}
            for row in training_clean + validation:
                window_id = row["window_id"]
                record = features[window_id]
                keys = [f"{channel}_{name}" for channel in REQUIRED_CHANNELS]
                values = [record["features"].get(key) for key in keys]
                if any(key in record.get("unavailable_reasons", {}) or value is None or not isfinite(value)
                       for key, value in zip(keys, values)):
                    raise ValueError(f"{window_id}: unavailable {name} for the candidate rule")
                maxima[window_id] = max(values)
            limit = quantile([maxima[row["window_id"]] for row in training_clean], .95)
            predictions = [{**row, "decision": "artifact" if maxima[row["window_id"]] > limit else row["decision"]}
                           for row in baseline]
            candidates.append({"feature": name, "units": "microvolts" if name.endswith("_uv") else "fraction",
                               "threshold": limit, "validation": evaluate_predictions(validation, predictions)})
        reports.append({"fold_id": fold["fold_id"], "baseline": baseline_metrics, "candidates": candidates})
    return reports


def read_cnn_predictions(path):
    """Read the exported JSONL files in Namit's ZIP or a JSON list."""
    if Path(path).suffix.lower() != ".zip":
        return read_json(path)
    with ZipFile(path) as archive:
        records = [json.loads(line) for member in archive.infolist()
                   if not member.is_dir() and member.filename.lower().endswith(".jsonl")
                   and not member.filename.startswith("__MACOSX/")
                   for line in archive.read(member).decode("utf-8-sig").splitlines() if line.strip()]
    if not records:
        raise ValueError(f"{path}: no prediction records in JSONL files")
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Count labels in a review ZIP")
    audit.add_argument("release")
    prep = commands.add_parser("prepare", help="Join reviews to private saved EEG and calculate features")
    prep.add_argument("sessions")
    prep.add_argument("participants", help="JSON object mapping session ID to participant ID")
    prep.add_argument("output")
    prep.add_argument("--release", action="append", required=True, nargs=2, metavar=("VERSION", "ZIP"))
    prep.add_argument("--flatline-tolerance-uv", type=float, default=0.1)
    score = commands.add_parser("evaluate", help="Select and test fold settings; optionally compare CNN")
    score.add_argument("prepared")
    score.add_argument("folds")
    score.add_argument("output")
    score.add_argument("--cnn-predictions")
    investigate = commands.add_parser("investigate", help="Compare extra rules on validation windows")
    investigate.add_argument("prepared")
    investigate.add_argument("evaluation")
    investigate.add_argument("output")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            sheets = read_release(args.release)
            counts = Counter(row["label"] for _, rows in sheets.values() for row in rows)
            print(json.dumps({"sessions": len(sheets), "labels": counts}, indent=2))
            return
        output = Path(args.output)
        if output.exists():
            raise FileExistsError(f"Output already exists: {output}")
        if args.command == "prepare":
            result = prepare(args.release, args.sessions, read_json(args.participants), args.flatline_tolerance_uv)
        elif args.command == "investigate":
            result = investigate_rules(read_json(args.prepared), read_json(args.evaluation))
        else:
            cnn = read_cnn_predictions(args.cnn_predictions) if args.cnn_predictions else None
            result = evaluate(read_json(args.prepared), read_json(args.folds), cnn)
        serialized = json.dumps(result, indent=2, allow_nan=False)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
    except (BadZipFile, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
