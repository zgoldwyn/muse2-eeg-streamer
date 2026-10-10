"""Load synthetic Muse EEG sessions and divide them into fixed-time windows."""

from __future__ import annotations

import csv
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any

from .preprocessing import REQUIRED_CHANNELS


REQUIRED_CSV_COLUMNS = (
    "session_id",
    "elapsed_s",
    "channel",
    "packet_index",
    "sample_in_packet",
    "microvolts",
)
WINDOW_DURATION_S = 2.0
NOMINAL_SAMPLE_RATE_HZ = 256.0
TIMESTAMP_TOLERANCE_S = 0.0005


@dataclass(frozen=True)
class EegSample:
    """One preserved EEG CSV row after basic validation."""

    elapsed_s: float
    channel: str
    packet_index: int
    sample_in_packet: int
    microvolts: float


@dataclass(frozen=True)
class LoadedSession:
    """Validated samples and immutable metadata for one EEG session."""

    session_id: str
    sampling_rate_hz: float
    samples_per_packet: int
    samples: tuple[EegSample, ...]


@dataclass(frozen=True)
class EegWindow:
    """One fixed-time EEG window, including unusable windows and their reasons."""

    window_id: str
    session_id: str
    start_time_s: float
    end_time_s: float
    sampling_rate_hz: float
    channel_samples: Mapping[str, tuple[float, ...]]
    channel_times_s: Mapping[str, tuple[float, ...]]
    is_valid: bool
    invalid_reasons: tuple[str, ...]


def load_synthetic_session(
    csv_path: str | Path,
    metadata: Mapping[str, Any] | str | Path,
    *,
    development_session_ids: Collection[str] | None = None,
) -> LoadedSession:
    """Load one CSV session and preserve its timing without filling data gaps.

    Metadata must provide ``session_id``, ``sampling_rate_hz``, and
    ``samples_per_packet``. It may be a mapping or the path to a JSON file.
    """
    metadata_mapping = _load_metadata(metadata)
    session_id = _required_nonempty_string(metadata_mapping, "session_id")
    sampling_rate_hz = _required_finite_number(metadata_mapping, "sampling_rate_hz")
    samples_per_packet = _required_nonnegative_integer(
        metadata_mapping, "samples_per_packet", allow_zero=False
    )

    allowed_sessions = development_session_ids
    if allowed_sessions is None:
        listed_sessions = metadata_mapping.get("development_session_ids")
        if listed_sessions is not None:
            if isinstance(listed_sessions, (str, bytes)) or not isinstance(
                listed_sessions, Collection
            ):
                raise ValueError("metadata field development_session_ids must be a collection.")
            allowed_sessions = listed_sessions

    if allowed_sessions is not None and session_id not in allowed_sessions:
        raise ValueError(f"Session {session_id!r} is not in the development session list.")

    path = Path(csv_path)
    try:
        stream = path.open(newline="", encoding="utf-8")
    except OSError as error:
        raise ValueError(f"Could not read EEG CSV {path}: {error}") from error

    samples: list[EegSample] = []
    seen_positions: set[tuple[str, int, int]] = set()
    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("EEG CSV must include a header row.")
        missing_columns = [name for name in REQUIRED_CSV_COLUMNS if name not in reader.fieldnames]
        if missing_columns:
            raise ValueError(
                "EEG CSV is missing required columns: " + ", ".join(missing_columns) + "."
            )

        for row_number, row in enumerate(reader, start=2):
            row_session_id = row["session_id"]
            if row_session_id != session_id:
                raise ValueError(
                    f"Row {row_number} belongs to session {row_session_id!r}; "
                    f"expected {session_id!r}."
                )
            channel = row["channel"]
            if channel not in REQUIRED_CHANNELS:
                raise ValueError(f"Row {row_number} has unrecognized channel {channel!r}.")

            elapsed_s = _parse_finite_float(row["elapsed_s"], "elapsed_s", row_number)
            if elapsed_s < 0:
                raise ValueError(f"Row {row_number} has a negative elapsed_s value.")
            microvolts = _parse_finite_float(row["microvolts"], "microvolts", row_number)
            packet_index = _parse_nonnegative_integer(
                row["packet_index"], "packet_index", row_number
            )
            sample_in_packet = _parse_nonnegative_integer(
                row["sample_in_packet"], "sample_in_packet", row_number
            )
            if sample_in_packet >= samples_per_packet:
                raise ValueError(
                    f"Row {row_number} sample_in_packet must be smaller than "
                    f"samples_per_packet ({samples_per_packet})."
                )

            position = (channel, packet_index, sample_in_packet)
            if position in seen_positions:
                raise ValueError(
                    f"Duplicate sample for {channel} packet {packet_index}, "
                    f"sample {sample_in_packet}."
                )
            seen_positions.add(position)
            samples.append(
                EegSample(elapsed_s, channel, packet_index, sample_in_packet, microvolts)
            )

    if not samples:
        raise ValueError("EEG CSV contains no samples.")

    return LoadedSession(
        session_id=session_id,
        sampling_rate_hz=sampling_rate_hz,
        samples_per_packet=samples_per_packet,
        samples=tuple(samples),
    )


def create_fixed_windows(session: LoadedSession) -> list[EegWindow]:
    """Create two-second, non-overlapping EEG windows without repairing gaps."""
    expected_samples = int(round(session.sampling_rate_hz * WINDOW_DURATION_S))
    if abs(session.sampling_rate_hz * WINDOW_DURATION_S - expected_samples) > 1e-9:
        raise ValueError("Sampling rate does not produce a whole number of samples per window.")

    last_time = max(sample.elapsed_s for sample in session.samples)
    window_count = int(last_time // WINDOW_DURATION_S) + 1
    windows: list[EegWindow] = []
    for index in range(window_count):
        start = index * WINDOW_DURATION_S
        end = start + WINDOW_DURATION_S
        by_channel = {
            channel: [
                sample
                for sample in session.samples
                if sample.channel == channel and start <= sample.elapsed_s < end
            ]
            for channel in REQUIRED_CHANNELS
        }
        windows.append(
            _build_window(session, index, start, end, by_channel, expected_samples)
        )
    return windows


def _build_window(
    session: LoadedSession,
    index: int,
    start: float,
    end: float,
    by_channel: Mapping[str, list[EegSample]],
    expected_samples: int,
) -> EegWindow:
    reasons: list[str] = []
    ordered = {
        channel: sorted(
            samples,
            key=lambda sample: (sample.packet_index, sample.sample_in_packet, sample.elapsed_s),
        )
        for channel, samples in by_channel.items()
    }

    for channel in REQUIRED_CHANNELS:
        count = len(ordered[channel])
        if count == 0:
            reasons.append(f"required channel {channel} is missing from this window")
        elif count != expected_samples:
            reasons.append(
                f"channel {channel} has {count} samples; expected {expected_samples}"
            )

    reference = ordered[REQUIRED_CHANNELS[0]]
    reference_positions = [_position(sample, session.samples_per_packet) for sample in reference]
    if reference_positions and not _positions_are_contiguous(reference_positions):
        reasons.append("TP9 has missing packet/sample positions in this window")

    for channel in REQUIRED_CHANNELS[1:]:
        current = ordered[channel]
        positions = [_position(sample, session.samples_per_packet) for sample in current]
        if positions and not _positions_are_contiguous(positions):
            reasons.append(f"{channel} has missing packet/sample positions in this window")
        if positions != reference_positions:
            reasons.append(f"sample positions for {channel} are not aligned with TP9")
        if len(current) == len(reference):
            for position, (expected, observed) in enumerate(zip(reference, current)):
                if abs(expected.elapsed_s - observed.elapsed_s) > TIMESTAMP_TOLERANCE_S:
                    reasons.append(
                        f"timestamp for {channel} sample {position} differs from TP9 by more "
                        f"than {TIMESTAMP_TOLERANCE_S} seconds"
                    )
                    break

    return EegWindow(
        window_id=f"{session.session_id}:window-{index:06d}",
        session_id=session.session_id,
        start_time_s=start,
        end_time_s=end,
        sampling_rate_hz=session.sampling_rate_hz,
        channel_samples={
            channel: tuple(sample.microvolts for sample in ordered[channel])
            for channel in REQUIRED_CHANNELS
        },
        channel_times_s={
            channel: tuple(sample.elapsed_s for sample in ordered[channel])
            for channel in REQUIRED_CHANNELS
        },
        is_valid=not reasons,
        invalid_reasons=tuple(reasons),
    )


def _load_metadata(metadata: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(metadata, Mapping):
        return metadata
    try:
        with Path(metadata).open(encoding="utf-8") as stream:
            loaded = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read session metadata: {error}") from error
    if not isinstance(loaded, Mapping):
        raise ValueError("Session metadata must be a JSON object.")
    return loaded


def _required_nonempty_string(metadata: Mapping[str, Any], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"metadata field {name} must be a nonempty string.")
    return value


def _required_finite_number(metadata: Mapping[str, Any], name: str) -> float:
    value = metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or value <= 0:
        raise ValueError(f"metadata field {name} must be a positive finite number.")
    return float(value)


def _required_nonnegative_integer(
    metadata: Mapping[str, Any], name: str, *, allow_zero: bool
) -> int:
    value = metadata.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or (value < 0 or (not allow_zero and value == 0)):
        raise ValueError(f"metadata field {name} must be a positive integer.")
    return value


def _parse_finite_float(value: str | None, name: str, row_number: int) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"Row {row_number} has a nonnumeric {name} value.") from error
    if not isfinite(number):
        raise ValueError(f"Row {row_number} has a nonfinite {name} value.")
    return number


def _parse_nonnegative_integer(value: str | None, name: str, row_number: int) -> int:
    if value is None or not value.isdigit():
        raise ValueError(f"Row {row_number} {name} must be a nonnegative integer.")
    return int(value)


def _position(sample: EegSample, samples_per_packet: int) -> int:
    return sample.packet_index * samples_per_packet + sample.sample_in_packet


def _positions_are_contiguous(positions: list[int]) -> bool:
    return all(current == previous + 1 for previous, current in zip(positions, positions[1:]))
