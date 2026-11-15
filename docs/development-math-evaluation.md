# Mathematical detector evaluation on reviewed development recordings

Run from the repo root. Store real releases, recordings, manifests, and outputs
in the team's private location. The paths below illustrate a Git-ignored local
workspace. The synthetic integration test uses only the repository fixture.

```text
python -m eeg_app.development_math audit "path/to/FinalSessionAnalyses.zip"
python -m eeg_app.development_math prepare data/private/sessions data/private/session-participants.json data/private/prepared.json --release FinalSessionAnalyses.zip "path/to/FinalSessionAnalyses.zip" --release ben-final-sessions.zip "path/to/ben-final-sessions.zip"
python -m eeg_app.development_math evaluate data/private/prepared.json data/private/folds.json data/private/math-results.json
python -m eeg_app.development_math evaluate data/private/prepared.json data/private/cnn-folds.json data/private/comparison.json --cnn-predictions "path/to/waveform-cnn-held-out-predictions.zip"
python -m eeg_app.development_math investigate data/private/prepared.json data/private/comparison.json data/private/rule-validation.json
python -m unittest tests.test_development_math tests.test_review tests.test_math_detector tests.test_metrics tests.test_window_comparison
```

The run uses the two release filenames shown above. Together they cover
464 reviewed windows across 13 sessions: 205 clean, 213 artifact, and
46 uncertain after applying the confirmed `unsure` mapping.
The loader also identified 16 technically invalid windows. The feature
pipeline returned 24 values for every reviewable window.

Preparation needs each reviewed session's `eeg.csv` and `metadata.json`. The
session-to-participant JSON maps each session ID to its pseudonymous participant
ID. Use the same participant ID for all runs and refits of one person. The
review rows are checked against the original two-second window IDs and
intervals. Preparation keeps all six features per channel, settings, units,
label provenance, and loader exclusion reasons. Original review ZIPs are read
only.

Use Namit's approved `docs/development-split-manifest.json` from
[PR #31](https://github.com/zgoldwyn/muse2-eeg-streamer/pull/31) at commit
`3a9c83772a1163933546a50c125ec777fbdc971a`. Save a copy as `cnn-folds.json`.
The original local format also works as a list of fold objects with
`fold_id`, `training`, `validation`, and `heldout`. Each participant is held
out once. A fold stops if training or validation lacks either class.

The initial two-feature detector derives candidates at the 90th, 95th, and
99th percentiles of each training window's largest value across the four
channels. Validation selects the candidate with the highest mean of clean
retention and artifact recall, breaking ties toward higher recall. Each
selected setting is applied unchanged to its held-out participant. All
candidate validation metrics, held-out metrics, and thresholds are saved.
The resulting thresholds remain provisional development settings. The initial
baseline used the earlier public 2-second limits of 584.45 µV peak-to-peak and
248.88 µV adjacent jump; it flagged 101 of the 418 eligible windows.

The optional CNN input accepts the original ZIP of JSONL files or a JSON list
carrying `window_id`, `decision`, and
`fold_id`; score and version fields can accompany those fields. The scorer
checks held-out fold IDs and requires a prediction for every eligible window.
It reports each detector and the combined rule, which accepts a window when
both decisions are clean. Reports include confusion counts, metric numerators
and denominators, and uncertain and invalid counts. The actual CNN export
passed the ID, session, participant, fold, and completeness checks directly.

## Held-out development results

All three methods scored the same 418 eligible windows from the two review
ZIPs. The evaluator separately counted 46 uncertain and 16 invalid windows.
Validation selected the 90th-percentile math setting in all four folds.

| Detector | TP / FP / TN / FN | Recall | Precision | Clean retention | Accepted contamination | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| Math | 52 / 0 / 205 / 161 | 52/213 | 52/52 | 205/205 | 161/366 | 366/418 |
| CNN | 189 / 53 / 152 / 24 | 189/213 | 189/242 | 152/205 | 24/176 | 176/418 |
| Both must say clean | 189 / 53 / 152 / 24 | 189/213 | 189/242 | 152/205 | 24/176 | 176/418 |

Every math flag was also a CNN flag, so the combined decisions matched the
CNN. These scores use the saved development settings and CNN export. Coverage
differs between detectors. A matched-coverage comparison needs CNN validation
scores to choose the operating point before scoring the held-out predictions.
The delivered CNN ZIP contains held-out scores.

## Additional rule investigation

Each candidate adds one trigger to the saved math baseline. Standard deviation
can capture sustained high variation even when individual jumps are modest.
Flatline fraction can capture long runs of nearly unchanged samples. For each
rule and fold, the threshold is the 95th percentile of the maximum across
channels in windows labeled clean by the training participants. A strict
exceedance on any channel adds a flag. Flatline fraction uses the prepared
features with the 0.1 µV tolerance.

| Validation measure, averaged across folds | Baseline | Add standard deviation | Add flatline fraction |
| --- | ---: | ---: | ---: |
| Balanced accuracy (mean of recall and clean retention) | 62.7% | 82.9% | 60.8% |

Standard deviation improved balanced accuracy on all four validation
participants, with lower clean retention in two folds. Keep it as a candidate
for a future evaluation. Flatline fraction reduced balanced accuracy in two
folds and had a lower average, so drop it from follow-up. This exploration
used training and validation only. Because the baseline held-out results
had already been reviewed, the published held-out comparison keeps the
original rule and settings. The private rule report saves the per-fold
thresholds and validation metrics.

The public-data rerun in PR #27 awaits Namit's importer that reads the
Muse EDF's own markers and the regenerated 2-, 4-, and 8-second exports.
