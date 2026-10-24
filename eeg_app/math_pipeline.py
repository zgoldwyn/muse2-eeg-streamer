"""Extract window features and optionally produce illustrative demo predictions."""

from collections.abc import Iterable, Mapping, Sequence
from math import isfinite
from numbers import Real
from typing import Protocol

from .features import calculate_window_features
from .preprocessing import REQUIRED_CHANNELS


DEMO_PEAK_TO_PEAK_THRESHOLD_UV = 100.0


class WindowRecord(Protocol):
    """Fields read from Namit's EegWindow (dataset.py, PR #12).

    Structural typing keeps this adapter usable before that PR is merged.
    No conversion of an actual EegWindow is needed. The loader remains
    responsible for time-grid, packet continuity, and channel alignment checks.
    """

    session_id: str
    window_id: str
    start_time_s: float
    end_time_s: float
    nominal_sample_rate_hz: float
    channel_samples: Mapping[str, Sequence[float]]
    is_valid: bool
    invalid_reasons: Sequence[str]


def extract_window_features(
    window: WindowRecord, *, flatline_tolerance_uv: float,
    entropy_m: int = 2, entropy_tolerance_uv: float | None = None,
) -> dict[str, object]:
    """Return one feature record for one valid, continuous four-channel window.

    Read attributes using EegWindow's exact field names. Invalid windows raise
    ValueError before feature calculation. A true validity flag is an upstream
    guarantee of continuity, not an artifact label; this adapter does not
    independently reconstruct packet timing. Channel shape and finite samples
    are checked again by the existing feature functions. Inputs are not changed.

    IDs and timing remain outside ``features``. All six features are calculated
    separately for each channel. Unavailable values remain None, with reasons;
    settings preserve the actual per-channel entropy tolerances and conventions.
    Flatline tolerance must be chosen explicitly, in microvolts.
    """
    if window.is_valid is not True or window.invalid_reasons:
        raise ValueError(
            f"Window {window.window_id!r} is invalid: {window.invalid_reasons!r}."
        )

    for name in ("session_id", "window_id"):
        value = getattr(window, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string.")
    for name in ("start_time_s", "end_time_s", "nominal_sample_rate_hz"):
        value = getattr(window, name)
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            raise ValueError(f"{name} must be a finite number.")
    if window.start_time_s < 0 or window.end_time_s <= window.start_time_s:
        raise ValueError("Window times must satisfy 0 <= start_time_s < end_time_s.")
    if window.nominal_sample_rate_hz <= 0:
        raise ValueError("nominal_sample_rate_hz must be positive.")

    result = calculate_window_features(
        window.channel_samples,
        continuous=True,
        flatline_tolerance_uv=flatline_tolerance_uv,
        entropy_m=entropy_m,
        entropy_tolerance_uv=entropy_tolerance_uv,
    )
    units = {
        key: "microvolts" if key.endswith("_uv") else "dimensionless"
        for key in result["features"]
    }
    return {
        "session_id": window.session_id,
        "window_id": window.window_id,
        "start_time_s": window.start_time_s,
        "end_time_s": window.end_time_s,
        "nominal_sample_rate_hz": window.nominal_sample_rate_hz,
        **result,
        "units": units,
    }


def extract_features_for_windows(
    windows: Iterable[WindowRecord], *, flatline_tolerance_uv: float,
    entropy_m: int = 2, entropy_tolerance_uv: float | None = None,
) -> dict[str, object]:
    """Extract only valid windows and retain invalid IDs, times, and reasons.

    Never concatenate windows, fill gaps, or modify sample arrays. Calculation
    errors in valid windows propagate instead of being reported as exclusions.
    """
    records = []
    skipped = []
    for window in windows:
        if window.is_valid is not True or window.invalid_reasons:
            skipped.append({
                "session_id": window.session_id,
                "window_id": window.window_id,
                "start_time_s": window.start_time_s,
                "end_time_s": window.end_time_s,
                "invalid_reasons": list(window.invalid_reasons) or [
                    "Window was not explicitly marked valid by the loader."
                ],
            })
            continue
        records.append(extract_window_features(
            window, flatline_tolerance_uv=flatline_tolerance_uv,
            entropy_m=entropy_m, entropy_tolerance_uv=entropy_tolerance_uv,
        ))
    return {
        "feature_records": records,
        "skipped_windows": skipped,
        "summary": {
            "total_windows": len(records) + len(skipped),
            "valid_windows_processed": len(records),
            "invalid_windows_skipped": len(skipped),
        },
    }


def demo_peak_to_peak_prediction(feature_record: Mapping[str, object]) -> dict[str, str]:
    """Predict artifact if any channel's peak-to-peak value exceeds 100 uV.

    This fixed threshold is an illustrative fixture rule, not a validated
    research threshold. Only use records extracted from valid windows. No
    reference labels are read. All four peak-to-peak values must be available,
    finite, nonnegative, and in microvolts, even if another channel exceeds the
    threshold. Missing required values raise ValueError rather than imply clean.
    Other features are not used by this rule and may be unavailable.

    Return exactly the window_id/decision schema accepted by metrics.py.
    """
    window_id = feature_record.get("window_id")
    if not isinstance(window_id, str) or not window_id.strip():
        raise ValueError("Demo prediction requires a nonempty window_id.")
    features = feature_record.get("features")
    units = feature_record.get("units")
    reasons = feature_record.get("unavailable_reasons", {})
    if not all(isinstance(value, Mapping) for value in (features, units, reasons)):
        raise ValueError(f"Window {window_id!r}: features, units, and reasons must be mappings.")

    values = []
    for channel in REQUIRED_CHANNELS:
        key = f"{channel}_peak_to_peak_uv"
        value = features.get(key)
        if (key in reasons or isinstance(value, bool) or not isinstance(value, Real)
                or not isfinite(value) or value < 0):
            reason = reasons.get(key, "Required value is missing or is not finite and nonnegative.")
            raise ValueError(f"Window {window_id!r}: cannot predict without {key}: {reason}")
        if units.get(key) != "microvolts":
            raise ValueError(f"Window {window_id!r}: {key} must have microvolts units.")
        values.append(value)

    return {
        "window_id": window_id,
        "decision": (
            "artifact" if any(value > DEMO_PEAK_TO_PEAK_THRESHOLD_UV for value in values)
            else "clean"
        ),
    }


def main():
    """Run the saved-session handoff when Namit's dataset module is available."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--flatline-tolerance-uv", type=float, required=True)
    parser.add_argument("--demo-predictions", action="store_true",
                        help="Use the illustrative, unvalidated >100 microvolt rule.")
    parser.add_argument("--reference-labels", type=Path,
                        help="Existing predeclared JSON reference records for metrics evaluation.")
    args = parser.parse_args()
    if args.reference_labels and not args.demo_predictions:
        parser.error("--reference-labels requires --demo-predictions.")
    references = None
    if args.reference_labels:
        try:
            references = json.loads(args.reference_labels.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            parser.error(f"Cannot read reference labels: {error}")
    try:
        from .dataset import create_fixed_windows, load_synthetic_session
    except ModuleNotFoundError as error:
        if error.name != "eeg_app.dataset":
            raise
        parser.error("Requires eeg_app.dataset from Namit's PR #12; see docs/math-pipeline.md.")

    session = load_synthetic_session(
        args.session_dir / "eeg.csv", args.session_dir / "metadata.json",
    )
    result = extract_features_for_windows(
        create_fixed_windows(session), flatline_tolerance_uv=args.flatline_tolerance_uv,
    )
    summary = result["summary"]
    print(f"{summary['total_windows']} total windows")
    print(f"{summary['valid_windows_processed']} valid windows passed to feature extraction")
    skipped = summary["invalid_windows_skipped"]
    print(f"{skipped} invalid window{'s' if skipped != 1 else ''} skipped")
    for window in result["skipped_windows"]:
        print(f"Skipped {window['window_id']}: " + "; ".join(window["invalid_reasons"]))
    if args.demo_predictions:
        try:
            predictions = [demo_peak_to_peak_prediction(record)
                           for record in result["feature_records"]]
        except ValueError as error:
            parser.error(str(error))
        print("Demo rule: peak-to-peak >100 microvolts on any channel; not validated.")
        print("Prediction records: " + json.dumps(predictions))
        if references is None:
            print("Reference-label evaluation: NOT RUN (predeclared labels not supplied).")
        else:
            from .metrics import evaluate_predictions
            try:
                evaluation = evaluate_predictions(references, predictions)
            except ValueError as error:
                parser.error(f"Reference-label evaluation failed: {error}")
            print("Reference-label evaluation: " + json.dumps(evaluation, sort_keys=True))


if __name__ == "__main__":
    main()
