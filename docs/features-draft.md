## Peak-to-peak Amplitude:

Peak-to-peak Amplitude measures the difference between the largest and smallest value in a window. In other words, the vertical distance from the highest point to the lowest point.
It can be calculated as:

```text
peak-to-peak = maximum value − minimum value
```

## Maximum Adjacent Jump:

Maximum Adjacent Jump measures the largest absolute change between two consecutive samples. In other words, the highest "jump" between two back-to-back values.
It can be calculated as:

```text
maximum adjacent jump = maximum of |current sample − previous sample|
```

## Synthetic Window Testing:

### Window A: [1, 1, 1, 1, 1]

```text
peak-to-peak = maximum value − minimum value
peak-to-peak = 1 − 1
peak-to-peak = 0 μV
```

```text
maximum adjacent jump = maximum of |current sample − previous sample|
maximum adjacent jump = max(|1 − 1|, |1 − 1|, |1 − 1|, |1 − 1|)
maximum adjacent jump = max(0, 0, 0, 0)
maximum adjacent jump = 0 μV
```

With a peak-to-peak of 0 and a maximum adjacent jump of 0, this window is perfectly flat, with every sample having the same amplitude.

### Window B: [0, 0, 10, 0, 0]

```text
peak-to-peak = 10 − 0
peak-to-peak = 10 μV
```

```text
maximum adjacent jump = max(|0 − 0|, |0 − 10|, |10 − 0|, |0 − 0|)
maximum adjacent jump = max(0, 10, 10, 0)
maximum adjacent jump = 10 μV
```

With a peak-to-peak of 10 and a maximum adjacent jump of 10, this window fluctuates more than Window A, and consists of a significant jump of amplitude 10.

### Custom Window: [-100, -10, 0, 60, 120]

```text
peak-to-peak = 120 - -100
peak-to-peak = 120 + 100
peak-to-peak = 220 μV
```

```text
maximum adjacent jump = max(|-100 − -10|, |-10 − 0|, |0 − 60|, |60 − 120|)
maximum adjacent jump = max(|-90|, |-10|, |−60|, |-60|)
maximum adjacent jump = max(90, 10, 60, 60)
maximum adjacent jump = 90 μV
```

This window illustrates the idea that a maximum jump can be between two negative values, and that the peak-to-peak range can span from a negative number to a positive number.

## What the features can and cannot tell us:

1. What produces a large peak-to-peak value?
A large difference between the highest and lowest samples produces a large peak-to-peak value. This can happen through either a sudden change or a gradual rise or fall.
2. What produces a large adjacent jump?
A sudden, large change between two consecutive samples produces a large adjacent jump.
3. Can a clean EEG window still produce a large value?
Yes, because even though there are not significant artifacts in a clean window, normal brain activity can still vary in amplitude.
4. Can an artifact produce a small value?
Yes, an artifact is an unwanted disturbance, such as muscle activity, headset movement, or a recording problem. A subtle physical disturbance or ecording failure could produce small values.
5. How could one unusual sample affect each feature?
One unusually high or low sample can increase peak-to-peak amplitude even when the other samples are steady, which could be deceptive. It can also create a large adjacent jump between that sample and its neighbors.
6. How might window length affect the result?
Longer windows contain more samples and neighboring pairs, giving both features more chances to encounter an extreme change.
7. Why should missing values or recording gaps not be treated as zero?
Zero means a value of zero µV was actually measured, whereas a missing value means no measurement is available. Replacing missing values with zero could create artificial extremes or jumps, so features should not be calculated across them.
8. Should features be calculated separately for TP9, AF7, AF8, and TP10?
Yes, calculating features separately preserves information about which channel contains an unusual change. Each of these channels contains EEG information from the left ear, left forehead, right forehead, and right ear, respectively.
9. How could per-channel results become one window-level decision?
We could combine the features from each channel into a window-level unusualness score, allowing one highly unusual channel to raise the score substantially. We could also scale the features relative to their typical values so neither dominates simply because its numbers tend to be larger.

### Peak-to-peak limitations:

1. It cannot distinguish a gradual change from a sudden change with the same overall range.
2. One extreme sample can dominate the result.
3. It can miss a constant offset or flat signal caused by a recording problem.

### Maximum adjacent jump limitations:

1. It can miss gradual drift because each individual step may be small.
2. One unusual sample can dominate the result.
3. Its value depends on the sampling rate, which affects how much time passes between consecutive samples. Long delays between samples could miss large jumps.

These feature functions could help summarize what is happening in each validated EEG window. We can use peak-to-peak amplitude to give information about the range of activity within a channel, and we can use maximum adjacent jump to tell us how quickly the signal changes between consecutive samples.

A four-channel window now produces the feature values, calculation settings,
and unavailable-value reasons described below.

## Additional feature definitions and examples

All input samples and tolerances are in microvolts (µV). Samples must be finite
numeric values; missing values, NaN, infinity, and booleans are rejected.

### Flatline fraction

```text
flatline fraction = count(|samples[i] - samples[i-1]| <= tolerance_uv) / (N - 1)
```

This unitless fraction measures how often neighboring values barely change.
It requires two samples and a finite, nonnegative tolerance. For
`[1, 1, 1, 2, 2]` with tolerance `0 µV`, the changes are `[0, 0, 1, 0]`, giving
`3 / 4 = 0.75`. A constant signal gives one, but may reflect a recording problem
rather than usable EEG. Results depend on sampling rate and tolerance; this
feature also ignores the size of changes that exceed the tolerance.

### Standard deviation and kurtosis

```text
mean = sum(samples) / N
variance = sum((sample - mean)^2) / N
standard deviation = sqrt(variance)
fourth central moment = sum((sample - mean)^4) / N
Pearson kurtosis = fourth central moment / variance^2
```

Both use population moments, dividing by N. Standard deviation is in µV;
kurtosis is dimensionless. The kurtosis convention does not subtract three
and does not apply bias correction. Constant signals have standard deviation
zero and kurtosis None, because division by zero variance is undefined.

For `[0, 0, 0, 0, 10]` µV:

```text
mean = 10 / 5 = 2 µV
variance = (4 + 4 + 4 + 4 + 64) / 5 = 16 µV²
standard deviation = sqrt(16) = 4 µV
fourth central moment = (16 + 16 + 16 + 16 + 4096) / 5 = 832 µV⁴
Pearson kurtosis = 832 / 16² = 3.25
```

| Synthetic window (µV) | Standard deviation (µV) | Pearson kurtosis |
| --- | ---: | ---: |
| Smooth: `[0, 1, 2, 3, 4]` | 1.414214 | 1.700000 |
| One spike: `[0, 1, 20, 3, 4]` | 7.337575 | 3.069025 |

The spike increases spread and contributes strongly to the fourth moment.
Standard deviation does not capture sample order or distinguish physiological
variation from artifacts. Kurtosis can be dominated by one extreme value and
is unstable in short windows; it also ignores sample order. Neither feature
alone establishes whether an artifact is present.

### Approximate entropy

For each length L, form all `N - L + 1` overlapping templates. Compare each
template with every template of that length, including itself. A match requires
every corresponding absolute difference to be at most the tolerance.

```text
C_i(L) = matches for template i / (N - L + 1)
phi(L) = sum(ln(C_i(L))) / (N - L + 1)
approximate entropy = phi(m) - phi(m + 1)
```

This is dimensionless approximate entropy using natural logarithms, separate
averages for each length, self-matches, and an inclusive tolerance. It is not
sample entropy. It requires a positive integer m, a finite nonnegative tolerance,
and at least `m + 2` samples.

For `[0, 0, 0, 1, 0, 0]` µV, `m = 2`, and tolerance `0.1 µV`:

| Length | Templates in position order | Match counts | Match fractions |
| --- | --- | --- | --- |
| 2 | `[0,0]`, `[0,0]`, `[0,1]`, `[1,0]`, `[0,0]` | `[3,3,1,1,3]` | `[3/5,3/5,1/5,1/5,3/5]` |
| 3 | `[0,0,0]`, `[0,0,1]`, `[0,1,0]`, `[1,0,0]` | `[1,1,1,1]` | `[1/4,1/4,1/4,1/4]` |

```text
phi(2) = [3 * ln(3/5) + 2 * ln(1/5)] / 5 = -0.950270539
phi(3) = ln(1/4) = -1.386294361
approximate entropy = 0.436023822
```

Constant samples with zero tolerance give one for every match fraction, so
both phi values and approximate entropy are zero. A disconnected or failed
sensor could also produce a constant signal, so zero does not establish quality.

For `[0, 1, 2, 3]`, `m = 2`, and zero tolerance, all templates match only
themselves. `phi(2) = -ln(3)` and `phi(3) = -ln(2)`, giving `-0.405465108`.
This negative finite-sample estimate reflects the different template populations
and self-match contribution, not negative physical randomness. It is preserved,
not silently clamped to zero.

### Window length and runtime

Following the assignment's starting settings, these demonstrations use `m = 2`
and tolerance `0.2 * population standard deviation` for each window. The sine
wave has frequency 10 Hz and amplitude 10 µV; noise is uniform between -10 and
10 µV with `random.Random(42)`. Each signal is generated once at 2,048 samples,
and shorter windows are prefixes. The assumed sampling rate is 256 Hz.

| Signal | Samples | Duration (s) | Tolerance (µV) | Approximate entropy | Runtime (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sine | 512 | 2 | 1.414214 | 0.180155 | 0.0767 |
| Sine | 1024 | 4 | 1.414214 | 0.180448 | 0.3105 |
| Sine | 2048 | 8 | 1.414214 | 0.180586 | 1.2094 |
| Noise | 512 | 2 | 1.163250 | 1.495933 | 0.0720 |
| Noise | 1024 | 4 | 1.150905 | 1.837663 | 0.2982 |
| Noise | 2048 | 8 | 1.142357 | 2.023030 | 1.1530 |

These are single-call `time.perf_counter()` measurements on the local Windows
machine using the bundled Python runtime, excluding signal generation. They
measure one channel; four-channel processing requires four entropy calls.
Timings vary by machine and run. This snippet reproduces the investigation:

```python
import math
import random
from time import perf_counter
from eeg_app.features import approximate_entropy, standard_deviation

rng = random.Random(42)
signals = {
    "Sine": [10 * math.sin(2 * math.pi * 10 * i / 256) for i in range(2048)],
    "Noise": [rng.uniform(-10, 10) for _ in range(2048)],
}
for name, signal in signals.items():
    for n in (512, 1024, 2048):
        window = signal[:n]
        tolerance = 0.2 * standard_deviation(window)
        start = perf_counter()
        entropy = approximate_entropy(window, 2, tolerance)
        runtime = perf_counter() - start
        print(name, n, n / 256, tolerance, entropy, runtime)
```

The repeating sine pattern produces relatively stable entropy here. Noise has
higher values and changes more with length. More data changes template counts
and the influence of self-matches; it does not guarantee a monotonic entropy
change. Tolerance controls which templates match, and is recalculated for every
window here, so the noise comparison reflects both length and tolerance changes.
A fixed-tolerance comparison would help separate their effects. Regular
artifacts can have low entropy, and irregular physiological activity can have
high entropy; entropy alone cannot establish an artifact.

The direct matching implementation has worst-case time `O(N² * (m + 1))`, so
doubling N roughly quadruples comparison work for fixed m. Template storage is
`O(N * (m + 1))`.

## Four-channel integration and output

`calculate_window_features` uses Namit's existing `validate_eeg_window` for
nonempty, equal-length TP9, AF7, AF8, and TP10 sequences of finite numeric samples.
The caller must explicitly supply `continuous=True` only after establishing
that the window contains no recording gap. False or unknown continuity is
rejected. Sample values alone cannot reveal missing timestamps, so upstream
code must split or reject windows spanning gaps. Missing samples are never
zero-filled or joined across gaps by this function.

Example call, with synthetic data and an exact-equality flatline tolerance:

```python
from eeg_app.features import calculate_window_features

window = {
    channel: [0, 0, 0, 0, 10]
    for channel in ("TP9", "AF7", "AF8", "TP10")
}
result = calculate_window_features(
    window,
    continuous=True,
    flatline_tolerance_uv=0,
    entropy_m=2,
)
```

The result contains three dictionaries:

- `features`: 24 values with channel-prefixed names.
- `settings`: sample count per channel, continuity assertion, input units,
  flatline tolerance, entropy m, actual entropy tolerances per channel, and
  the moment and entropy conventions.
- `unavailable_reasons`: explanations keyed by the same output names for
  every unavailable value. An empty dictionary means all values are available.

The TP9 results for this example are:

| Output name | Value | Units |
| --- | ---: | --- |
| `TP9_peak_to_peak_uv` | 10 | µV |
| `TP9_max_adjacent_jump_uv` | 10 | µV |
| `TP9_flatline_fraction` | 0.75 | dimensionless |
| `TP9_standard_deviation_uv` | 4 | µV |
| `TP9_kurtosis` | 3.25 | dimensionless |
| `TP9_approximate_entropy` | 0.074179 | dimensionless |

AF7, AF8, and TP10 use the same six suffixes with their respective prefixes.
The channels in this example are identical, so their values are identical.
Default entropy tolerance is `0.2 * 4 = 0.8 µV` for each channel. An explicitly
supplied `entropy_tolerance_uv` overrides the rule for all channels; the actual
value for each channel is still recorded. Flatline tolerance must always be
supplied explicitly. These demonstration settings are not final artifact
thresholds.

Individual feature functions reject too-short inputs. The window-level wrapper
preserves available features for a short but otherwise valid window and records
unavailable results as None. For a one-sample channel `[5]`, peak-to-peak and
standard deviation are zero, kurtosis is None because variance is zero, adjacent
jump and flatline fraction are None because they require two samples, and entropy
is None because it requires `m + 2` samples. Each None has a corresponding reason;
for example:

```python
result["unavailable_reasons"]["TP9_approximate_entropy"]
# "Requires at least 4 samples; received 1."
```

Invalid windows or parameters raise errors instead of producing feature values.
No reference labels are accepted or used, and the original input remains unchanged.

## Research connection and checks

Witteveen et al.'s [wearable-EEG signal-quality study](https://doi.org/10.1109/JBHI.2019.2920381)
evaluated statistical features for signal-quality assessment. Our synthetic
examples check the calculations, but testing on labeled EEG is still needed to
assess artifact detection.

Run from the repository root in CMD:

```cmd
python -m unittest discover -s tests -v
```

`tests/test_features.py` covers the original examples, constants, isolated spikes,
repeating and fixed-seed irregular signals, inclusive tolerance boundaries,
negative entropy, invalid samples and parameters, minimum lengths, unchanged
inputs, channel names, shared validation, continuity rejection, and unavailable
values with reasons. Existing preprocessing tests are also run by this command.

## Questions for the Team:

1. How should we determine the size of the window to calculate our features for?
2. How should we handle missing/corrupted samples?

## Assumptions:

* Namit’s preprocessing code will validate a window before feature calculation.
* A validated window will contain TP9, AF7, AF8, and TP10.
* Each channel will contain the same number of samples.
* Feature values will be calculated separately for each channel.
* Shrinithi’s reference labels will remain separate from the feature calculations.
* Channels use the same sampling rate.
* Namit's validator checks that samples are finite
* Peak-to-peak and maximum adjacent jump are useful indicators of unusual signal behavior.

## Ideas for Future Features:

1. Rate of change (slope) at different intervals of a window
2. Average amplitude
3. The general trend of amplitude across windows, positive, negative, increasing, decreasing, etc.

