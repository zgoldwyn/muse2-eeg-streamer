# Public Muse math handoff — Step 1

Use Namit's `make_feature_records` JSONL exports unchanged. The exporter calls
our existing `extract_features_for_windows` adapter on Namit's accepted windows.
The summary script consumes those 24 feature keys directly; it never re-windows,
renames IDs, or uses participant IDs, events, or time as feature values.

The shared split follows Namit's documented setup: `sub-01`, `sub-08`, and
`sub-09` for training and `sub-10` for testing (seed 17). All four participants
appear in each supplied JSONL export; split roles are metadata, not features.

Place the exports under Git-ignored `data/public_muse/exports/`, then run from the repo:

```cmd
python scratch/samuel/summarize_public_features.py data/public_muse/exports/features-2s.jsonl data/public_muse/exports/features-4s.jsonl data/public_muse/exports/features-8s.jsonl > data/public_muse/public-feature-summary.json
```

The report separates lengths and task/rest groups. For each channel-feature
pair it lists available and missing counts, median, quartiles, extrema with
their original window IDs, and example values outside the 1.5-IQR fences.
Quartiles and fences are omitted for groups with fewer than four finite values.
These are descriptive outliers for inspection, not artifact decisions or
provisional detector thresholds. Pooled summaries count windows, so participants
with more windows contribute more. Check the reported participants before
comparing lengths; absent or excluded windows cannot be recovered from JSONL.
Task/rest is a weak event-derived grouping, not artifact ground truth.

Verification on the existing synthetic fixture used the actual exporter from
Namit's `cf42ed8` PR commit with EDF/MAT I/O bypassed. Both valid windows kept
their original IDs and all 24 features; the missing-packet window stayed out.
The synthetic AF7 peak-to-peak values were 11.96 and 306.20 µV, respectively,
for the baseline and planted-disturbance windows. Synthetic task/rest tags
were used only to exercise the report grouping.

## Results from Namit's exports

All 616 records at 256 Hz passed the feature-schema check, with 24 available
values each and no duplicate window IDs. The script used the original windows
and did not recalculate features from EDF samples.

| Duration | Rest | Task | Total |
| --- | ---: | ---: | ---: |
| 2 s | 236 | 124 | 360 |
| 4 s | 116 | 60 | 176 |
| 8 s | 52 | 28 | 80 |

Across all three durations, task medians for peak-to-peak, maximum adjacent
jump, standard deviation, and kurtosis were higher in every channel. Task
approximate entropy medians were lower in all channels. Flatline fractions
were no higher in task on any channel: AF8 and TP10 were consistently lower,
TP9 was equal at the reported precision, and AF7 was equal for 4 s windows
and lower for the other durations.
TP9 had the largest median peak-to-peak and jump values, and AF8 the smallest,
in each task/rest group. These are pooled descriptive comparisons only, not
evidence that a specific window is contaminated.

Median peak-to-peak amplitudes in microvolts:

| Duration / period | TP9 | AF7 | AF8 | TP10 |
| --- | ---: | ---: | ---: | ---: |
| 2 s / rest | 122.06 | 93.02 | 45.41 | 87.88 |
| 2 s / task | 246.33 | 156.97 | 84.23 | 181.14 |
| 4 s / rest | 135.98 | 98.88 | 50.78 | 95.70 |
| 4 s / task | 349.60 | 193.35 | 103.76 | 246.82 |
| 8 s / rest | 143.52 | 90.08 | 54.93 | 103.75 |
| 8 s / task | 389.40 | 242.42 | 124.51 | 279.54 |

The supplied records preserve IDs, times, participants, sample rates, and
weak targets throughout the summary.

The largest peak-to-peak value is 1,940.40 µV on TP9 in
`sub-08_task-BT_acq-Muse2_eeg:w4:0024` (and its overlapping 8 s counterpart
`sub-08_task-BT_acq-Muse2_eeg:w8:0012`). A conspicuous rest-period example is
1,515.10 µV at `sub-08_task-BT_acq-Muse2_eeg:w2:0010`. These are candidates
for raw-trace inspection, not confirmed artifact labels.

The JSONL format omits feature settings, units maps, unavailable reasons, and
raw samples. All supplied values are available, so no unavailable reason is
needed for these particular records. Confirm the fixed flatline tolerance and
feature-generation settings with Namit. The exports establish
structural compatibility, not independent verification of EDF calibration or
feature recalculation from raw samples. This Part 1 check uses Namit's supplied
feature records; it does not claim independent recalculation from raw recordings.

Part 1's export handoff and descriptive summary are complete. The Part 2 rule
is documented separately in `docs/math-detector.md`; no threshold selection
or public-subset detector comparison was performed as part of this handoff.

The full report is saved locally at `data/public_muse/public-feature-summary.json`.
Neither exports nor generated JSON reports are committed.

Public dataset: [EEG dataset of consumer- and research-grade systems](https://doi.org/10.6084/m9.figshare.30162868.v1).
