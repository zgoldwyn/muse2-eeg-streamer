"""Describe Namit's existing feature exports without re-windowing or relabeling."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median, quantiles


CHANNELS = ("TP9", "AF7", "AF8", "TP10")
FEATURES = ("peak_to_peak_uv", "max_adjacent_jump_uv", "flatline_fraction",
            "standard_deviation_uv", "kurtosis", "approximate_entropy")
FEATURE_KEYS = {f"{channel}_{name}" for channel in CHANNELS for name in FEATURES}
TARGETS = ("rest_period", "task_period")


def summarize(records):
    groups = defaultdict(list)
    ids = set()
    participants = defaultdict(set)
    for row in records:
        window_id = row["window_id"]
        if not isinstance(window_id, str) or not window_id or window_id in ids:
            raise ValueError(f"Missing or duplicate window ID: {window_id!r}")
        ids.add(window_id)
        duration = float(row["window_length_s"])
        length = next((n for n in (2, 4, 8) if math.isclose(duration, n)), None)
        if length is None or not math.isclose(row["end_time_s"] - row["start_time_s"], length):
            raise ValueError(f"{window_id}: inconsistent or unsupported window duration")
        target = row["weak_target"]
        if target not in TARGETS:
            raise ValueError(f"{window_id}: unsupported weak target {target!r}")
        values = row["features"]
        if set(values) != FEATURE_KEYS:
            raise ValueError(f"{window_id}: expected Namit's exact 24 feature keys")
        for key, value in values.items():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError(f"{window_id}: invalid feature value for {key}")
        participants[length].add(row["participant_id"])
        groups[length, target].append(row)
    if not ids:
        raise ValueError("No public feature records supplied")
    report = {"interpretation": "Descriptive task/rest proxy groups, not artifact labels.",
              "participant_ids_by_length": {n: sorted(people) for n, people in participants.items()},
              "groups": []}
    for length in sorted(participants):
        for target in TARGETS:
            rows = groups[length, target]
            features = {}
            for channel in CHANNELS:
                for name in FEATURES:
                    key = f"{channel}_{name}"
                    available = sorted((r["features"][key], r["window_id"]) for r in rows
                                       if r["features"][key] is not None)
                    numbers = [value for value, _ in available]
                    q1, _, q3 = quantiles(numbers, n=4, method="inclusive") if len(numbers) >= 4 else (None,) * 3
                    outliers = [] if q1 is None else [
                        {"value": value, "window_id": wid}
                        for value, wid in available
                        if value < q1 - 1.5 * (q3 - q1) or value > q3 + 1.5 * (q3 - q1)
                    ]
                    features[key] = {
                        "available": len(numbers), "missing": len(rows) - len(numbers),
                        "median": median(numbers) if numbers else None, "q1": q1, "q3": q3,
                        "minimum": dict(zip(("value", "window_id"), available[0])) if available else None,
                        "maximum": dict(zip(("value", "window_id"), available[-1])) if available else None,
                        "descriptive_outliers": len(outliers),
                        "outlier_examples": outliers[:2] + outliers[max(2, len(outliers) - 2):],
                    }
            report["groups"].append({"window_length_s": length, "weak_target": target,
                                     "windows": len(rows), "features": features})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        records = [json.loads(line) for path in args.exports
                   for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(json.dumps(summarize(records), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
