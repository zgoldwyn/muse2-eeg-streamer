"""Training-derived extra rules and a bounded P0005 validation comparison."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import isfinite
from numbers import Real
from pathlib import Path
from statistics import median

from .math_detector import DetectorSettings, REQUIRED_FEATURES, WindowExcluded, predict_window
from .metrics import ELIGIBLE_LABELS, evaluate_predictions
from .preprocessing import REQUIRED_CHANNELS
from .threshold_search import (
    P0005_SESSIONS, PERCENTILES, _checked_prepared, _complete_records, derive_candidates,
)
from .window_comparison import quantile


EXTRA_FEATURES = ("standard_deviation_uv", "kurtosis", "approximate_entropy")
DEFINITION_FIELDS = (
    "sample_count_per_channel", "continuous", "input_units", "flatline_tolerance_uv",
    "entropy_m", "entropy_tolerance_rule", "entropy_convention", "moment_convention",
)


def feature_definition(records):
    """Compare fixed definitions while allowing the documented adaptive entropy tolerance."""
    definitions = []
    for record in records:
        settings = record.get("settings", {})
        if any(name not in settings for name in DEFINITION_FIELDS):
            raise ValueError(f"{record['window_id']}: missing feature-definition settings")
        definition = {name: settings[name] for name in DEFINITION_FIELDS}
        if settings["entropy_tolerance_rule"] == "explicit shared tolerance":
            definition["entropy_tolerance_uv"] = settings["entropy_tolerance_uv"]
        if (settings["sample_count_per_channel"] != 512 or settings["input_units"] != "microvolts"
                or settings["continuous"] is not True):
            raise ValueError(f"{record['window_id']}: expected 512 continuous samples per channel in microvolts")
        definitions.append(definition)
    if not definitions or any(item != definitions[0] for item in definitions[1:]):
        raise ValueError("Feature definitions must agree across the prepared windows")
    return definitions[0]


def extra_values(record, feature):
    values, reasons = [], []
    units = "microvolts" if feature.endswith("_uv") else "dimensionless"
    for channel in REQUIRED_CHANNELS:
        key = f"{channel}_{feature}"
        value = record["features"].get(key)
        unavailable = record.get("unavailable_reasons", {})
        if (key in unavailable or isinstance(value, bool) or not isinstance(value, Real)
                or not isfinite(value) or (feature != "approximate_entropy" and value < 0)):
            reasons.append(f"{key}: {unavailable.get(key, 'missing or invalid value')}")
        elif record.get("units", {}).get(key) != units:
            reasons.append(f"{key}: expected {units}")
        else:
            values.append((channel, float(value)))
    if reasons:
        raise WindowExcluded(record["window_id"], reasons)
    return values


def _rank_fraction(artifacts, clean, direction):
    """Probability that an artifact is more extreme, with half credit for ties."""
    if not artifacts or not clean:
        return None
    correct = 0.0
    for artifact in artifacts:
        for baseline in clean:
            if artifact == baseline:
                correct += .5
            elif (direction == "high" and artifact > baseline) or (direction == "low" and artifact < baseline):
                correct += 1
    return correct / (len(artifacts) * len(clean))


def derive_rule_grid(prepared, approved_sessions):
    """Keep the base grid and derive three additional clean-tail rule grids."""
    base = derive_candidates(prepared, approved_sessions)
    references, features = _checked_prepared(prepared, approved_sessions)
    eligible = [row for row in references.values() if row["label"] in ELIGIBLE_LABELS]
    rows, exclusions = _complete_records(eligible, features)
    if exclusions:
        raise ValueError(f"Original-recipe training inputs unavailable: {exclusions}")
    definition = feature_definition(rows)
    original = []
    for percentile in (90, 95, 99):
        limits = {feature: quantile(
            [max(row["features"][f"{channel}_{feature}"] for channel in REQUIRED_CHANNELS) for row in rows],
            percentile / 100) for feature in REQUIRED_FEATURES}
        settings = DetectorSettings(2, **limits, selection_note=(
            f"Original recipe refit: all eligible November 8 training-window channel maxima, percentile {percentile}."
        ))
        original.append({"candidate_id": f"original-p{percentile}", "settings": settings.to_dict(),
                         "additional_rules": []})
    extra_grids = []
    for feature in EXTRA_FEATURES:
        grouped = {"clean": [], "artifact": []}
        missing = []
        for reference in eligible:
            record = features[reference["window_id"]]
            try:
                values = extra_values(record, feature)
            except WindowExcluded as error:
                missing.append({"window_id": record["window_id"], "reasons": error.reasons})
                continue
            grouped[reference["label"]].append((record["window_id"], dict(values)))
        channel_summary = {}
        for label, items in grouped.items():
            channel_summary[label] = {}
            for channel in REQUIRED_CHANNELS:
                values = [item[channel] for _, item in items]
                channel_summary[label][channel] = {
                    "count": len(values), "median": median(values) if values else None,
                    "q1": quantile(values, .25), "q3": quantile(values, .75),
                }
        evidence = {}
        for direction, aggregate in (("high", max), ("low", min)):
            clean = [aggregate(item.values()) for _, item in grouped["clean"]]
            artifacts = [aggregate(item.values()) for _, item in grouped["artifact"]]
            evidence[direction] = {
                "rank_fraction": _rank_fraction(artifacts, clean, direction),
                "clean_median": median(clean) if clean else None,
                "artifact_median": median(artifacts) if artifacts else None,
            }
        if feature == "standard_deviation_uv":
            direction = "high"
        else:
            scores = {side: item["rank_fraction"] for side, item in evidence.items()}
            direction = max(scores, key=lambda side: scores[side]) if all(v is not None for v in scores.values()) else None
            if direction and scores[direction] <= .5:
                direction = None
        rules = []
        if direction and grouped["clean"]:
            aggregate = max if direction == "high" else min
            clean = [aggregate(item.values()) for _, item in grouped["clean"]]
            for percentile in PERCENTILES:
                tail = percentile / 100 if direction == "high" else (100 - percentile) / 100
                rules.append({"feature": feature, "direction": direction,
                              "units": "microvolts" if feature.endswith("_uv") else "dimensionless",
                              "comparison": ">" if direction == "high" else "<",
                              "clean_retention_percentile": percentile,
                              "threshold": quantile(clean, tail)})
        extra_grids.append({
            "feature": feature, "direction": direction, "training_direction_evidence": evidence,
            "channel_summary": channel_summary, "input_exclusions": missing,
            "clean_window_ids": [wid for wid, _ in grouped["clean"]], "rules": rules,
        })
    return {"status": "awaiting_P0005_validation", "feature_definition": definition,
            "training_grid": base, "original_recipe_candidates": original, "extra_rule_grids": extra_grids,
            "selection_plan": {
                "objective": "Mean of artifact recall and clean retention; ties prefer higher recall, then retention.",
                "retain_extra_rule": "Require a strict validation objective improvement over the preceding rule.",
                "bounded_search": "3 original, 16 retuned, then 4 standard deviation, 4 kurtosis, and 4 entropy candidates.",
                "extension": "Kurtosis and entropy separately extend the retained standard-deviation stage.",
            }}


def predict_policy(record, policy):
    """Apply base thresholds and any extra triggers, checking every required channel."""
    result = predict_window(record, DetectorSettings.from_dict(policy["settings"]), validity_confirmed=True)
    triggers = []
    for rule in policy.get("additional_rules", []):
        feature = rule["feature"]
        if feature not in EXTRA_FEATURES or rule["comparison"] not in (">", "<"):
            raise ValueError("Unsupported extra feature or inequality")
        expected_units = "microvolts" if feature.endswith("_uv") else "dimensionless"
        threshold = rule["threshold"]
        if (rule["units"] != expected_units or isinstance(threshold, bool)
                or not isinstance(threshold, Real) or not isfinite(threshold)
                or (feature != "approximate_entropy" and threshold < 0)):
            raise ValueError("Extra rule requires a finite threshold and the feature's units")
        for channel, value in extra_values(record, feature):
            exceeds = value > threshold if rule["comparison"] == ">" else value < threshold
            if exceeds:
                triggers.append({"feature": feature, "channel": channel, "feature_key": f"{channel}_{feature}",
                                 "value": value, "threshold": threshold, "units": rule["units"],
                                 "comparison": rule["comparison"]})
    return {**result, "decision": "artifact" if result["triggers"] or triggers else "clean",
            "triggers": result["triggers"] + triggers, "additional_rules": policy.get("additional_rules", [])}


def _score(policy, references, features):
    predictions, exclusions = [], []
    for reference in references:
        if reference["label"] not in ELIGIBLE_LABELS:
            continue
        try:
            predictions.append(predict_policy(features[reference["window_id"]], policy))
        except WindowExcluded as error:
            exclusions.append({"window_id": reference["window_id"], "reasons": error.reasons})
    evaluation = None if exclusions else evaluate_predictions(references, predictions)
    return {"policy": policy, "evaluation": evaluation, "input_exclusions": exclusions}


def _objective(result):
    metrics = result["evaluation"]["metrics"]
    return (metrics["recall"]["value"] + metrics["clean_retention"]["value"]) / 2


def _best(results):
    available = [result for result in results if result["evaluation"] is not None]
    if not available:
        return None
    return max(available, key=lambda result: (
        _objective(result), result["evaluation"]["metrics"]["recall"]["value"],
        result["evaluation"]["metrics"]["clean_retention"]["value"],
    ))


def _change(result, preceding):
    if result is None:
        return None
    changes = {}
    for name in ("recall", "clean_retention", "accepted_contamination", "coverage"):
        new, old = (row["evaluation"]["metrics"][name]["value"] for row in (result, preceding))
        changes[name] = new - old if new is not None and old is not None else None
    return changes


def validate_rule_grid(grid, prepared):
    """Select each stage on P0005 and keep useful extensions for approval."""
    base = grid["training_grid"]
    references, features = _checked_prepared(prepared, dict.fromkeys(P0005_SESSIONS, "P0005"))
    if "P0005" in base["training_sessions"].values() or set(base["training_sessions"]) & set(P0005_SESSIONS):
        raise ValueError("Training and P0005 validation must be disjoint")
    eligible = [row for row in references.values() if row["label"] in ELIGIBLE_LABELS]
    if {row["label"] for row in eligible} != ELIGIBLE_LABELS:
        raise ValueError("Validation needs reviewed clean and artifact windows")
    rows, missing = _complete_records(eligible, features)
    if missing:
        raise ValueError(f"Missing/unavailable eligible validation inputs: {missing}")
    if feature_definition(rows) != grid["feature_definition"]:
        raise ValueError("Validation feature definitions differ from training")
    references = list(references.values())
    original = [_score(policy, references, features) for policy in grid["original_recipe_candidates"]]
    original_best = _best(original)
    if original_best is None:
        raise ValueError("The original recipe has no scorable validation candidate")
    retuned = [_score({**candidate, "additional_rules": []}, references, features) for candidate in base["candidates"]]
    retuned_best = _best(retuned)
    if retuned_best is None:
        raise ValueError("The retuned grid has no scorable validation candidate")
    stages = [
        {"variant": "original_recipe_refit", "candidates": original, "best": original_best},
        {"variant": "retuned", "candidates": retuned, "best": retuned_best,
         "change_from_preceding": _change(retuned_best, original_best)},
    ]
    preceding = retuned_best
    recommendations = [original_best, retuned_best]
    for extra in grid["extra_rule_grids"]:
        candidates = []
        for rule in extra["rules"]:
            parent = preceding["policy"]
            policy = {"candidate_id": f"{parent['candidate_id']}+{rule['feature']}-p{rule['clean_retention_percentile']}",
                      "settings": parent["settings"],
                      "additional_rules": parent["additional_rules"] + [rule]}
            candidates.append(_score(policy, references, features))
        best = _best(candidates)
        retain = best is not None and _objective(best) > _objective(preceding)
        stages.append({"variant": extra["feature"], "candidates": candidates, "best": best,
                       "preceding_policy": preceding["policy"]["candidate_id"],
                       "retain": retain, "change_from_preceding": _change(best, preceding)})
        if retain:
            recommendations.append(best)
        if extra["feature"] == "standard_deviation_uv" and retain:
            preceding = best
    recommendation = _best(recommendations)
    review_status = prepared.get("label_review_status", "unspecified")
    status = ("preliminary_pending_label_reconciliation" if review_status == "preliminary"
              else "awaiting_operating_point_approval")
    return {"status": status, "label_review_status": review_status, "stages": stages,
            "recommendation": recommendation, "selection_plan": grid["selection_plan"],
            "feature_definition": grid["feature_definition"],
            "training_label_releases": base["label_releases"],
            "validation_label_releases": sorted({row["label_release"] for row in references}),
            "validation_label_counts": dict(Counter(row["label"] for row in references))}


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
            result = derive_rule_grid(prepared, json.loads(manifest_bytes.decode("utf-8-sig")))
            result["approved_sessions_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        else:
            grid_bytes = args.grid.read_bytes()
            result = validate_rule_grid(json.loads(grid_bytes.decode("utf-8-sig")), prepared)
            result["candidate_grid_sha256"] = hashlib.sha256(grid_bytes).hexdigest()
        result["prepared_input_sha256"] = hashlib.sha256(prepared_bytes).hexdigest()
        result["rule_search_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        result["feature_code_sha256"] = {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("features.py", "math_pipeline.py", "math_detector.py", "threshold_search.py")
        }
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(f"{result['status']}: {args.output}")
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
