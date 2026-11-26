# Clean-training threshold search

The new search derives limits from the 205 clean windows in the approved
November 8 development recordings. The training session manifest is the
existing `data/private/nov9/session-participants.json`, which identifies the
13 sessions across P001, P0002, P0003, and P0004. All runs and refits keep
their participant identity. The prepared feature file records the releases
`FinalSessionAnalyses.zip` and `ben-final-sessions.zip`.

For each clean window and each feature, take the largest value across TP9,
AF7, AF8, and TP10. Use inclusive linear interpolation to calculate the
80th, 90th, 95th, and 99th percentiles of those window maxima. Pair every
peak-to-peak percentile with every adjacent-jump percentile to create 16
settings. Both limits use microvolts. A strict exceedance of either limit
on any channel flags a window. Equality passes.

| Clean-training percentile | Peak-to-peak limit (µV) | Adjacent-jump limit (µV) |
| --- | ---: | ---: |
| 80 | 123.6328125 | 46.484375 |
| 90 | 162.109375 | 52.24609375 |
| 95 | 178.22265625 | 60.83984375 |
| 99 | 310.37109375 | 82.08984375 |

All 205 clean windows had the required eight values. The saved grid records
full-precision limits, clean window IDs, session assignments, label releases,
and hashes of the prepared input, session manifest, and search source.
Candidate IDs make the two independently chosen percentiles explicit,
for example `p2p-p80-jump-p99`. The input check reports incomplete clean
windows with their reasons. Numeric calibration uses the labeled clean rows.
Each candidate uses the existing detector's validity, units, and missing-value
checks.

## Run locally

```text
python -m eeg_app.threshold_search derive data/private/nov9/prepared.json data/private/nov9/session-participants.json data/private/thanksgiving/clean-training-grid.json
python -m unittest tests.test_threshold_search
```

Use a new output filename when repeating a command. The historical
development results remain available in `data/private/nov9/comparison.json`.
The new grid is local under the Git-ignored `data/private/thanksgiving/`.

## P0005 validation

The task assigns these three P0005 sessions to development validation:
`ses-hdektduv`, `ses-2v798e9y`, and `ses-frivba5s`. Prepare their
features and reviewed labels with the existing `eeg_app.development_math
prepare` command, using a session-to-participant manifest containing these
three sessions mapped to P0005.

After the reviewed release arrives, run:

```text
python -m eeg_app.threshold_search validate data/private/thanksgiving/clean-training-grid.json data/private/thanksgiving/validation-p0005.json data/private/thanksgiving/threshold-validation.json
```

The report includes confusion counts, recall, precision, clean retention,
accepted contamination, coverage, and uncertain/invalid exclusions for all
16 candidate pairs. It identifies the options with achieved clean retention
closest to 80% and 90%, reports each distance from its target, and breaks ties
toward greater artifact recall, then greater retention. These rankings provide
options for Zach's operating-point approval. The actual values and recall
tradeoffs depend on the reviewed P0005 windows.

Each eligible validation window requires a complete feature record. A
missing required value produces a clear error for that window. Session and
participant checks restrict validation to the three assigned sessions.
The raw signals and labels of reserved repeats were left unopened during this
search.

The completed `P0005-reviews.zip` release contains 53 clean, 35 artifact,
and 20 uncertain labels across the three sessions. The loader separately
identified three technically invalid windows. The validation run scored
all 16 pairs on the same 88 eligible windows and saved
`data/private/thanksgiving/threshold-validation.json`.

The closest available option to both retention targets was
`p2p-p80-jump-p80`, with 50/53 clean retention (94.34%) and 35/35 recall.
It was 14.34 percentage points above the 80% target and 4.34 points above
the 90% target. The grid therefore supplies a higher-retention option
rather than achieving either requested target exactly.

The rule comparison's validation objective recommended
`p2p-p80-jump-p90`, with thresholds 123.6328125 µV peak-to-peak and
52.24609375 µV adjacent jump. This setting gave 53/53 clean retention
and 35/35 recall on P0005. Operating-point approval remains pending.

Namit subsequently confirmed that this review release is preliminary and
awaits Ben and Rushil's independent checks and reconciliation. The prepared
input and reports now carry `label_review_status: preliminary`. Revalidate
the same candidate grid against the reconciled release before recommending
the method freeze.
