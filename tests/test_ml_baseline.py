import unittest

from eeg_app.ml_baseline import check_no_participant_overlap, train_participant_baseline


def record(window_id, participant, target, features=None):
    return {
        "window_id": window_id,
        "participant_id": participant,
        "session_id": f"{participant}-session",
        "weak_target": target,
        "features": features if features is not None else {"TP9.peak_to_peak_uv": 1.0, "AF7.std_uv": 2.0},
    }


class BaselineValidationTests(unittest.TestCase):
    def test_duplicate_window_ids_are_rejected(self):
        records = [record("same", "sub-01", "rest_period"), record("same", "sub-02", "task_period")]
        with self.assertRaisesRegex(ValueError, "Duplicate window_id"):
            train_participant_baseline(records, holdout_participants=["sub-02"])

    def test_missing_features_or_target_are_rejected(self):
        records = [record("one", "sub-01", "rest_period", {}), record("two", "sub-02", "task_period")]
        with self.assertRaisesRegex(ValueError, "missing features"):
            train_participant_baseline(records, holdout_participants=["sub-02"])

        records = [record("one", "sub-01", "rest_period"), record("two", "sub-02", None)]
        with self.assertRaisesRegex(ValueError, "weak_target"):
            train_participant_baseline(records, holdout_participants=["sub-02"])

    def test_one_class_training_is_rejected(self):
        records = [
            record("one", "sub-01", "rest_period"),
            record("two", "sub-01", "rest_period"),
            record("three", "sub-02", "rest_period"),
            record("four", "sub-02", "task_period"),
        ]
        with self.assertRaisesRegex(ValueError, "Both weak targets"):
            train_participant_baseline(records, holdout_participants=["sub-02"])

    def test_participant_held_out_result_contains_window_ids(self):
        records = [
            record("one", "sub-01", "rest_period", {"a": 1, "b": 2}),
            record("two", "sub-01", "task_period", {"a": 3, "b": 4}),
            record("three", "sub-02", "rest_period", {"a": 2, "b": None}),
            record("four", "sub-02", "task_period", {"a": 4, "b": 5}),
        ]
        result = train_participant_baseline(records, holdout_participants=["sub-02"])
        self.assertEqual({row["window_id"] for row in result.predictions}, {"three", "four"})
        self.assertEqual(result.summary["holdout_participants"], ["sub-02"])

    def test_participant_overlap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Participant overlap"):
            check_no_participant_overlap(
                [record("one", "sub-01", "rest_period")],
                [record("two", "sub-01", "task_period")],
            )


if __name__ == "__main__":
    unittest.main()
