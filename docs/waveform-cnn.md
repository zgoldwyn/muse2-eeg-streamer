# Waveform CNN baseline

This baseline learns only from raw two-second Muse waveform windows. Each input
has shape `4 x 512`, is in microvolts before normalization, and uses this exact
channel order: `TP9`, `AF7`, `AF8`, `TP10`.

Final review releases are joined by `window_id`. `clean` maps to 0 and
`artifact` maps to 1. `uncertain`/`unsure`, technically invalid, missing, and
unmatched windows are retained in the join report but excluded from model
fitting and evaluation.

The model is a CPU-sized PyTorch Conv1d baseline: 4-to-16 convolution, ReLU,
average pooling, 16-to-32 convolution, ReLU, adaptive average pooling,
dropout, and a 32-to-1 logit head. It uses `BCEWithLogitsLoss`; sigmoid turns
the logit into an artifact score, with 0.5 as the initial cutoff.

Use participant-level folds only. The shared manifest must hold one participant
out, use one other participant for validation, and train on the remaining two.
Normalize channels with mean and standard deviation calculated from training
waveforms only. Never use participant IDs, timestamps, event markers, review
notes, or mathematical-detector features as model inputs.

Real EEG files, final labels, checkpoints, and prediction exports remain in the
private research-data location and must not be committed to the code PR.

## Initial training settings

Use Adam with learning rate `0.001`, batch size `16`, random seed `17`, a
maximum of `40` epochs, and validation-loss early stopping after `6` epochs
without improvement. Report the majority-class result beside the CNN result.

The included split helper creates a draft rotating four-participant manifest.
Confirm its exact participant assignments with Samuel before any final run;
every session for a participant must remain in the same fold.

Each completed fold writes a private PyTorch checkpoint and reloads it in
evaluation mode before accepting the prediction export. The predictions must be
identical before and after reload.

After Samuel approves `docs/development-split-manifest.json`, set its `status`
to `approved` and run the private-data command below. The output directory is
also private and must not be committed.

```bash
# Fresh virtual environment: installs NumPy and the CPU-compatible PyTorch
# dependency declared by this project.
python -m pip install -e .

# If PyTorch was not installed by your platform's package resolver, install it
# explicitly, then confirm it imports before running training.
python -m pip install torch
python -c "import torch; print(torch.__version__)"

python scripts/run_waveform_cnn.py \
  --sessions-dir /path/to/MuseDataNov9/data/sessions \
  --labels /private-labels/review-*-final.csv \
  --split-manifest docs/development-split-manifest.json \
  --output-dir /private-output/waveform-cnn
```
