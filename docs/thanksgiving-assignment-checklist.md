# Samuel's Thanksgiving assignment coverage

Checked against the supplied "Assignments (thru thanksgiving)" on November 26,
2026. This checklist distinguishes implementation and development validation
from the approval and reserved-evaluation work that remains.

| Part | Status | Evidence and remaining work |
| --- | --- | --- |
| 1. Existing PR handoff | Checked; main-branch dependency remains | PRs #27 and #32 have no inline review comments, formal reviews, or discussion comments at this check. #27 merged into main; #32 merged into samuel/public-muse-math. Keep that branch as this PR's base until the dependency lands in main. Namit's PR #31 now reads Muse EDF annotations in its shared importer; the public task/rest study remains separate. |
| 2. Improve threshold selection | Implemented and validated on preliminary P0005 labels | Clean-only November 8 calibration; independent 80/90/95/99 percentiles for peak-to-peak and jump, giving 16 pairs. Report recall, clean retention, and nearest 80%/90% options with their distances. No reserved repeats used. |
| 3. Additional mathematical rules | Implemented and compared | All six unchanged features per channel. Compare the original recipe, retuned pair, standard deviation, kurtosis, and entropy in 31 bounded policies. Document hypotheses, units, inequalities, clean-training thresholds, training direction evidence, and validation changes. Reject additions without strict benefit. |
| 4. Math, CNN, and agreement comparison | Completed as preliminary development validation | Namit's native export matches all 88 eligible IDs. Report all requested metrics, numerators/denominators, uncertain/invalid exclusions, majority-class and always-clean references, selected cutoffs, matched acceptance, compact tables, aggregate plot, and the earlier baseline. |
| 5. Freeze and final evaluation | Recommendation and reusable handoff prepared; approval and final run pending | Save proposed settings, exact rule/feature definitions, source and input hashes, data/label versions, selection objective, exclusions, and proposed minimum retention. Blind predict/score/verify commands are dry-run tested. Reconciliation, final CNN handoff, Zach's approval, and Ben's reserved evaluation remain outstanding. |

## Suggestions submitted for approval

1. Keep the any-channel OR rule: peak-to-peak **>123.63281250000001 µV** or
   maximum adjacent jump **>52.24609375 µV**. Equality passes. Missing required
   inputs cannot produce clean decisions.
2. Leave standard deviation, kurtosis, and entropy out of the decision rule
   while continuing to calculate all six features. Standard deviation and
   entropy added no validation benefit; the best kurtosis extension rejected
   two additional clean windows.
3. Propose **80% minimum useful clean retention**, subject to Zach's decision;
   also show the 90% comparison target. The closest tested base-grid option
   to either target achieved 50/53 (94.34%), with recall 35/35. The recommended
   pair achieved 53/53 clean retention and recall 35/35. Neither target was
   forced by expanding the search after inspecting the reserved data.
4. Keep the supplied CNN cutoff **0.5** as the primary reported operating point.
   Show **0.692649245262146** separately as a validation-selected,
   similar-acceptance comparison. It is not silently adopted as a final CNN
   setting. Agreement currently rejects extra clean windows without adding
   artifact catches over math on P0005; report this directly.
5. Reconcile the development labels and resolve the CNN training-set difference
   before approval. Only after approval, save the exact frozen method and stop
   tuning. No optional frequency feature, filtering, or protocol change is
   included.

## Evidence locations

- [Clean-training grid and retention targets](clean-training-threshold-search.md).
- [Additional-rule hypotheses, directions, thresholds, and deltas](additional-mathematical-rules.md).
- [Both operating-point comparisons and original-baseline preservation](p0005-policy-comparison.md).
- [Recommendation, aggregate tradeoff plot, versions, and open items](method-freeze-recommendation.md).
- [Machine-readable proposed method](proposed-math-method.json).
- [Ben's prediction, scoring, verification, and defect-reporting commands](final-evaluation-handoff.md).

The shared importer was verified in Namit's PR #31 at commit
`1fbcd7c9f413f33d30eafa4653dd1c7c9d809683`, in
`eeg_app/public_muse.py`: `import_public_muse_recording` calls
`_read_edf_event_times(raw.annotations, raw.first_time)`. The legacy BLP helper
still exists, but that import path uses the Muse EDF's own annotations.
This confirms the shared fix without merging or modifying Namit's branch.

The fresh P0005 sample-based run reproduced all 2,592 feature values and all
three detector evaluations. Tests: 206 run, 199 passed, seven C tests skipped
because clang is unavailable. Saved-setting source fingerprints match the
committed implementation. The synthetic checkpoint backend checks the handoff
API; it does not establish that Namit's final real checkpoint runs locally.

## Work that must not be marked complete yet

- Deliver the recommendation prepared on November 26 to Zach and obtain
  approval of the exact method and minimum useful clean retention.
- Record the independently reconciled P0005 release; rerun the same fixed
  development grid and comparison if labels change.
- Obtain and pin the final CNN checkpoint, normalization, code version, and
  training metadata. The supplied CNN run used P0001/P0003 and 89 training
  windows; math used the four approved November 8 participants and 418 eligible
  windows. Resolve that difference for the final handoff.
- After approval, Ben runs the reserved recordings with the saved method and
  finalized private labels. Check his returned report for missing predictions,
  window-set mismatches, denominators, and reproducibility. Report the result
  even if agreement does not improve performance, and document defects before
  a corrected rerun.

The submission contains reusable code, documentation, aggregate results, and
the plot. Real recordings, review sheets, checkpoints, and per-window outputs
remain private.
