"""Save EEG sample records into a new session directory.

A session directory holds two files:

    <sessions_dir>/<session_id>/
        eeg.csv         one decoded sample per row
        metadata.json   session information, including completion status

The writer only accepts ``SampleRecord`` objects. It does not know where they
come from, so a synthetic generator (``eeg_app.synthetic``) and a future
live-stream adapter can feed it the same way.

Status values in metadata.json:

    recording    the session is open (or the process died without cleanup)
    complete     every supplied record was saved and the writer closed normally
    interrupted  saving stopped early; rows already written are kept

Uses only the Python standard library.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
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
SAMPLE_RATE_HZ = 256
SAMPLES_PER_PACKET = 12
PACKET_INDEX_MODULUS = 65536  # packet index is 16-bit, so it wraps 65535 -> 0
UNITS = "microvolts"
DEFAULT_TIMING_METHOD = "packet_index_estimate"

STATUS_RECORDING = "recording"
STATUS_COMPLETE = "complete"
STATUS_INTERRUPTED = "interrupted"

# Session IDs become folder names, so keep them to safe characters (no "/" or "..").
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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
        sample_rate_hz: float = SAMPLE_RATE_HZ,
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
            "sample_rate_hz": sample_rate_hz,
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
