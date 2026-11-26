"""Derive clean-training threshold pairs and compare them on reviewed P0005."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
from sys import float_info

from .math_detector import DetectorSettings, REQUIRED_FEATURES, predict_records
from .metrics import ELIGIBLE_LABELS, VALID_REFERENCE_LABELS, evaluate_predictions
from .preprocessing import REQUIRED_CHANNELS
from .window_comparison import quantile


PERCENTILES = (80, 90, 95, 99)
P0005_SESSIONS = ("ses-hdektduv", "ses-2v798e9y", "ses-frivba5s")


def _checked_prepared(prepared, approved_sessions):
    """Validate session membership before reading feature values."""
    if not approved_sessions or any(not person for person in approved_sessions.values()):
        raise ValueError("Provide approved session-to-participant assignments")
    references = {}
    for row in prepared["references"]:
        window_id = row.get("window_id")
        if not isinstance(window_id, str) or not window_id or window_id in references:
            raise ValueError(f"Missing or duplicate reference window ID: {window_id!r}")
        if (row.get("session_id") not in approved_sessions
                or row.get("participant_id") != approved_sessions[row["session_id"]]):
            raise ValueError(f"{window_id}: session/participant is outside the approved data")
        if row.get("label") not in VALID_REFERENCE_LABELS or not row.get("label_release"):
            raise ValueError(f"{window_id}: a supported label and label release are required")
        references[window_id] = row
    present = {row["session_id"] for row in references.values()}
    if present != set(approved_sessions):
        raise ValueError("Prepared data must cover exactly the approved sessions")
    features = {}
    for row in prepared["features"]:
        window_id = row.get("window_id")
        if window_id not in references or window_id in features:
            raise ValueError(f"Unknown or duplicate feature window ID: {window_id!r}")
        reference = references[window_id]
        if any(row.get(key) != reference[key] for key in ("session_id", "participant_id")):
            raise ValueError(f"{window_id}: feature identity disagrees with reference")
        features[window_id] = row
    return references, features


def _complete_records(references, features):
    settings = DetectorSettings(2, float_info.max, float_info.max, "Input completeness check")
    missing = [{"window_id": row["window_id"], "reasons": ["Missing feature record"]}
               for row in references if row["window_id"] not in features]
    rows = [features[row["window_id"]] for row in references if row["window_id"] in features]
    checked = predict_records(rows, settings, validity_confirmed=True)
    available = {row["window_id"] for row in checked["prediction_records"]}
    return [row for row in rows if row["window_id"] in available], missing + checked["excluded_windows"]


def derive_candidates(prepared, approved_sessions):
    """Compute the 4 by 4 grid from labeled clean November 8 windows."""
    if "P0005" in approved_sessions.values():
        raise ValueError("P0005 is reserved for development validation")
    references, features = _checked_prepared(prepared, approved_sessions)
    clean = [row for row in references.values() if row["label"] == "clean"]
    rows, exclusions = _complete_records(clean, features)
    if not rows:
        raise ValueError("No complete labeled clean training windows")
    limits = {}
    for feature in REQUIRED_FEATURES:
        maxima = [max(row["features"][f"{channel}_{feature}"] for channel in REQUIRED_CHANNELS)
                  for row in rows]
        limits[feature] = {str(percentile): quantile(maxima, percentile / 100)
                           for percentile in PERCENTILES}
    candidates = []
    for peak_percentile, jump_percentile in product(PERCENTILES, repeat=2):
        settings = DetectorSettings(
            2, limits["peak_to_peak_uv"][str(peak_percentile)],
            limits["max_adjacent_jump_uv"][str(jump_percentile)],
            f"Clean November 8 training-window channel maxima; inclusive percentiles "
            f"peak-to-peak={peak_percentile}, adjacent-jump={jump_percentile}.",
        )
        candidates.append({
            "candidate_id": f"p2p-p{peak_percentile}-jump-p{jump_percentile}",
            "peak_to_peak_percentile": peak_percentile,
            "max_adjacent_jump_percentile": jump_percentile,
            "settings": settings.to_dict(),
        })
    return {
        "status": "awaiting_P0005_validation", "percentile_grid": list(PERCENTILES),
        "training_sessions": dict(approved_sessions),
        "label_releases": sorted({row["label_release"] for row in references.values()}),
        "training_label_counts": dict(Counter(row["label"] for row in references.values())),
        "clean_windows_used": len(rows), "clean_window_ids": [row["window_id"] for row in rows],
        "clean_input_exclusions": exclusions, "thresholds_uv": limits, "candidates": candidates,
        "rule": "Flag when any channel strictly exceeds either threshold.",
    }


def validate_candidates(grid, prepared):
    """Score the unchanged grid and identify options closest to retention targets."""
    approved_sessions = dict.fromkeys(P0005_SESSIONS, "P0005")
    references, features = _checked_prepared(prepared, approved_sessions)
    if set(grid["training_sessions"]) & set(approved_sessions):
        raise ValueError("Training and validation sessions overlap")
    if "P0005" in grid["training_sessions"].values():
        raise ValueError("Training must exclude P0005")
    eligible = [row for row in references.values() if row["label"] in ELIGIBLE_LABELS]
    if {row["label"] for row in eligible} != ELIGIBLE_LABELS:
        raise ValueError("Validation needs reviewed clean and artifact windows")
    rows, exclusions = _complete_records(eligible, features)
    if exclusions:
        raise ValueError(f"Missing/unavailable features for eligible validation windows: {exclusions}")
    results = []
    for candidate in grid["candidates"]:
        predictions = predict_records(rows, DetectorSettings.from_dict(candidate["settings"]),
                                      validity_confirmed=True)
        evaluation = evaluate_predictions(list(references.values()), predictions["prediction_records"])
        results.append({**candidate, "evaluation": evaluation})
    if not results:
        raise ValueError("The candidate grid is empty")
    options = []
    for target in (.8, .9):
        def order(candidate):
            metrics = candidate["evaluation"]["metrics"]
            return (abs(metrics["clean_retention"]["value"] - target),
                    -metrics["recall"]["value"], -metrics["clean_retention"]["value"],
                    candidate["candidate_id"])
        nearest = min(results, key=order)
        retention = nearest["evaluation"]["metrics"]["clean_retention"]["value"]
        options.append({"target_clean_retention": target, "candidate_id": nearest["candidate_id"],
                        "achieved_clean_retention": retention, "absolute_distance": abs(retention - target)})
    review_status = prepared.get("label_review_status", "unspecified")
    status = ("preliminary_pending_label_reconciliation" if review_status == "preliminary"
              else "awaiting_operating_point_approval")
    return {"status": status, "label_review_status": review_status, "candidates": results,
            "validation_label_releases": sorted({row["label_release"] for row in references.values()}),
            "training_label_releases": grid["label_releases"],
            "retention_options": options,
            "option_ranking": "Closest clean retention, then higher artifact recall, then higher retention."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    derive = commands.add_parser("derive")
    derive.add_argument("prepared", type=Path)
    derive.add_argument("approved_sessions", type=Path)
    derive.add_argument("output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("grid", type=Path)
    validate.add_argument("prepared", type=Path)
    validate.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError(f"Output already exists: {args.output}")
        prepared_bytes = args.prepared.read_bytes()
        prepared = json.loads(prepared_bytes.decode("utf-8-sig"))
        if args.command == "derive":
            manifest_bytes = args.approved_sessions.read_bytes()
            result = derive_candidates(prepared, json.loads(manifest_bytes.decode("utf-8-sig")))
            result["approved_sessions_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        else:
            grid_bytes = args.grid.read_bytes()
            result = validate_candidates(json.loads(grid_bytes.decode("utf-8-sig")), prepared)
            result["candidate_grid_sha256"] = hashlib.sha256(grid_bytes).hexdigest()
        result["prepared_input_sha256"] = hashlib.sha256(prepared_bytes).hexdigest()
        result["threshold_search_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(f"{len(result['candidates'])} candidate pairs saved to {args.output}")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
