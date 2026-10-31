"""Synthetic tests for the scanner ``EEG_PACKET`` to saved-session bridge."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from eeg_app.live_adapter import (
    DuplicatePacketError,
    LivePacketAdapter,
    PACKET_RECEIPTS_FILENAME,
    PacketFormatError,
    StreamAlignmentError,
    iter_packet_lines,
    load_packet_session_windows,
    parse_eeg_packet_line,
    record_packet_lines,
)
from eeg_app.recording import SessionInterruptedError


CHANNELS = ("TP9", "AF7", "AF8", "TP10")


def packet_line(channel: str, packet_index: int, receipt_ns: int = 1000) -> str:
    """Return one valid hand-written scanner line with twelve distinct values."""
    values = [str(packet_index * 100 + position) for position in range(12)]
    return ",".join(["EEG_PACKET", channel, str(packet_index), str(receipt_ns), *values])


class LiveAdapterTests(unittest.TestCase):
    """No scanner, headset, C build, or real participant data is required."""

    def test_bens_example_line_creates_twelve_sample_records(self) -> None:
        line = (
            "EEG_PACKET,TP9,93,1234567890123,21.48437500,-216.30859375,"
            "-151.85546875,95.21484375,90.82031250,-152.34375000,"
            "-195.31250000,39.55078125,142.57812500,-94.23828125,"
            "-219.23828125,-8.30078125"
        )
        batch = LivePacketAdapter().accept_line(line)

        self.assertEqual(len(batch.records), 12)
        self.assertEqual(batch.records[0].channel, "TP9")
        self.assertEqual(batch.records[0].packet_index, 93)
        self.assertEqual(batch.records[0].sample_in_packet, 0)
        self.assertEqual(batch.records[-1].sample_in_packet, 11)
        self.assertEqual(batch.records[0].elapsed_s, 0.0)
        self.assertEqual(batch.records[-1].elapsed_s, 11 / 256)
        self.assertEqual(batch.packet.receipt_monotonic_ns, 1234567890123)

    def test_all_channels_share_the_same_packet_time_grid(self) -> None:
        adapter = LivePacketAdapter()
        batches = [adapter.accept_line(packet_line(channel, 93)) for channel in CHANNELS]

        self.assertEqual(
            [batch.records[5].elapsed_s for batch in batches], [5 / 256] * 4
        )

    def test_missing_packet_is_not_created_and_middle_window_is_invalid(self) -> None:
        # 128 packets hold 1,536 sample positions: exactly six seconds at 256 Hz.
        # Packet 50 is omitted for every channel, leaving 6,096 saved rows.
        lines = [
            packet_line(channel, packet, 1_000_000 + packet)
            for packet in range(128)
            if packet != 50
            for channel in CHANNELS
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = record_packet_lines(lines, temporary_directory, "packet-gap")
            with (session_dir / "eeg.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            windows = load_packet_session_windows(session_dir)

        self.assertEqual(len(rows), 6096)
        self.assertFalse(any(row["packet_index"] == "50" for row in rows))
        self.assertEqual([window.is_valid for window in windows], [True, False, True])
        self.assertTrue(windows[1].invalid_reasons)

    def test_receipts_are_saved_separately_from_eeg_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = record_packet_lines([packet_line("TP9", 7, 998877)], temporary_directory, "receipts")
            with (session_dir / PACKET_RECEIPTS_FILENAME).open(newline="", encoding="utf-8") as stream:
                receipts = list(csv.DictReader(stream))
            with (session_dir / "eeg.csv").open(newline="", encoding="utf-8") as stream:
                eeg_columns = next(csv.reader(stream))

        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["receipt_monotonic_ns"], "998877")
        self.assertNotIn("receipt_monotonic_ns", eeg_columns)

    def test_packet_index_wraparound_continues_the_time_grid(self) -> None:
        adapter = LivePacketAdapter()
        first = adapter.accept_line(packet_line("TP9", 65535))
        wrapped = adapter.accept_line(packet_line("TP9", 0))

        self.assertEqual(first.records[0].elapsed_s, 0.0)
        self.assertEqual(wrapped.records[0].elapsed_s, 12 / 256)

    def test_duplicate_packet_is_rejected(self) -> None:
        adapter = LivePacketAdapter()
        adapter.accept_line(packet_line("AF7", 8))

        with self.assertRaisesRegex(DuplicatePacketError, "Duplicate EEG_PACKET"):
            adapter.accept_line(packet_line("AF7", 8))

    def test_malformed_unknown_and_nonfinite_lines_are_rejected(self) -> None:
        malformed_lines = (
            "EEG,TP9,1,2,3",
            packet_line("UNKNOWN", 1),
            "EEG_PACKET,TP9,1,2,1,2,3,4,5,6,7,8,9,10,11,nan",
        )
        for line in malformed_lines:
            with self.subTest(line=line), self.assertRaises(PacketFormatError):
                parse_eeg_packet_line(line)

    def test_packet_before_origin_is_rejected_as_unalignable(self) -> None:
        adapter = LivePacketAdapter()
        adapter.accept_line(packet_line("TP9", 100))

        with self.assertRaisesRegex(StreamAlignmentError, "cannot align"):
            adapter.accept_line(packet_line("AF7", 99))

    def test_bad_line_marks_an_already_started_session_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory) / "interrupted"
            with self.assertRaises(SessionInterruptedError):
                record_packet_lines(
                    [packet_line("TP9", 1), "EEG_PACKET,TP9,2,3,not-enough-values"],
                    temporary_directory,
                    "interrupted",
                )
            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            with (session_dir / "eeg.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))

        self.assertEqual(metadata["status"], "interrupted")
        self.assertEqual(len(rows), 12)

    def test_only_exact_packet_prefix_is_sent_to_the_adapter(self) -> None:
        lines = ["debug EEG_PACKET,TP9,1", packet_line("TP9", 1), "EEG,TP9,1,2"]
        self.assertEqual(list(iter_packet_lines(lines)), [packet_line("TP9", 1)])


if __name__ == "__main__":
    unittest.main()
