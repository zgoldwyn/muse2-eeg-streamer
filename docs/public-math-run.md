# Public subset detector run — Part 3

This run applies the Part 2 rule to Namit's existing 2-second public windows,
preserving their exact IDs. Results are **task/rest flagging fractions**, not
artifact recall, precision, or accuracy. There are no independent artifact
labels for these public examples. A flag is a proposed detector decision;
a non-flag does not establish clean EEG.

## One provisional setting

Training participants: `sub-01`, `sub-08`, `sub-09` (270 windows).
Heldout participant: `sub-10` (90 windows).

For each feature, take its maximum across the four channels within each
training window. Set the limit to the 95th percentile of those training-window
maxima using inclusive linear interpolation. Rest and task training windows
are pooled; the weak targets do not affect threshold selection. Heldout
values are not used to select or modify limits.

The 95th percentile is an explicit initial development heuristic to flag
unusually large values relative to this training subset. It is not a chosen
false-positive rate or a validated clinical/artifact threshold. No percentile
search or optimization was performed. The setting was fixed before applying
it unchanged to the heldout participant. The immutable settings object and
saved JSON record this provenance.

| Feature | Threshold in µV | Comparison |
| --- | ---: | --- |
| Peak-to-peak amplitude | 584.448217760586 | strictly greater than |
| Maximum adjacent jump | 248.87632014740214 | strictly greater than |

Flag if either threshold is exceeded on any channel. All triggers are retained.
Missing required features or explicit invalidity cause exclusion, not a clean
decision. The export contains only Namit's accepted windows; it does not
include counts for his earlier boundary exclusions. No additional feature
criterion or amplitude rescaling was introduced.

## Run and output

From the repository root, using a new output directory:

```text
python -m eeg_app.public_math_run data/public_muse/exports/features-2s.jsonl --training-participants sub-01 sub-08 sub-09 --heldout-participants sub-10 --window-length-s 2 --output-dir data/public_muse/part3-2s
```

| Split | Weak period | Flagged / predicted | Fraction flagged |
| --- | --- | ---: | ---: |
| Training | Rest | 3 / 177 | 1.69% |
| Training | Task | 17 / 93 | 18.28% |
| Heldout | Rest | 0 / 59 | 0.00% |
| Heldout | Task | 2 / 31 | 6.45% |

All 360 exported IDs received one prediction; zero records were excluded at
this detector-input stage. Flags occur more often in task in this run, but
that is not evidence that the weak targets identify contaminated windows.

Local ignored output under `data/public_muse/part3-2s/`:

- `settings.json`: the exact selected setting and rationale.
- `predictions.json`: only `window_id` and `decision`, directly accepted by the
  existing evaluator once matching independent reference records exist.
- `report.json`: all channel/feature/value/threshold triggers, split-specific
  fractions, selection window IDs, exclusions, source-export SHA-256, and trace
  example metadata.
- `analyst-traces/index.html`: four trace-backed examples with provisional
  decisions. This folder is for analysts, never blinded reviewers.

Public predictions must not be evaluated against labels from unrelated pilot
windows. For later dashboard sessions, generate predictions for those same
independently labeled IDs. Neither mathematical nor ML predictions should be
visible to reviewers before their labels are finalized. Namit's model must be
retrained on the appropriate independent development labels for that later
comparison. This run does not make that comparison or invent reference labels.

## Trace-backed examples

Only matching files for the two participants used in the examples (`sub-01`
and `sub-10`) were retrieved from the public dataset: each participant's BT
Muse2 EDF and companion BLP MAT marker file. The other participants' raw files
were not downloaded. Selective ZIP byte ranges avoid a full dataset download.
Raw recordings remain in `data/public_muse/trace-inputs/`, ignored by Git.

Public source: [Figshare EEG dataset](https://doi.org/10.6084/m9.figshare.30162868.v1).

Reproduce the examples after installing `mne` and `h5py` in the project virtual
environment (MNE supplies the matplotlib plotting dependency):

```text
python -m scratch.samuel.public_trace_examples --download
```

Omit `--download` to reuse local source files. The output directory must be
new; the script refuses to overwrite existing plots. It pins Namit's exact
importer source at `54ad8e17a2e8036f2ad03041df8084f12bfddfee`, without merging
his PR or changing his windowing. It matches window IDs, time intervals,
validity, and weak targets, then recalculates all six features per channel
from the underlying samples using the existing feature adapter. The fixed
flatline tolerance used for verification is 0.1 µV.

**All 96 feature comparisons passed** across the four examples, using relative
tolerance 1e-9 and absolute tolerance 1e-10. Raw-sample decisions and triggers
also matched the saved run. Settings and predictions are left unchanged.
`verification.json` records the importer/source hashes and verification details.
No filtering or resampling is applied. Each plot uses a common vertical scale
across its four channels; the scale may differ between plots.

| Participant / window suffix | Interval | Proposed decision | Trace-backed observation |
| --- | --- | --- | --- |
| `sub-01`, `w2:0031` | `[63, 65)` | Flag | Large late TP9 excursion: peak-to-peak 909.17 µV and adjacent jump 427.25 µV exceed their limits. TP10 jump 272.93 µV also triggers. |
| `sub-01`, `w2:0000` | `[1, 3)` | No flag | All channels remain below both configured limits; oscillations are still visible. This does not establish artifact-free EEG. |
| `sub-10`, `w2:0046` | `[93, 95)` | Flag | A sharp TP9 change near 94.6 s yields adjacent jump 303.23 µV, above 248.88 µV. |
| `sub-10`, `w2:0000` | `[1, 3)` | No flag | Waveforms vary on all channels, but neither rule triggers. This is not an independent clean label. |

Full IDs retain the session prefix `sub-XX_task-BT_acq-Muse2_eeg:`. These are
illustrative examples selected deterministically as the first matching ID for
each split/decision, not a representative sample or an estimate of performance.
Plots were visually inspected for readable channels, times, and trigger notes.

The EDF physical-dimension labels are unspecified (`n/a`). These examples use
Namit's dataset-specific sample-unit convention exactly, with no extra scaling,
and establish numerical agreement with his exports rather than an independent
metrological calibration of the recording hardware.

## Scope and checks

Tests verify training-only limit selection, independence from task/rest labels,
preserved IDs, missing-value exclusions, split overlap and duplicate rejection,
evaluator-ready output shape, and rejection of mismatched raw feature values.
No task/rest targets are passed to the artifact evaluator.

Verification: full discovery ran 162 tests, with 155 passing and 7 existing
tests skipped. The eight new public-run/trace-verification tests passed.
All four generated plots were visually inspected, and hashes confirmed that
the saved settings and predictions were unchanged during trace verification.

This is one 2-second provisional run. The subsequent
[Part 4 comparison](public-window-length-comparison.md) recalculates all three
lengths from the same recordings and reports length-specific provisional
limits and stability. No independent pilot-label evaluation or final
threshold selection is claimed here.
