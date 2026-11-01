"""Export prediction-free EEG review sheets and validate completed annotations."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path

from .dataset import EegWindow, create_fixed_windows, load_synthetic_session
from .metrics import VALID_REFERENCE_LABELS, evaluate_predictions
from .preprocessing import REQUIRED_CHANNELS


REVIEW_COLUMNS = (
    "session_id", "window_id", "start_time_s", "end_time_s", "reviewer_id",
    "label", "suspected_subtype", "affected_channels", "evidence_notes",
    "uncertainty", "trace_file",
)
INVALID_COLUMNS = (
    "session_id", "window_id", "start_time_s", "end_time_s", "loader_reasons", "trace_file",
)


def load_windows(session_dir: str | Path) -> list[EegWindow]:
    """Use the saved session and Namit's actual IDs, intervals, and validity."""
    root = Path(session_dir)
    session = load_synthetic_session(root / "eeg.csv", root / "metadata.json")
    return create_fixed_windows(session)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _trace_segments(times, samples, rate):
    """Preserve actual time positions; never draw across a missing sample."""
    segments = []
    for index, (time, value) in enumerate(zip(times, samples)):
        if index == 0 or time - times[index - 1] > 1.5 / rate:
            segments.append([])
        segments[-1].append((time, value))
    return segments


def _write_trace(window: EegWindow, path: Path) -> None:
    """Draw four raw saved microvolt traces with shared scale and real time axes.

    SVG is a local, browser-viewable plot format, requiring no third-party
    libraries. These are decoded saved values, not raw device ADC counts.
    No feature or prediction function is imported or called.
    """
    values = [value for channel in REQUIRED_CHANNELS for value in window.channel_samples[channel]]
    low, high = (min(values), max(values)) if values else (-1.0, 1.0)
    padding = (high - low) * 0.05 or max(abs(low) * 0.05, 1.0)
    low, high = low - padding, high + padding
    start, end = window.start_time_s, window.end_time_s
    x0, width, panel_height, plot_height = 100, 940, 155, 105
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="760" viewBox="0 0 1120 760">',
        '<rect width="1120" height="760" fill="white"/>',
        '<g font-family="sans-serif" font-size="13" fill="#202832">',
        f'<text x="100" y="28" font-size="19">{html.escape(window.window_id)}</text>',
        f'<text x="100" y="52">Saved EEG samples · [{start:g}, {end:g}) seconds · microvolts · unfiltered</text>',
        '<text x="100" y="73">Shared vertical scale across channels; missing samples are breaks in the trace.</text>',
    ]
    for channel_index, channel in enumerate(REQUIRED_CHANNELS):
        top = 100 + channel_index * panel_height
        parts.append(f'<text x="{x0}" y="{top - 12}">{channel}</text>')
        for value in (low, (low + high) / 2, high):
            y = top + plot_height * (high - value) / (high - low)
            parts.append(f'<path d="M{x0} {y:.2f}h{width}" stroke="#dce1e7"/>')
            parts.append(f'<text x="92" y="{y + 4:.2f}" text-anchor="end">{value:.2f}</text>')
        for tick in range(5):
            time = start + (end - start) * tick / 4
            x = x0 + width * tick / 4
            parts.append(f'<path d="M{x:.2f} {top}v{plot_height}" stroke="#e7eaee"/>')
            parts.append(f'<text x="{x:.2f}" y="{top + plot_height + 19}" text-anchor="middle">{time:g}</text>')
        segments = _trace_segments(window.channel_times_s[channel], window.channel_samples[channel],
                                   window.nominal_sample_rate_hz)
        for segment in segments:
            points = [(x0 + width * (time - start) / (end - start),
                       top + plot_height * (high - value) / (high - low)) for time, value in segment]
            if len(points) == 1:
                x, y = points[0]
                parts.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="1.8" fill="#234d70"/>')
            else:
                coordinates = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
                parts.append(f'<polyline data-channel="{channel}" points="{coordinates}" '
                             'fill="none" stroke="#234d70" stroke-width="1.2"/>')
        if not segments:
            parts.append(f'<text x="120" y="{top + 50}">No saved samples for this channel</text>')
    parts.append('<text x="570" y="748" text-anchor="middle">Session elapsed time (seconds)</text></g></svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def export_review_bundle(session_dir: str | Path, output_dir: str | Path) -> dict[str, int]:
    """Create a new bundle; leave every human annotation field blank."""
    windows = load_windows(session_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "traces").mkdir()
    review_rows, invalid_rows = [], []
    valid_links, invalid_links = [], []
    for index, window in enumerate(windows):
        trace_file = f"traces/trace-{index:06d}.svg"
        _write_trace(window, output / trace_file)
        identity = {
            "session_id": window.session_id, "window_id": window.window_id,
            "start_time_s": window.start_time_s, "end_time_s": window.end_time_s,
            "trace_file": trace_file,
        }
        link = (f'<li><a href="{trace_file}">{html.escape(window.window_id)} '
                f'[{window.start_time_s:g}, {window.end_time_s:g}) seconds</a>')
        if window.is_valid:
            review_rows.append({**dict.fromkeys(REVIEW_COLUMNS, ""), **identity})
            valid_links.append(link + '</li>')
        else:
            invalid_rows.append({**identity, "loader_reasons": json.dumps(list(window.invalid_reasons))})
            invalid_links.append(link + "<ul>" + "".join(
                f"<li>{html.escape(reason)}</li>" for reason in window.invalid_reasons
            ) + "</ul></li>")
    _write_csv(output / "review.csv", REVIEW_COLUMNS, review_rows)
    _write_csv(output / "technically_invalid.csv", INVALID_COLUMNS, invalid_rows)
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>EEG reviewer traces</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;line-height:1.6}li{margin:8px 0}</style>
<h1>EEG review</h1><p>Inspect the four saved channel traces using the links below,
then fill in a copy of <a href="review.csv">review.csv</a>. No signal processing
or resampling is applied. Each plot uses a shared vertical scale across channels.
This view provides no automated decisions or suggested human labels.</p>
<p>Enter your reviewer ID and one label: clean, artifact, uncertain, or invalid.
Use suspected_subtype and evidence_notes to explain your judgment;
affected_channels accepts TP9;AF7;AF8;TP10 as applicable. Record confidence or
boundary ambiguity in uncertainty as free text; label uncertain remains a
distinct decision. Do not infer clean from a missing marker. Prompts and
operator observations, if supplied separately later, are context only.</p>
<h2>Windows for human review</h2><ul>'''
    page += "".join(valid_links) or "<li>No technically valid windows.</li>"
    page += '</ul><h2>Technically invalid windows (loader exclusions)</h2><p>These are separate from human annotations; do not relabel them clean.</p><ul>'
    page += "".join(invalid_links) or "<li>No technical exclusions.</li>"
    page += '</ul><p><a href="technically_invalid.csv">Download loader exclusions and reasons</a></p></html>'
    (output / "index.html").write_text(page, encoding="utf-8")
    return {"total_windows": len(windows), "review_windows": len(review_rows),
            "technically_invalid_windows": len(invalid_rows)}


def validate_review_sheet(session_dir: str | Path, sheet_path: str | Path) -> list[dict]:
    """Validate a complete single-reviewer sheet against the actual loader output.

    All technically valid windows require one human label and reviewer ID.
    Technical exclusions cannot be overridden by adding them to the human sheet.
    Shape validation alone does not establish reviewer independence or adjudication.
    """
    windows = load_windows(session_dir)
    expected = {window.window_id: window for window in windows if window.is_valid}
    excluded = {window.window_id for window in windows if not window.is_valid}
    seen, records, errors = set(), [], []
    with Path(sheet_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)):
            raise ValueError("Review sheet has duplicate column names.")
        missing_columns = set(REVIEW_COLUMNS) - set(columns)
        if missing_columns:
            raise ValueError("Review sheet missing columns: " + ", ".join(sorted(missing_columns)))
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                errors.append(f"Row {line}: wrong number of CSV fields.")
                continue
            row = {name: value.strip() for name, value in row.items()}
            window_id = row["window_id"]
            prefix = f"Row {line}, window {window_id!r}"
            if window_id in seen:
                errors.append(f"{prefix}: duplicate window ID.")
                continue
            seen.add(window_id)
            if window_id in excluded:
                errors.append(f"{prefix}: technically invalid window belongs in the loader exclusion list.")
                continue
            if window_id not in expected:
                errors.append(f"{prefix}: unknown window ID.")
                continue
            window = expected[window_id]
            if row["session_id"] != window.session_id:
                errors.append(f"{prefix}: session ID does not match the saved session.")
            for name in ("start_time_s", "end_time_s"):
                try:
                    value = float(row[name])
                except ValueError:
                    value = math.nan
                if not math.isfinite(value) or not math.isclose(value, getattr(window, name), rel_tol=0, abs_tol=1e-9):
                    errors.append(f"{prefix}: {name} does not match the loader interval.")
            if not row["label"]:
                errors.append(f"{prefix}: missing required human label.")
            elif row["label"] not in VALID_REFERENCE_LABELS:
                errors.append(f"{prefix}: unsupported label {row['label']!r}; use clean, artifact, uncertain, or invalid.")
            if not row["reviewer_id"]:
                errors.append(f"{prefix}: missing required reviewer ID.")
            affected = [value.strip() for value in row["affected_channels"].split(";") if value.strip()]
            if set(affected) - set(REQUIRED_CHANNELS):
                errors.append(f"{prefix}: affected_channels must use TP9;AF7;AF8;TP10.")
            records.append({
                "session_id": window.session_id, "window_id": window.window_id,
                "start_time_s": window.start_time_s, "end_time_s": window.end_time_s,
                "reviewer_id": row["reviewer_id"], "label": row["label"],
                "suspected_subtype": row["suspected_subtype"], "affected_channels": affected,
                "evidence_notes": row["evidence_notes"], "uncertainty": row["uncertainty"],
                "label_source": "human_review",
            })
    for window_id in expected.keys() - seen:
        errors.append(f"Missing review row and required label for window {window_id!r}.")
    if errors:
        raise ValueError("Review validation failed:\n" + "\n".join(errors))
    return records


def validated_reference_records(session_dir: str | Path, sheet_path: str | Path) -> list[dict[str, str]]:
    """Convert validated human labels plus technical exclusions to metrics input.

    No predictions or feature values participate. Uncertain and invalid stay
    distinct; metrics.py excludes both from its primary binary metrics.
    """
    reviewed = {row["window_id"]: row for row in validate_review_sheet(session_dir, sheet_path)}
    return [{"window_id": window.window_id,
             "label": reviewed[window.window_id]["label"] if window.is_valid else "invalid"}
            for window in load_windows(session_dir)]


def evaluate_review_sheet(session_dir: str | Path, sheet_path: str | Path, predictions) -> dict:
    """Evaluate supplied predictions against validated, separately completed labels.

    No predictions are made here and no labels are inferred from predictions.
    The existing evaluator owns eligibility, ID matching, and metric definitions.
    """
    references = validated_reference_records(session_dir, sheet_path)
    return evaluate_predictions(references, predictions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Create a blank sheet and raw trace plots.")
    generate.add_argument("session_dir", type=Path)
    generate.add_argument("output_dir", type=Path)
    validate = commands.add_parser("validate", help="Validate a completed sheet, optionally export records.")
    validate.add_argument("session_dir", type=Path)
    validate.add_argument("sheet", type=Path)
    validate.add_argument("--output-dir", type=Path, help="New directory for reviewed records and metrics-format labels.")
    evaluate = commands.add_parser("evaluate", help="Evaluate supplied predictions against a completed sheet.")
    evaluate.add_argument("session_dir", type=Path)
    evaluate.add_argument("sheet", type=Path)
    evaluate.add_argument("predictions", type=Path, help="JSON list of window_id/decision records.")
    evaluate.add_argument("--output-dir", type=Path, help="New local directory for evaluation.json.")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            print(json.dumps(export_review_bundle(args.session_dir, args.output_dir)))
            print(f"Open {args.output_dir / 'index.html'} to inspect traces; human labels are blank.")
        elif args.command == "validate":
            records = validate_review_sheet(args.session_dir, args.sheet)
            references = validated_reference_records(args.session_dir, args.sheet)
            if args.output_dir:
                args.output_dir.mkdir(parents=True, exist_ok=False)
                (args.output_dir / "reviewed_records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
                (args.output_dir / "reference_records.json").write_text(json.dumps(references, indent=2), encoding="utf-8")
            print(f"Validated {len(records)} human labels; {len(references) - len(records)} technical exclusions retained.")
        else:
            predictions = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            evaluation = evaluate_review_sheet(args.session_dir, args.sheet, predictions)
            if args.output_dir:
                args.output_dir.mkdir(parents=True, exist_ok=False)
                (args.output_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
            print(json.dumps(evaluation, indent=2))
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
