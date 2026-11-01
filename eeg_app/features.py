import math
from collections.abc import Sequence
from numbers import Real

from .preprocessing import REQUIRED_CHANNELS, validate_eeg_window


def validate_samples(samples, min_length):
    """Validate sample values and the minimum number of samples."""
    if samples is None:
        raise ValueError("Samples cannot be missing.")

    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        raise ValueError("Samples must be a sequence of numeric values.")

    if len(samples) < min_length:
        raise ValueError(
            f"At least {min_length} sample(s) are required "
            "to calculate this feature."
        )

    for i, sample in enumerate(samples):
        if isinstance(sample, bool) or not isinstance(sample, Real):
            raise ValueError(f"Sample at position {i} must be numeric.")

        if not math.isfinite(sample):
            raise ValueError(
                f"Sample at position {i} must be finite; "
                "NaN and infinity are not allowed."
            )


def _validate_tolerance(tolerance_uv):
    if isinstance(tolerance_uv, bool) or not isinstance(tolerance_uv, Real):
        raise ValueError("Tolerance must be numeric.")
    if not math.isfinite(tolerance_uv) or tolerance_uv < 0:
        raise ValueError("Tolerance must be finite and nonnegative.")


def _validate_m(m):
    if isinstance(m, bool) or not isinstance(m, int) or m < 1:
        raise ValueError("m must be a positive integer.")


def peak_to_peak(samples):
    """Return the maximum minus minimum in microvolts (µV).

    Input samples must be in µV. Requires at least one sample.
    Raises ValueError for missing, nonnumeric, nonfinite, or empty input.
    """
    validate_samples(samples, min_length=1)

    return max(samples) - min(samples)


def max_adjacent_jump(samples):
    """Return the largest absolute change between neighbors in microvolts (µV).

    Input samples must be in µV. Requires at least two samples.
    Raises ValueError for missing, nonnumeric, nonfinite, or insufficient input.
    """
    validate_samples(samples, min_length=2)

    max_jump = abs(samples[1] - samples[0])

    for i in range(2, len(samples)):
        current_jump = abs(samples[i] - samples[i - 1])
        if current_jump > max_jump:
            max_jump = current_jump

    return max_jump


def flatline_fraction(samples, tolerance_uv):
    """Return the fraction of neighboring samples that barely change.

    Samples and tolerance must be in microvolts (µV).
    A pair counts when its absolute change is <= tolerance_uv.
    The returned fraction is unitless and ranges from 0 to 1.

    Requires at least two samples and a finite, nonnegative tolerance.
    """
    validate_samples(samples, min_length=2)

    _validate_tolerance(tolerance_uv)

    flat_pairs = 0

    for i in range(1, len(samples)):
        change = abs(samples[i] - samples[i - 1])
        if change <= tolerance_uv:
            flat_pairs += 1

    total_pairs = len(samples) - 1
    return flat_pairs / total_pairs


def standard_deviation(samples):
    """Return population standard deviation in microvolts (µV).

    Input samples must be in µV. Uses population variance, dividing by N.
    Returns 0 for a constant signal.
    """
    validate_samples(samples, min_length=1)

    if all(sample == samples[0] for sample in samples):
        return 0.0

    n = len(samples)
    mean = sum(samples) / n
    variance = sum((sample - mean) ** 2 for sample in samples) / n

    return math.sqrt(variance)


def kurtosis(samples):
    """Return dimensionless Pearson kurtosis using population moments.

    Divides moments by N and does not subtract 3 or apply bias correction.
    Returns None when variance is zero because kurtosis is undefined.
    """
    validate_samples(samples, min_length=1)

    if all(sample == samples[0] for sample in samples):
        return None

    n = len(samples)
    mean = sum(samples) / n
    variance = sum((sample - mean) ** 2 for sample in samples) / n

    if variance == 0:
        return None

    fourth_moment = sum(
        (sample - mean) ** 4 for sample in samples
    ) / n

    return fourth_moment / (variance ** 2)


def approximate_entropy(samples, m, tolerance_uv):
    """Return dimensionless approximate entropy using natural logarithms.

    Samples and tolerance_uv are in microvolts (µV). Requires a positive
    integer m, a finite nonnegative tolerance, and at least m + 2 finite
    numeric samples. Includes self-matches and differences <= tolerance_uv.

    Each phi averages log(match_count / template_count) separately for its
    template length. This is approximate entropy, not sample entropy.
    Negative finite-sample estimates are returned without clamping.
    Zero for a constant signal describes regularity, not usable EEG.
    Inputs are not modified. Worst-case time is O(N**2 * (m + 1)).
    """
    _validate_m(m)
    _validate_tolerance(tolerance_uv)
    validate_samples(samples, min_length=m + 2)

    def phi(length):
        templates = [
            samples[i:i + length]
            for i in range(len(samples) - length + 1)
        ]
        total = len(templates)
        logs = []

        for template in templates:
            matches = 0
            # Every template is a candidate, including this template itself.
            for candidate in templates:
                for a, b in zip(template, candidate):
                    if abs(a - b) > tolerance_uv:
                        break
                else:
                    # No coordinate exceeded the tolerance: all matched.
                    matches += 1

            # Self-matches ensure a positive fraction and a defined logarithm.
            logs.append(math.log(matches / total))

        return math.fsum(logs) / total

    return phi(m) - phi(m + 1)


def calculate_window_features(
    window, *, continuous, flatline_tolerance_uv,
    entropy_m=2, entropy_tolerance_uv=None,
):
    """Calculate six features per channel using Namit's four-channel validator.

    Caller must explicitly supply continuous=True for a window known to have
    no recording gaps; the sample-only validator cannot establish continuity.
    Known gaps must be handled upstream, not filled with zero.

    Samples and tolerances are in µV. If entropy_tolerance_uv is None, use
    0.2 times each channel's population standard deviation. An explicit
    entropy tolerance applies to all channels. Flatline tolerance is required.

    Return features, settings, and unavailable_reasons dictionaries. Values
    unavailable due to sample count or zero-variance kurtosis are None, with
    explanations keyed by feature name. Invalid windows/parameters raise
    ValueError. Inputs and reference labels are not modified; no labels are
    used in the calculation.
    """
    if continuous is not True:
        raise ValueError("Only windows supplied as continuous=True may be calculated.")
    _validate_tolerance(flatline_tolerance_uv)
    _validate_m(entropy_m)
    if entropy_tolerance_uv is not None:
        _validate_tolerance(entropy_tolerance_uv)

    sample_count = validate_eeg_window(window)
    values = {}
    reasons = {}
    entropy_tolerances = {}

    for channel in REQUIRED_CHANNELS:
        samples = window[channel]
        std = standard_deviation(samples)
        tolerance = 0.2 * std if entropy_tolerance_uv is None else entropy_tolerance_uv
        _validate_tolerance(tolerance)
        entropy_tolerances[channel] = tolerance

        # Required length, calculation, and positional arguments for each feature.
        calculations = (
            ("peak_to_peak_uv", 1, peak_to_peak, (samples,)),
            ("max_adjacent_jump_uv", 2, max_adjacent_jump, (samples,)),
            ("flatline_fraction", 2, flatline_fraction, (samples, flatline_tolerance_uv)),
            ("standard_deviation_uv", 1, lambda: std, ()),
            ("kurtosis", 1, kurtosis, (samples,)),
            ("approximate_entropy", entropy_m + 2, approximate_entropy,
             (samples, entropy_m, tolerance)),
        )
        for name, required, function, arguments in calculations:
            key = f"{channel}_{name}"
            if sample_count < required:
                values[key] = None
                reasons[key] = f"Requires at least {required} samples; received {sample_count}."
            else:
                values[key] = function(*arguments)
                if name == "kurtosis" and values[key] is None:
                    reasons[key] = "Kurtosis is undefined when variance is zero."

    return {
        "features": values,
        "settings": {
            "sample_count_per_channel": sample_count,
            "continuous": True,
            "input_units": "microvolts",
            "flatline_tolerance_uv": flatline_tolerance_uv,
            "entropy_m": entropy_m,
            "entropy_tolerance_uv": entropy_tolerances,
            "entropy_tolerance_rule": (
                "0.2 * per-channel population standard deviation"
                if entropy_tolerance_uv is None else "explicit shared tolerance"
            ),
            "entropy_convention": "natural log, self-matches, inclusive tolerance",
            "moment_convention": "population moments; Pearson kurtosis without bias correction",
        },
        "unavailable_reasons": reasons,
    }
