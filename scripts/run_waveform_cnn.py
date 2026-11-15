"""Train the waveform-only CNN on an approved participant split manifest.

Keep labels, local recordings, models, and output predictions outside Git.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eeg_app.waveform_cnn import (
    eligible_examples,
    join_reviewed_waveforms,
    load_checkpoint,
    load_final_review_labels,
    majority_class_predictions,
    predict_examples,
    select_participants,
    save_checkpoint,
    train_baseline,
    write_prediction_records,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, nargs="+", required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    manifest = json.loads(arguments.split_manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "approved":
        parser.error("Split manifest is not approved; confirm it with Samuel before training.")
    folds = manifest.get("folds")
    if not isinstance(folds, list) or not folds:
        parser.error("Split manifest must contain a nonempty folds list.")

    labels = load_final_review_labels(arguments.labels)
    examples, report = join_reviewed_waveforms(arguments.sessions_dir, labels)
    print("join report:", report)
    if not eligible_examples(examples):
        parser.error("No eligible clean/artifact waveform windows were found.")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)

    for fold in folds:
        fold_id = fold["fold_id"]
        held_out = fold["held_out"]
        validation = fold["validation"]
        training = fold["training"]
        if not isinstance(fold_id, str) or not isinstance(held_out, str) or not isinstance(validation, str):
            parser.error("Each fold must provide string fold_id, held_out, and validation values.")
        if not isinstance(training, list) or not all(isinstance(item, str) for item in training):
            parser.error("Each fold must provide a training list of participant IDs.")

        result = train_baseline(
            select_participants(examples, training),
            select_participants(examples, [validation]),
        )
        held_out_examples = select_participants(examples, [held_out])
        predictions = predict_examples(held_out_examples, result, fold_id=fold_id)
        checkpoint_path = arguments.output_dir / f"{fold_id}-checkpoint.pt"
        save_checkpoint(result, checkpoint_path)
        reloaded_predictions = predict_examples(
            held_out_examples, load_checkpoint(checkpoint_path), fold_id=fold_id
        )
        if predictions != reloaded_predictions:
            raise RuntimeError(f"{fold_id}: predictions changed after checkpoint reload.")
        write_prediction_records(predictions, arguments.output_dir / f"{fold_id}-predictions.jsonl")
        write_prediction_records(
            majority_class_predictions(select_participants(examples, training), held_out_examples),
            arguments.output_dir / f"{fold_id}-majority-baseline.jsonl",
        )
        print(
            f"{fold_id}: epoch {result.best_epoch}, validation loss {result.validation_loss:.4f}, "
            f"held-out predictions {len(predictions)}; reload check passed"
        )


if __name__ == "__main__":
    main()
