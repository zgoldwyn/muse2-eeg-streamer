# Preprocessing Input Contract (Draft)

## Purpose and scope

This document defines the initial in-memory format for one short Muse 2 EEG window before it enters preprocessing. It is for synthetic data and early development, not the final saved-recording-file format. Benjamin's recording work will determine how saved data is read, and Shrinithi's work will determine how labels are represented.

The initial validation function is named `validate_eeg_window`. It accepts a mapping from channel names to sample sequences and returns the number of samples per channel when the window is valid.

## Required window contents

Each EEG window must provide these four required channels:

1. `TP9`
2. `AF7`
3. `AF8`
4. `TP10`

The required downstream order is `TP9`, `AF7`, `AF8`, `TP10`. Each channel must contain a nonempty sequence of numeric samples measured in microvolts (uV). All four channels must contain the same number of samples. The nominal sampling rate is 256 Hz.

A valid window must have:

- All four required channel names.
- At least one sample in every channel.
- The same sample count in every channel.
- Only finite numeric values; `NaN`, positive infinity, and negative infinity are invalid.
- Input that is read but never modified by validation.

Extra channels are not part of this first contract. Preprocessing code should operate only on the four required channels until the team decides how extra channels should be handled.

## Small synthetic example

The following is made-up data for demonstrating the interface. It is not real EEG data.

```python
synthetic_window = {
    "TP9": [1.2, 1.0, 0.9, 1.1],
    "AF7": [-0.4, -0.3, -0.5, -0.4],
    "AF8": [0.2, 0.3, 0.1, 0.2],
    "TP10": [1.5, 1.4, 1.6, 1.5],
}

sample_count = validate_eeg_window(synthetic_window)  # 4
```

Every channel has four samples.

## Why these rules matter

### Consistent channel names and ordering

Each Muse channel comes from a different electrode location. Consistent names prevent one channel, such as `AF7`, from being accidentally treated as another, such as `TP10`. A fixed order also matters when a mapping is converted into an array for filtering, plotting, feature extraction, or machine learning: each array column must always represent the same electrode.

### Equal sample counts

At the same sample rate, sample index *i* in each channel should represent the same instant in time. Equal lengths allow the four signals to be aligned and processed together. Different lengths may indicate dropped samples or another recording issue.

### Missing samples and gaps

Missing samples or time gaps must not be silently filled with zeros, repeated values, or interpolation. Filling changes the real signal and could hide an artifact or look like brain activity. The future recorder should preserve timing information and explicitly report gaps or dropped samples.

### Missing required channels

If `TP9`, `AF7`, `AF8`, or `TP10` is missing, `validate_eeg_window` must raise `ValueError` that identifies the missing channel. The remaining channels must not be analyzed as a complete four-channel window.

### Nonnumeric and nonfinite values

If a value is not numeric, `NaN`, positive infinity, or negative infinity, the validator must raise `ValueError`. These values are not usable EEG measurements and could cause later filters, statistics, and machine-learning code to fail or produce misleading results.

## Metadata to accompany a window later

The initial validator receives only the channel-to-samples mapping. A future recorder or enclosing window object should also provide:

- `session_id`
- `window_id`
- `start_time` and `end_time`
- `sampling_rate_hz`
- Sample timestamps or explicit gap/drop indicators
- Device, participant pseudonym, and headset/contact-status information when available

This metadata should remain separate from the four EEG sample sequences.

## Assumptions and questions needing team approval

Current assumptions:

- Samples are already expressed in microvolts.
- The nominal sample rate is 256 Hz.
- Validation checks basic structure and numeric validity; it does not decide whether a valid window contains blink, muscle, motion, or contact artifacts.

Questions for the team:

1. Should extra non-EEG Muse channels be rejected, retained as metadata, or ignored?
2. What timestamp format and precision will the recorder provide?
3. How will the recorder explicitly identify dropped samples or timing gaps?
4. Is 256 Hz always the effective rate, or must later code support measured-rate variation or resampling?

## Handoff notes

The future recorder must provide the four required channels using their exact names, nonempty numeric sequences with aligned lengths, and metadata such as IDs, timing, sampling rate, and explicit gap/drop information. It should not silently repair missing samples before this package receives them.

After `validate_eeg_window` succeeds, Samuel's future feature functions may assume all four required channels exist, have the same positive number of samples, and contain finite numeric values. They should not assume the signals are artifact-free, filtered, re-referenced, normalized, or continuous in time.

The team has intentionally not yet chosen filtering settings, re-referencing, resampling, window duration, gap handling, channel-quality thresholds, artifact-label rules, or window-segmentation policy. Before real preprocessing begins, the team should at least agree on the recorder's gap/timing representation and the window duration and boundary policy.

## Synthetic-session loader and fixed-time windows

`load_synthetic_session` reads a CSV with these required columns:

```text
session_id,elapsed_s,channel,packet_index,sample_in_packet,microvolts
```

It also requires metadata containing `session_id`, `sampling_rate_hz`, and `samples_per_packet`. The loader preserves timestamps and rejects unknown channels, nonfinite values or times, invalid packet/sample positions, rows from another session, and duplicate samples. It never fills missing values or rewrites timestamps.

`create_fixed_windows` returns two-second, non-overlapping windows such as `[0, 2)`, `[2, 4)`, and `[4, 6)`. At 256 Hz, each complete window requires 512 samples per channel. Each returned window includes its stable ID, session ID, start/end time, sampling rate, samples, timestamps, validity status, and invalid reasons.

Equal counts do not prove time alignment or a gap-free recording. Valid windows require aligned, contiguous packet/sample positions and timestamps that match across channels within a 0.0005-second rounding tolerance. Missing, incomplete, mismatched, gapped, and trailing partial windows remain in the output as invalid; no samples are shifted, repeated, zero-filled, or interpolated.

For a valid window, Sam’s future feature code may assume all four required channels have exactly 512 finite numeric samples, aligned positions, and matching timestamps within that tolerance. It must not assume the signal is artifact-free, filtered, normalized, or clinically meaningful.

## Optional reference-label interval join

`join_reference_label_intervals` accepts independently reviewed reference intervals following Shrinithi’s label guide. It does not use observer prompts, markers, or either detector’s output as labels.

A label is assigned only when reviewed interval(s) fully cover the valid window and agree on one label. Clean therefore requires full clean coverage; a missing label never means clean. The project has not selected a final partial-overlap rule, so partial artifact overlap, uncertain boundaries, and conflicting annotations remain unassigned for adjudication rather than being guessed.

Technically invalid windows are reported as `invalid` with their technical reasons. Invalid and uncertain windows remain in the summary and are excluded from primary metrics.