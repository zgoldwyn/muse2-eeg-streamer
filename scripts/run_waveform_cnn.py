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
    validate_split_manifest,
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
    labels = load_final_review_labels(arguments.labels)
    examples, report = join_reviewed_waveforms(arguments.sessions_dir, labels)
    print("join report:", report)
    if not eligible_examples(examples):
        parser.error("No eligible clean/artifact waveform windows were found.")
    try:
        folds = validate_split_manifest(
            manifest,
            available_participants={example.participant_id for example in eligible_examples(examples)},
        )
    except ValueError as error:
        parser.error(str(error))
    arguments.output_dir.mkdir(parents=True, exist_ok=True)

    for fold in folds:
        fold_id = fold["fold_id"]
        held_out = fold["held_out"]
        validation = fold["validation"]
        training = fold["training"]
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
