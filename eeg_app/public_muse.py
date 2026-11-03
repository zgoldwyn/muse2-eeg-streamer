"""Import a small public Muse 2 EDF subset into feature-ready EEG windows.

The raw EDF recordings are local, ignored research inputs.  This module reads
only TP9, AF7, AF8, and TP10, converts MNE's EEG volts to microvolts, and uses
the matching BLP MATLAB event file only for task/rest timing markers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import h5py
import numpy as np

from .math_pipeline import extract_features_for_windows
from .preprocessing import REQUIRED_CHANNELS


PUBLIC_WINDOW_LENGTHS_S = (2.0, 4.0, 8.0)
EVENT_CODES = {
    1: "experiment_start",
    2: "task_start",
    3: "task_beep",
    4: "task_end",
    5: "experiment_end",
}


@dataclass(frozen=True)
class PublicMuseWindow:
    """One fixed EDF interval, shaped for ``extract_window_features``."""

    session_id: str
    window_id: str
    start_time_s: float
    end_time_s: float
    nominal_sample_rate_hz: float
    channel_samples: Mapping[str, Sequence[float]]
    is_valid: bool
    invalid_reasons: Sequence[str]
    participant_id: str
    weak_target: str | None
    target_provenance: Mapping[str, Any]


@dataclass(frozen=True)
class PublicMuseImport:
    """Windows plus exclusions retained for transparent reporting."""

    windows: tuple[PublicMuseWindow, ...]
    exclusions: tuple[dict[str, Any], ...]
    participant_id: str
    session_id: str
    sample_rate_hz: float


def _subject_id(path: Path) -> str:
    match = re.search(r"(sub-\d+)", path.name)
    if not match:
        raise ValueError(f"Cannot find a participant ID in {path.name!r}.")
    return match.group(1)


def _read_mat_value(file: h5py.File, reference: Any) -> Any:
    value = np.asarray(file[reference][()]).ravel()
    if value.size == 1:
        return value.item()
    if value.dtype.kind in "ui":
        return "".join(chr(int(item)) for item in value if int(item) != 0)
    return value.tolist()


def read_event_times(mat_path: str | Path) -> dict[int, float]:
    """Return first event times in seconds from a matching BLP MATLAB file.

    EEGLAB event latencies are one-based samples.  The returned times therefore
    use ``(latency - 1) / event_sample_rate``.
    """

    path = Path(mat_path)
    with h5py.File(path, "r") as file:
        try:
            data = file["data"]
            event = data["event"]
            event_rate = float(np.asarray(data["srate"][()]).item())
            code_refs = event["edftype"][()].ravel()
            latency_refs = event["latency"][()].ravel()
        except KeyError as error:
            raise ValueError(f"{path} is missing required event data: {error}.") from error

        if not isfinite(event_rate) or event_rate <= 0:
            raise ValueError(f"{path} has invalid event sample rate {event_rate!r}.")
        if len(code_refs) != len(latency_refs):
            raise ValueError(f"{path} has mismatched event code and latency arrays.")

        times: dict[int, float] = {}
        for code_ref, latency_ref in zip(code_refs, latency_refs):
            try:
                code = int(float(_read_mat_value(file, code_ref)))
                latency = float(_read_mat_value(file, latency_ref))
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path} contains an unreadable event marker.") from error
            if code not in EVENT_CODES or not isfinite(latency) or latency < 1:
                continue
            times.setdefault(code, (latency - 1.0) / event_rate)

    missing = [EVENT_CODES[code] for code in (1, 2, 4, 5) if code not in times]
    if missing:
        raise ValueError(f"{path} is missing required event marker(s): {', '.join(missing)}.")
    if not times[1] < times[2] < times[4] < times[5]:
        raise ValueError(f"{path} has non-monotonic experiment/task event times.")
    return times


def _target_for_interval(start_s: float, end_s: float, events: Mapping[int, float]) -> tuple[str | None, dict[str, Any]]:
    if events[1] <= start_s and end_s <= events[2]:
        return "rest_period", {"source": "public_event_markers", "event_codes": [1, 2]}
    if events[2] <= start_s and end_s <= events[4]:
        return "task_period", {"source": "public_event_markers", "event_codes": [2, 4]}
    if events[4] <= start_s and end_s <= events[5]:
        return "rest_period", {"source": "public_event_markers", "event_codes": [4, 5]}
    return None, {"source": "public_event_markers", "reason": "window crosses an event boundary"}


def import_public_muse_recording(
    edf_path: str | Path,
    mat_path: str | Path,
    *,
    window_length_s: float = 2.0,
) -> PublicMuseImport:
    """Read one Muse 2 EDF plus matching event file into fixed valid/invalid windows."""

    if window_length_s not in PUBLIC_WINDOW_LENGTHS_S:
        raise ValueError(f"window_length_s must be one of {PUBLIC_WINDOW_LENGTHS_S}, got {window_length_s!r}.")

    try:
        import mne
    except ImportError as error:  # pragma: no cover - installation is documented
        raise RuntimeError("MNE is required; install the project's development dependencies.") from error

    edf_path = Path(edf_path)
    participant_id = _subject_id(edf_path)
    session_id = edf_path.stem
    events = read_event_times(mat_path)
    raw = mne.io.read_raw_edf(edf_path, preload=False, verbose="ERROR")
    missing_channels = [name for name in REQUIRED_CHANNELS if name not in raw.ch_names]
    if missing_channels:
        raise ValueError(f"{edf_path} is missing required Muse channels: {', '.join(missing_channels)}.")

    sample_rate_hz = float(raw.info["sfreq"])
    if not isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError(f"{edf_path} has invalid sample rate {sample_rate_hz!r}.")
    samples_per_window = round(window_length_s * sample_rate_hz)
    if not np.isclose(samples_per_window / sample_rate_hz, window_length_s):
        raise ValueError(f"{window_length_s} seconds is not an integer number of EDF samples at {sample_rate_hz} Hz.")

    # MNE keeps EEG in SI volts.  Convert only the selected EEG signal to uV.
    signal_uv = raw.get_data(picks=list(REQUIRED_CHANNELS)) * 1_000_000.0
    if not np.isfinite(signal_uv).all():
        raise ValueError(f"{edf_path} contains nonfinite values in a required EEG channel.")

    recording_end_s = signal_uv.shape[1] / sample_rate_hz
    if events[5] > recording_end_s + (1.0 / sample_rate_hz):
        raise ValueError("Event end time is beyond the matching Muse EDF recording.")

    windows: list[PublicMuseWindow] = []
    exclusions: list[dict[str, Any]] = []
    start_s = events[1]
    index = 0
    while start_s < events[5] - 1e-9:
        end_s = start_s + window_length_s
        window_id = f"{session_id}:w{window_length_s:g}:{index:04d}"
        target, provenance = _target_for_interval(start_s, end_s, events)
        start_sample = round(start_s * sample_rate_hz)
        end_sample = start_sample + samples_per_window
        reasons: list[str] = []
        if end_s > events[5] + 1e-9:
            reasons.append("trailing partial interval after experiment end")
        if target is None:
            reasons.append("window crosses an event boundary")
        if end_sample > signal_uv.shape[1]:
            reasons.append("window extends past EDF samples")

        channel_samples = {
            channel: tuple(float(value) for value in signal_uv[position, start_sample:end_sample])
            for position, channel in enumerate(REQUIRED_CHANNELS)
        }
        if any(len(values) != samples_per_window for values in channel_samples.values()):
            reasons.append("incomplete required EEG channel samples")

        is_valid = not reasons
        window = PublicMuseWindow(
            session_id=session_id,
            window_id=window_id,
            start_time_s=start_s,
            end_time_s=end_s,
            nominal_sample_rate_hz=sample_rate_hz,
            channel_samples=channel_samples,
            is_valid=is_valid,
            invalid_reasons=tuple(reasons),
            participant_id=participant_id,
            weak_target=target if is_valid else None,
            target_provenance=provenance,
        )
        windows.append(window)
        if not is_valid:
            exclusions.append({"window_id": window_id, "reasons": reasons, "start_time_s": start_s, "end_time_s": end_s})
        start_s = end_s
        index += 1

    return PublicMuseImport(tuple(windows), tuple(exclusions), participant_id, session_id, sample_rate_hz)


def _flatten_features(value: Mapping[str, Any], prefix: str = "") -> dict[str, float | None]:
    flattened: dict[str, float | None] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            flattened.update(_flatten_features(item, name))
        elif item is None:
            flattened[name] = None
        elif isinstance(item, (int, float, np.number)) and not isinstance(item, bool):
            numeric = float(item)
            flattened[name] = numeric if isfinite(numeric) else None
    return flattened


def make_feature_records(
    imported: PublicMuseImport,
    *,
    flatline_tolerance_uv: float,
) -> list[dict[str, Any]]:
    """Use Samuel's feature adapter and attach weak targets outside the features."""

    result = extract_features_for_windows(imported.windows, flatline_tolerance_uv=flatline_tolerance_uv)
    windows_by_id = {window.window_id: window for window in imported.windows}
    records: list[dict[str, Any]] = []
    for feature_record in result["feature_records"]:
        window = windows_by_id[feature_record["window_id"]]
        if window.weak_target is None:
            raise ValueError(f"Valid feature window {window.window_id!r} has no weak target.")
        records.append({
            "window_id": window.window_id,
            "participant_id": window.participant_id,
            "session_id": window.session_id,
            "start_time_s": window.start_time_s,
            "end_time_s": window.end_time_s,
            "window_length_s": window.end_time_s - window.start_time_s,
            "sample_rate_hz": window.nominal_sample_rate_hz,
            "features": _flatten_features(feature_record.get("features", {})),
            "weak_target": window.weak_target,
            "target_provenance": dict(window.target_provenance),
        })
    return records


def write_feature_records(records: Iterable[Mapping[str, Any]], output_path: str | Path) -> None:
    """Write shareable JSON Lines records; raw EDF samples are intentionally omitted."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(dict(record), sort_keys=True) + "\n")
