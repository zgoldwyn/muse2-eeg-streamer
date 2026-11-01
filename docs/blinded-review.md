# Blinded window review and synthetic evaluation (Parts 2 and 3)

The review tool reads the saved session through Namit's loader and fixed-window
functions. It does not import the feature pipeline, read reference-label files,
run a detector, propose labels, or read prompts/operator events. The existing
100 microvolt demo rule is not used or shown to reviewers.

## Generate a blank reviewer bundle

From the repository root:

```text
python -m eeg_app.review generate tests/fixtures/integration/integration-demo-001 recordings/review-demo
```

Use an output directory that does not already exist; existing reviewer work is
never overwritten. For a pilot, replace the session path with the actual saved
session. The current loader accepts the project's four-channel, 256 Hz saved
CSV/JSON format; this tool does not add live recording support.

The output includes:

- `review.csv`: one row for each technically valid window, with original
  session/window IDs and start/end times. `reviewer_id`, `label`,
  `suspected_subtype`, `affected_channels`, `evidence_notes`, and `uncertainty`
  are all blank. `trace_file` points to the corresponding plot.
- `technically_invalid.csv`: excluded windows and their original loader
  reasons. This separate list has no human-label column.
- `traces/*.svg`: four panels per window, showing the saved decoded microvolt
  values against the original elapsed times. No filtering, normalization,
  resampling, or gap filling is applied. Each window uses a shared vertical
  scale for its four channels; the scale can differ between windows.
- `index.html`: a local list of plot links, separated into human-review windows
  and loader exclusions. Open it in a browser and click a window to inspect
  its full plot. Plot breaks preserve gaps, including packet 50 in the demo.

No extra Python plotting libraries, network service, or browser server is
required. The output directory contains no detector decisions, feature values,
suggested labels, or scenario answer key. SVG files and the index can be viewed
offline. Share only this bundle and the agreed review instructions with each
reviewer; do not share detector results or the synthetic fixture's answer key.

## Complete the sheet independently

Keep the original blank bundle and edit a copy of `review.csv`. Retain the
identifying fields and intervals exactly as exported; rows may be reordered.
Enter a reviewer ID and one of the distinct labels:

- `clean`: technically usable data with no contamination identified by review.
- `artifact`: contamination identified from the traces; describe evidence,
  suspected subtype, and affected channels when possible.
- `uncertain`: usable data but insufficient evidence to decide confidently.
- `invalid`: a review finding that the data cannot be meaningfully interpreted.
  This is distinct from uncertain. Loader-invalid windows are already listed
  separately and cannot be overridden through the human sheet.

Follow `docs/label-guide-draft.md` for operational definitions and independent
review/adjudication. `suspected_subtype` and `evidence_notes` are free text;
`affected_channels` uses semicolon-separated names such as `AF7;AF8`.
`uncertainty` is free text for confidence, ambiguity, or boundary uncertainty;
it has no invented numeric scale and does not replace the `uncertain` label.

Reviewers must not see detector predictions while labeling. Later prompts and
operator markers can be context, but a prompt is not an observed artifact and
a missing marker is not evidence of clean EEG. The tool does not convert them
to labels. Keep each reviewer's sheet separate; preserve original annotations
and resolve disagreements under the agreed adjudication process.

## Validate and convert

```text
python -m eeg_app.review validate tests/fixtures/integration/integration-demo-001 recordings/completed-review.csv --output-dir recordings/validated-review
```

Validation reloads the original saved session and checks unknown and duplicate
window IDs, missing review rows, missing/unsupported labels, reviewer IDs,
session IDs, start/end times, and affected channel names. A blank export is
intentionally incomplete and must fail validation. All technically valid
windows require one annotation. Technical exclusions must stay out of the human
sheet. Errors name the row/window and problem; no missing label defaults to
clean. `clean`, `artifact`, `uncertain`, and `invalid` are retained distinctly.

Omit `--output-dir` for validation without writing files. When specified, this
must also be a new directory. It receives:

- `reviewed_records.json`: validated human annotations with notes, uncertainty,
  times, and reviewer provenance.
- `reference_records.json`: exact `window_id`/`label` mappings accepted by
  `eeg_app.metrics.evaluate_predictions`. Human labels come unchanged from the
  completed sheet; loader exclusions are included as `invalid`. Both invalid
  and uncertain references are excluded by the evaluator's primary metrics.

Validation establishes format and completeness, not independence or scientific
correctness. It does not automatically adjudicate multiple reviewers or make a
single review a final answer key. Once the team's independent review and
adjudication are complete, the accepted completed sheet can be converted using
the same command. Keep its rich annotations and loader exclusion list for audit.

No pilot labels are supplied or invented by this implementation. The reviewer
exporter never loads the scenario answer key. The separate synthetic-only
rehearsal below explicitly uses Zack's already supplied example labels.

## Checks

```text
python -m unittest discover -s tests -p test_review.py -v
```

Tests use the real merged fixture/loader to check blank fields, original IDs
and times, separate loader exclusions, four-channel plots with breaks across
gaps, no feature/prediction execution, overwrite protection, invalid completed
sheets, all four labels, unchanged notes, record reordering, and conversion to
the merged evaluator. Completed labels in tests are explicitly unit-test
inputs, not independent pilot labels or a new answer key.

Verified on the merged `integration-demo-001` fixture: two blank human-review
rows, one separate loader exclusion, and three raw four-channel plots. Visual
inspection confirmed the missing packet appears as a break in all channels
and the planted AF7 disturbance is visible without a suggested label. The generated
blank sheet correctly fails completed-sheet validation until a reviewer fills
in the required annotations.

## Part 3: repeatable synthetic rehearsal

```text
python -m eeg_app.review_demo recordings/synthetic-review-dry-run
```

Use a new output directory on each run. This command is restricted to the
existing synthetic `integration-demo-001` session; it has no pilot-session
argument and rejects metadata that is not marked synthetic. The label source
is Zack's unchanged `tests/fixtures/integration/reference_records.json`:
`[0, 2)` clean, `[2, 4)` invalid, `[4, 6)` artifact. These labels predate this
rehearsal and are based on the fixture scenario, not detector predictions.

In order, the script:

1. Generates a prediction-free `reviewer_bundle/` with its original blank CSV.
2. Completes a separate `completed_synthetic_review.csv` from those predeclared
   example labels. Its reviewer ID is `synthetic-example-only`, and notes
   identify it as an automated rehearsal rather than human pilot review.
3. Validates the completed copy, saves its metric-format references, and records
   a SHA-256 digest before calling any feature extraction or prediction function.
4. Runs the existing illustrative detector separately, writes `predictions.json`,
   and passes references and predictions to the existing evaluator.
5. Checks missing eligible predictions and excluded-window prediction changes,
   and verifies that the completed sheet's digest has not changed.

Output:

```text
Synthetic workflow rehearsal only; no independent pilot labels created.
Eligible windows: 2
Uncertain windows: 0
Invalid windows: 1
Counts: {"false_negatives": 0, "false_positives": 0, "true_negatives": 1, "true_positives": 1}
Missing eligible predictions rejected: 2
Excluded-window predictions leave metrics unchanged: PASS
```

`dry_run_report.json` contains the stage order, reference-source and completed-
sheet digests, actual missing-prediction errors, and full evaluation. The blank
reviewer bundle remains blank; completed examples and predictions are outside
that folder. This ordering is tested. Because the example labels and results
were already known from last week's exercise, this is a workflow test, not a
claim that a person newly reviewed these windows blindly.

The existing fixture has zero uncertain labels; it is not relabeled to make
that count nonzero. A separate unit test uses controlled annotation inputs
with one eligible, one uncertain, and one technical-invalid window. Supplying
either binary decision for either excluded window, or no prediction for it,
produces identical counts and primary metrics. Those unit-test annotations
are not pilot labels or a replacement fixture answer key.

## Repeat locally on private pilot sessions

Keep saved pilot data, reviewer sheets, labels, predictions, plots, and results
under the existing Git-ignored `recordings/` (or `data/`) directory. Do not
copy them into committed `tests/fixtures/`, docs, or PR descriptions. The tool
works locally, without uploads. Share only non-identifying summary/error
information when coordinating the handoff.

1. Generate the bundle with `review generate`, using the local saved session.
   Give each reviewer a separate copy with no detector output or known labels.
2. Review the raw traces and complete the sheet independently. Preserve the
   original sheets. Resolve disagreements under the agreed process before
   deciding which completed annotations will serve as final references.
3. Validate and export the accepted sheet before generating/inspecting detector
   predictions. Keep that completed sheet and reference export fixed.
4. Supply the separately generated predictions as a JSON list of
   `{"window_id": "...", "decision": "clean"}` or `artifact` records. Retain the
   loader's IDs. Do not put this file in the reviewer bundle.
5. Run the existing evaluator through the review tool:

```text
python -m eeg_app.review generate recordings/pilot-session recordings/pilot-review
python -m eeg_app.review validate recordings/pilot-session recordings/completed-pilot-review.csv --output-dir recordings/pilot-accepted-labels
python -m eeg_app.review evaluate recordings/pilot-session recordings/completed-pilot-review.csv recordings/pilot-predictions.json --output-dir recordings/pilot-evaluation
```

The last command prints the evaluator's separate eligible, uncertain, and
invalid counts inside `summary`, plus counts and metric numerators/denominators.
It does not run a detector, relabel windows, infer missing predictions, or
combine uncertain with invalid. Missing eligible predictions are errors;
excluded-window predictions are validated but ignored by primary metrics.

For a local plumbing check only, after references have been fixed, the
existing API can write the illustrative detector's prediction file:

```python
import json
from pathlib import Path
from eeg_app.review import load_windows
from eeg_app.math_pipeline import extract_features_for_windows, demo_peak_to_peak_prediction

result = extract_features_for_windows(load_windows("recordings/pilot-session"), flatline_tolerance_uv=0)
predictions = [demo_peak_to_peak_prediction(r) for r in result["feature_records"]]
with Path("recordings/pilot-predictions.json").open("x", encoding="utf-8") as stream:
    json.dump(predictions, stream, indent=2)
```

This remains the existing unvalidated demo rule; it does not choose a final
pilot threshold. Do not change the labels after inspecting its outputs or
present a small pilot's scores as independent sealed validation.

## Namit handoff and label-policy decisions

The tool calls the merged `load_synthetic_session(eeg_csv, metadata_json)` and
`create_fixed_windows(session)` directly. It consumes `window_id`, `session_id`,
`start_time_s`, `end_time_s`, `nominal_sample_rate_hz`, `channel_samples`,
`channel_times_s`, `is_valid`, and `invalid_reasons`. No column/ID translation
or receipt-time substitution is applied. The saved format uses
`nominal_sample_rate_hz: 256` and `samples_per_packet: 12`.

Verified synthetic IDs are `integration-demo-001:window-000000` for `[0, 2)`,
`...:window-000001` for `[2, 4)`, and `...:window-000002` for `[4, 6)`.
The first and last have 512 samples per channel; the middle has 500 and stays
invalid. The validator rejects unknown IDs and changed intervals instead of
silently guessing a mapping. Confirm with Namit that his live adapter's saved
sessions use this same loader contract before the first pilot.

Coordination message prepared for Sam to send (no message has been sent by
this tool):

> Hey Namit, the review tool reads your saved eeg.csv/metadata.json through
> load_synthetic_session and create_fixed_windows directly, preserving the
> window IDs, start/end seconds, validity, and reasons. The merged synthetic
> fixture passes. Can you confirm the live adapter keeps this handoff, and
> flag any ID or time-field changes before we use it for the pilot?

No label-guide policy changes are made. In particular, the tool does not
choose partial-window overlap rules, automatically label a whole window from
one affected channel, or adjudicate reviewer disagreement. Record the evidence
and affected channels. Bring any proposed change in those policies to Zack
for a final decision; do not silently adopt it as policy.

Final verification: `python -m unittest discover -s tests` passed all 126
tests, including 15 review/dry-run tests. The generic `review evaluate`
command was also run against the completed synthetic copy and separately
saved predictions; it returned the same counts and separate eligibility
summary. `git check-ignore` confirmed the example completed sheet,
predictions, and report under `recordings/` are excluded from Git.

## Question to include in the final PR

The assignment asks for a small review tool, so this version covers the blank
sheet, raw plots, validation, and evaluator handoff. Would you like it to be
more comprehensive for the pilot, or should we keep this scope for now?
