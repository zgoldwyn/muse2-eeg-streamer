# Additional mathematical rule comparison

The prepared November 8 development data contains all six existing features
for TP9, AF7, AF8, and TP10 in every one of the 464 reviewable two-second
windows. The feature pipeline, units, population moments, and entropy
definitions are retained. The historical four-participant evaluation is
saved in `data/private/nov9/comparison.json`, including the original math
detector's 52/213 artifact recall and 205/205 clean retention.

The new candidate grid uses the same approved 13 training sessions and the
two original review releases. All candidate limits come from the 205 labeled
clean windows. Training artifact labels are used to investigate the direction
of kurtosis and approximate entropy.

## Bounded validation plan

The command prepares the following stages for selection on reviewed P0005:

| Variant | Candidates and comparison |
| --- | --- |
| Original evaluated recipe | Refit its original 90th/95th/99th-percentile procedure on all eligible November 8 training windows, including artifact windows. Select among those three on P0005. |
| Retuned peak-to-peak and jump | The 16 independent clean-training percentile pairs from Part 2. Compare the best with the original recipe. |
| Retuned plus standard deviation | Add one of four standard-deviation limits to the best retuned pair. Compare with that pair. |
| Kurtosis extension | Add one of four kurtosis limits to the retained standard-deviation stage, or to the retuned pair if standard deviation is rejected. |
| Entropy extension | Separately add one of four entropy limits to the same preceding stage used for kurtosis. |

This evaluates at most 31 policies. The original recipe's P0005 control is a
refit on the four training participants. Its role and data differ from the
earlier rotating held-out baseline, which remains available as a separate
historical result.

Validation maximizes the mean of artifact recall and clean retention,
breaking ties toward higher recall, then greater retention. An extra feature
is retained only when its best candidate strictly improves this objective
over its preceding policy. The report records every candidate, its settings,
confusion counts, metric numerators and denominators, and the change in
recall, clean retention, accepted contamination, and coverage. A failed
candidate's required inputs are reported with window IDs and reasons.
The recommendation is the highest-scoring retained policy, pending approval.

## Rules and training evidence

The base rule flags when any channel strictly exceeds its configured
peak-to-peak or adjacent-jump limit. Each additional feature also flags on
any channel. All required channel values are checked even when another rule
has already triggered.

For high-side rules, calculate the clean training window maximum across
channels and take its 80th, 90th, 95th, or 99th percentile. For low-side
rules, calculate the clean window minimum and take its complementary
20th, 10th, 5th, or 1st percentile. All quantiles use inclusive linear
interpolation. Equality passes.

| Feature | Possible missed pattern | Rule tested | Units |
| --- | --- | --- | --- |
| Standard deviation | Sustained large variation that individual adjacent changes may miss | Any channel's value > limit | µV, population standard deviation |
| Kurtosis | Large isolated transients relative to the window's usual variation | Any channel's value > limit, supported by training direction analysis | Dimensionless Pearson kurtosis |
| Approximate entropy | More regular contamination that amplitude limits may miss | Any channel's value < limit, supported by training direction analysis | Dimensionless, natural logarithms |

For kurtosis and entropy, compare both directions using training data. The
high-side score is the fraction of artifact/clean pairs where the artifact
window maximum is larger. The low-side score is the fraction where the
artifact window minimum is smaller. Ties count one half. Choose the stronger
direction only when its score exceeds 0.5. The grid saves channel-specific
medians and quartiles and both direction scores. These are descriptive
training comparisons that support candidate design.

| Feature and selected direction | Clean median of window extrema | Artifact median of window extrema | Training direction score |
| --- | ---: | ---: | ---: |
| Standard deviation, high maximum | 13.3919 | 115.0101 | 0.9666 |
| Kurtosis, high maximum | 3.2996 | 5.5823 | 0.7373 |
| Entropy, low minimum | 1.2164 | 0.2994 | 0.9614 |

The alternative direction scores were 0.5391 for low kurtosis and 0.0957 for
high entropy. Kurtosis directions differ across channels: AF7's artifact
median was slightly lower than its clean median. The resulting single
high-kurtosis candidate rule is supported by the window-maximum comparison.
Training associations describe this dataset and remain subject to P0005
validation.

| Nominal clean percentile | Std > limit (µV) | Kurtosis > limit | Entropy < limit |
| --- | ---: | ---: | ---: |
| 80 | 22.8365 | 3.9296 | 0.9201 |
| 90 | 31.0665 | 4.7718 | 0.7089 |
| 95 | 38.4316 | 6.0723 | 0.5157 |
| 99 | 79.6346 | 9.0803 | 0.3579 |

Full precision is retained in the private grid. There were zero missing
inputs in these training comparisons. Undefined kurtosis, nonfinite values,
or unavailable added features cause exclusion for that rule. A validation
candidate missing an eligible prediction is ineligible for selection.

## Feature consistency and execution

The settings use 512 samples per channel, population standard deviation,
Pearson kurtosis, and approximate entropy with `m=2`, natural logarithms,
self-matches, and an inclusive matching tolerance of 0.2 times each channel's
population standard deviation. The other existing features keep their
definitions, including flatline tolerance 0.1 µV. The validator checks that
feature definitions agree between training and validation. Saved reports
include input hashes and source hashes for the feature pipeline and rule code.

```text
python -m eeg_app.rule_search derive data/private/nov9/prepared.json data/private/nov9/session-participants.json data/private/thanksgiving/rule-grid.json
python -m eeg_app.rule_search validate data/private/thanksgiving/rule-grid.json data/private/thanksgiving/validation-p0005.json data/private/thanksgiving/rule-validation.json
python -m unittest tests.test_rule_search tests.test_threshold_search
```

Prepare the reviewed P0005 sessions with
`eeg_app.development_math prepare`, using release name `P0005-reviews.zip`
and its supplied ZIP. The new release has 53 clean, 35 artifact, and
20 uncertain windows. Three technical exclusions come from the loader.
The original blank templates remain in `MuseDataNov15.zip`.

## P0005 validation results

The unchanged training grid scored 88 eligible windows from the completed
review release. All 108 review IDs and intervals matched their source EEG.
Every reviewable window produced the existing 24 feature values.

| Best candidate per variant | TP / FP / TN / FN | Recall | Clean retention | Added artifact catches | Clean-retention change |
| --- | --- | --- | --- | ---: | ---: |
| Original recipe refit, p90 | 14 / 0 / 53 / 21 | 14/35 | 53/53 | — | — |
| Retuned p2p-p80/jump-p90 | 35 / 0 / 53 / 0 | 35/35 | 53/53 | +21 | 0 |
| Add std, p90 | 35 / 0 / 53 / 0 | 35/35 | 53/53 | 0 | 0 |
| Add kurtosis, p99 | 35 / 2 / 51 / 0 | 35/35 | 51/53 | 0 | −3.77 percentage points |
| Add entropy, p90 | 35 / 0 / 53 / 0 | 35/35 | 53/53 | 0 | 0 |

Each extension is compared with the retuned pair because standard deviation
provided no strict objective improvement. Standard deviation and entropy
added no benefit at their best settings. Kurtosis reduced clean retention,
including at its best tested setting. Exclude all three additions from the
current recommendation.

The validation recommendation keeps two features, using peak-to-peak
>123.6328125 µV or adjacent jump >52.24609375 µV on any channel.
Its validation precision was 35/35, accepted contamination 0/53, and coverage
53/88. These are P0005 development-validation results. The method remains
subject to Zach's approval and the reserved evaluation. Namit has confirmed
the review release is preliminary while Ben and Rushil's independent
checks and reconciliation are pending. The current results carry that
status and need to be rerun if any reconciled labels change.

The private `rule-validation.json` saves all 31 candidate evaluations,
their deltas and exclusions, and the code/input hashes. The original
four-participant baseline remains saved separately. Reserved repeat
recordings and their labels were left unopened.
