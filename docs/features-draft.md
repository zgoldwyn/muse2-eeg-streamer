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

A four-channel window could produce an output structured like this nested dictionary:

```python
{
    "TP9": {
        "peak_to_peak": 12.0,
        "max_adjacent_jump": 6.0
    },
    "AF7": {
        "peak_to_peak": 195.0,
        "max_adjacent_jump": 42.0
    },
    "AF8": {
        "peak_to_peak": 16.1,
        "max_adjacent_jump": 16.1
    },
    "TP10": {
        "peak_to_peak": 40.0,
        "max_adjacent_jump": 17.0
    }
}
```

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
* Unrealistic samples that are still numerical (something like -478362462837) have been handled in pre-processing.
* Peak-to-peak and maximum adjacent jump are useful indicators of unusual signal behavior.

## Ideas for Future Features:

1. Rate of change (slope) at different intervals of a window
2. Average amplitude
3. The general trend of amplitude across windows, positive, negative, increasing, decreasing, etc.

