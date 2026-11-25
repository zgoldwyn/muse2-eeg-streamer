# Configurable mathematical detector — Part 2

`eeg_app.math_detector` supersedes the fixed >100 microvolt demo for this
assignment. Historical explicitly named demo functions remain for the previous
synthetic exercises; they do not supply defaults to this detector.

## The rule

For a technically valid window, examine peak-to-peak amplitude and maximum
adjacent jump separately on TP9, AF7, AF8, and TP10. Propose `artifact` if
**any channel exceeds either configured threshold**. Otherwise propose `clean`.
Comparison is strictly `>`: equality does not trigger. The same feature limit
applies to each channel. Every trigger is retained, not just the first one.

Each prediction contains the unchanged `window_id`, `decision`, `triggers`,
and settings. Every trigger identifies its channel, feature, exact feature key,
observed value in microvolts, threshold in microvolts, and comparison operator.
A `clean` proposal means neither configured rule triggered; it is not a human
label or a guarantee of artifact-free EEG.

## Settings and threshold rationale

`DetectorSettings` requires `window_length_s`, `peak_to_peak_uv`,
`max_adjacent_jump_uv`, and `selection_note`. There are no automatic numeric
threshold defaults. Both limits must be finite and nonnegative. The window
length must be 2, 4, or 8 seconds, and each record must match that duration.

No artifact thresholds were selected or tuned in Part 2. The implementation
and tests use explicitly synthetic limits solely to verify the comparisons.
For later development, choose provisional values from the training participants
only (`sub-01`, `sub-08`, `sub-09`); apply them unchanged to `sub-10`. Public
task/rest separation is not artifact-label validation. The saved settings
therefore identify their status as `provisional_development` and require a note
explaining how their values were selected. Do not invent a validated threshold
or tune against the held-out participant to complete this implementation.

The six-feature Step 1 summary was inspected. Standard deviation also describes
amplitude; kurtosis reflects shape/tails; approximate entropy changes with
window length; and flatline fraction depends on a fixed tolerance. Their
task/rest associations alone do not justify additional artifact criteria.
This initial rule uses only the two requested features rather than adding an
unsupported extra trigger.

Create settings using explicitly chosen values, then save/reload the same
JSON for repeatable use:

```python
import json
from pathlib import Path
from eeg_app.math_detector import DetectorSettings

# Supply values and a rationale from the agreed development procedure.
settings = DetectorSettings(
    window_length_s=2,
    peak_to_peak_uv=chosen_peak_to_peak_limit,
    max_adjacent_jump_uv=chosen_jump_limit,
    selection_note=threshold_selection_rationale,
)
Path("data/public_muse/detector-settings-2s.json").write_text(
    json.dumps(settings.to_dict(), indent=2), encoding="utf-8"
)
```

The three `chosen_...`/rationale names above are placeholders, not supplied
thresholds. Settings objects are immutable. Later, independently reviewed
development labels can guide the final choices; retain and freeze the exact
settings JSON before sealed evaluation. Do not change it after inspecting
sealed results. No public flagging-rate run, threshold search, or sealed
evaluation is part of this change.

## Validity, missing values, and input compatibility

`predict_window` and `predict_records` accept Namit's existing flattened feature
records unchanged; weak targets, participant/session IDs, event provenance, and
times never enter the numeric rule. `_uv` feature keys follow the shared
microvolt contract. If a record provides an explicit units map, it is checked.

Features alone cannot prove that raw samples are complete and continuous.
Namit's public exporter includes valid windows only, but omits a validity flag.
For such records, the caller must explicitly pass `validity_confirmed=True`
after confirming that upstream contract. Unknown validity otherwise causes
exclusion. Explicit `is_valid=False` or nonempty `invalid_reasons` always
overrides confirmation; loader reasons are retained. The existing loader and
feature adapter continue to own missing-sample/gap checks. Do not bypass them.

All eight required feature values must be available, finite, nonnegative, and
numeric. No missing value becomes zero. Even if one channel exceeds a limit,
an unavailable required value on another channel causes exclusion, not an
incomplete binary proposal. An unavailable unused feature does not block this
two-feature rule. Supplied unavailable-value reasons are preserved in the
exclusion explanation.

Single-record exclusion raises `WindowExcluded`. Batch output separates
`prediction_records` from `excluded_windows`; excluded records have an ID and
reasons but no binary decision. Duplicate/missing IDs are errors.

When settings have been explicitly chosen, the command is:

```text
python -m eeg_app.math_detector data/public_muse/exports/features-2s.jsonl --settings data/public_muse/detector-settings-2s.json --valid-windows-confirmed --output data/public_muse/detector-results-2s.json
```

This command is documented for the next run; it was not run on the public
subset in Part 2. It refuses to overwrite an existing result file. A new
result includes the exact settings, proposed decisions with triggers, and
separate exclusions. No source exports are modified.

## Checks

```text
python -m unittest discover -s tests -p test_math_detector.py -v
```

Tests cover strict boundaries, both features on all four channels, multiple
triggers, missing values even after a trigger, preserved invalid reasons,
unknown validity, units, duration mismatch, metadata independence, immutable
saved settings, repeatability, duplicate IDs, and the CLI on synthetic input.

Verification: all 11 detector tests passed. Full discovery ran 154 tests with
147 passing and 7 skipped. No downloads, dependency installations, public-data
detector runs, or threshold fitting were performed for Part 2.
