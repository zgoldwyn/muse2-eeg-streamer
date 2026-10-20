"""Known-answer checks for the synthetic integration-demo-001 session.

The committed fixture in tests/fixtures/integration/ must match what the
generator produces and the answer key in that folder's README.md. No headset,
Bluetooth, or C scanner is used.
"""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from eeg_app.recording import EEG_COLUMNS, check_session, read_session

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "integration"
SESSION_DIR = FIXTURE_DIR / "integration-demo-001"
CHANNELS = ["TP9", "AF7", "AF8", "TP10"]


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "integration_fixture_generator", FIXTURE_DIR / "generate_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_rows(session_dir):
    with (session_dir / "eeg.csv").open(newline="") as f:
        return list(csv.DictReader(f))


class IntegrationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_rows(SESSION_DIR)
        cls.metadata = json.loads((SESSION_DIR / "metadata.json").read_text())

    def test_metadata_uses_shared_keys(self):
        self.assertEqual(self.metadata["session_id"], "integration-demo-001")
        self.assertEqual(self.metadata["nominal_sample_rate_hz"], 256)
        self.assertEqual(self.metadata["samples_per_packet"], 12)
        self.assertEqual(self.metadata["channels"], CHANNELS)
        self.assertEqual(self.metadata["data_source"], "synthetic")
        self.assertEqual(self.metadata["eeg_row_count"], 6096)

    def test_complete_status_with_a_dropped_packet(self):
        # "complete" is the recording outcome; it does not mean no packets were lost.
        check = check_session(read_session(SESSION_DIR))
        self.assertEqual(self.metadata["status"], "complete")
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.missing_packets, {50: CHANNELS})

    def test_row_counts(self):
        self.assertEqual(len(self.rows), 6096)
        for channel in CHANNELS:
            self.assertEqual(sum(row["channel"] == channel for row in self.rows), 1524)

    def test_every_present_packet_has_positions_0_to_11(self):
        check = check_session(read_session(SESSION_DIR))
        self.assertEqual(check.incomplete_packets, [])
        self.assertEqual(check.duplicates, [])
        for channel in CHANNELS:
            self.assertEqual(
                check.packets_per_channel[channel], [p for p in range(128) if p != 50]
            )

    def test_no_replacement_values_for_packet_50(self):
        self.assertFalse(any(row["packet_index"] == "50" for row in self.rows))

    def test_elapsed_s_follows_the_sample_grid(self):
        for row in self.rows:
            expected = (int(row["packet_index"]) * 12 + int(row["sample_in_packet"])) / 256
            self.assertEqual(float(row["elapsed_s"]), expected)

    def test_missing_packet_keeps_its_place_in_time(self):
        tp9 = [row for row in self.rows if row["channel"] == "TP9"]
        before = next(r for r in tp9 if r["packet_index"] == "49" and r["sample_in_packet"] == "11")
        after = next(r for r in tp9 if r["packet_index"] == "51" and r["sample_in_packet"] == "0")
        self.assertEqual(float(before["elapsed_s"]), 599 / 256)
        self.assertEqual(float(after["elapsed_s"]), 612 / 256)

    def test_no_receipt_time_column(self):
        with (SESSION_DIR / "eeg.csv").open(newline="") as f:
            self.assertEqual(tuple(next(csv.reader(f))), EEG_COLUMNS)

    def test_disturbance_is_only_in_af7_packets_96_to_99(self):
        large = [row for row in self.rows if abs(float(row["microvolts"])) > 50]
        self.assertTrue(large)
        self.assertEqual({row["channel"] for row in large}, {"AF7"})
        self.assertTrue(all(96 <= int(row["packet_index"]) <= 99 for row in large))
        af7 = [row for row in self.rows if row["channel"] == "AF7"]
        peak = max(af7, key=lambda row: float(row["microvolts"]))
        self.assertGreater(float(peak["microvolts"]), 290)
        self.assertTrue(4.5 <= float(peak["elapsed_s"]) < 4.6875)

    def test_baseline_is_low_amplitude(self):
        quiet = [
            row for row in self.rows
            if not (row["channel"] == "AF7" and 96 <= int(row["packet_index"]) <= 99)
        ]
        self.assertLess(max(abs(float(row["microvolts"])) for row in quiet), 20)

    def test_generator_reproduces_the_committed_fixture(self):
        generator = load_generator()
        with tempfile.TemporaryDirectory() as temp:
            session_dir = generator.generate(temp)
            self.assertEqual(
                (session_dir / "eeg.csv").read_bytes(), (SESSION_DIR / "eeg.csv").read_bytes()
            )
            fresh = json.loads((session_dir / "metadata.json").read_text())
        # Start and end times record when the generator ran, so they always differ.
        ignore = {"started_at_utc", "ended_at_utc"}
        self.assertEqual(
            {k: v for k, v in fresh.items() if k not in ignore},
            {k: v for k, v in self.metadata.items() if k not in ignore},
        )


try:
    from eeg_app.dataset import create_fixed_windows, load_synthetic_session
except ImportError:  # the loader is in PR #12 and not merged yet
    load_synthetic_session = None


@unittest.skipIf(load_synthetic_session is None, "eeg_app.dataset (PR #12) is not available")
class LoaderHandoffTests(unittest.TestCase):
    """Namit's loader opens the writer's files unchanged."""

    def test_loader_accepts_the_files_unchanged(self):
        session = load_synthetic_session(SESSION_DIR / "eeg.csv", SESSION_DIR / "metadata.json")
        self.assertEqual(session.session_id, "integration-demo-001")
        self.assertEqual(len(session.samples), 6096)
        self.assertFalse(any(sample.packet_index == 50 for sample in session.samples))

    def test_windows_match_the_answer_key(self):
        session = load_synthetic_session(SESSION_DIR / "eeg.csv", SESSION_DIR / "metadata.json")
        windows = create_fixed_windows(session)
        # 0-2 s complete; 2-4 s contains the missing packet; 4-6 s complete
        # (the AF7 disturbance does not make a window invalid).
        self.assertEqual([w.is_valid for w in windows], [True, False, True])


if __name__ == "__main__":
    unittest.main()
