# P0005 development-validation screening policies

The selected mathematical policy uses peak-to-peak >123.6328125 µV or
maximum adjacent jump >52.24609375 µV on any Muse channel. All six features
continue to be calculated by the existing pipeline. The two-feature
recommendation came from the recorded P0005 validation search.

The supplied review release has 53 clean, 35 artifact, and 20 uncertain
windows. The loader identified three additional technically invalid
windows. The comparison uses the same 88 eligible IDs for every policy.

Namit confirmed that the labels still await Ben and Rushil's independent
checks and reconciliation. The current math and exported CNN results are
preliminary. Completed label fields establish a first-pass review release.
Independent-review reconciliation remains pending.

## Current compact comparison

| Policy | TP / FP / TN / FN | Recall | Precision | Clean retention | Accepted contamination | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| Selected math | 35 / 0 / 53 / 0 | 35/35 | 35/35 | 53/53 | 0/53 | 53/88 |
| Exported CNN, score >=0.5 | 35 / 12 / 41 / 0 | 35/35 | 35/47 | 41/53 | 0/41 | 41/88 |
| Both clean, exported CNN decisions | 35 / 12 / 41 / 0 | 35/35 | 35/47 | 41/53 | 0/41 | 41/88 |
| Training-majority reference | 35 / 53 / 0 / 0 | 35/35 | 35/88 | 0/53 | 0/0, unavailable | 0/88 |
| Always clean | 0 / 0 / 53 / 35 | 0/35 | 0/0, unavailable | 53/53 | 35/88 | 88/88 |

The training-majority reference uses the 213 artifact and 205 clean labels
in the November 8 training recordings and therefore predicts artifact.
The class decision is derived from training labels. The always-clean
reference accepts every eligible window.

The plot in the local output folder shows artifact recall against clean
retention for all 31 tested math policies, the recommendation, both
reference policies, the exported CNN, the agreement rule, and the CNN
validation cutoff curve. The retuned pair improves recall from the original
recipe's best P0005 result of 14/35 to 35/35 while retaining 53/53 clean
windows. Standard deviation and entropy provide no improvement at their
best settings, and the best kurtosis addition rejects two extra clean
windows. These observations support keeping the retuned two-feature rule
for approval.

## Actual CNN validation export

`P0005-CNN-validation-output.zip` contains
`p0005-validation-predictions.json` and `p0005-validation-summary.json`.
The prediction file contains JSON Lines despite its `.json` extension.
The reader accepts the ZIP unchanged, without renaming files or fields.
All 88 eligible window IDs match the review release exactly, with no
duplicates, unknown IDs, or missing eligible predictions. The existing
scorer reproduces the supplied summary: 35 TP, 41 TN, 12 FP, and 0 FN.

The supplied summary names P0001 and P0003 as CNN training participants,
with 89 training windows, and P0005 as validation. The math calibration
uses all four approved November 8 participants, with 418 eligible
training windows. These are preliminary validation-policy comparisons
with different training sets. Align the intended final training data
before the final model handoff. The CNN versions are `waveform-cnn-v1`
and `channel-zscore-train-only-v1`; the exported decisions match
`artifact_score >= 0.5` on every record. The output status is
`preliminary_pending_label_reconciliation`.

The comparison accepts JSON Lines, including `.json` files, JSON lists,
and ZIPs containing `.jsonl` or `*predictions.json` files. Metadata summary
JSON and Mac resource forks are ignored inside ZIPs. Records retain
`window_id`, `decision`, `artifact_score`,
`model_version`, and `preprocessing_version`. Supplied session and
participant fields are checked against the review records. Scores must
be finite values between 0 and 1. Unknown or duplicate IDs and missing
eligible predictions are errors. Scores for uncertain or invalid windows
have no effect on the primary metrics or cutoff search.

The first table uses Namit's exported decisions for the selected CNN
operating point. The agreement rule accepts a window only when both methods
say clean. The existing `eeg_app.metrics` scorer calculates the confusion
counts, denominators, and exclusions.

The second comparison holds the selected math policy fixed and finds the
CNN score cutoff whose P0005 validation acceptance fraction is closest
to math's 53/88. Ties prefer higher validation recall, then higher clean
retention, then a lower cutoff. It flags when `artifact_score >= cutoff`.
The candidate set contains every distinct eligible score and boundary
cutoffs for accepting or rejecting all windows. Ties in scores may prevent
an exact acceptance-rate match. The report includes the achieved coverage
difference and the full validation cutoff curve. The reserved repeat
recordings are excluded from all selection.

The selected CNN cutoff is `0.692649245262146`. It achieves exactly the
math policy's acceptance rate of 53/88. At this cutoff, CNN recall is
29/35 and clean retention is 47/53; six accepted windows are artifacts.
The agreement rule rejects those six artifacts but also rejects the
CNN's six false positives. This cutoff is selected on P0005 validation
and remains provisional.

| Similar-acceptance policy | TP / FP / TN / FN | Recall | Precision | Clean retention | Accepted contamination | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| Selected math | 35 / 0 / 53 / 0 | 35/35 | 35/35 | 53/53 | 0/53 | 53/88 |
| CNN, score >=0.692649245262146 | 29 / 6 / 47 / 6 | 29/35 | 29/35 | 47/53 | 6/53 | 53/88 |
| Both clean, similar-acceptance CNN | 35 / 6 / 47 / 0 | 35/35 | 35/41 | 47/53 | 0/47 | 47/88 |

## Commands and output

```text
python -m eeg_app.validation_comparison data/private/nov9/prepared.json data/private/thanksgiving/rule-grid.json data/private/thanksgiving/validation-p0005.json data/private/thanksgiving/validation-comparison --historical-report data/private/nov9/comparison.json
python -m eeg_app.validation_comparison data/private/nov9/prepared.json data/private/thanksgiving/rule-grid.json data/private/thanksgiving/validation-p0005.json data/private/thanksgiving/validation-comparison-with-cnn --historical-report data/private/nov9/comparison.json --cnn-predictions "C:/Users/XBbur/Downloads/P0005-CNN-validation-output.zip"
python -m unittest tests.test_development_math tests.test_validation_comparison
```

Actual run output:

```text
preliminary_pending_label_reconciliation: data/private/thanksgiving/validation-comparison-with-cnn
Ran 11 tests
OK
```

Use a new output directory for each run. The comparison directory contains
`summary.md` with compact tables, `comparison.json` with metrics, settings,
and hashes, `predictions.json` with per-window records, and `tradeoff.png`.
The output is staged and published together after plotting succeeds.
These outputs remain local under Git-ignored `data/private/`.

The previous held-out development comparison is preserved alongside the
current P0005 results, with its distinct cohort and role identified. The
P0005 recommendation is still awaiting Zach's approval. The final reserved
evaluation will be performed after the method freeze.

See [the concrete recommendation](method-freeze-recommendation.md) for proposed
settings, the aggregate tradeoff plot, and unresolved freeze items; see
[Ben's evaluation handoff](final-evaluation-handoff.md) for inference, scoring,
and returned-report verification commands.
