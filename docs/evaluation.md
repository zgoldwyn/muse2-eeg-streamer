# EEG Artifact Evaluation — Draft v0.1

## Purpose

This module evaluates synthetic artifact-detector decisions against independently assigned reference labels for fixed EEG windows. It does not train a detector and does not infer labels from prompts, observer markers, or another detector's decisions.

Artifact is the positive class. A detector decision of `clean` means that the detector would accept the window for downstream use; a decision of `artifact` means that it would reject the window.

## Input records and validation

Pass two sequences of dictionary-like records to `evaluate_predictions`:

```python
reference_records = [
    {"window_id": "demo-001-w01", "label": "artifact"},
    {"window_id": "demo-001-w02", "label": "clean"},
]

prediction_records = [
    {"window_id": "demo-001-w02", "decision": "clean"},
    {"window_id": "demo-001-w01", "decision": "artifact"},
]
```

Records are matched by `window_id`, not their list position. Reference labels must be one of `clean`, `artifact`, `uncertain`, or `invalid`. Predictions must be exactly `clean` or `artifact`.

The evaluator raises `ValueError` for duplicate reference IDs, duplicate prediction IDs, unknown prediction IDs, malformed records, unrecognized label or decision values, and a missing prediction for an eligible window. It does not silently discard an eligible window.

## Counts and primary metrics

For an eligible reference window:

| Reference label | Detector decision | Count |
| --- | --- | --- |
| `artifact` | `artifact` | True positive (TP) |
| `artifact` | `clean` | False negative (FN) |
| `clean` | `artifact` | False positive (FP) |
| `clean` | `clean` | True negative (TN) |

The returned `metrics` dictionary stores `numerator`, `denominator`, and `value` for every rate:

| Metric | Formula | What it answers |
| --- | --- | --- |
| Recall | `TP / (TP + FN)` | Of true artifacts, how many were rejected? |
| Precision | `TP / (TP + FP)` | Of rejected windows, how many were truly artifacts? |
| Clean retention | `TN / (TN + FP)` | Of truly clean windows, how many were kept? |
| Accepted contamination | `FN / (TN + FN)` | Among accepted windows, what fraction were actually artifacts? |
| Coverage | `(TN + FN) / eligible windows` | What fraction of eligible windows were accepted? |

When a denominator is zero, `value` is `None`; `format_rate(...)` displays it as `unavailable`. The zero denominator is retained so that a caller can see why the rate is unavailable.

## Exclusion rules

Reference windows labeled `uncertain` or `invalid` are excluded from TP, FN, FP, TN, and all five primary rates. The summary still reports:

- total reference windows;
- eligible windows;
- uncertain windows excluded;
- invalid windows excluded; and
- eligible windows accepted as clean (`TN + FN`).

Predictions are not required for excluded reference windows. If valid predictions are supplied for them, they are validated but ignored by the primary calculations.

## Original ten-window example

For the original synthetic example, the mathematical detector has:

```text
TP = 3
FN = 1
FP = 1
TN = 5

Recall = 3 / 4 = 0.75
Precision = 3 / 4 = 0.75
Clean retention = 5 / 6 = 0.8333
Accepted contamination = 1 / 6 = 0.1667
Coverage = 6 / 10 = 0.60
```

Adding two `uncertain` reference windows and one `invalid` reference window gives this separate summary without changing the five primary metrics:

```text
Total reference windows: 13
Eligible windows: 10
Uncertain windows excluded: 2
Invalid windows excluded: 1
Accepted eligible windows: 6
Coverage: 6 / 10 = 0.60
```

## Comparing two detectors

`compare_detectors` evaluates the mathematical detector and machine-learning detector separately, then evaluates this combined rule:

```text
Predict clean only when BOTH detectors predict clean.
Otherwise, predict artifact.
```

All three results use the same eligible reference windows and therefore the same coverage denominator. The comparison also returns eligible window IDs where both detectors are correct, both are wrong, or their decisions disagree.

In the required ten-window synthetic example, the combined rule gives:

```text
TP = 3
FN = 1
FP = 2
TN = 4

Accepted contamination = 1 / 5 = 0.20
Coverage = 5 / 10 = 0.50
```

The detectors disagree on windows 5 and 6. Both miss the artifact in window 4. Requiring agreement does **not** guarantee lower accepted contamination: in this example, it rejects one extra genuinely clean window but does not catch the artifact both detectors missed. The rule trades more conservative acceptance for lower clean retention and coverage, without guaranteeing a safer accepted set.

## Running the synthetic tests

From the repository root, run:

```powershell
python -m unittest discover -s tests -v
```

These are synthetic tests only; they do not validate detector performance on headset recordings.
