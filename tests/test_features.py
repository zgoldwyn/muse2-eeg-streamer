"""Synthetic examples and validation checks for the reusable features."""

import copy
import math
import random
import unittest
from unittest.mock import patch

from eeg_app.features import (
    approximate_entropy, calculate_window_features, flatline_fraction,
    kurtosis, max_adjacent_jump, peak_to_peak, standard_deviation,
)
from eeg_app.preprocessing import REQUIRED_CHANNELS, validate_eeg_window


class FeatureTests(unittest.TestCase):
    def test_original_examples(self):
        for samples, expected_range, expected_jump in (
            ([1, 1, 1, 1, 1], 0, 0),
            ([0, 0, 10, 0, 0], 10, 10),
            ([-100, -10, 0, 60, 120], 220, 90),
        ):
            with self.subTest(samples=samples):
                self.assertEqual(peak_to_peak(samples), expected_range)
                self.assertEqual(max_adjacent_jump(samples), expected_jump)
        self.assertEqual(flatline_fraction([1, 1, 1, 2, 2], 0), 0.75)

    def test_constant_and_one_sample_signals(self):
        samples = [5] * 6
        self.assertEqual(peak_to_peak(samples), 0)
        self.assertEqual(max_adjacent_jump(samples), 0)
        self.assertEqual(flatline_fraction(samples, 0), 1)
        self.assertEqual(standard_deviation(samples), 0)
        self.assertIsNone(kurtosis(samples))
        self.assertEqual(approximate_entropy(samples, 2, 0), 0)
        self.assertEqual(peak_to_peak([5]), 0)
        self.assertEqual(standard_deviation([5]), 0)
        self.assertIsNone(kurtosis([5]))

    def test_constant_decimal_signal(self):
        samples = [0.1] * 6
        self.assertEqual(standard_deviation(samples), 0.0)
        self.assertIsNone(kurtosis(samples))

        window = {channel: samples.copy() for channel in REQUIRED_CHANNELS}
        result = calculate_window_features(
            window, continuous=True, flatline_tolerance_uv=0,
        )
        for channel in REQUIRED_CHANNELS:
            self.assertEqual(result['features'][f'{channel}_standard_deviation_uv'], 0.0)
            key = f'{channel}_kurtosis'
            self.assertIsNone(result['features'][key])
            self.assertIn('variance is zero', result['unavailable_reasons'][key])

    def test_statistical_example_and_isolated_spike(self):
        self.assertEqual(standard_deviation([0, 0, 0, 0, 10]), 4)
        self.assertEqual(kurtosis([0, 0, 0, 0, 10]), 3.25)
        smooth, spike = [0, 1, 2, 3, 4], [0, 1, 20, 3, 4]
        self.assertGreater(standard_deviation(spike), standard_deviation(smooth))
        self.assertGreater(kurtosis(spike), kurtosis(smooth))
        self.assertEqual(max_adjacent_jump(spike), 19)

    def test_entropy_worked_example(self):
        phi_two = (3 * math.log(3 / 5) + 2 * math.log(1 / 5)) / 5
        phi_three = math.log(1 / 4)
        self.assertAlmostEqual(approximate_entropy([0, 0, 0, 1, 0, 0], 2, 0.1),
                               phi_two - phi_three)

    def test_inclusive_tolerance_boundaries(self):
        self.assertEqual(flatline_fraction([0, 0.5, 1, 2], 0.5), 2 / 3)
        # Templates [0, 1] and [1, 0] differ by exactly one at both positions.
        self.assertEqual(approximate_entropy([0, 1, 0, 1], 2, 1), 0)

    def test_negative_entropy_is_preserved(self):
        value = approximate_entropy([0, 1, 2, 3], 2, 0)
        self.assertAlmostEqual(value, math.log(2 / 3))
        self.assertLess(value, 0)

    def test_repeating_and_seeded_irregular_signals(self):
        repeating = [0, 1] * 64
        rng = random.Random(42)
        irregular = [rng.uniform(-10, 10) for _ in range(128)]
        regular_entropy = approximate_entropy(repeating, 2, 0.2 * standard_deviation(repeating))
        irregular_entropy = approximate_entropy(irregular, 2, 0.2 * standard_deviation(irregular))
        self.assertGreater(irregular_entropy, regular_entropy)

    def test_invalid_samples(self):
        for function in (
            peak_to_peak, max_adjacent_jump, standard_deviation, kurtosis,
            lambda x: flatline_fraction(x, 0),
            lambda x: approximate_entropy(x, 2, 0.1),
        ):
            for samples in ([], None, 5, '0000', [0, 0, None, 0],
                            [0, 0, 'bad', 0], [0, 0, True, 0],
                            [0, 0, math.nan, 0], [0, 0, math.inf, 0],
                            [0, 0, -math.inf, 0]):
                with self.subTest(function=function, samples=samples):
                    with self.assertRaises(ValueError):
                        function(samples)

    def test_too_short_samples(self):
        for function in (max_adjacent_jump, lambda x: flatline_fraction(x, 0)):
            with self.assertRaisesRegex(ValueError, 'At least 2'):
                function([1])
        with self.assertRaisesRegex(ValueError, 'At least 4'):
            approximate_entropy([0, 0, 0], 2, 0)

    def test_invalid_parameters(self):
        for tolerance in (-1, math.nan, math.inf, -math.inf, None, '0', True):
            with self.subTest(tolerance=tolerance):
                with self.assertRaises(ValueError):
                    flatline_fraction([0] * 6, tolerance)
                with self.assertRaises(ValueError):
                    approximate_entropy([0] * 6, 2, tolerance)
        for m in (0, -1, 2.0, True, None, '2'):
            with self.subTest(m=m), self.assertRaisesRegex(ValueError, 'positive integer'):
                approximate_entropy([0] * 6, m, 0)

    def test_input_unchanged_and_tuple_supported(self):
        samples = [0, 0, 0, 1, 0, 0]
        before = samples.copy()
        for function in (
            peak_to_peak, max_adjacent_jump, standard_deviation, kurtosis,
            lambda x: flatline_fraction(x, 0),
            lambda x: approximate_entropy(x, 2, 0.1),
        ):
            self.assertEqual(function(samples), function(tuple(samples)))
            self.assertEqual(samples, before)


class WindowFeatureTests(unittest.TestCase):
    def setUp(self):
        self.window = {
            'TP9': [0, 0, 0, 1, 0, 0], 'AF7': [0, 0, 0, 10, 0, 0],
            'AF8': [5] * 6, 'TP10': [0, 1, 2, 3, 4, 5],
        }

    def calculate(self, window=None, **overrides):
        settings = {'continuous': True, 'flatline_tolerance_uv': 0}
        settings.update(overrides)
        return calculate_window_features(self.window if window is None else window, **settings)

    def test_validator_and_channel_results(self):
        with patch('eeg_app.features.validate_eeg_window', wraps=validate_eeg_window) as validator:
            result = self.calculate()
            validator.assert_called_once_with(self.window)
        expected = {
            f'{channel}_{feature}' for channel in REQUIRED_CHANNELS
            for feature in ('peak_to_peak_uv', 'max_adjacent_jump_uv', 'flatline_fraction',
                            'standard_deviation_uv', 'kurtosis', 'approximate_entropy')
        }
        self.assertEqual(set(result['features']), expected)
        self.assertEqual(result['features']['TP9_peak_to_peak_uv'], 1)
        self.assertEqual(result['features']['AF7_peak_to_peak_uv'], 10)
        self.assertIsNone(result['features']['AF8_kurtosis'])
        self.assertIn('variance is zero', result['unavailable_reasons']['AF8_kurtosis'])
        self.assertEqual(result['features']['AF8_approximate_entropy'], 0)

    def test_settings_and_explicit_tolerance(self):
        result = self.calculate()
        self.assertEqual(result['settings']['sample_count_per_channel'], 6)
        self.assertEqual(result['settings']['entropy_m'], 2)
        for channel in REQUIRED_CHANNELS:
            self.assertEqual(result['settings']['entropy_tolerance_uv'][channel],
                             0.2 * standard_deviation(self.window[channel]))
        explicit = self.calculate(entropy_tolerance_uv=0.1)
        self.assertEqual(explicit['settings']['entropy_tolerance_uv'],
                         dict.fromkeys(REQUIRED_CHANNELS, 0.1))
        self.assertAlmostEqual(explicit['features']['TP9_approximate_entropy'], 0.4360238218866561)

    def test_short_window_unavailable_reasons(self):
        result = self.calculate({channel: [5] for channel in REQUIRED_CHANNELS})
        for channel in REQUIRED_CHANNELS:
            self.assertEqual(result['features'][f'{channel}_peak_to_peak_uv'], 0)
            for name in ('max_adjacent_jump_uv', 'flatline_fraction', 'approximate_entropy'):
                key = f'{channel}_{name}'
                self.assertIsNone(result['features'][key])
                self.assertIn('received 1', result['unavailable_reasons'][key])

    def test_gap_or_unknown_continuity_rejected(self):
        for continuous in (False, None, 1, 'yes'):
            with self.subTest(continuous=continuous), self.assertRaisesRegex(ValueError, 'continuous=True'):
                self.calculate(continuous=continuous)
        with self.assertRaises(TypeError):
            calculate_window_features(self.window, flatline_tolerance_uv=0)

    def test_invalid_window(self):
        for channel_value in ([], [0], [0, 0, None, 0, 0, 0],
                              [0, 0, math.nan, 0, 0, 0], [0, 0, math.inf, 0, 0, 0]):
            invalid = copy.deepcopy(self.window)
            invalid['TP9'] = channel_value
            with self.subTest(channel_value=channel_value), self.assertRaises(ValueError):
                self.calculate(invalid)
        invalid = copy.deepcopy(self.window)
        del invalid['TP9']
        with self.assertRaisesRegex(ValueError, 'missing required channel: TP9'):
            self.calculate(invalid)

    def test_invalid_parameters(self):
        for overrides in ({'flatline_tolerance_uv': -1}, {'entropy_m': 0},
                          {'entropy_tolerance_uv': math.inf}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.calculate(**overrides)

    def test_input_unchanged(self):
        before = copy.deepcopy(self.window)
        self.calculate()
        self.assertEqual(self.window, before)


if __name__ == '__main__':
    unittest.main()
