"""Demonstrate the session writer and read-back check without a headset.

Run from the repository root:

    python3 -m eeg_app.demo_recording

By default the session is written to a temporary folder that is deleted
afterwards. Pass ``--sessions-dir data/sessions`` to keep it (``data/`` is
ignored by Git). This is a synthetic test only: no headset, Bluetooth or C
scanner is used.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .recording import RecordingError, record_session
from .session_reader import check_session, format_report, read_session
from .synthetic import synthetic_records


def run_demo(sessions_dir: Path, session_id: str, temporary: bool = False) -> bool:
    records = list(synthetic_records())
    session_dir = record_session(records, sessions_dir, session_id, data_source="synthetic")
    saved = read_session(session_dir)
    check = check_session(saved, expected_records=records)
    print("SYNTHETIC TEST: no headset or live data was used.")
    note = " (temporary folder, deleted after this run)" if temporary else ""
    print(f"Saved to: {session_dir}{note}")
    print(format_report(saved, check))
    return check.ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sessions-dir", type=Path,
                        help="keep the session here instead of a temporary folder")
    parser.add_argument("--session-id", default="demo-001")
    args = parser.parse_args(argv)

    try:
        if args.sessions_dir is not None:
            ok = run_demo(args.sessions_dir, args.session_id)
        else:
            with tempfile.TemporaryDirectory() as temp:
                ok = run_demo(Path(temp), args.session_id, temporary=True)
    except RecordingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
