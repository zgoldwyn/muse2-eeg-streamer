"""Apply saved screening settings and audit evaluation reports without tuning."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from math import isclose, isfinite
from numbers import Real
from pathlib import Path
import tempfile
from types import SimpleNamespace
from zipfile import BadZipFile

from .development_math import read_cnn_predictions, read_release
from .math_detector import DetectorSettings, WindowExcluded
from .math_pipeline import extract_window_features
from .metrics import ELIGIBLE_LABELS, compare_detectors, evaluate_predictions
from .preprocessing import REQUIRED_CHANNELS
from .review import _validate_review_rows, load_windows
from .rule_search import feature_definition, predict_policy
from .validation_comparison import _checked_cnn, _table


SOURCE_FILES = (
    "features.py", "preprocessing.py", "dataset.py", "review.py",
    "math_pipeline.py", "math_detector.py", "rule_search.py",
    "development_math.py", "metrics.py", "validation_comparison.py", "final_evaluation.py",
)


def source_versions():
    """Hash source with LF newlines so Windows checkouts have the same version."""
    root = Path(__file__).parent
    return {f"eeg_app/{name}": hashlib.sha256(
        (root / name).read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest() for name in SOURCE_FILES}


def object_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_settings(settings, *, development=False):
    if settings.get("schema_version") != 1:
        raise ValueError("Unsupported saved-method schema_version")
    if settings.get("channel_order") != list(REQUIRED_CHANNELS):
        raise ValueError("Saved channel order must be TP9, AF7, AF8, TP10")
    policy = settings["math_policy"]
    base = DetectorSettings.from_dict(policy["settings"])
    if base.window_length_s != 2 or settings.get("nominal_sample_rate_hz") != 256:
        raise ValueError("This handoff requires unchanged two-second, 256 Hz windows")
    if policy.get("additional_rules"):
        raise ValueError("This selected handoff contains only peak-to-peak and adjacent-jump rules")
    cutoff = settings["cnn"]["cutoff"]
    if (isinstance(cutoff, bool) or not isinstance(cutoff, Real)
            or not isfinite(cutoff) or not 0 <= cutoff <= 1):
        raise ValueError("Saved CNN cutoff must be finite and between 0 and 1")
    if settings["cnn"].get("comparison") != ">=":
        raise ValueError("CNN decision comparison must be >=")
    if settings.get("source_sha256_lf") != source_versions():
        raise ValueError("Source version differs from saved settings; document the defect/change before rerunning")
    if not development:
        approval = settings.get("approval", {})
        if (settings.get("status") != "approved_frozen" or not approval.get("approved_by")
                or not approval.get("approved_at")):
            raise ValueError("Reserved evaluation requires Zach's approved frozen settings")
        if settings.get("development_label_status") != "reconciled":
            raise ValueError("Frozen settings must identify reconciled development labels")
        if settings.get("open_items"):
            raise ValueError("Resolve the recorded handoff open_items before freezing")
        for key in ("checkpoint_sha256", "source_sha256_lf"):
            value = settings["cnn"].get(key)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"Frozen CNN handoff needs {key}")
    return settings


def _check_cnn_decisions(rows, windows, settings):
    checked, versions = _checked_cnn(rows, windows)
    expected = [settings["cnn"][key] for key in ("model_version", "preprocessing_version")]
    if versions != expected:
        raise ValueError("CNN model/preprocessing version differs from saved settings")
    for row in checked:
        decision = "artifact" if row["artifact_score"] >= settings["cnn"]["cutoff"] else "clean"
        if row.get("decision") != decision:
            raise ValueError(f"{row['window_id']}: CNN decision disagrees with the saved cutoff")
    return checked


def predict_sessions(manifest, settings, *, checkpoint=None, cnn_records=None,
                     development=False, backend=None):
    """Blind inference on explicitly listed sessions; reference labels are never read.

    Existing CNN exports are accepted only for a development dry run. Reserved
    inference requires the exact approved checkpoint and the actual PR #31 API.
    """
    check_settings(settings, development=development)
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Provide a nonempty session manifest")
    if (checkpoint is None) == (cnn_records is None):
        raise ValueError("Provide exactly one CNN checkpoint or development prediction export")
    if cnn_records is not None and not development:
        raise ValueError("Reserved inference must load the frozen checkpoint")
    if checkpoint is not None:
        if file_hash(checkpoint) != settings["cnn"].get("checkpoint_sha256"):
            raise ValueError("CNN checkpoint hash differs from saved settings")
        if backend is None:
            try:
                from . import waveform_cnn as backend
            except ImportError as error:
                raise ValueError("Install Namit's PR #31 waveform_cnn module and its documented dependencies") from error
        cnn_source = Path(backend.__file__).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(cnn_source).hexdigest() != settings["cnn"].get("source_sha256_lf"):
            raise ValueError("CNN source hash differs from saved settings")
    inventory, features, math, exclusions, raw_windows, inputs = [], [], [], [], [], {}
    seen = set()
    for session_id, entry in sorted(manifest.items()):
        if (not isinstance(session_id, str) or not session_id.strip() or not isinstance(entry, dict)
                or not isinstance(entry.get("participant_id"), str) or not entry["participant_id"].strip()):
            raise ValueError("Each session needs a nonempty session ID, path, and participant_id")
        root = Path(entry["path"])
        windows = load_windows(root)
        if not windows or any(window.session_id != session_id for window in windows):
            raise ValueError(f"Session manifest ID mismatch: {session_id}")
        inputs[session_id] = {name: file_hash(root / name) for name in ("eeg.csv", "metadata.json")}
        for window in windows:
            if window.window_id in seen:
                raise ValueError(f"Duplicate loader window ID: {window.window_id}")
            seen.add(window.window_id)
            item = {key: getattr(window, key) for key in
                    ("window_id", "session_id", "start_time_s", "end_time_s", "is_valid")}
            item.update(participant_id=entry["participant_id"], invalid_reasons=list(window.invalid_reasons))
            inventory.append(item)
            if window.is_valid is not True or window.invalid_reasons:
                exclusions.append({"window_id": window.window_id, "reasons": list(window.invalid_reasons)})
                continue
            raw_windows.append((window, entry["participant_id"]))
            definition = settings["feature_definition"]
            record = extract_window_features(window, flatline_tolerance_uv=definition["flatline_tolerance_uv"],
                                             entropy_m=definition["entropy_m"],
                                             entropy_tolerance_uv=definition.get("entropy_tolerance_uv"))
            if feature_definition([record]) != definition:
                raise ValueError(f"Feature definitions differ from saved settings: {window.window_id}")
            record["participant_id"] = entry["participant_id"]
            features.append(record)
            try:
                math.append(predict_policy(record, settings["math_policy"]))
            except WindowExcluded as error:
                exclusions.append({"window_id": window.window_id, "reasons": error.reasons})
    if checkpoint is not None:
        import numpy as np
        examples = []
        for window, participant in raw_windows:
            samples = np.asarray([window.channel_samples[channel] for channel in REQUIRED_CHANNELS], dtype=np.float32)
            if samples.shape != (4, 512) or not np.isfinite(samples).all():
                raise ValueError(f"CNN needs four finite 512-sample channels: {window.window_id}")
            # PR #31 filters by label. This sentinel means 'include for inference';
            # it is never read from a reviewer or used for fitting or scoring.
            examples.append(backend.WaveformExample(window_id=window.window_id, session_id=window.session_id,
                            participant_id=participant, samples_uv=samples, label=0,
                            review_label="inference_only", is_valid=True))
        def infer():
            model = backend.load_checkpoint(checkpoint)
            rows = backend.predict_examples(examples, model, fold_id="frozen-repeat-evaluation") if examples else []
            return sorted([{**row, "decision": "artifact" if row["artifact_score"] >= settings["cnn"]["cutoff"]
                            else "clean"} for row in rows], key=lambda row: row["window_id"])
        cnn_records = infer()
        if infer() != cnn_records:
            raise ValueError("CNN checkpoint reload did not reproduce predictions")
        if {row["window_id"] for row in cnn_records} != {window.window_id for window, _ in raw_windows}:
            raise ValueError("CNN inference did not cover exactly the valid loader window IDs")
        cnn_source_input = {"checkpoint_sha256": file_hash(checkpoint), "reload_reproduces_predictions": True}
    else:
        cnn_source_input = {"development_export_sha256": object_hash(cnn_records)}
    if cnn_records:
        cnn_records = _check_cnn_decisions(cnn_records, inventory, settings)
        invalid = {row["window_id"] for row in inventory if row["is_valid"] is not True}
        if any(row["window_id"] in invalid for row in cnn_records):
            raise ValueError("CNN supplied a decision for a technically invalid window")
    return {"schema_version": 1, "data_role": "development" if development else "reserved_evaluation",
            "settings_sha256": object_hash(settings), "input_sha256": inputs, "cnn_input": cnn_source_input,
            "windows": inventory, "feature_records": features, "math": math,
            "cnn": cnn_records, "excluded_windows": exclusions}


def score_bundle(bundle, sheets, settings, label_release, *, development=False):
    """Validate complete review sheets and score unchanged predictions by ID."""
    check_settings(settings, development=development)
    if bundle.get("settings_sha256") != object_hash(settings):
        raise ValueError("Prediction bundle does not match these saved settings")
    role = "development" if development else "reserved_evaluation"
    if bundle.get("data_role") != role:
        raise ValueError("Development and reserved evaluation outputs must remain separate")
    if not isinstance(label_release, str) or not label_release.strip():
        raise ValueError("Provide the exact label release identifier")
    windows = bundle["windows"]
    indexed = {row["window_id"]: row for row in windows}
    if len(indexed) != len(windows):
        raise ValueError("Duplicate inventory window ID")
    sessions = {row["session_id"] for row in windows}
    if set(sheets) != sessions:
        raise ValueError("Review sessions differ from prediction sessions")
    labels = {}
    for session, (fields, rows) in sheets.items():
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        text.seek(0)
        group = [SimpleNamespace(**row) for row in windows if row["session_id"] == session]
        checked = _validate_review_rows(group, csv.DictReader(text))
        labels.update({row["window_id"]: row["label"] for row in checked})
    references = [{**row, "label": labels[row["window_id"]] if row["is_valid"] is True else "invalid"}
                  for row in windows]
    eligible = {row["window_id"] for row in references if row["label"] in ELIGIBLE_LABELS}
    features = {row["window_id"]: row for row in bundle["feature_records"]}
    if len(features) != len(bundle["feature_records"]) or set(features) - set(indexed):
        raise ValueError("Duplicate or unknown feature record ID")
    math = bundle["math"]
    # First use the existing scorer for missing, duplicate, and unknown IDs.
    evaluate_predictions(references, math)
    for row in math:
        if row["window_id"] not in features:
            raise ValueError(f"Missing feature record: {row['window_id']}")
        record = features[row["window_id"]]
        window = indexed[row["window_id"]]
        if any(record.get(key) != window[key] for key in
               ("session_id", "participant_id", "start_time_s", "end_time_s")):
            raise ValueError(f"Feature metadata does not match loader window: {row['window_id']}")
        if feature_definition([record]) != settings["feature_definition"]:
            raise ValueError("Saved feature definitions changed")
        expected = predict_policy(record, settings["math_policy"])
        if row != expected:
            raise ValueError(f"Saved math prediction or triggers changed: {row['window_id']}")
    cnn = _check_cnn_decisions(bundle["cnn"], references, settings)
    invalid = {row["window_id"] for row in windows if row["is_valid"] is not True}
    if any(row["window_id"] in invalid for row in math + cnn):
        raise ValueError("Technically invalid windows must not receive binary predictions")
    comparison = compare_detectors(references, math, cnn)
    policies = {name: result for name, result in comparison.items() if "metrics" in result}
    for name, decision in (("training_majority", settings["training_majority_decision"]), ("always_clean", "clean")):
        predictions = [{"window_id": window_id, "decision": decision} for window_id in sorted(eligible)]
        policies[name] = evaluate_predictions(references, predictions)
    return {"schema_version": 1, "data_role": role, "label_release": label_release,
            "development_label_status": settings["development_label_status"],
            "development_open_items": settings.get("open_items", []) if development else [],
            "settings_sha256": object_hash(settings), "prediction_bundle_sha256": object_hash(bundle),
            "review_records_sha256": object_hash(sheets), "eligible_window_ids": sorted(eligible),
            "policies": policies, "agreement": comparison["agreement"],
            "excluded_windows": [{"window_id": row["window_id"], "label": row["label"],
                                  "reasons": row["invalid_reasons"]} for row in references
                                 if row["label"] not in ELIGIBLE_LABELS],
            "input_exclusions": bundle["excluded_windows"],
            "proposed_minimum_clean_retention": settings["proposed_minimum_clean_retention"]}


def write_bundle(output_dir, files):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for name, value in files.items():
            text = value if isinstance(value, str) else json.dumps(value, indent=2, allow_nan=False) + "\n"
            (staging / name).write_text(text, encoding="utf-8")
        staging.rename(output_dir)


def report_summary(report):
    lines = [f"# {report['data_role']} evaluation", "", f"Label release: {report['label_release']}", ""]
    if report["data_role"] == "development" and report["development_label_status"] != "reconciled":
        lines += ["Preliminary development labels; independent-review reconciliation remains pending.", ""]
    lines += _table(report["policies"])
    summary = next(iter(report["policies"].values()))["summary"]
    lines += ["", f"Eligible: {summary['eligible_windows']}; uncertain excluded: "
              f"{summary['uncertain_windows_excluded']}; invalid excluded: {summary['invalid_windows_excluded']}.",
              "", "No threshold search or model fitting occurs in these commands."]
    if report["development_open_items"]:
        lines += ["", "Open development handoff items:", ""]
        lines += [f"- {item}" for item in report["development_open_items"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict", help="Apply saved math policy and CPU CNN without labels")
    predict.add_argument("manifest", type=Path)
    sources = predict.add_mutually_exclusive_group(required=True)
    sources.add_argument("--checkpoint", type=Path)
    sources.add_argument("--cnn-predictions", type=Path, help="Existing export for development dry run only")
    for name in ("score", "verify"):
        sub = commands.add_parser(name, help="Score predictions" if name == "score" else "Recompute and audit a returned report")
        sub.add_argument("predictions", type=Path)
        sub.add_argument("--labels", type=Path, required=True)
        sub.add_argument("--label-release", required=True)
        if name == "verify":
            sub.add_argument("--report", type=Path, required=True)
    for sub in (predict, *[commands.choices[name] for name in ("score", "verify")]):
        sub.add_argument("--settings", type=Path, required=True)
        sub.add_argument("--development", action="store_true", help="Allow a proposed method on approved development data")
        if sub is not commands.choices["verify"]:
            sub.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        settings = read(args.settings)
        if args.command == "predict":
            result = predict_sessions(read(args.manifest), settings, checkpoint=args.checkpoint,
                                      cnn_records=read_cnn_predictions(args.cnn_predictions) if args.cnn_predictions else None,
                                      development=args.development)
            write_bundle(args.output_dir, {"predictions.json": result})
            print(f"{result['data_role']}: {len(result['math'])} math predictions; {len(result['cnn'])} CNN predictions")
        else:
            result = score_bundle(read(args.predictions), read_release(args.labels), settings,
                                  args.label_release, development=args.development)
            if args.command == "verify":
                if result != read(args.report):
                    raise ValueError("Returned report differs from recomputed counts, window IDs, denominators, or provenance")
                print("VERIFIED: same eligible IDs, predictions, confusion counts, denominators, and provenance")
            else:
                write_bundle(args.output_dir, {"report.json": result, "summary.md": report_summary(result)})
                print(report_summary(result))
    except (BadZipFile, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
