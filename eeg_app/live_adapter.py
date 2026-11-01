"""Convert complete Muse ``EEG_PACKET`` lines into saved EEG sample records.

``elapsed_s`` is derived from Muse packet indices and the nominal 256 Hz sample
grid.  ``receipt_monotonic_ns`` is deliberately kept in a separate sidecar file:
it records packet arrival on the scanner computer's monotonic clock and is not an
EEG sample timestamp.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from .dataset import create_fixed_windows, load_synthetic_session
from .preprocessing import REQUIRED_CHANNELS
from .recording import (
    NOMINAL_SAMPLE_RATE_HZ,
    PACKET_INDEX_MODULUS,
    SAMPLES_PER_PACKET,
    SampleRecord,
    SessionWriter,
)


PACKET_PREFIX = "EEG_PACKET"
PACKET_RECEIPTS_FILENAME = "packet_receipts.csv"
PACKET_RECEIPT_COLUMNS = (
    "session_id",
    "channel",
    "packet_index",
    "receipt_monotonic_ns",
)
_MAX_FORWARD_PACKETS = PACKET_INDEX_MODULUS // 2


class LiveAdapterError(ValueError):
    """Base class for malformed or unusable live packet input."""


class PacketFormatError(LiveAdapterError):
    """A line is not one complete agreed ``EEG_PACKET`` record."""


class DuplicatePacketError(LiveAdapterError):
    """The same channel and packet index appeared twice in one short capture."""


class StreamAlignmentError(LiveAdapterError):
    """A packet would place samples before the shared session origin."""


@dataclass(frozen=True)
class EegPacket:
    """One parsed 12-sample packet from Ben's scanner output."""

    channel: str
    packet_index: int
    receipt_monotonic_ns: int
    microvolts: tuple[float, ...]


@dataclass(frozen=True)
class PacketBatch:
    """One accepted packet and its twelve derived, savable sample records."""

    packet: EegPacket
    records: tuple[SampleRecord, ...]


def parse_eeg_packet_line(line: str) -> EegPacket:
    """Parse exactly one ``EEG_PACKET`` line with 12 finite microvolt values."""
    if not isinstance(line, str):
        raise PacketFormatError("EEG_PACKET input must be text.")

    fields = line.rstrip("\r\n").split(",")
    if len(fields) != 16 or fields[0] != PACKET_PREFIX:
        raise PacketFormatError(
            "Expected exactly 16 comma-separated fields beginning with 'EEG_PACKET,'."
        )
    if any(field != field.strip() or not field for field in fields):
        raise PacketFormatError("EEG_PACKET fields must be nonempty and contain no padding.")

    channel = fields[1]
    if channel not in REQUIRED_CHANNELS:
        raise PacketFormatError(
            f"Unknown EEG_PACKET channel {channel!r}; expected one of {', '.join(REQUIRED_CHANNELS)}."
        )
    packet_index = _parse_unsigned_integer(fields[2], "packet_index", PACKET_INDEX_MODULUS)
    receipt_monotonic_ns = _parse_nonnegative_integer(fields[3], "receipt_monotonic_ns")

    values = tuple(_parse_microvolts(value, position) for position, value in enumerate(fields[4:]))
    return EegPacket(channel, packet_index, receipt_monotonic_ns, values)


class LivePacketAdapter:
    """Assign a shared packet-index origin and expand packets without repairing gaps."""

    def __init__(self) -> None:
        self._first_packet_index: int | None = None
        self._seen_packets: set[tuple[str, int]] = set()

    @property
    def first_packet_index(self) -> int | None:
        """The original index of the first accepted packet in this capture."""
        return self._first_packet_index

    def accept_line(self, line: str) -> PacketBatch:
        """Parse one line and return its twelve records using the shared origin."""
        return self.accept_packet(parse_eeg_packet_line(line))

    def accept_packet(self, packet: EegPacket) -> PacketBatch:
        """Expand one packet; missing packets remain absent and are never synthesized."""
        key = (packet.channel, packet.packet_index)
        if key in self._seen_packets:
            raise DuplicatePacketError(
                f"Duplicate EEG_PACKET for {packet.channel} packet {packet.packet_index}."
            )
        if self._first_packet_index is None:
            self._first_packet_index = packet.packet_index

        packets_since_first = (packet.packet_index - self._first_packet_index) % PACKET_INDEX_MODULUS
        if packets_since_first >= _MAX_FORWARD_PACKETS:
            raise StreamAlignmentError(
                f"Packet {packet.packet_index} cannot align after shared origin "
                f"{self._first_packet_index}; it would place samples before the session start."
            )

        self._seen_packets.add(key)
        records = tuple(
            SampleRecord(
                channel=packet.channel,
                packet_index=packet.packet_index,
                sample_in_packet=position,
                microvolts=value,
                elapsed_s=(packets_since_first * SAMPLES_PER_PACKET + position)
                / NOMINAL_SAMPLE_RATE_HZ,
            )
            for position, value in enumerate(packet.microvolts)
        )
        return PacketBatch(packet, records)


class PacketReceiptWriter:
    """Write scanner-monotonic packet arrival times separately from ``eeg.csv``."""

    def __init__(self, session_dir: str | Path, session_id: str) -> None:
        self.path = Path(session_dir) / PACKET_RECEIPTS_FILENAME
        self._session_id = session_id
        self._file = None
        self._csv = None

    def __enter__(self) -> "PacketReceiptWriter":
        self._file = self.path.open("x", newline="", encoding="utf-8")
        self._csv = csv.writer(self._file)
        self._csv.writerow(PACKET_RECEIPT_COLUMNS)
        self._file.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._file is not None:
            self._file.close()
        return False

    def write(self, packet: EegPacket) -> None:
        """Append one packet receipt time from the scanner's monotonic clock."""
        if self._csv is None or self._file is None:
            raise RuntimeError("packet receipt sidecar is not open")
        self._csv.writerow(
            (self._session_id, packet.channel, packet.packet_index, packet.receipt_monotonic_ns)
        )
        self._file.flush()


def record_packet_lines(
    lines: Iterable[str],
    sessions_dir: str | Path,
    session_id: str,
) -> Path:
    """Save complete packet lines and receipt times as one session.

    A normal return produces complete metadata.  If parsing or writing fails,
    ``SessionWriter`` retains rows already written and marks the session
    interrupted before it raises its normal interruption error.
    """
    adapter = LivePacketAdapter()
    with SessionWriter(
        sessions_dir,
        session_id,
        timing_method="packet_index_estimate",
        data_source="live_eeg_packet",
    ) as writer:
        with PacketReceiptWriter(writer.session_dir, session_id) as receipt_writer:
            for line in lines:
                batch = adapter.accept_line(line)
                writer.write_all(batch.records)
                receipt_writer.write(batch.packet)
        return writer.session_dir


def load_packet_session_windows(session_dir: str | Path):
    """Load one saved live session and return its two-second EEG windows."""
    directory = Path(session_dir)
    session = load_synthetic_session(directory / "eeg.csv", directory / "metadata.json")
    return create_fixed_windows(session)


def iter_packet_lines(stream: Iterable[str]) -> Iterator[str]:
    """Yield only lines whose exact prefix is ``EEG_PACKET,`` from scanner stdout."""
    for line in stream:
        if line.startswith(f"{PACKET_PREFIX},"):
            yield line


def _parse_unsigned_integer(value: str, name: str, upper_bound: int) -> int:
    result = _parse_nonnegative_integer(value, name)
    if result >= upper_bound:
        raise PacketFormatError(f"{name} must be from 0 to {upper_bound - 1}, got {result}.")
    return result


def _parse_nonnegative_integer(value: str, name: str) -> int:
    if not value.isdigit():
        raise PacketFormatError(f"{name} must be a nonnegative decimal integer, got {value!r}.")
    return int(value)


def _parse_microvolts(value: str, position: int) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise PacketFormatError(
            f"microvolt value {position} must be numeric, got {value!r}."
        ) from error
    if not isfinite(result):
        raise PacketFormatError(
            f"microvolt value {position} must be finite, got {value!r}."
        )
    return result
