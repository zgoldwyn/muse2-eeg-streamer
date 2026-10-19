"""Save EEG sample records as a session, then read the session back and check it.

A session directory holds two files:

    <sessions_dir>/<session_id>/
        eeg.csv         one decoded sample per row
        metadata.json   session information, including completion status

Status values in metadata.json:

    recording    the session is open (or the process died without cleanup)
    complete     every supplied record was saved and the writer closed normally
    interrupted  saving stopped early; rows already written are kept

Sections of this module:

    Writing      SampleRecord, SessionWriter, record_session
    Synthetic    synthetic_records, a headset-free record source
    Reading      read_session, check_session, format_report
    Demo         python3 -m eeg_app.recording

The writer only accepts ``SampleRecord`` objects. It does not know where they
come from, so the synthetic source and a future live-stream adapter can feed
it the same way.

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite, pi, sin
from numbers import Real
from pathlib import Path

from .preprocessing import REQUIRED_CHANNELS

SCHEMA_VERSION = "0.1"
EEG_FILENAME = "eeg.csv"
METADATA_FILENAME = "metadata.json"
EEG_COLUMNS = (
    "session_id",
    "elapsed_s",
    "channel",
    "packet_index",
    "sample_in_packet",
    "microvolts",
)
NOMINAL_SAMPLE_RATE_HZ = 256
SAMPLES_PER_PACKET = 12
PACKET_INDEX_MODULUS = 65536  # packet index is 16-bit, so it wraps 65535 -> 0
UNITS = "microvolts"
DEFAULT_TIMING_METHOD = "packet_index_estimate"

STATUS_RECORDING = "recording"
STATUS_COMPLETE = "complete"
STATUS_INTERRUPTED = "interrupted"

# Session IDs become folder names, so keep them to safe characters (no "/" or "..").
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# ---------------------------------------------------------------- Writing


class RecordingError(Exception):
    """Base class for errors raised while saving a session."""


class SessionExistsError(RecordingError, FileExistsError):
    """The session directory already exists. Nothing was written."""


class InvalidRecordError(RecordingError, ValueError):
    """A sample record is malformed, out of range, nonfinite, or a duplicate."""


class SessionInterruptedError(RecordingError):
    """Saving stopped before the input ended.

    The rows written before the problem are kept on disk and the session is
    marked ``interrupted`` in metadata.json. The original error is available
    as ``__cause__``.
    """

    def __init__(self, message: str, session_dir: Path, rows_written: int):
        super().__init__(message)
        self.session_dir = session_dir
        self.rows_written = rows_written


@dataclass(frozen=True)
class SampleRecord:
    """One decoded EEG sample.

    ``elapsed_s`` is the time supplied by the data source, in seconds from the
    start of the session. The writer saves it unchanged.
    """

    channel: str
    packet_index: int
    sample_in_packet: int
    microvolts: float
    elapsed_s: float


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def validate_record(record: object, channels: Sequence[str] = REQUIRED_CHANNELS) -> None:
    """Raise InvalidRecordError if one record breaks the saved-data contract."""
    if not isinstance(record, SampleRecord):
        raise InvalidRecordError(
            f"expected a SampleRecord, got {type(record).__name__}: {record!r}"
        )
    if record.channel not in channels:
        raise InvalidRecordError(
            f"unknown channel {record.channel!r}. Expected one of: {', '.join(channels)}"
        )
    if not _is_int(record.packet_index) or not 0 <= record.packet_index < PACKET_INDEX_MODULUS:
        raise InvalidRecordError(
            f"packet_index must be an integer from 0 to {PACKET_INDEX_MODULUS - 1}, "
            f"got {record.packet_index!r}"
        )
    if not _is_int(record.sample_in_packet) or not 0 <= record.sample_in_packet < SAMPLES_PER_PACKET:
        raise InvalidRecordError(
            f"sample_in_packet must be an integer from 0 to {SAMPLES_PER_PACKET - 1}, "
            f"got {record.sample_in_packet!r}"
        )
    if not _is_finite_number(record.microvolts):
        raise InvalidRecordError(
            f"microvolts must be a finite number, got {record.microvolts!r}"
        )
    if not _is_finite_number(record.elapsed_s) or record.elapsed_s < 0:
        raise InvalidRecordError(
            f"elapsed_s must be a finite number of seconds >= 0, got {record.elapsed_s!r}"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _format_number(value: float) -> str:
    # repr gives the shortest text that converts back to the exact same float,
    # so saved values and times read back identical to the input.
    return repr(float(value))


class SessionWriter:
    """Write sample records into a new session directory.

    Use it as a context manager::

        with SessionWriter("data/sessions", "demo-001") as writer:
            for record in records:
                writer.write(record)

    On a normal exit the session is marked ``complete``. If the input raises,
    or a record is rejected, the rows already written are kept, the session
    is marked ``interrupted``, and ``SessionInterruptedError`` is raised.
    ``KeyboardInterrupt`` is recorded the same way but passed through as-is.
    """

    def __init__(
        self,
        sessions_dir: str | os.PathLike[str],
        session_id: str,
        *,
        nominal_sample_rate_hz: float = NOMINAL_SAMPLE_RATE_HZ,
        channels: Sequence[str] = REQUIRED_CHANNELS,
        units: str = UNITS,
        timing_method: str = DEFAULT_TIMING_METHOD,
        data_source: str = "synthetic",
    ):
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(
                f"session_id {session_id!r} must start with a letter or digit and "
                "contain only letters, digits, '.', '_' or '-'"
            )
        self.session_id = session_id
        self.session_dir = Path(sessions_dir) / session_id
        self.channels = tuple(channels)
        self.rows_written = 0
        self._metadata = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "status": STATUS_RECORDING,
            "started_at_utc": None,
            "ended_at_utc": None,
            "nominal_sample_rate_hz": nominal_sample_rate_hz,
            "samples_per_packet": SAMPLES_PER_PACKET,
            "channels": list(self.channels),
            "units": units,
            "timing_method": timing_method,
            "data_source": data_source,
            "eeg_row_count": 0,
            "stop_reason": None,
        }
        self._file = None
        self._csv = None
        # Per channel: the current packet index and the sample positions seen in it.
        self._current_packet: dict[str, int] = {}
        self._positions_seen: dict[str, set[int]] = {}

    @property
    def metadata(self) -> dict:
        return dict(self._metadata)

    def __enter__(self) -> SessionWriter:
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self.close()
            return False
        reason = f"{exc_type.__name__}: {exc}" if str(exc) else exc_type.__name__
        self._finish(STATUS_INTERRUPTED, stop_reason=reason)
        if not isinstance(exc, Exception):
            return False  # let KeyboardInterrupt / SystemExit through unchanged
        raise SessionInterruptedError(
            f"Recording stopped: {reason}. Kept {self.rows_written} sample row(s) "
            f"already written in {self.session_dir} and marked the session "
            f"'{STATUS_INTERRUPTED}'.",
            session_dir=self.session_dir,
            rows_written=self.rows_written,
        ) from exc

    def open(self) -> None:
        """Create the session directory, the CSV header and initial metadata."""
        self.session_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.session_dir.mkdir()
        except FileExistsError:
            raise SessionExistsError(
                f"session directory already exists: {self.session_dir}. "
                "Nothing was written; choose a new session_id."
            ) from None
        self._metadata["started_at_utc"] = _utc_now()
        self._write_metadata()
        # "x" mode: never open an existing eeg.csv for writing.
        self._file = open(self.session_dir / EEG_FILENAME, "x", newline="", encoding="utf-8")
        self._csv = csv.writer(self._file)
        self._csv.writerow(EEG_COLUMNS)
        self._file.flush()

    def write(self, record: SampleRecord) -> None:
        """Validate one record and append it to eeg.csv."""
        if self._csv is None:
            raise RecordingError("session is not open; use SessionWriter as a context manager")
        validate_record(record, self.channels)
        self._check_sequence(record)
        self._csv.writerow((
            self.session_id,
            _format_number(record.elapsed_s),
            record.channel,
            record.packet_index,
            record.sample_in_packet,
            _format_number(record.microvolts),
        ))
        self._file.flush()
        self.rows_written += 1

    def write_all(self, records: Iterable[SampleRecord]) -> None:
        for record in records:
            self.write(record)

    def close(self) -> None:
        """Mark the session complete. Only call after all records are written."""
        self._finish(STATUS_COMPLETE, stop_reason=None)

    def _check_sequence(self, record: SampleRecord) -> None:
        """Reject a duplicate sample or a packet that steps backwards.

        A new packet starts whenever a channel's packet index moves forward.
        Forward jumps (gaps) are allowed and are left as missing rows. Steps
        are measured modulo 65536, so wraparound 65535 -> 0 counts as forward.
        """
        channel = record.channel
        current = self._current_packet.get(channel)
        if current is None or current != record.packet_index:
            if current is not None:
                step = (record.packet_index - current) % PACKET_INDEX_MODULUS
                if step > PACKET_INDEX_MODULUS // 2:
                    raise InvalidRecordError(
                        f"channel {channel} packet {record.packet_index} arrived after "
                        f"packet {current} (repeated or out-of-order packet)"
                    )
            self._current_packet[channel] = record.packet_index
            self._positions_seen[channel] = set()
        if record.sample_in_packet in self._positions_seen[channel]:
            raise InvalidRecordError(
                f"duplicate sample: channel={channel} packet={record.packet_index} "
                f"sample_in_packet={record.sample_in_packet} was already written"
            )
        self._positions_seen[channel].add(record.sample_in_packet)

    def _finish(self, status: str, stop_reason: str | None) -> None:
        if self._file is not None:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None
            self._csv = None
        self._metadata.update(
            status=status,
            ended_at_utc=_utc_now(),
            eeg_row_count=self.rows_written,
            stop_reason=stop_reason,
        )
        self._write_metadata()

    def _write_metadata(self) -> None:
        # Write to a temporary file, then rename over the old one, so a crash
        # never leaves a half-written metadata.json.
        path = self.session_dir / METADATA_FILENAME
        temp = path.with_name(path.name + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)


def record_session(
    records: Iterable[SampleRecord],
    sessions_dir: str | os.PathLike[str],
    session_id: str,
    **metadata_options,
) -> Path:
    """Save every record from ``records`` as a new session and return its directory.

    ``metadata_options`` are passed to ``SessionWriter`` (for example
    ``timing_method`` or ``data_source``).
    """
    with SessionWriter(sessions_dir, session_id, **metadata_options) as writer:
        writer.write_all(records)
    return writer.session_dir


# -------------------------------------------------------------- Synthetic
# The default output matches scratch/benjamin/synthetic_eeg.csv: packets 100,
# 101 and 103 (packet 102 deliberately missing) on all four channels, with a
# 10 Hz, ±20 µV sine wave and a fixed offset per channel.

DEMO_PACKETS = (100, 101, 103)
CHANNEL_OFFSETS_UV = {"TP9": 0.0, "AF7": 5.0, "AF8": -5.0, "TP10": 10.0}
SINE_HZ = 10.0
SINE_AMPLITUDE_UV = 20.0


def synthetic_records(
    packet_indices: Iterable[int] = DEMO_PACKETS,
    channels: Sequence[str] = REQUIRED_CHANNELS,
) -> Iterator[SampleRecord]:
    """Yield records packet by packet, then channel by channel, then sample.

    ``elapsed_s`` is estimated from packet timing, measured from the first
    packet (wraparound 65535 -> 0 is handled):

        elapsed_s = packets_since_first * 12/256 + sample_in_packet/256

    Leave an index out of ``packet_indices`` to create a gap.
    """
    first = None
    for packet_index in packet_indices:
        if first is None:
            first = packet_index
        packets_since_first = (packet_index - first) % PACKET_INDEX_MODULUS
        for channel in channels:
            for position in range(SAMPLES_PER_PACKET):
                elapsed_s = (packets_since_first * SAMPLES_PER_PACKET + position) / NOMINAL_SAMPLE_RATE_HZ
                value = SINE_AMPLITUDE_UV * sin(2 * pi * SINE_HZ * elapsed_s)
                yield SampleRecord(
                    channel=channel,
                    packet_index=packet_index,
                    sample_in_packet=position,
                    microvolts=round(value + CHANNEL_OFFSETS_UV.get(channel, 0.0), 2),
                    elapsed_s=elapsed_s,
                )


# ---------------------------------------------------------------- Reading
# Adapted from scratch/benjamin/read_synthetic_session.py.
#
# read_session parses the files and rejects anything malformed (missing
# columns, non-numbers, NaN or infinity, out-of-range packet or sample
# positions, unknown channels, cut-off rows).
#
# check_session then reports what the data contains: rows per channel,
# missing packets, duplicate samples, incomplete packets, ordering problems,
# whether metadata agrees with the file and, optionally, whether the saved
# records match the records that were supplied to the writer. Missing packets
# are reported but are not a problem: a gap is a real property of the
# recording. Duplicates are reported separately from gaps.

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


# ------------------------------------------------------------------- Demo
# Run from the repository root:
#
#     python3 -m eeg_app.recording
#
# By default the session is written to a temporary folder that is deleted
# afterwards. Pass --sessions-dir data/sessions to keep it (data/ is ignored
# by Git). This is a synthetic test only: no headset, Bluetooth or C scanner
# is used.


def run_demo(sessions_dir: Path, session_id: str, temporary: bool = False) -> bool:
    records = list(synthetic_records())
    session_dir = record_session(records, sessions_dir, session_id, data_source="synthetic")
    saved = read_session(session_dir)
    check = check_session(saved, expected_records=records)
    print("SYNTHETIC TEST: no headset or live data was used.")
    note = " (temporary folder, deleted after this run)" if temporary else ""
    print(f"Saved to: {session_dir}{note}")
    print(format_report(saved, check))
    return check.ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a synthetic session and check it can be read back (no headset)."
    )
    parser.add_argument("--sessions-dir", type=Path,
                        help="keep the session here instead of a temporary folder")
    parser.add_argument("--session-id", default="demo-001")
    args = parser.parse_args(argv)

    try:
        if args.sessions_dir is not None:
            ok = run_demo(args.sessions_dir, args.session_id)
        else:
            with tempfile.TemporaryDirectory() as temp:
                ok = run_demo(Path(temp), args.session_id, temporary=True)
    except RecordingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
