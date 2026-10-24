# Preprocessing Input Contract (Draft)

## Purpose and scope

This document defines the initial in-memory format for one short Muse 2 EEG window before it enters the preprocessing pipeline. It is intentionally a small contract for synthetic data and early development, not the final format for saved recording files. Benjamin's recording work will determine how saved data is read, and Shrinithi's work will determine how labels are represented.

The initial Python validation function is named `validate_eeg_window`. It accepts a mapping from channel names to sample sequences and returns the number of samples in each channel when the window is valid.

## Required window contents

Each window must provide exactly these required EEG channels:

1. `TP9`
2. `AF7`
3. `AF8`
4. `TP10`

The required channel order for downstream processing is `TP9`, `AF7`, `AF8`, `TP10`. The input mapping may be dictionary-like, but any code that converts the mapping into an array must use this explicit order rather than relying on the order in which keys happened to be added.

Each required channel must contain a nonempty sequence of numeric samples measured in microvolts (uV). All four channels must have the same number of samples. The nominal sample rate is 256 Hz. Sample rate is metadata that accompanies the window rather than a fifth signal channel.

For this first contract, a valid window has the following properties:

- All four required channel names are present.
- Each channel has at least one sample.
- Every channel has the same sample count.
- Every sample is numeric and finite; `NaN`, positive infinity, and negative infinity are invalid.
- Validation reads the input only and does not modify the original mapping or its sample sequences.

Extra channels are not part of this initial contract. If a future recorder provides extra channels, the team should decide whether the validator should reject them, preserve them as metadata, or explicitly ignore them. Until that decision is made, preprocessing code should operate only on the four required channels.

## Small synthetic example

The following made-up window has four samples per channel. Its values are in microvolts and are only for demonstrating the interface; they are not real EEG data.

```python
synthetic_window = {
    "TP9": [1.2, 1.0, 0.9, 1.1],
    "AF7": [-0.4, -0.3, -0.5, -0.4],
    "AF8": [0.2, 0.3, 0.1, 0.2],
    "TP10": [1.5, 1.4, 1.6, 1.5],
}

sample_count = validate_eeg_window(synthetic_window)  # 4
```

## Why these rules matter

### Consistent channel names and ordering

Each Muse electrode has a distinct physical location. Consistent names ensure that `AF7`, for example, is never accidentally treated as `TP10`. A fixed ordering is equally important when the mapping is converted to a matrix for filtering, plotting, feature extraction, or a machine-learning model: column one must always represent the same electrode. Otherwise, a model could learn from mismatched signals and produce unreliable results.

### Equal sample counts

At a shared sample rate, sample index *i* in every channel should represent the same moment in the window. Equal lengths allow the channels to be aligned into a four-by-*N* structure and compared or processed together. Different lengths make that alignment ambiguous and may hide a dropped sample or a recording problem.

### Missing samples and gaps

Missing samples or time gaps must not be silently filled with zeros, repeated values, or interpolation. Filling changes the signal and could look like real brain activity or hide an artifact. The recorder should preserve enough timing information to identify gaps, and a window affected by a gap should be marked or rejected according to a future team decision.

### Required channels that are missing

If any of `TP9`, `AF7`, `AF8`, or `TP10` is missing, the validator must raise `ValueError` that identifies the missing channel. It must not analyze the remaining three channels as though they form a complete four-channel window.

### Nonnumeric and nonfinite values

If a sample is not numeric, or is `NaN`, positive infinity, or negative infinity, the validator must raise `ValueError` with the channel and sample position when practical. Such values are not valid EEG measurements and can cause later filters, statistics, and machine-learning code to fail or yield misleading output.

## Metadata to accompany a window later

The initial validation function accepts only the channel-to-samples mapping. The recorder or an enclosing window object should later accompany it with metadata such as:

- `session_id`: identifies the recording session.
- `window_id`: uniquely identifies this window within a session.
- `start_time` and `end_time`: identify when the window occurred, preferably in a documented timestamp format.
- `nominal_sample_rate_hz`: records the expected headset sampling rate (initially 256 Hz), rather than a rate measured from the computer clock.
- Sample timestamps or gap/drop indicators: preserve timing irregularities instead of concealing them.
- Recording/device context when available, such as device identifier, participant pseudonym, and headset/contact status.

Metadata should be separate from the four EEG channel arrays so that future feature and preprocessing code can receive a clear, validated signal matrix.

## Synthetic-session loader and fixed-time windows

`load_synthetic_session` reads a CSV with these required columns:

```text
session_id,elapsed_s,channel,packet_index,sample_in_packet,microvolts
```

It also requires JSON metadata with `session_id`, `nominal_sample_rate_hz`, and `samples_per_packet`; `development_session_ids` is optional metadata used to exclude sessions that are outside the current development set. The loader returns a `LoadedSession` containing the preserved, validated rows and this metadata. It rejects unknown channels, nonfinite values or times, invalid packet/sample indices, rows from another session, and duplicate sample rows. Because Muse packet indices wrap, an exact duplicate is identified by channel, packet index, sample position, and timestamp rather than packet index alone. It never fills missing values or rewrites timestamps.

`create_fixed_windows` then returns two-second, non-overlapping `EegWindow` objects with intervals `[0, 2)`, `[2, 4)`, and so on. At the initial nominal rate of 256 Hz, each complete window needs 512 samples per channel. The shared session metadata uses the exact fields `nominal_sample_rate_hz: 256` and `samples_per_packet: 12`; nominal means the headset's expected rate, not a rate measured from the computer clock. Each window keeps its stable `window_id`, session ID, start/end time, sampling rate, channel-to-samples mapping, channel time grids, validity flag, and invalid reasons separate from the values that may later become model inputs.

Equal counts alone do not prove that channels are time-aligned or gap-free. For this draft, sample positions must be contiguous and match across all channels, and every channel must independently follow the expected 256 Hz time grid within a 0.0005-second rounding tolerance. This rejects a window where all four channels share the same compressed or gapped timestamps. Muse packet indices are treated as unsigned 16-bit counters: chronological continuity may wrap from 65535 to 0. Timestamps, rather than numerical packet-index sorting, establish the chronological row order.

Windows with a gap, missing or incomplete channel, mismatched positions or times, or trailing partial duration are retained as invalid windows with their reasons; later samples are never shifted earlier and no zeros, repeats, or interpolation are inserted.

## Assumptions and questions needing team approval

Current assumptions:

- Incoming channel samples are already expressed in microvolts.
- 256 Hz is the nominal sample rate for the initial synthetic examples.
- This validator confirms basic shape and numeric validity; it does not decide whether an otherwise valid window contains blink, muscle, motion, or contact artifacts.

Questions for the team:

1. Should windows with extra, non-EEG Muse channels be rejected, retained as metadata, or ignored by the validator?
2. What timestamp format and precision will the recorder provide, and how will it explicitly report dropped samples or timing gaps?
3. Should a temporarily missing required channel invalidate only that window, or should it end or flag the full recording session?
4. Is 256 Hz always the effective rate from the recorder, or must downstream code support measured rate variation or resampling?

## Handoff notes

The recorder needs to provide the four required channels by their exact names, nonempty numeric sample sequences with aligned lengths, and accompanying window metadata such as IDs, timing, sampling rate, and explicit gap/drop information. It should not silently repair missing samples before this package receives the data.

After a window is marked valid, Samuel's future feature functions may assume the four required channels exist, each has exactly 512 finite numeric samples in the documented order, packet/sample positions are aligned and contiguous (including valid 65535-to-0 packet-index wraparound), and the preserved timestamps both match across channels and follow the expected 256 Hz grid within the documented tolerance. They should not assume the signal is artifact-free, filtered, re-referenced, normalized, or clinically meaningful.

The following preprocessing decisions are intentionally deferred: gap handling, filter types and settings, detrending, re-referencing, resampling, channel quality thresholds, artifact labels, and how windows are segmented from an ongoing recording. Before real preprocessing begins, the team should at least agree on the recorder's timing/gap representation and the window duration and boundary policy. The team should also decide how contact-quality information is represented and whether it changes validation or later artifact classification.

## Week 3 downstream handoff: actual valid window

The following is a real valid `EegWindow` returned from Ben's unchanged synthetic session, `integration-demo-001`. It is the first fixed-time window, covering the half-open interval `[0.0, 2.0)`.

```text
EegWindow(
    window_id="integration-demo-001:window-000000",
    session_id="integration-demo-001",
    start_time_s=0.0,
    end_time_s=2.0,
    nominal_sample_rate_hz=256.0,
    channel_samples={
        "TP9":  (0.0, 1.0, 1.93, 2.76, 3.42, ..., -3.89, -3.42, -2.76, -1.93, -1.0),
        "AF7":  (5.0, 6.0, 6.93, 7.76, 8.42, ..., 1.11, 1.58, 2.24, 3.07, 4.0),
        "AF8":  (-5.0, -4.0, -3.07, -2.24, -1.58, ..., -8.89, -8.42, -7.76, -6.93, -6.0),
        "TP10": (10.0, 11.0, 11.93, 12.76, 13.42, ..., 6.11, 6.58, 7.24, 8.07, 9.0)
    },
    channel_times_s=<one preserved timestamp per sample in each channel>,
    is_valid=True,
    invalid_reasons=()
)
```

Each channel array contains exactly 512 finite microvolt samples, even though the example above shows only the beginning and end of each array. Samuel should use a window for feature calculations only when `is_valid` is `True`. In that case, he can rely on the four expected channels being present in the documented order, each having 512 aligned samples on the 256 Hz time grid, with no missing or duplicated positions.

Samuel must still treat validity as a technical data-quality check, not a clinical or artifact-cleanliness decision. A valid window is not automatically filtered, normalized, re-referenced, artifact-free, or clinically meaningful. Invalid windows remain available for reporting through `invalid_reasons`, but must not be used as continuous EEG input for feature calculations.

## Optional reference-label interval join

`join_reference_label_intervals` is a separate optional step. It accepts only independently reviewed `ReferenceLabelInterval` records following Shrinithi's draft guide; it does not read observer prompts, markers, mathematical-detector outputs, or AI-detector outputs as labels.

For a technically valid window, a reference label is assigned only when one or more reviewed intervals fully cover the complete window and agree on the same operational label (`clean`, `artifact`, `uncertain`, or `invalid`). In particular, clean requires full clean coverage; an absent interval is never treated as clean.

The project has not adopted a final partial-overlap rule. Therefore, an artifact interval that overlaps only part of a window is retained with status `needs_adjudication`, not automatically promoted to an artifact label. The same is true for partial clean or uncertain intervals. If a label carries nonzero boundary uncertainty and only partly overlaps a window, the join records that explicit reason for human adjudication. Conflicting overlapping annotations also remain unassigned with status `conflicting_reference_labels`; the guide's independent review and adjudication process must resolve them.

When preprocessing has already marked a window invalid, the join reports it as `invalid` with status `technical_invalid` and preserves the technical reasons. This is not a human artifact decision. Invalid and uncertain windows remain in the summary and are excluded from primary metric calculations as specified in the label guide.