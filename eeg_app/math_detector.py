"""Configurable, explainable mathematical proposals from valid feature records."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import json
from math import isclose, isfinite
from numbers import Real
from pathlib import Path

from .preprocessing import REQUIRED_CHANNELS


RULE = "peak_to_peak_or_adjacent_jump"
REQUIRED_FEATURES = ("peak_to_peak_uv", "max_adjacent_jump_uv")


def _finite_nonnegative(value):
    return (not isinstance(value, bool) and isinstance(value, Real)
            and isfinite(value) and value >= 0)


@dataclass(frozen=True)
class DetectorSettings:
    """Required limits in microvolts; no calibrated or implicit defaults.

    The selection note records how the caller selected the limits. Public
    task/rest exploration can only justify provisional development settings.
    """

    window_length_s: float
    peak_to_peak_uv: float
    max_adjacent_jump_uv: float
    selection_note: str

    def __post_init__(self):
        if not _finite_nonnegative(self.window_length_s) or self.window_length_s not in (2, 4, 8):
            raise ValueError("window_length_s must be 2, 4, or 8 seconds.")
        for name in REQUIRED_FEATURES:
            if not _finite_nonnegative(getattr(self, name)):
                raise ValueError(f"{name} threshold must be finite and nonnegative, in microvolts.")
        if not isinstance(self.selection_note, str) or not self.selection_note.strip():
            raise ValueError("selection_note must explain where the threshold values came from.")
        for name in ("window_length_s", *REQUIRED_FEATURES):
            object.__setattr__(self, name, float(getattr(self, name)))

    def to_dict(self):
        return {"rule": RULE, "status": "provisional_development",
                "channel_combination": "any_channel_any_feature", "comparison": ">",
                **asdict(self)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("Detector settings must be a JSON object.")
        expected = {"rule", "status", "channel_combination", "comparison",
                    "window_length_s", *REQUIRED_FEATURES, "selection_note"}
        if set(value) != expected:
            raise ValueError("Detector settings have missing or unsupported fields.")
        for name, required in (("rule", RULE), ("status", "provisional_development"),
                               ("channel_combination", "any_channel_any_feature"), ("comparison", ">")):
            if value[name] != required:
                raise ValueError(f"Unsupported detector setting {name}: {value[name]!r}.")
        return cls(**{name: value[name] for name in
                      ("window_length_s", *REQUIRED_FEATURES, "selection_note")})


class WindowExcluded(ValueError):
    """An invalid/incomplete record cannot receive a binary decision."""

    def __init__(self, window_id, reasons):
        self.reasons = list(reasons)
        super().__init__(f"Window {window_id!r} excluded: " + "; ".join(self.reasons))


def _window_id(record):
    if not isinstance(record, Mapping):
        raise ValueError("Feature records must be mappings.")
    value = record.get("window_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Feature record needs a nonempty window_id.")
    return value


def predict_window(record, settings: DetectorSettings, *, validity_confirmed=False):
    """Return ID, proposed binary decision, all triggers, and the exact settings.

    Accepts Namit's flattened feature records without renaming fields. For
    exports lacking a validity flag, the caller must explicitly confirm that
    the records came from a loader that already excluded gaps/invalid windows.
    An explicit invalid flag or reason always overrides that confirmation.
    Features alone cannot establish continuity or detect missing raw samples.

    All eight required channel-feature values are checked before deciding,
    including when a different feature already exceeds its limit. Missing
    required values never imply clean. Unused features may be unavailable.
    """
    window_id = _window_id(record)
    if not isinstance(settings, DetectorSettings):
        raise TypeError("settings must be DetectorSettings.")
    reasons = []
    invalid_reasons = record.get("invalid_reasons", ())
    if invalid_reasons:
        if isinstance(invalid_reasons, (list, tuple)):
            reasons.extend(str(reason) for reason in invalid_reasons)
        else:
            reasons.append(str(invalid_reasons))
    if "is_valid" in record:
        if record["is_valid"] is not True:
            reasons.append("Loader did not mark the window valid.")
    elif validity_confirmed is not True:
        reasons.append("Validity is unknown; confirm upstream gap/continuity checks before prediction.")
    if reasons:
        raise WindowExcluded(window_id, reasons)

    # Support both Namit's JSONL metadata and the existing sample adapter output.
    duration = record.get("window_length_s")
    if "start_time_s" in record and "end_time_s" in record:
        start, end = record["start_time_s"], record["end_time_s"]
        if not _finite_nonnegative(start) or not _finite_nonnegative(end) or end <= start:
            reasons.append("Invalid window start/end times.")
        else:
            interval = end - start
            if duration is None:
                duration = interval
            elif not _finite_nonnegative(duration) or not isclose(duration, interval, rel_tol=0, abs_tol=1e-9):
                reasons.append("Window duration disagrees with start/end times.")
    if not _finite_nonnegative(duration) or not isclose(duration, settings.window_length_s, rel_tol=0, abs_tol=1e-9):
        reasons.append("Window length does not match the saved detector settings.")

    features = record.get("features")
    unavailable = record.get("unavailable_reasons", {})
    units = record.get("units")
    if not isinstance(features, Mapping) or not isinstance(unavailable, Mapping):
        reasons.append("features and unavailable_reasons must be mappings.")
    if units is not None and not isinstance(units, Mapping):
        reasons.append("units must be a mapping when supplied.")
    if reasons:
        raise WindowExcluded(window_id, reasons)

    checked = []
    for channel in REQUIRED_CHANNELS:
        for feature in REQUIRED_FEATURES:
            key = f"{channel}_{feature}"
            value = features.get(key)
            if key in unavailable or not _finite_nonnegative(value):
                reason = unavailable.get(key, "missing, nonfinite, negative, or nonnumeric value")
                reasons.append(f"{key}: {reason}")
            elif units is not None and units.get(key) != "microvolts":
                reasons.append(f"{key}: units must be microvolts.")
            else:
                checked.append((channel, feature, key, float(value)))
    if reasons:
        raise WindowExcluded(window_id, reasons)

    triggers = [
        {"channel": channel, "feature": feature, "feature_key": key,
         "value_uv": value, "threshold_uv": getattr(settings, feature), "comparison": ">"}
        for channel, feature, key, value in checked if value > getattr(settings, feature)
    ]
    return {"window_id": window_id, "decision": "artifact" if triggers else "clean",
            "triggers": triggers, "settings": settings.to_dict()}


def predict_records(records: Iterable[Mapping], settings: DetectorSettings, *, validity_confirmed=False):
    """Keep exclusions separate and never give them a clean/artifact prediction."""
    if not isinstance(settings, DetectorSettings):
        raise TypeError("settings must be DetectorSettings.")
    predictions, excluded, seen = [], [], set()
    for record in records:
        window_id = _window_id(record)
        if window_id in seen:
            raise ValueError(f"Duplicate window_id: {window_id!r}.")
        seen.add(window_id)
        try:
            predictions.append(predict_window(record, settings, validity_confirmed=validity_confirmed))
        except WindowExcluded as error:
            excluded.append({"window_id": window_id, "reasons": error.reasons})
    return {"prediction_records": predictions, "excluded_windows": excluded,
            "settings": settings.to_dict(),
            "summary": {"total_records": len(seen), "predicted": len(predictions), "excluded": len(excluded)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, help="Existing valid-window feature JSONL.")
    parser.add_argument("--settings", type=Path, required=True, help="Saved DetectorSettings JSON.")
    parser.add_argument("--valid-windows-confirmed", action="store_true",
                        help="Confirm upstream validation for an export without is_valid flags.")
    parser.add_argument("--output", type=Path, required=True, help="New local JSON result file.")
    args = parser.parse_args()
    try:
        settings = DetectorSettings.from_dict(json.loads(args.settings.read_text(encoding="utf-8-sig")))
        records = [json.loads(line) for line in args.records.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip()]
        result = predict_records(records, settings, validity_confirmed=args.valid_windows_confirmed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
        print(json.dumps(result["summary"]))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
