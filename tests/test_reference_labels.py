"""Tests for joining independently reviewed reference labels to EEG windows."""

import tempfile
import unittest
from pathlib import Path

from eeg_app import (
    ReferenceLabelInterval,
    create_fixed_windows,
    join_reference_label_intervals,
    load_synthetic_session,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dataset"


class ReferenceLabelJoinTests(unittest.TestCase):
    """Exercise only reviewed synthetic label intervals, never detector output."""

    def setUp(self) -> None:
        self.windows = create_fixed_windows(
            load_synthetic_session(
                FIXTURE_DIR / "complete_six_seconds.csv",
                FIXTURE_DIR / "session_metadata.json",
            )
        )

    def interval(self, start: float, end: float, label: str, **kwargs: object) -> ReferenceLabelInterval:
        return ReferenceLabelInterval(
            session_id="synthetic-6s",
            start_s=start,
            end_s=end,
            label=label,
            reviewer_id="reviewer-01",
            label_version="v0.1",
            **kwargs,
        )

    def test_full_clean_coverage_assigns_clean(self) -> None:
        joined = join_reference_label_intervals(self.windows[:1], [self.interval(0.0, 2.0, "clean")])

        self.assertEqual(joined[0].label, "clean")
        self.assertEqual(joined[0].status, "assigned")

    def test_full_artifact_coverage_assigns_artifact(self) -> None:
        joined = join_reference_label_intervals(
            self.windows[:1], [self.interval(0.0, 2.0, "artifact", subtype="blink")]
        )

        self.assertEqual(joined[0].label, "artifact")
        self.assertEqual(joined[0].status, "assigned")

    def test_partial_artifact_overlap_needs_adjudication(self) -> None:
        joined = join_reference_label_intervals(self.windows[:1], [self.interval(0.5, 1.0, "artifact")])

        self.assertIsNone(joined[0].label)
        self.assertEqual(joined[0].status, "needs_adjudication")

    def test_uncertain_boundary_needs_adjudication(self) -> None:
        joined = join_reference_label_intervals(
            self.windows[:1],
            [self.interval(0.5, 1.0, "uncertain", boundary_uncertainty_s=0.1)],
        )

        self.assertEqual(joined[0].status, "needs_adjudication")
        self.assertIn("uncertain boundary", joined[0].reasons[0])

    def test_conflicting_annotations_remain_unassigned(self) -> None:
        joined = join_reference_label_intervals(
            self.windows[:1],
            [self.interval(0.0, 2.0, "clean"), self.interval(0.0, 2.0, "artifact")],
        )

        self.assertIsNone(joined[0].label)
        self.assertEqual(joined[0].status, "conflicting_reference_labels")

    def test_technical_invalid_window_is_invalid_without_reference_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "missing.csv"
            metadata_path = Path(temp_dir) / "metadata.json"
            rows = (FIXTURE_DIR / "complete_six_seconds.csv").read_text(encoding="utf-8").splitlines()
            csv_path.write_text("\n".join(line for line in rows if ",TP9,6,4," not in line), encoding="utf-8")
            metadata_path.write_text(
                (FIXTURE_DIR / "session_metadata.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            invalid_window = create_fixed_windows(load_synthetic_session(csv_path, metadata_path))[0]

        joined = join_reference_label_intervals([invalid_window], [])
        self.assertEqual(joined[0].label, "invalid")
        self.assertEqual(joined[0].status, "technical_invalid")


if __name__ == "__main__":
    unittest.main()
