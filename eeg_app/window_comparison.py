"""Continuity guards and descriptive training-only window-length comparisons."""

from collections import defaultdict
from dataclasses import replace
from math import isclose, isfinite
from statistics import median

from .preprocessing import REQUIRED_CHANNELS


def annotated_gaps(annotations):
    """Read explicit gap markers, not task prompts or inferred artifact labels.

    Input uses MNE's onset/duration/description fields, in recording seconds.
    A zero-duration discontinuity excludes only a window straddling that point.
    """
    gaps = []
    for annotation in annotations:
        description = str(annotation["description"])
        name = description.lower().replace("_", " ")
        if any(word in name for word in ("gap", "discontinu", "acq skip", "bad boundary", "edge boundary")):
            start, duration = float(annotation["onset"]), float(annotation["duration"])
            if not isfinite(start) or not isfinite(duration) or start < 0 or duration < 0:
                raise ValueError("Malformed recording-gap annotation")
            gaps.append((start, start + duration, description))
    return gaps


def guard_window(window, gaps):
    """Retain IDs/times; exclude incomplete arrays or known gap intersections."""
    reasons = list(window.invalid_reasons)
    expected = round((window.end_time_s - window.start_time_s) * window.nominal_sample_rate_hz)
    if set(window.channel_samples) != set(REQUIRED_CHANNELS):
        reasons.append("window must contain exactly the four required Muse channels")
    for channel in REQUIRED_CHANNELS:
        values = window.channel_samples.get(channel, ())
        if len(values) != expected or any(not isfinite(value) for value in values):
            reasons.append(f"{channel}: incomplete or nonfinite samples; expected {expected}")
    for start, end, description in gaps:
        overlaps = (window.start_time_s < end and start < window.end_time_s
                    if end > start else window.start_time_s < start < window.end_time_s)
        if overlaps:
            reasons.append(f"recording gap [{start:g}, {end:g}): {description}")
    if not window.is_valid and not reasons:
        reasons.append("loader did not mark window valid")
    return replace(window, is_valid=not reasons, invalid_reasons=tuple(reasons))


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (position - left) * (ordered[right] - ordered[left])


def training_stability(records, training_participants):
    """Within participant/period/channel dispersion, never heldout selection.

    Relative IQR and adjacent changes are descriptive, not estimator accuracy.
    Adjacent changes cannot cross an exclusion, session, or period boundary.
    """
    groups = defaultdict(list)
    for record in records:
        if record["participant_id"] in training_participants:
            groups[(record["participant_id"], record["session_id"], record["weak_target"])].append(record)
    details = []
    for (participant, session, target), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda row: row["start_time_s"])
        for key in sorted(rows[0]["features"]):
            values = [row["features"][key] for row in rows if row["features"][key] is not None]
            if not values:
                continue
            center = median(values)
            iqr = quantile(values, .75) - quantile(values, .25)
            changes = [abs(right["features"][key] - left["features"][key])
                       for left, right in zip(rows, rows[1:])
                       if isclose(left["end_time_s"], right["start_time_s"], abs_tol=1e-9)
                       and left["features"][key] is not None and right["features"][key] is not None]
            details.append({"participant_id": participant, "session_id": session, "weak_target": target,
                            "feature_key": key, "n": len(values), "median": center, "iqr": iqr,
                            "relative_iqr": iqr / abs(center) if center else None,
                            "adjacent_pairs": len(changes),
                            "median_adjacent_change": median(changes) if changes else None})
    summary = []
    for feature in sorted({row["feature_key"].split("_", 1)[1] for row in details}):
        rows = [row for row in details if row["feature_key"].split("_", 1)[1] == feature]
        item = {"feature": feature, "participant_period_channel_groups": len(rows)}
        for statistic in ("median", "iqr", "relative_iqr", "median_adjacent_change"):
            values = [row[statistic] for row in rows if row[statistic] is not None]
            item["median_group_" + statistic] = median(values) if values else None
        summary.append(item)
    return {"summary": summary, "groups": details}
