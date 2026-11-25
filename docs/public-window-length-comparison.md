# Public window-length comparison — Part 4

This compares the shared public BT recordings using Namit's existing IDs,
window generator, and participant split. Results describe **provisional
task/rest flagging**, not artifact-detection accuracy. No human labels or
sealed sessions were used, and no final window length was selected.

## Shared inputs and recalculation

Training participants are `sub-01`, `sub-08`, and `sub-09`; `sub-10` remains
held out. This is the split documented in Namit's handoff.

For each participant, use the matching BT Muse2 EDF and BLP MAT event file
under local ignored `data/public_muse/trace-inputs/`. The remaining two
training participants' matching files were retrieved for this comparison;
Part 3 had needed raw files for only two participants' examples.

The runner pins Namit's importer at
`54ad8e17a2e8036f2ad03041df8084f12bfddfee`. It uses that function separately
at 2, 4, and 8 seconds, anchored at experiment start, without changing IDs or
shifting samples. Each accepted window passes its actual four-channel arrays
to the existing `extract_window_features` function. At 256 Hz, that means
512, 1,024, or 2,048 samples per channel. **Features are never averaged from
two-second records.** All six features are recalculated per channel.

Feature parameters remain fixed: flatline tolerance 0.1 µV; approximate
entropy `m=2`, tolerance 0.2 times the window/channel population standard
deviation, natural logarithms, inclusive matches, and self-matches. Population
standard deviation and Pearson kurtosis retain their existing definitions.
Settings, actual entropy tolerances, units, and unavailable-value reasons
are retained separately in each recalculation audit.

Recalculated IDs, session/participant IDs, intervals, sample rates, weak
targets, provenance, and feature keys must match Namit's unedited exports.
Numeric comparisons use relative tolerance 1e-9 and absolute tolerance 1e-10.
The detector accepts those export fields directly; no manual field renaming
or new target encoding is involved.

All **14,784 feature comparisons passed** across 616 accepted windows. Saved
predictions retained every accepted ID and excluded every loader-rejected ID.
Repeated predictions with reversed input order matched by ID at all lengths.

Values retain Namit's dataset-specific microvolt convention. EDF physical
dimension headers are unspecified (`n/a`), so matching the exports establishes
numerical agreement rather than independent hardware-unit calibration.

### Exclusions and continuity limits

The importer retains ambiguous task/rest crossings and trailing partial
intervals as exclusions. Additional guards reject incomplete/nonfinite
four-channel arrays and any window intersecting an explicit recording-gap
annotation. A point discontinuity excludes windows straddling that point;
half-open intervals touching a gap without overlapping remain eligible.
Discontinuous EDF+D inputs are refused rather than silently stitched into
a continuous signal. Excluded IDs, original intervals, and reasons remain
in the reports; they receive no binary prediction.

These four files declare EDF+C and contain no explicit gap annotations.
Their accepted arrays have the expected sample counts. This does **not**
establish that a dropout hidden before EDF export never occurred: an
unmarked, already filled or compressed gap cannot be reconstructed from
these inputs. No samples are filled or shifted by this comparison.

| Length | Usable training | Usable heldout | Total usable | Loader exclusions |
| --- | ---: | ---: | ---: | ---: |
| 2 s | 270 | 90 | 360 | 8 |
| 4 s | 132 | 44 | 176 | 8 |
| 8 s | 60 | 20 | 80 | 12 |

The exclusions are boundary/trailing intervals, not human artifact labels.
Different lengths retain different intervals and durations because the
windows must fit fully inside one weak period.

## Training distributions and provisional limits

Inspect training distributions separately at each length. The table shows
per-window maxima across the four channels, pooled across training task/rest
periods. No heldout values or weak target labels select the limits.

| Length | Feature | Training median (µV) | Training maximum (µV) | Selected 95th percentile (µV) |
| --- | --- | ---: | ---: | ---: |
| 2 s | Peak-to-peak | 194.57 | 1,568.33 | 584.45 |
| 2 s | Adjacent jump | 102.78 | 467.27 | 248.88 |
| 4 s | Peak-to-peak | 221.43 | 1,940.40 | 736.14 |
| 4 s | Adjacent jump | 113.53 | 467.27 | 309.12 |
| 8 s | Peak-to-peak | 242.41 | 1,940.40 | 1,013.20 |
| 8 s | Adjacent jump | 128.40 | 467.27 | 326.89 |

The distributions have large upper tails, and longer windows expose larger
extremes. Retain Part 3's transparent provisional heuristic: independently
select each feature's inclusive, linearly interpolated training 95th
percentile at each length. No percentile search or heldout tuning was done.
This is not a validated artifact threshold or a guaranteed false-positive
rate. Full-precision limits and training selection IDs are saved in JSON.

Apply each setting unchanged to `sub-10`. Propose artifact if **any** of
TP9, AF7, AF8, or TP10 strictly exceeds either limit. Equality does not flag.
All eight required values must be available; missing required features
cause exclusion, never an automatic clean proposal. No additional feature
trigger was added on the basis of weak task/rest comparisons.

| Length | Split | Rest flagged / usable | Rest fraction | Task flagged / usable | Task fraction |
| --- | --- | ---: | ---: | ---: | ---: |
| 2 s | Training | 3 / 177 | 1.69% | 17 / 93 | 18.28% |
| 2 s | Heldout | 0 / 59 | 0.00% | 2 / 31 | 6.45% |
| 4 s | Training | 2 / 87 | 2.30% | 9 / 45 | 20.00% |
| 4 s | Heldout | 0 / 29 | 0.00% | 0 / 15 | 0.00% |
| 8 s | Training | 1 / 39 | 2.56% | 5 / 21 | 23.81% |
| 8 s | Heldout | 0 / 13 | 0.00% | 0 / 7 | 0.00% |

Zero heldout flags at a longer length is not evidence of better artifact
detection: the thresholds, intervals, and number of windows differ. A
non-flag is a proposed decision, not an independent clean reference label.

## Feature stability

Use training participants only. For each participant × weak period × channel
group, calculate median, IQR, IQR/absolute median, and median absolute change
between adjacent retained windows. Adjacent changes cannot bridge an
excluded window, session, or task/rest boundary. Summaries below are medians
across the 24 groups, not pooled estimates of artifact performance.

| Feature | Relative IQR, 2 s | Relative IQR, 4 s | Relative IQR, 8 s |
| --- | ---: | ---: | ---: |
| Peak-to-peak | 0.248 | 0.200 | 0.159 |
| Adjacent jump | 0.220 | 0.189 | 0.137 |
| Flatline fraction | 0.500 | 0.345 | 0.214 |
| Standard deviation | 0.177 | 0.145 | 0.120 |
| Kurtosis | 0.206 | 0.175 | 0.141 |
| Approximate entropy | 0.0525 | 0.0434 | 0.0364 |

Approximate entropy's median group estimate rises from 1.284 to 1.492 to
1.625. Its raw IQR is 0.0662, 0.0664, and 0.0557; its median adjacent
absolute change falls from 0.0473 to 0.0392 to 0.0317. Longer windows show
less relative dispersion and smaller adjacent entropy changes here, but
four-second raw entropy IQR is not lower than two-second IQR. Entropy also
has finite-sample dependence and a changing per-window tolerance.

The descriptive stability evidence is therefore qualified. Longer windows
have fewer observations and different boundary exclusions. Larger adjacent
jumps themselves have increasing median adjacent changes (5.62, 6.59,
8.67 µV), despite lower relative IQR. These observations do not establish
that every feature or the detector improves with longer windows.

## Repeat locally

Use the project's virtual environment with `mne` and `h5py` installed. The
pinned importer commit must be available in the local Git object database.
Put the three original feature exports in `data/public_muse/exports/` and
the four matching EDF/MAT pairs in `trace-inputs/` as above. This comparison
command performs no downloads and requires a new output directory:

```text
python -m scratch.samuel.compare_public_window_lengths --output-dir data/public_muse/part4-window-comparison
python -m unittest discover -s tests
```

Ignored output contains `comparison.json`, recalculated `features-2s.jsonl`,
`features-4s.jsonl`, and `features-8s.jsonl`, plus per-length settings,
predictions, trigger reports, loader exclusions, and stability statistics.
Recalculation audits include source hashes and feature settings/reasons.
The per-length `predictions.json` files contain only `window_id`/`decision`,
the schema accepted by `eeg_app.metrics`. Neither predictions nor analyst
reports belong in a blinded reviewer bundle.

Reversing record order and repeating prediction must produce the same
ID-keyed results using the saved immutable settings. Tests cover threshold
boundaries on both features and every channel at all three lengths,
missing values, invalid arrays, gaps, preserved boundary reasons, direct
sample-based extraction, training-only selection, and repeatability.

The full test suite ran 169 tests successfully, with seven existing skips.

## Later independently labeled evaluation

Independent reviewed development recordings are still needed to choose the
final length and refine thresholds. Once available, compare eligible IDs
with `eeg_app.metrics.evaluate_predictions`; report its recall, clean
retention, accepted contamination, and coverage with counts and denominators.
Keep uncertain and invalid exclusions separate. Do not substitute public
task/rest targets for those reference labels.

Freeze the chosen length, feature parameters, detector limits, and selection
provenance before sealed repeat-session evaluation. Do not adjust them after
looking at sealed results. This comparison supplies provisional settings
and evaluator-compatible predictions; it does not claim to complete that
future label-dependent evaluation.
