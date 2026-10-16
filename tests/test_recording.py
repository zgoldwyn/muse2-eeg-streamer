"""Synthetic tests for the session writer and read-back check.

No headset, Bluetooth, or C scanner is used. Every test writes into a
temporary directory that is removed afterwards.
"""

import csv
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from eeg_app.recording import (
    EEG_COLUMNS,
    InvalidRecordError,
    SampleRecord,
    SessionExistsError,
    SessionInterruptedError,
    SessionWriter,
    record_session,
)
from eeg_app.session_reader import (
    SessionFormatError,
    check_session,
    format_report,
    read_session,
)
from eeg_app.synthetic import synthetic_records

SCRATCH_CSV = Path(__file__).resolve().parents[1] / "scratch" / "benjamin" / "synthetic_eeg.csv"


class RecordingTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sessions_dir = Path(temp.name)
        self.records = list(synthetic_records())

    def load_metadata(self, session_dir):
        return json.loads((session_dir / "metadata.json").read_text())

    def eeg_lines(self, session_dir):
        return (session_dir / "eeg.csv").read_text().splitlines()


class SaveAndReopenTests(RecordingTestCase):
    def test_valid_session_round_trips(self):
        session_dir = record_session(self.records, self.sessions_dir, "demo-001")

        saved = read_session(session_dir)
        check = check_session(saved, expected_records=self.records)

        self.assertTrue(check.ok, check.problems)
        self.assertEqual(saved.records, self.records)  # values, times and order
        self.assertEqual(check.total_rows, 144)
        self.assertEqual(check.rows_per_channel, {"TP9": 36, "AF7": 36, "AF8": 36, "TP10": 36})
        self.assertEqual(check.incomplete_packets, [])

        metadata = self.load_metadata(session_dir)
        self.assertEqual(metadata["session_id"], "demo-001")
        self.assertEqual(metadata["schema_version"], "0.1")
        self.assertEqual(metadata["sample_rate_hz"], 256)
        self.assertEqual(metadata["channels"], ["TP9", "AF7", "AF8", "TP10"])
        self.assertEqual(metadata["units"], "microvolts")
        self.assertEqual(metadata["timing_method"], "packet_index_estimate")
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["eeg_row_count"], 144)
        self.assertIsNone(metadata["stop_reason"])

    def test_csv_keeps_the_draft_format(self):
        session_dir = record_session(self.records, self.sessions_dir, "demo-001")
        with (session_dir / "eeg.csv").open(newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(tuple(rows[0]), EEG_COLUMNS)
        self.assertEqual(rows[1], ["demo-001", "0.0", "TP9", "100", "0", "0.0"])

    def test_synthetic_source_matches_existing_example_file(self):
        with SCRATCH_CSV.open(newline="") as f:
            example = list(csv.DictReader(f))
        self.assertEqual(len(example), len(self.records))
        for row, record in zip(example, self.records):
            self.assertEqual(row["channel"], record.channel)
            self.assertEqual(int(row["packet_index"]), record.packet_index)
            self.assertEqual(int(row["sample_in_packet"]), record.sample_in_packet)
            self.assertEqual(float(row["microvolts"]), record.microvolts)
            self.assertAlmostEqual(float(row["elapsed_s"]), record.elapsed_s, delta=1e-6)

    def test_report_matches_expected_example_output(self):
        session_dir = record_session(self.records, self.sessions_dir, "demo-001")
        saved = read_session(session_dir)
        report = format_report(saved, check_session(saved, self.records))
        self.assertIn("144 sample rows total", report)
        self.assertIn("36 sample rows per channel", report)
        self.assertIn("Packet 102 missing on all four channels", report)

    def test_writer_can_be_used_directly(self):
        with SessionWriter(self.sessions_dir, "direct-001", data_source="test") as writer:
            for record in self.records[:12]:
                writer.write(record)
        self.assertEqual(writer.rows_written, 12)
        self.assertEqual(self.load_metadata(writer.session_dir)["data_source"], "test")


class PacketGapTests(RecordingTestCase):
    def test_deliberate_gap_stays_missing(self):
        session_dir = record_session(self.records, self.sessions_dir, "gap-001")
        check = check_session(read_session(session_dir))

        self.assertEqual(check.missing_packets, {102: ["TP9", "AF7", "AF8", "TP10"]})
        for channel, packets in check.packets_per_channel.items():
            self.assertEqual(packets, [100, 101, 103], channel)
        # Nothing was filled in for packet 102.
        self.assertNotIn(",102,", (session_dir / "eeg.csv").read_text())
        self.assertTrue(check.ok, check.problems)

    def test_gap_on_one_channel_only(self):
        records = [r for r in self.records if not (r.channel == "AF8" and r.packet_index == 101)]
        check = check_session(read_session(record_session(records, self.sessions_dir, "gap-002")))
        self.assertEqual(check.missing_packets, {101: ["AF8"], 102: ["TP9", "AF7", "AF8", "TP10"]})

    def test_wraparound_is_not_a_gap_or_duplicate(self):
        records = list(synthetic_records(packet_indices=[65534, 65535, 0, 1]))
        session_dir = record_session(records, self.sessions_dir, "wrap-001")
        check = check_session(read_session(session_dir), expected_records=records)
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.missing_packets, {})
        self.assertEqual(check.duplicates, [])

    def test_gap_across_wraparound(self):
        records = list(synthetic_records(packet_indices=[65535, 1]))
        check = check_session(read_session(record_session(records, self.sessions_dir, "wrap-002")))
        self.assertEqual(list(check.missing_packets), [0])


class ExistingSessionTests(RecordingTestCase):
    def test_refuses_existing_session_directory(self):
        session_dir = record_session(self.records, self.sessions_dir, "demo-001")
        before = (session_dir / "eeg.csv").read_bytes()

        with self.assertRaises(SessionExistsError) as caught:
            record_session(self.records[:12], self.sessions_dir, "demo-001")

        self.assertIn("already exists", str(caught.exception))
        self.assertEqual((session_dir / "eeg.csv").read_bytes(), before)
        self.assertEqual(self.load_metadata(session_dir)["eeg_row_count"], 144)

    def test_refuses_empty_existing_directory(self):
        (self.sessions_dir / "demo-002").mkdir()
        with self.assertRaises(SessionExistsError):
            record_session(self.records, self.sessions_dir, "demo-002")
        self.assertEqual(list((self.sessions_dir / "demo-002").iterdir()), [])

    def test_rejects_unsafe_session_id(self):
        for bad_id in ("", "../escape", "a/b", ".hidden"):
            with self.subTest(session_id=bad_id), self.assertRaises(ValueError):
                SessionWriter(self.sessions_dir, bad_id)


class InterruptedStreamTests(RecordingTestCase):
    def test_interrupted_input_keeps_written_rows(self):
        def stream_that_drops():
            yield from self.records[:50]
            raise ConnectionError("headset disconnected")

        with self.assertRaises(SessionInterruptedError) as caught:
            record_session(stream_that_drops(), self.sessions_dir, "drop-001")

        error = caught.exception
        self.assertIsInstance(error.__cause__, ConnectionError)
        self.assertEqual(error.rows_written, 50)
        self.assertIn("Kept 50 sample row(s)", str(error))
        self.assertIn("interrupted", str(error))

        metadata = self.load_metadata(error.session_dir)
        self.assertEqual(metadata["status"], "interrupted")
        self.assertEqual(metadata["eeg_row_count"], 50)
        self.assertIn("headset disconnected", metadata["stop_reason"])

        saved = read_session(error.session_dir)
        self.assertEqual(saved.records, self.records[:50])
        check = check_session(saved)
        # Row 50 ends partway through TP9's packet 101, and the check says so.
        self.assertIn(("TP9", 101, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), check.incomplete_packets)
        self.assertFalse(check.ok)

    def test_keyboard_interrupt_is_recorded_and_passed_through(self):
        def stream_stopped_by_operator():
            yield from self.records[:24]
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            record_session(stream_stopped_by_operator(), self.sessions_dir, "ctrl-c-001")

        metadata = self.load_metadata(self.sessions_dir / "ctrl-c-001")
        self.assertEqual(metadata["status"], "interrupted")
        self.assertEqual(metadata["stop_reason"], "KeyboardInterrupt")
        self.assertEqual(metadata["eeg_row_count"], 24)

    def test_empty_input_is_complete_with_zero_rows(self):
        session_dir = record_session([], self.sessions_dir, "empty-001")
        metadata = self.load_metadata(session_dir)
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["eeg_row_count"], 0)
        self.assertEqual(self.eeg_lines(session_dir), [",".join(EEG_COLUMNS)])


class DuplicateTests(RecordingTestCase):
    def assert_rejected_after(self, records, rows_kept, message):
        with self.assertRaises(SessionInterruptedError) as caught:
            record_session(records, self.sessions_dir, "dup-001")
        error = caught.exception
        self.assertIsInstance(error.__cause__, InvalidRecordError)
        self.assertIn(message, str(error))
        self.assertEqual(error.rows_written, rows_kept)
        self.assertEqual(self.load_metadata(error.session_dir)["status"], "interrupted")
        self.assertEqual(len(self.eeg_lines(error.session_dir)), rows_kept + 1)

    def test_rejects_duplicate_sample(self):
        records = self.records[:5] + [self.records[4]] + self.records[5:]
        self.assert_rejected_after(records, 5, "duplicate sample: channel=TP9 packet=100 sample_in_packet=4")

    def test_rejects_repeated_earlier_packet(self):
        tp9_packet_100 = [r for r in self.records if r.channel == "TP9" and r.packet_index == 100]
        self.assert_rejected_after(self.records + tp9_packet_100, 144, "repeated or out-of-order packet")

    def test_reader_reports_duplicates_separately_from_gaps(self):
        session_dir = record_session(self.records, self.sessions_dir, "dup-002")
        # Simulate a file edited or merged by hand: repeat one row.
        with (session_dir / "eeg.csv").open("a", newline="") as f:
            f.write("dup-002,0.183594,TP10,103,11,18.48\n")

        check = check_session(read_session(session_dir))
        self.assertEqual(check.duplicates, [("TP10", 103, 11)])
        self.assertEqual(check.missing_packets, {102: ["TP9", "AF7", "AF8", "TP10"]})
        self.assertTrue(any("duplicate sample" in p for p in check.problems))
        self.assertTrue(any("eeg_row_count is 144" in p for p in check.problems))


class MalformedRecordTests(RecordingTestCase):
    def test_rejects_malformed_and_nonfinite_records(self):
        good = self.records[0]
        bad_records = {
            "nan microvolts": replace(good, microvolts=math.nan),
            "infinite microvolts": replace(good, microvolts=math.inf),
            "negative infinite time": replace(good, elapsed_s=-math.inf),
            "nan time": replace(good, elapsed_s=math.nan),
            "negative time": replace(good, elapsed_s=-0.5),
            "text microvolts": replace(good, microvolts="12.5"),
            "bool microvolts": replace(good, microvolts=True),
            "packet too large": replace(good, packet_index=65536),
            "negative packet": replace(good, packet_index=-1),
            "float packet": replace(good, packet_index=100.0),
            "sample position 12": replace(good, sample_in_packet=12),
            "negative sample position": replace(good, sample_in_packet=-1),
            "unknown channel": replace(good, channel="AUX"),
            "not a record": {"channel": "TP9"},
        }
        for i, (name, bad) in enumerate(bad_records.items()):
            with self.subTest(name):
                with self.assertRaises(SessionInterruptedError) as caught:
                    record_session([*self.records[:3], bad], self.sessions_dir, f"bad-{i}")
                self.assertIsInstance(caught.exception.__cause__, InvalidRecordError)
                self.assertEqual(caught.exception.rows_written, 3)
                metadata = self.load_metadata(caught.exception.session_dir)
                self.assertEqual(metadata["status"], "interrupted")
                self.assertEqual(metadata["eeg_row_count"], 3)

    def test_reader_rejects_malformed_saved_values(self):
        cases = {
            "nan": ("0.0", "nan", "finite"),
            "inf": ("0.0", "inf", "finite"),
            "text": ("0.0", "abc", "not a valid float"),
            "time nan": ("nan", "1.0", "elapsed_s"),
        }
        for i, (name, (elapsed, value, message)) in enumerate(cases.items()):
            with self.subTest(name):
                session_dir = record_session(self.records[:12], self.sessions_dir, f"edit-{i}")
                with (session_dir / "eeg.csv").open("a", newline="") as f:
                    f.write(f"edit-{i},{elapsed},AF7,100,0,{value}\n")
                with self.assertRaises(SessionFormatError) as caught:
                    read_session(session_dir)
                self.assertIn("row 14", str(caught.exception))
                self.assertIn(message, str(caught.exception))

    def test_reader_rejects_out_of_range_positions(self):
        cases = {"packet": "AF7,70000,0", "sample": "AF7,100,12", "channel": "XYZ,100,0"}
        for i, (name, fields) in enumerate(cases.items()):
            with self.subTest(name):
                session_dir = record_session(self.records[:12], self.sessions_dir, f"range-{i}")
                with (session_dir / "eeg.csv").open("a", newline="") as f:
                    f.write(f"range-{i},0.0,{fields},1.0\n")
                with self.assertRaises(SessionFormatError):
                    read_session(session_dir)

    def test_reader_rejects_cut_off_last_row(self):
        session_dir = record_session(self.records[:12], self.sessions_dir, "cut-001")
        with (session_dir / "eeg.csv").open("a", newline="") as f:
            f.write("cut-001,0.04,TP9\n")
        with self.assertRaises(SessionFormatError) as caught:
            read_session(session_dir)
        self.assertIn("cut off", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
