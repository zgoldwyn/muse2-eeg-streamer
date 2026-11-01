import math

def validate_samples(samples, min_length):
    if samples is None:
        raise ValueError("Samples cannot be missing.")

    if len(samples) < min_length:
        raise ValueError(f"At least {min_length} sample(s) are required to calculate this feature.")

    for i, sample in enumerate(samples):
        if not isinstance(sample, (int, float)):
            raise ValueError(f"ERROR at position {i} in {samples}. All samples must be numeric.")

        if not math.isfinite(sample):
            raise ValueError(f"ERROR at position {i} in {samples}. Samples cannot contain NaN or infinity.")
        

def peak_to_peak(samples):
    validate_samples(samples, min_length=1)


    max_value = max(samples)
    min_value = min(samples)

    peak_to_peak_distance = max_value - min_value

    return peak_to_peak_distance



def max_adjacent_jump(samples):
    validate_samples(samples, min_length=2)


    max_jump = abs(samples[1] - samples[0])

    for i in range(2, len(samples)):
        current_jump = abs(samples[i] - samples[i - 1])
        if current_jump > max_jump:
            max_jump = current_jump

    return max_jump


def print_results(window_name, window):
    print(window_name)
    print(f"Peak-to-peak: {peak_to_peak(window)}")
    print(f"Maximum adjacent jump: {max_adjacent_jump(window)}")
    print()


window_a = [1, 1, 1, 1, 1]
window_b = [0, 0, 10, 0, 0]
window_c = [-100, -10, 0, 60, 120]

if __name__ == "__main__":
    print_results("Window A", window_a)
    print_results("Window B", window_b)
    print_results("Window C", window_c)


    # Valid input tests
    assert peak_to_peak(window_a) == 0
    assert max_adjacent_jump(window_a) == 0

    assert peak_to_peak(window_b) == 10
    assert max_adjacent_jump(window_b) == 10

    assert peak_to_peak(window_c) == 220
    assert max_adjacent_jump(window_c) == 90



    # Invalid input tests

    # Empty window
    try:
        peak_to_peak([])
        assert False, "Expected ValueError for empty window"
    except ValueError:
        pass

    # One sample for max_adjacent_jump
    try:
        max_adjacent_jump([5])
        assert False, "Expected ValueError for one-sample window"
    except ValueError:
        pass

    # Missing value
    try:
        peak_to_peak([1, None, 3])
        assert False, "Expected ValueError for None value"
    except ValueError:
        pass

    # NaN
    try:
        peak_to_peak([1, math.nan, 3])
        assert False, "Expected ValueError for NaN"
    except ValueError:
        pass

    # Infinity
    try:
        peak_to_peak([1, math.inf, 3])
        assert False, "Expected ValueError for infinity"
    except ValueError:
        pass

    print("All assertions passed.")