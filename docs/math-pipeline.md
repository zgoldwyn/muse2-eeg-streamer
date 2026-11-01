# Mathematical window adapter and illustrative predictions (Parts 1–4)

`eeg_app.math_pipeline.extract_window_features` accepts Namit's `EegWindow`
attribute format from PR #12, commit `892ea3c`. It uses structural typing so
that the feature adapter can be developed before `eeg_app.dataset` is merged;
it does not define a replacement loader or require renaming window fields.

```python
from eeg_app.dataset import load_synthetic_session, create_fixed_windows
from eeg_app.math_pipeline import extract_window_features

# Requires Namit's dataset module from PR #12.
session = load_synthetic_session("path/to/eeg.csv", "path/to/metadata.json")
windows = create_fixed_windows(session)
record = extract_window_features(
    next(window for window in windows if window.is_valid),
    flatline_tolerance_uv=0.0,  # Explicit demonstration setting, not validated.
)
print(record["window_id"], record["features"]["AF7_peak_to_peak_uv"])
```

The adapter reads `session_id`, `window_id`, `start_time_s`, `end_time_s`,
`nominal_sample_rate_hz`, `channel_samples`, `is_valid`, and `invalid_reasons`.
The loader owns the packet, time-grid, and channel alignment checks. The
adapter requires `is_valid is True` and no invalid reasons before declaring
continuity to the existing feature function. It checks basic metadata and
reuses sample validation in `calculate_window_features`. A validity flag is
not an artifact label and does not imply filtered or normalized data.

Each call produces one dictionary containing:

- Original IDs, times, and nominal rate, outside the numeric feature mapping.
- `features`: six separately calculated values for each of TP9, AF7, AF8, TP10
  (24 keys, such as `AF7_peak_to_peak_uv`).
- `units`: microvolts for peak-to-peak, maximum adjacent jump, and population
  standard deviation; dimensionless for flatline fraction, Pearson kurtosis,
  and approximate entropy.
- `settings`: sample count, explicit flatline tolerance, entropy embedding
  dimension, actual per-channel entropy tolerances, and calculation conventions.
  Entropy defaults to `m=2` and tolerance `0.2 * channel standard deviation`.
- `unavailable_reasons`: explanations keyed by feature name. An undefined value
  stays `None`, not zero (for example, kurtosis of a constant channel).

The adapter reads input arrays without modifying them. Flatline tolerance has
no implicit default: the caller must record a chosen value. No feature setting
here has been selected or validated as a research threshold.

Run the hand-constructed window tests from the repository root:

```text
python -m unittest discover -s tests -p test_math_pipeline.py -v
```

These tests cover complete 512-sample channel arrays, separate IDs and metadata,
channel-specific values, units and parameters, unavailable kurtosis, invalid
window rejection, unchanged inputs, and batch exclusion reporting.

A separate compatibility check loaded `dataset.py` and the original
`complete_six_seconds.csv` fixture directly from Namit's remote branch at
`892ea3c`, without merging or modifying his files. Its actual loader and
windowing functions returned `synthetic-6s:window-000000`; passing that
`EegWindow` directly to this adapter produced 24 feature values from 512 samples
per channel. This checks the object handoff only, not Ben's shared fixture.

## Part 2: respect validity and retain exclusions

`extract_features_for_windows(windows, flatline_tolerance_uv=...)` returns
`feature_records`, `skipped_windows`, and a `summary`. Invalid windows keep
their IDs, time bounds, and reasons in `skipped_windows`; their samples never
enter the calculation. Valid windows each produce their own feature record.
Errors while calculating a supposedly valid window propagate to the caller.
No samples are joined across windows, shifted, filled, or modified.

Once the upstream loader and fixture are available in the checkout, run:

```text
python -m eeg_app.math_pipeline tests/fixtures/integration/integration-demo-001 --flatline-tolerance-uv 0
```

Until those PRs are merged, this repeatable check uses their actual files in a
temporary copy, leaving the working branch unchanged:

```text
python scratch/samuel/verify_math_handoff.py
```

The check pins Namit's loader from PR #12 at
`892ea3c65cf83e00f750315aa056e570dae920b7` and Ben's writer-generated CSV and JSON
from PR #17 at `07443afbfce8a575b75157e01fdd41f4be1b8b2d`. Those Git objects must
be present locally; `git fetch origin` retrieves the branches. It runs the
full test suite including integration tests, then the saved-session demo.
It reads the committed fixture byte-for-byte, without translating metadata.

Verified result: all 60 tests passed with upstream dependencies supplied,
followed by:

```text
3 total windows
2 valid windows passed to feature extraction
1 invalid window skipped
```

The detailed exclusion output names `integration-demo-001:window-000001` and
preserves Namit's reasons, including missing packet/sample positions and
500 rather than 512 samples per channel. The two feature records retain IDs
`integration-demo-001:window-000000` and `integration-demo-001:window-000002`.
The integration test also verifies 6,096 loaded rows, packet 50 remaining
absent, intervals `[0, 2)`, `[2, 4)`, `[4, 6)`, 24 features per valid window,
and unchanged sample arrays for all three windows.

Normal test discovery reports 57 passes and three integration skips while the
upstream files are absent. The temporary verification run supplies those files
and runs that integration test successfully rather than skipping it.

This is a synthetic pipeline check. No headset or live recording was tested.

## Part 3: illustrative prediction rule

`demo_peak_to_peak_prediction(feature_record)` reads only the four channels'
peak-to-peak values and returns exactly `{"window_id": ..., "decision": ...}`.
It retains the original window ID. A value strictly greater than 100 microvolts
on any channel predicts `artifact`; otherwise the rule predicts `clean`.
Exactly 100 does not exceed the threshold. This fixed illustrative threshold
comes from the assignment; it has not been tuned against reference labels or
validated as a research threshold.

All four required values must be present, finite, nonnegative, and in
microvolts. An unavailable value raises an error naming the window, feature,
and reason; it is never replaced with zero or interpreted as clean. The rule
checks every required value even when another channel already exceeds 100.
Unavailable unused features, such as zero-variance kurtosis, do not prevent
this peak-to-peak-only rule from running.

With Namit's loader and Ben's fixture in the checkout, run:

```text
python -m eeg_app.math_pipeline tests/fixtures/integration/integration-demo-001 --flatline-tolerance-uv 0 --demo-predictions --reference-labels tests/fixtures/integration/reference_records.json
```

For the current branch, which does not merge their open PRs, run:

```text
python scratch/samuel/verify_math_handoff.py
```

In addition to the three-window summary above and the detailed exclusion
reasons, the actual output is:

```text
Demo rule: peak-to-peak >100 microvolts on any channel; not validated.
Prediction records: [{"window_id": "integration-demo-001:window-000000", "decision": "clean"}, {"window_id": "integration-demo-001:window-000002", "decision": "artifact"}]
Reference-label evaluation: {"counts": {"false_negatives": 0, "false_positives": 0, "true_negatives": 1, "true_positives": 1}, "metrics": {"accepted_contamination": {"denominator": 1, "numerator": 0, "value": 0.0}, "clean_retention": {"denominator": 1, "numerator": 1, "value": 1.0}, "coverage": {"denominator": 2, "numerator": 1, "value": 0.5}, "precision": {"denominator": 1, "numerator": 1, "value": 1.0}, "recall": {"denominator": 1, "numerator": 1, "value": 1.0}}, "summary": {"accepted_eligible_windows": 1, "eligible_windows": 2, "invalid_windows_excluded": 1, "total_reference_windows": 3, "uncertain_windows_excluded": 0}}
```

### Zack's supplied reference labels and completed evaluation

Zack supplied the following scenario-based reference records, relayed by Sam
in this chat on October 20, 2026. They are saved unchanged in
`tests/fixtures/integration/reference_records.json`. Zack specified them based
on the fixture scenario rather than the predictions; they are synthetic test
labels, not independently reviewed labels for real EEG.

| Interval | Supplied window ID | Supplied label |
| --- | --- | --- |
| `[0, 2)` | `integration-demo-001:window-000000` | `clean` |
| `[2, 4)` | `integration-demo-001:window-000001` | `invalid` |
| `[4, 6)` | `integration-demo-001:window-000002` | `artifact` |

The fixed demo rule and 100 microvolt threshold were not changed. Run:

```text
python scratch/samuel/verify_math_handoff.py --reference-labels tests/fixtures/integration/reference_records.json
```

The runner defaults to this supplied file, so its shorter command also runs
the evaluation. It forwards the reference file unchanged. The CLI calls
`evaluate_predictions(references, predictions)` directly, with no field
translation, ID reassignment, or generated labels, and prints the returned
counts, metrics, and exclusions. Missing predictions, unknown IDs, or other
format errors are reported rather than hidden.

The actual output above reports TP=1, TN=1, FP=0, FN=0; three reference windows,
two eligible windows, and one invalid window excluded. Recall, precision, and
clean retention are 1.0; accepted contamination is 0.0; coverage is 0.5.
Coverage measures the fraction accepted as clean, not the fraction processed.
These results only verify this tiny synthetic plumbing test.

No prediction/reference format or ID mismatch was found. A fresh fetch
confirmed Namit's remote branch remains at `892ea3c`; the integration test
checks each supplied ID against its explicit time interval. If that format
changes before merging, reconcile the supplied labels by those intervals,
preserve the loader's actual IDs in predictions, and report the mapping change
to Zack. Do not guess IDs by list position. No remapping was needed for this run.

For later research work, select thresholds using development data, then freeze
the rule and parameters before sealed evaluation. The two-window synthetic
demo cannot establish accuracy on recorded EEG.

## Part 4: test coverage and handoff

| Required check | Test coverage |
| --- | --- |
| One valid four-channel window produces one feature record | `test_one_record_with_six_features_per_channel_and_separate_metadata` checks all 24 keys, channel-specific results, and separate IDs/timing. |
| Two valid windows produce two predictions with distinct IDs | `test_two_valid_windows_produce_two_predictions_with_distinct_original_ids` checks the adapter and rule together; `test_two_real_window_predictions_preserve_ids_and_exclude_invalid_middle` checks actual loader output. |
| Missing-packet window is excluded | `test_batch_skips_gap_without_calculating_or_mutating_it` and `test_actual_loader_gap_exclusion_and_unchanged_samples` check exclusion reasons and that only the two valid windows reach extraction. |
| Unavailable features are not zero or automatic clean | `test_units_settings_and_unavailable_reason_survive` checks undefined kurtosis stays `None` with its reason; `test_unavailable_required_feature_reports_window_key_and_reason` verifies missing peak-to-peak raises instead of predicting clean. |
| Different record ordering still matches references by ID | `test_demo_rule_predictions_match_existing_references_by_id_when_reordered` passes demo-rule records directly to the evaluator in multiple orders, using Shrinithi's existing ten-window test references unchanged. |

The ordering test uses the existing `demo-001-w01` through `demo-001-w10`
reference data from `tests/test_metrics.py`. Its feature inputs exercise the
prediction/evaluator contract. They are not Ben's fixture, do not provide
labels for `integration-demo-001`. The separate integration test
`test_zack_labels_match_intervals_and_evaluator_excludes_invalid_window` uses
Zack's supplied fixture references, verifies their time intervals, checks
invalid exclusion and metrics, and repeats evaluation with reordered records.

Run the tests in the current checkout:

```text
python -m unittest discover -s tests
# Ran 60 tests; OK (skipped=3): 57 pass, 3 need upstream PR files.
```

Run the same full suite with the pinned actual upstream loader and shared
fixture in a temporary directory:

```text
python scratch/samuel/verify_math_handoff.py
# Ran 60 tests; OK: all pass, none skipped.
```

Namit supplies valid continuous sample arrays and stable window IDs. The
adapter preserves those IDs, calculates all six features per channel, and
retains unavailable reasons. The demo rule uses only the four peak-to-peak
features. Predictions go to Shrinithi in the evaluator's `window_id`/`decision`
format; invalid windows remain in the separate exclusion summary.

The 100 microvolt threshold is only the assignment's illustrative plumbing
check. Later threshold selection must use development data with reference
labels kept separate from predictions. Freeze the selected threshold, feature
parameters, and decision rule before evaluating sealed data; do not adjust
them after inspecting sealed results. No research threshold selection or
sealed evaluation has been performed here.

**Reference-label evaluation complete:** Zack's supplied scenario labels are
accepted directly by the merged evaluator. The invalid window receives no
binary prediction and is excluded from the primary metrics. The command and
actual output above can replace the pending-evaluation section in the PR.
