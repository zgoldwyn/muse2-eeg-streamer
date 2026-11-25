"""Recalculate 2/4/8 s features from the shared local public EEG recordings.

No network access, human labels, model fitting, or final window-length choice.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

from eeg_app.math_detector import DetectorSettings, predict_records
from eeg_app.math_pipeline import extract_window_features
from eeg_app.public_math_run import prepare_run, save_run
from eeg_app.window_comparison import annotated_gaps, guard_window, training_stability
from .public_trace_examples import IMPORTER_REF, verify_features

PARTICIPANTS = ("sub-01", "sub-08", "sub-09", "sub-10")
TRAINING = PARTICIPANTS[:3]
HELDOUT = PARTICIPANTS[3:]


def calculate_job(root_string, output_string, participant, length, source):
    import mne
    root, output = Path(root_string), Path(output_string)
    importer = types.ModuleType("eeg_app._window_comparison_importer")
    sys.modules[importer.__name__] = importer
    exec(compile(source, "pinned-public-muse-importer", "exec"), importer.__dict__)
    edf = root / "trace-inputs/sourcedata" / participant / f"{participant}_task-BT_acq-Muse2_eeg.edf"
    mat = root / "trace-inputs/derivatives" / participant / f"{participant}_task-BT_acq-BLP_eeg.mat"
    with edf.open("rb") as stream:
        stream.seek(192)
        reserved = stream.read(44).decode("ascii").strip()
    if reserved.startswith("EDF+D"):
        raise ValueError("Discontinuous EDF+D needs a gap-preserving importer before comparison")
    raw = mne.io.read_raw_edf(edf, preload=False, verbose="ERROR")
    gaps = annotated_gaps(raw.annotations)
    raw.close()
    imported = importer.import_public_muse_recording(edf, mat, window_length_s=length)
    export_content = (root / f"exports/features-{length}s.jsonl").read_bytes()
    references = {record["window_id"]: record for record in map(json.loads, export_content.decode().splitlines())
                  if record["participant_id"] == participant}
    records, exclusions, audit = [], [], []
    for original in imported.windows:
        window = guard_window(original, gaps)
        if not window.is_valid:
            exclusions.append({"window_id": window.window_id, "participant_id": participant,
                               "start_time_s": window.start_time_s, "end_time_s": window.end_time_s,
                               "reasons": list(window.invalid_reasons)})
            continue
        # Calculate on this length's actual arrays, not on shorter-window features.
        feature_record = extract_window_features(window, flatline_tolerance_uv=0.1)
        record = {"window_id": window.window_id, "participant_id": window.participant_id,
                  "session_id": window.session_id, "start_time_s": window.start_time_s,
                  "end_time_s": window.end_time_s, "window_length_s": length,
                  "sample_rate_hz": window.nominal_sample_rate_hz,
                  "features": feature_record["features"], "weak_target": window.weak_target,
                  "target_provenance": dict(window.target_provenance)}
        reference = references[window.window_id]
        if {k: v for k, v in record.items() if k != "features"} != {k: v for k, v in reference.items() if k != "features"}:
            raise ValueError(f"Export identity/metadata differs: {window.window_id}")
        verify_features(record["features"], reference["features"])
        records.append(record)
        audit.append({key: value for key, value in feature_record.items() if key != "features"})
        if len(records) % 15 == 0:
            print(f"{participant} / {length}s: recalculated {len(records)} windows", flush=True)
    excluded_ids = {row["window_id"] for row in exclusions}
    if set(references) - excluded_ids != {row["window_id"] for row in records}:
        raise ValueError("Raw/extracted window set differs from Namit's export")
    result = {"participant_id": participant, "window_length_s": length, "records": records,
              "exclusions": exclusions, "feature_audit": audit, "explicit_gaps": gaps,
              "edf_reserved": reserved, "source_hashes": {
                  str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (edf, mat)},
              "export_sha256": hashlib.sha256(export_content).hexdigest()}
    (output / f"{participant}-{length}s.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/public_muse"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/public_muse/part4-window-comparison"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    jobs_dir = args.output_dir / "recalculation"
    jobs_dir.mkdir()
    source = subprocess.check_output(["git", "show", f"{IMPORTER_REF}:eeg_app/public_muse.py"])
    (args.output_dir / "importer-source.py").write_bytes(source)
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(calculate_job, str(args.root), str(jobs_dir), participant, length, source)
                for length in (2, 4, 8) for participant in PARTICIPANTS]
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            print(f"Completed {result['participant_id']} / {result['window_length_s']}s: "
                  f"{len(result['records'])} usable, {len(result['exclusions'])} excluded", flush=True)
    summary = {"importer_commit": IMPORTER_REF, "training_participants": list(TRAINING),
               "heldout_participants": list(HELDOUT), "percentile": 95,
               "interpretation": "Provisional development settings; task/rest flagging is not artifact accuracy.",
               "lengths": []}
    for length in (2, 4, 8):
        group = sorted((result for result in results if result["window_length_s"] == length),
                       key=lambda result: result["participant_id"])
        records = [record for result in group for record in result["records"]]
        report = prepare_run(records, training_participants=TRAINING, heldout_participants=HELDOUT,
                             window_length_s=length, percentile=95)
        settings = DetectorSettings.from_dict(report["settings"])
        repeated = predict_records(list(reversed(records)), settings, validity_confirmed=True)
        if sorted(repeated["prediction_records"], key=lambda r: r["window_id"]) != sorted(report["prediction_records"], key=lambda r: r["window_id"]):
            raise AssertionError("Predictions changed on repeat/reordered input")
        report["loader_exclusions"] = [row for result in group for row in result["exclusions"]]
        report["feature_recalculation"] = "All six features per channel recalculated directly from each length's sample arrays."
        report["source_export_sha256"] = group[0]["export_sha256"]
        save_run(report, args.output_dir / f"{length}s")
        (args.output_dir / f"features-{length}s.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        stability = training_stability(records, TRAINING)
        (args.output_dir / f"stability-{length}s.json").write_text(json.dumps(stability, indent=2), encoding="utf-8")
        item = {"window_length_s": length, "usable_windows": len(records),
                "loader_exclusions": len(report["loader_exclusions"]), "settings": report["settings"],
                "groups": report["groups"], "stability": stability["summary"],
                "repeat_and_reordered_predictions_match": True,
                "recalculated_feature_values_verified": sum(len(record["features"]) for record in records)}
        summary["lengths"].append(item)
        print(json.dumps({k: item[k] for k in ("window_length_s", "usable_windows", "loader_exclusions", "settings", "groups")}), flush=True)
    (args.output_dir / "comparison.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Comparison saved to {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
