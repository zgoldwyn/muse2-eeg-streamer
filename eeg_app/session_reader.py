"""Reopen a saved session and check it, adapted from
``scratch/benjamin/read_synthetic_session.py``.

``read_session`` parses the files and rejects anything malformed (missing
columns, non-numbers, NaN or infinity, out-of-range packet or sample
positions, unknown channels).

``check_session`` then reports what the data contains: rows per channel,
missing packets, duplicate samples, incomplete packets, ordering problems,
whether metadata agrees with the file and, optionally, whether the saved
records match the records that were supplied to the writer.

Missing packets are reported but are not a problem: a gap is a real property
of the recording. Duplicates are reported separately from gaps.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .recording import (
    EEG_COLUMNS,
    EEG_FILENAME,
    METADATA_FILENAME,
    PACKET_INDEX_MODULUS,
    SAMPLES_PER_PACKET,
    InvalidRecordError,
    SampleRecord,
    validate_record,
)

_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


class SessionFormatError(ValueError):
    """A saved session file is missing or cannot be parsed."""


@dataclass
class SavedSession:
    session_dir: Path
    metadata: dict
    session_ids: set[str]
    records: list[SampleRecord]


@dataclass
class SessionCheck:
    total_rows: int = 0
    rows_per_channel: dict[str, int] = field(default_factory=dict)
    packets_per_channel: dict[str, list[int]] = field(default_factory=dict)
    # missing packet index -> channels it is missing on
    missing_packets: dict[int, list[str]] = field(default_factory=dict)
    duplicates: list[tuple[str, int, int]] = field(default_factory=list)
    incomplete_packets: list[tuple[str, int, list[int]]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _parse(text: str, convert, column: str, row_number: int):
    try:
        return convert(text)
    except (ValueError, TypeError):
        raise SessionFormatError(
            f"row {row_number}: column '{column}' has value {text!r}, "
            f"which is not a valid {convert.__name__}"
        ) from None


def read_session(session_dir: str | Path) -> SavedSession:
    """Load metadata.json and eeg.csv, validating every row."""
    session_dir = Path(session_dir)
    metadata_path = session_dir / METADATA_FILENAME
    eeg_path = session_dir / EEG_FILENAME
    for path in (metadata_path, eeg_path):
        if not path.is_file():
            raise SessionFormatError(f"file not found: {path}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SessionFormatError(f"{metadata_path} is not valid JSON: {exc}") from None
    channels = metadata.get("channels")
    if not isinstance(channels, list) or not channels:
        raise SessionFormatError(f"{metadata_path} has no 'channels' list")

    records: list[SampleRecord] = []
    session_ids: set[str] = set()
    with eeg_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SessionFormatError(f"file is empty: {eeg_path}")
        missing = [c for c in EEG_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise SessionFormatError(
                f"missing required column(s): {', '.join(missing)}. "
                f"Found: {', '.join(reader.fieldnames)}"
            )
        # Row 1 is the header, so data starts at row 2 (matches a spreadsheet view).
        for row_number, raw in enumerate(reader, start=2):
            if None in raw.values() or None in raw:
                raise SessionFormatError(
                    f"row {row_number}: expected {len(reader.fieldnames)} fields "
                    "(the row may have been cut off mid-write)"
                )
            record = SampleRecord(
                channel=raw["channel"],
                packet_index=_parse(raw["packet_index"], int, "packet_index", row_number),
                sample_in_packet=_parse(raw["sample_in_packet"], int, "sample_in_packet", row_number),
                microvolts=_parse(raw["microvolts"], float, "microvolts", row_number),
                elapsed_s=_parse(raw["elapsed_s"], float, "elapsed_s", row_number),
            )
            try:
                validate_record(record, channels)
            except InvalidRecordError as exc:
                raise SessionFormatError(f"row {row_number}: {exc}") from None
            session_ids.add(raw["session_id"])
            records.append(record)

    return SavedSession(session_dir, metadata, session_ids, records)


def _missing_between(previous: int, current: int) -> list[int] | None:
    """Packets skipped between two indices, or None for a step backwards."""
    step = (current - previous) % PACKET_INDEX_MODULUS
    if step > PACKET_INDEX_MODULUS // 2:
        return None
    return [(previous + k) % PACKET_INDEX_MODULUS for k in range(1, step)]


def check_session(
    saved: SavedSession,
    expected_records: Sequence[SampleRecord] | None = None,
) -> SessionCheck:
    """Check the contents of a saved session. See the module docstring."""
    channels = saved.metadata["channels"]
    check = SessionCheck(total_rows=len(saved.records))
    rows_per_channel = defaultdict(int)
    packets = defaultdict(list)
    positions = defaultdict(list)  # (channel, packet number in order) -> positions
    missing = defaultdict(list)

    # Walk each channel in file order. A new packet starts whenever the packet
    # index changes, so an index that comes back after wraparound is a new packet.
    for record in saved.records:
        channel = record.channel
        rows_per_channel[channel] += 1
        channel_packets = packets[channel]
        if not channel_packets or channel_packets[-1] != record.packet_index:
            if channel_packets:
                skipped = _missing_between(channel_packets[-1], record.packet_index)
                if skipped is None:
                    check.problems.append(
                        f"{channel}: packet {record.packet_index} follows packet "
                        f"{channel_packets[-1]} (repeated or out-of-order packet)"
                    )
                else:
                    for packet_index in skipped:
                        missing[packet_index].append(channel)
            channel_packets.append(record.packet_index)
        key = (channel, len(channel_packets) - 1)
        seen = positions[key]
        if record.sample_in_packet in seen:
            check.duplicates.append((channel, record.packet_index, record.sample_in_packet))
        elif seen and record.sample_in_packet < seen[-1]:
            check.problems.append(
                f"{channel}: packet {record.packet_index} sample {record.sample_in_packet} "
                f"comes after sample {seen[-1]} (samples out of order)"
            )
        seen.append(record.sample_in_packet)

    for (channel, packet_number), seen in positions.items():
        absent = sorted(set(range(SAMPLES_PER_PACKET)) - set(seen))
        if absent:
            check.incomplete_packets.append((channel, packets[channel][packet_number], absent))

    check.rows_per_channel = {c: rows_per_channel[c] for c in channels}
    check.packets_per_channel = {c: packets[c] for c in channels}
    check.missing_packets = dict(sorted(missing.items()))

    for channel, packet_index, position in check.duplicates:
        check.problems.append(
            f"duplicate sample: channel={channel} packet={packet_index} "
            f"sample_in_packet={position}"
        )
    for channel, packet_index, absent in check.incomplete_packets:
        check.problems.append(
            f"incomplete packet: channel={channel} packet={packet_index} "
            f"is missing sample position(s) {', '.join(map(str, absent))}"
        )
    check.problems.extend(_metadata_problems(saved))
    if expected_records is not None:
        check.problems.extend(_comparison_problems(saved.records, list(expected_records), channels))
    return check


def _metadata_problems(saved: SavedSession) -> list[str]:
    metadata = saved.metadata
    problems = []
    if saved.session_ids and saved.session_ids != {metadata.get("session_id")}:
        problems.append(
            f"metadata session_id {metadata.get('session_id')!r} does not match "
            f"eeg.csv session_id(s) {', '.join(sorted(saved.session_ids))}"
        )
    if metadata.get("session_id") != saved.session_dir.name:
        problems.append(
            f"metadata session_id {metadata.get('session_id')!r} does not match "
            f"folder name {saved.session_dir.name!r}"
        )
    if metadata.get("eeg_row_count") != len(saved.records):
        problems.append(
            f"metadata eeg_row_count is {metadata.get('eeg_row_count')}, "
            f"but eeg.csv has {len(saved.records)} sample rows"
        )
    if metadata.get("status") != "complete":
        problems.append(
            f"session status is {metadata.get('status')!r}, not 'complete'"
            + (f" (stop reason: {metadata['stop_reason']})" if metadata.get("stop_reason") else "")
        )
    return problems


def _comparison_problems(
    saved: list[SampleRecord], expected: list[SampleRecord], channels: Sequence[str]
) -> list[str]:
    if saved == expected:
        return []
    problems = []
    if len(saved) != len(expected):
        problems.append(f"saved {len(saved)} rows but {len(expected)} records were supplied")
    for channel in channels:
        saved_channel = [r for r in saved if r.channel == channel]
        expected_channel = [r for r in expected if r.channel == channel]
        for position, (got, want) in enumerate(zip(saved_channel, expected_channel)):
            if got != want:
                problems.append(
                    f"{channel} sample #{position} differs from input: saved {got}, supplied {want}"
                )
                break
    if not problems:
        problems.append("saved rows contain the supplied records, but in a different order across channels")
    return problems


def format_report(saved: SavedSession, check: SessionCheck) -> str:
    """A short human-readable summary of a check."""
    channels = saved.metadata["channels"]
    lines = [
        f"Session:  {saved.metadata.get('session_id')} "
        f"(status: {saved.metadata.get('status')}, source: {saved.metadata.get('data_source')})",
        f"{check.total_rows} sample rows total",
    ]
    counts = set(check.rows_per_channel.values())
    if len(counts) == 1:
        lines.append(f"{counts.pop()} sample rows per channel")
    else:
        lines.append("Sample rows per channel: " + ", ".join(
            f"{c} {n}" for c, n in check.rows_per_channel.items()))
    for packet_index, missing_on in check.missing_packets.items():
        if len(missing_on) == len(channels):
            where = f"all {_NUMBER_WORDS.get(len(channels), len(channels))} channels"
        else:
            where = ", ".join(missing_on)
        lines.append(f"Packet {packet_index} missing on {where}")
    if not check.missing_packets:
        lines.append("No missing packets")
    lines.append(f"Duplicate samples: {len(check.duplicates)}")
    if check.ok:
        lines.append("Read-back check: PASSED")
    else:
        lines.append(f"Read-back check: FAILED ({len(check.problems)} problem(s))")
        lines.extend(f"  - {problem}" for problem in check.problems)
    return "\n".join(lines)
