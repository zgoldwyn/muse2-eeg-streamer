"""Small, temporary terminal guide for one Muse pilot capture.

Run from the repository root: ``python3 -m eeg_app.guided_pilot``.
The cues and Space presses are timing hints, never reference EEG labels.
"""

from __future__ import annotations

import csv
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime, timezone
from pathlib import Path

from .live_adapter import iter_packet_lines, parse_eeg_packet_line, record_packet_lines
from .recording import check_session, format_report, read_session
from .review import export_review_bundle


# Pilot-only cues, not a finalized participant protocol.
CUES = (
    ("Rest quietly", 10),
    ("Blink softly twice, then firmly once", 10),
    ("Rest quietly", 10),
    ("Raise your eyebrows", 10),
    ("Rest quietly", 10),
    ("Move your head gently", 10),
    ("Rest quietly", 10),
)
READY = {1: "blink", 3: "raise your eyebrows", 5: "move your head gently"}
SCANNER = Path("muse2-c/build/muse2_scan")


def main() -> int:
    if not sys.stdin.isatty():
        print("Run this in a terminal so Space can mark an observed blink.", file=sys.stderr)
        return 1
    if not SCANNER.is_file():
        print("Build the scanner first: cd muse2-c && make scan", file=sys.stderr)
        return 1

    session_id = "pilot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    events: list[tuple[str, str, int, float]] = []
    first_receipt_ns: int | None = None
    cue_index = 0
    ready_announced_for: int | None = None
    next_cue_s = 0
    duration_s = sum(seconds for _, seconds in CUES)
    terminal_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(terminal_fd)

    print(f"Starting {duration_s}-second pilot-only recording. Press Space when you observe a blink.")
    print("Keep the headset wearer still; ideally, another person presses Space. Ctrl+C aborts.")
    print("Waiting for Muse EEG packets...", flush=True)
    scanner = subprocess.Popen([str(SCANNER)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        tty.setcbreak(terminal_fd)

        def guided_lines():
            nonlocal first_receipt_ns, cue_index, ready_announced_for, next_cue_s
            assert scanner.stdout is not None
            for line in iter_packet_lines(scanner.stdout):
                receipt_ns = parse_eeg_packet_line(line).receipt_monotonic_ns
                if first_receipt_ns is None:
                    first_receipt_ns = receipt_ns
                elapsed_s = (receipt_ns - first_receipt_ns) / 1e9

                while cue_index < len(CUES) and elapsed_s >= next_cue_s:
                    cue, seconds = CUES[cue_index]
                    stamp_ns = time.monotonic_ns()
                    approx_s = (stamp_ns - first_receipt_ns) / 1e9
                    events.append(("prompt", cue, stamp_ns, approx_s))
                    print(f"\n{approx_s:5.1f}s  NOW: {cue}", flush=True)
                    if shutil.which("say"):
                        subprocess.Popen(["say", cue], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    next_cue_s += seconds
                    cue_index += 1

                if (cue_index in READY and ready_announced_for != cue_index
                        and next_cue_s - 3 <= elapsed_s < next_cue_s):
                    message = f"Get ready to {READY[cue_index]}"
                    stamp_ns = time.monotonic_ns()
                    approx_s = (stamp_ns - first_receipt_ns) / 1e9
                    events.append(("ready", message, stamp_ns, approx_s))
                    print(f"\n{approx_s:5.1f}s  {message}...", flush=True)
                    if shutil.which("say"):
                        subprocess.Popen(["say", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    ready_announced_for = cue_index

                if select.select([terminal_fd], [], [], 0)[0]:
                    for key in os.read(terminal_fd, 32):
                        if key == ord(" "):
                            stamp_ns = time.monotonic_ns()
                            approx_s = (stamp_ns - first_receipt_ns) / 1e9
                            events.append(("space_pressed", "possible blink", stamp_ns, approx_s))
                            print(f"\n{approx_s:5.1f}s  Blink marker noted", flush=True)

                if elapsed_s >= duration_s:
                    return
                yield line
            raise RuntimeError("Scanner stopped before the pilot finished; recording is incomplete.")

        session_dir = record_packet_lines(guided_lines(), Path("data/sessions"), session_id)
    finally:
        termios.tcsetattr(terminal_fd, termios.TCSADRAIN, old_settings)
        scanner.terminate()
        try:
            scanner.wait(timeout=3)
        except subprocess.TimeoutExpired:
            scanner.kill()
            scanner.wait()

    with (session_dir / "pilot_events.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("session_id", "event_type", "detail", "monotonic_ns", "approx_elapsed_s"))
        writer.writerows((session_id, *event) for event in events)

    saved = read_session(session_dir)
    print("\n" + format_report(saved, check_session(saved)))
    review_dir = Path("recordings") / f"{session_id}-review"
    summary = export_review_bundle(session_dir, review_dir)
    print(f"Events: {session_dir / 'pilot_events.csv'}")
    print(f"Review plots and blank labels: {review_dir / 'index.html'}")
    print(f"Reviewable windows: {summary['review_windows']} / {summary['total_windows']}")
    print("Times are approximate relative to first packet receipt; prompts and keypresses are not artifact labels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
