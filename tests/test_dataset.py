"""Tests for synthetic-session loading and two-second EEG windows."""

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from eeg_app import create_fixed_windows, load_synthetic_session


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dataset"


class DatasetTests(unittest.TestCase):
    """Use deterministic synthetic EEG data only; no headset is required."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.temp_dir.name) / "session.csv"
        self.metadata_path = Path(self.temp_dir.name) / "metadata.json"
        shutil.copy(FIXTURE_DIR / "complete_six_seconds.csv", self.csv_path)
        shutil.copy(FIXTURE_DIR / "session_metadata.json", self.metadata_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def load_windows(self):
        return create_fixed_windows(load_synthetic_session(self.csv_path, self.metadata_path))

    def test_complete_six_seconds_produces_three_valid_windows(self) -> None:
        windows = self.load_windows()

        self.assertEqual(len(windows), 3)
        self.assertTrue(all(window.is_valid for window in windows))
        self.assertEqual([window.start_time_s for window in windows], [0.0, 2.0, 4.0])
        self.assertEqual([window.end_time_s for window in windows], [2.0, 4.0, 6.0])
        self.assertTrue(windows[0].window_id.endswith("window-000000"))
        self.assertEqual(len(windows[0].channel_samples["TP9"]), 512)
        self.assertEqual(windows[0].nominal_sample_rate_hz, 256.0)

    def test_missing_sample_marks_its_window_invalid(self) -> None:
        rows = self._read_rows()
        self._write_rows(
            [
                row
                for row in rows
                if not (row["channel"] == "TP9" and row["packet_index"] == "10" and row["sample_in_packet"] == "0")
            ]
        )

        windows = self.load_windows()
        self.assertFalse(windows[0].is_valid)
        self.assertIn("channel TP9 has 511 samples; expected 512", windows[0].invalid_reasons)

    def test_missing_channel_marks_windows_invalid(self) -> None:
        self._write_rows([row for row in self._read_rows() if row["channel"] != "AF8"])

        windows = self.load_windows()
        self.assertTrue(all(not window.is_valid for window in windows))
        self.assertIn("required channel AF8 is missing from this window", windows[0].invalid_reasons)

    def test_equal_lengths_with_mismatched_times_are_invalid(self) -> None:
        rows = self._read_rows()
        for row in rows:
            if row["channel"] == "AF7" and row["packet_index"] == "1" and row["sample_in_packet"] == "0":
                row["elapsed_s"] = "0.750000000"
                break
        self._write_rows(rows)

        windows = self.load_windows()
        self.assertFalse(windows[0].is_valid)
        self.assertTrue(any("timestamp for AF7" in reason for reason in windows[0].invalid_reasons))

    def test_aligned_compressed_timestamps_are_invalid_against_256_hz_grid(self) -> None:
        """Channels agreeing with one another is insufficient when all are mistimed."""
        rows = self._read_rows()
        for row in rows:
            if float(row["elapsed_s"]) < 2.0:
                sample_number = int(row["packet_index"]) * 12 + int(row["sample_in_packet"])
                row["elapsed_s"] = f"{sample_number / 512:.9f}"
        self._write_rows(rows)

        windows = self.load_windows()
        self.assertFalse(windows[0].is_valid)
        self.assertTrue(
            any("expected 256 Hz time grid" in reason for reason in windows[0].invalid_reasons)
        )

    def test_duplicate_sample_is_rejected_by_loader(self) -> None:
        rows = self._read_rows()
        rows.append(dict(rows[0]))
        self._write_rows(rows)

        with self.assertRaisesRegex(ValueError, "Duplicate sample"):
            load_synthetic_session(self.csv_path, self.metadata_path)

    def test_boundary_sample_belongs_to_second_window(self) -> None:
        windows = self.load_windows()

        self.assertEqual(windows[0].channel_samples["TP9"][-1], 511.0)
        self.assertEqual(windows[1].channel_samples["TP9"][0], 512.0)

    def test_trailing_partial_window_is_reported_invalid(self) -> None:
        rows = self._read_rows()
        for sample_number in range(1536, 1664):
            for channel_index, channel in enumerate(("TP9", "AF7", "AF8", "TP10")):
                rows.append(
                    {
                        "session_id": "synthetic-6s",
                        "elapsed_s": f"{sample_number / 256:.9f}",
                        "channel": channel,
                        "packet_index": str(sample_number // 12),
                        "sample_in_packet": str(sample_number % 12),
                        "microvolts": str(float(sample_number + channel_index / 10)),
                    }
                )
        self._write_rows(rows)

        windows = self.load_windows()
        self.assertEqual(len(windows), 4)
        self.assertFalse(windows[-1].is_valid)
        self.assertIn("channel TP9 has 128 samples; expected 512", windows[-1].invalid_reasons)

    def test_packet_index_wraparound_from_65535_to_zero_is_contiguous(self) -> None:
        rows = self._read_rows()
        for row in rows:
            row["packet_index"] = str((int(row["packet_index"]) + 65_534) % 65_536)
        self._write_rows(rows)

        windows = self.load_windows()
        self.assertTrue(all(window.is_valid for window in windows))

    def test_session_excluded_from_development_list_is_rejected(self) -> None:
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        metadata["development_session_ids"] = ["another-session"]
        self.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "not in the development session list"):
            load_synthetic_session(self.csv_path, self.metadata_path)

    def _read_rows(self) -> list[dict[str, str]]:
        with self.csv_path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        with self.csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
