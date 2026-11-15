# Public Muse ML baseline

This module uses a small local subset of the public Figshare EEG dataset, not
participant recordings made by this project. Raw `sourcedata` and
`derivatives` stay under `data/public_muse/`, which is ignored by Git.

## Input contract

For each selected public participant and condition, pair:

- `sourcedata/sub-XX/sub-XX_task-BT_acq-Muse2_eeg.edf`
- `derivatives/sub-XX/sub-XX_task-BT_acq-BLP_eeg.mat`

The EDF provides the four Muse EEG channels (`TP9`, `AF7`, `AF8`, `TP10`) at
its actual recorded sample rate. The reader ignores `Right AUX` and time
channels. For this public Muse EDF dataset, those four channel arrays are
already on a microvolt scale, so the importer preserves that scale for feature extraction.

The paired BLP MATLAB file supplies timing markers only. It is MATLAB v7.3,
read with `h5py`. EEGLAB's one-based event latency is converted as
`(latency - 1) / event_sample_rate`. Codes 1, 2, 4, and 5 define experiment
start, task start, task end, and experiment end. Code 3 is a repeated beep and
is retained as provenance but is not a label boundary.

## Windowing and weak targets

`import_public_muse_recording` supports 2-, 4-, and 8-second non-overlapping
windows, anchored at experiment start. A window is accepted only when it is
fully within one of these marker intervals:

- `[experiment start, task start)`: `rest_period`
- `[task start, task end)`: `task_period`
- `[task end, experiment end)`: `rest_period`

Windows crossing a marker or trailing experiment end remain in the returned
summary as invalid exclusions; no samples are shifted or synthesized. These
are **weak task/rest targets**, not artifact/clean labels and not evidence of
artifact contamination.

## Samuel handoff

`make_feature_records` passes valid public windows directly to Samuel's
`extract_features_for_windows` adapter. The JSON Lines records contain stable
`window_id`, `participant_id`, `session_id`, start/end times, actual sample
rate, flattened six-feature outputs, `weak_target`, and target provenance.
The target/provenance fields are outside `features`; participant, session,
task, event codes, and time are never model inputs.

Samuel can use the same records or call `import_public_muse_recording` and
`make_feature_records` for 2, 4, or 8 seconds. The original four-channel
sample arrays remain available through the returned windows, rather than being
stored in the shareable feature file.

## Baseline

`train_participant_baseline` uses a fixed participant-held-out split. It fits a
training-only median imputer, `StandardScaler`, and
`LogisticRegression(max_iter=1000, class_weight="balanced")`. It saves
`pipeline.joblib`, holdout window IDs with task-period probabilities, and an
auditable summary of counts, class balance, missing-feature columns,
exclusions, and holdout metrics.

The summary must be described as a **weak task-period versus rest-period
check**, not artifact-detection accuracy.

## Example use

```python
from pathlib import Path
from eeg_app.public_muse import import_public_muse_recording, make_feature_records, write_feature_records
from eeg_app.ml_baseline import train_participant_baseline, save_baseline

root = Path("data/public_muse")
all_records = []
for participant in ("sub-01", "sub-08", "sub-09", "sub-10"):
    edf = next((root / "sourcedata" / participant).glob("*_task-BT_acq-Muse2_eeg.edf"))
    mat = next((root / "derivatives" / participant).glob("*_task-BT_acq-BLP_eeg.mat"))
    imported = import_public_muse_recording(edf, mat, window_length_s=2.0)
    all_records.extend(make_feature_records(imported, flatline_tolerance_uv=0.1))

write_feature_records(all_records, "outputs/public_muse/features-2s.jsonl")
result = train_participant_baseline(all_records, holdout_participants=["sub-10"], random_seed=17)
save_baseline(result, "outputs/public_muse/baseline-2s")
print(result.summary)
```

The selected four people and `sub-10` holdout are a reproducible development
split. Keep the same people in the 2-, 4-, and 8-second comparisons.
