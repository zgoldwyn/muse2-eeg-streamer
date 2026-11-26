# Saved-method evaluation handoff

`python -m eeg_app.final_evaluation` applies saved settings without searching
thresholds or training a model. It has separate `predict`, `score`, and `verify`
commands. Run from the repository root, with all participant files in private
storage. The reserved evaluation is performed by Ben after Zach approves the
freeze. The commands below have been exercised on synthetic data and on the
approved P0005 development sessions using the actual CNN prediction export.
Actual frozen-checkpoint inference remains to be exercised with Namit's final
checkpoint; its API is tested with a synthetic backend, not a real network.

## Before the reserved run

Use a checkout containing this handoff and Namit's PR #31 `eeg_app.waveform_cnn`
module. Follow his PyTorch installation instructions in `docs/waveform-cnn.md`.
The checkpoint is loaded on CPU and includes the training-only normalizer.
No EDF importer or public-data download is needed for these local sessions.

Resolve the items in [the recommendation](method-freeze-recommendation.md).
Copy `docs/proposed-math-method.json` to private storage. After Zach's approval,
record the actual approving person and date, final reconciled development
label versions, final code/data versions, the exact final CNN checkpoint and
CNN source SHA-256 hashes, and its complete training metadata. Clear the
resolved `open_items`, set `development_label_status` to `reconciled`, and set
the outer status to `approved_frozen`. Do not make these changes as a substitute
for approval. Save this one artifact as `frozen-method.json`; do not edit it
after evaluation starts. The nested math settings retain their existing schema.

`source_sha256_lf` pins the math, loader, feature, and scorer implementations.
CNN `source_sha256_lf` separately pins `waveform_cnn.py`. Source hashes normalize
CRLF to LF. `checkpoint_sha256` hashes the original checkpoint bytes. The
inference command rejects changes to these versions and a different checkpoint.

Create a private session manifest listing only the approved reserved sessions.
Each entry uses the saved session ID as its key, a path to the directory with
`eeg.csv` and `metadata.json`, and the participant code. Keep all refits of the
same person under the same participant identity. For example, this is the
manifest shape using a **synthetic** session:

```json
{
  "integration-demo-001": {
    "path": "tests/fixtures/integration/integration-demo-001",
    "participant_id": "synthetic-person"
  }
}
```

Paths are resolved from the current working directory. There is no recursive
search through unrelated recordings. Real session IDs and paths belong in the
private manifest, rather than this documentation.

## Ben: generate predictions, then score

Set these PowerShell variables to the approved private files and choose new
output directories. The command syntax is complete; paths identify Ben's
private inputs and are not recordings supplied in the repository.

```powershell
$privateRoot = "C:/path/to/private-evaluation"
$method = "$privateRoot/frozen-method.json"
$sessions = "$privateRoot/reserved-sessions.json"
$checkpoint = "$privateRoot/final-cnn.pt"
$reviews = "$privateRoot/reconciled-reserved-reviews.zip"
$release = "THE-EXACT-FINAL-RESERVED-LABEL-RELEASE"

python -m eeg_app.final_evaluation predict $sessions --settings $method --checkpoint $checkpoint --output-dir "$privateRoot/reserved-predictions"

python -m eeg_app.final_evaluation score "$privateRoot/reserved-predictions/predictions.json" --settings $method --labels $reviews --label-release $release --output-dir "$privateRoot/reserved-report"

python -m eeg_app.final_evaluation verify "$privateRoot/reserved-predictions/predictions.json" --settings $method --labels $reviews --label-release $release --report "$privateRoot/reserved-report/report.json"
```

`predict` reads no human labels or prompts. It loads Namit's original windows,
calculates all six existing features per channel, records technical exclusions,
and applies the saved math policy. It passes the same valid four-channel
waveforms to Namit's `load_checkpoint` / `predict_examples` API and applies the
saved CNN cutoff. It reloads the checkpoint and checks identical predictions.
PR #31's inference API filters examples by its training-label field; the adapter
uses an internal inclusion sentinel with `review_label: inference_only`.
That sentinel is not a human label and is never used as a reference or for
model fitting. No normalization is fitted on these recordings.

`score` validates the completed review sheets against the loader's saved IDs
and exact intervals. It preserves uncertain and invalid exclusions, requires
every eligible prediction, checks saved math decisions and trigger explanations
against the features, and checks CNN versions, identities, scores, and cutoff.
The existing scorer reports math, CNN, both-clean acceptance, the fixed
training-majority comparator, and always-clean comparator. Artifact is the
positive class. Every rate includes its numerator and denominator; zero
denominators remain unavailable.

`verify` recomputes the report from the same frozen artifact, predictions, and
review release. A changed window set, decision, denominator, count, or provenance
fails verification. On success it prints:

```text
VERIFIED: same eligible IDs, predictions, confusion counts, denominators, and provenance
```

All three commands write private outputs. Prediction JSON includes features,
IDs, trigger explanations, input hashes, and exclusions. The report directory
contains `report.json` and a compact `summary.md`. Existing output directories
are refused; failed runs do not publish a partial output directory. Keep the
prediction bundle, frozen artifact, original review release, and report together
in the private handoff. Provide Samuel the report for interpretation, even if
the combined rule offers no benefit or clean retention misses the proposed
minimum.

If a command fails, save its command line and error before changing anything.
Document any defect discovered after evaluation and obtain agreement on the
corrected rerun. Do not adjust thresholds after inspecting reserved results.

## Development dry run performed locally

The development-only manifest lists P0005's three approved sessions. No reserved
session was opened. The CNN input here is Namit's actual native ZIP; it is not
a substitute for the final checkpoint handoff.

```powershell
python -m eeg_app.final_evaluation predict data/private/thanksgiving/handoff-p0005-manifest.json --settings docs/proposed-math-method.json --cnn-predictions "C:/Users/XBbur/Downloads/P0005-CNN-validation-output.zip" --development --output-dir data/private/thanksgiving/handoff-dry-run-v2/predictions

python -m eeg_app.final_evaluation score data/private/thanksgiving/handoff-dry-run-v2/predictions/predictions.json --settings docs/proposed-math-method.json --labels "C:/Users/XBbur/Downloads/P0005-reviews.zip" --label-release P0005-reviews.zip --development --output-dir data/private/thanksgiving/handoff-dry-run-v2/report

python -m eeg_app.final_evaluation verify data/private/thanksgiving/handoff-dry-run-v2/predictions/predictions.json --settings docs/proposed-math-method.json --labels "C:/Users/XBbur/Downloads/P0005-reviews.zip" --label-release P0005-reviews.zip --development --report data/private/thanksgiving/handoff-dry-run-v2/report/report.json
```

The draft artifact requires `--development`; a reserved run refuses it.
Existing development CNN exports are accepted only with that flag. The same
settings hash follows predictions through scoring and verification. The math
pipeline processes all 108 technically valid windows without consulting labels;
the human review later identifies the 88 eligible binary-scoring windows.
The supplied CNN export covers exactly those 88 eligible IDs.

Tests:

```text
python -m unittest tests.test_final_evaluation tests.test_math_detector tests.test_rule_search tests.test_validation_comparison
python -m unittest discover -s tests
```

Observed local validation:

```text
development: 108 math predictions; 88 CNN predictions
VERIFIED: same eligible IDs, predictions, confusion counts, denominators, and provenance
Ran 206 tests
OK (skipped=7)
```

The fresh sample-based run exactly reproduced all 2,592 previously prepared
feature values, their units, unavailability reasons, definitions, IDs, and
intervals. All three detector evaluations exactly matched the earlier native
export comparison: math TP/FP/TN/FN = 35/0/53/0; CNN and agreement =
35/12/41/0. The draft was also confirmed to fail the reserved-run approval
check. Tests cover the checkpoint API with a synthetic backend and approved
synthetic settings; no real reserved session or checkpoint was used.
