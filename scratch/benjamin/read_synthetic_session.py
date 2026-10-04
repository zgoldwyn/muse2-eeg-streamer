"""Read a synthetic EEG session CSV, validate it, and print a summary.

By default it reads synthetic_eeg.csv from the same folder as this script,
so it can be run from the repository root:
    python3 path/to/read_synthetic_session.py

Optionally pass a different CSV path as the first argument (useful for
testing broken files):
    python3 path/to/read_synthetic_session.py path/to/other.csv

Uses only the Python standard library. Needs no headset, Bluetooth,
C scanner, or live graph.
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent / "synthetic_eeg.csv"

REQUIRED_COLUMNS = [
    "session_id",
    "elapsed_s",
    "channel",
    "packet_index",
    "sample_in_packet",
    "microvolts",
]
KNOWN_CHANNELS = ["TP9", "AF7", "AF8", "TP10"]
SAMPLES_PER_PACKET = 12
PACKET_INDEX_MODULUS = 65536  # packet index is 16-bit, so it wraps 65535 -> 0


def fail(message):
    """Print an error explanation and stop the program."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def parse_number(text, convert, column, row_number):
    """Convert one cell to int/float, or fail with the row and column named."""
    try:
        return convert(text)
    except (ValueError, TypeError):
        fail(f"row {row_number}: column '{column}' has value {text!r}, "
             f"which is not a valid {convert.__name__}")


def read_rows(csv_path):
    """Open the CSV, check its columns, and return a list of validated rows."""
    if not csv_path.exists():
        fail(f"file not found: {csv_path}")

    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            fail(f"file is empty: {csv_path}")
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            fail(f"missing required column(s): {', '.join(missing)}. "
                 f"Found: {', '.join(reader.fieldnames)}")

        rows = []
        # Row 1 is the header, so data starts at row 2 (matches a spreadsheet view).
        for row_number, raw in enumerate(reader, start=2):
            channel = raw["channel"]
            if channel not in KNOWN_CHANNELS:
                fail(f"row {row_number}: unknown channel {channel!r}. "
                     f"Expected one of: {', '.join(KNOWN_CHANNELS)}")

            sample_in_packet = parse_number(raw["sample_in_packet"], int, "sample_in_packet", row_number)
            if not 0 <= sample_in_packet < SAMPLES_PER_PACKET:
                fail(f"row {row_number}: sample_in_packet is {sample_in_packet}, "
                     f"expected 0 to {SAMPLES_PER_PACKET - 1}")

            rows.append({
                "session_id": raw["session_id"],
                "elapsed_s": parse_number(raw["elapsed_s"], float, "elapsed_s", row_number),
                "channel": channel,
                "packet_index": parse_number(raw["packet_index"], int, "packet_index", row_number),
                "sample_in_packet": sample_in_packet,
                "microvolts": parse_number(raw["microvolts"], float, "microvolts", row_number),
            })

    if not rows:
        fail(f"file has a header but no data rows: {csv_path}")
    return rows


def find_gaps(packet_indices):
    """Return (previous, next, missing_list) for every step that isn't +1.

    packet_indices must be in the order packets arrived.
    Wraparound (65535 -> 0) counts as consecutive. A step backwards (a
    repeated or out-of-order packet) is returned with missing_list = None
    instead of being reported as ~65,000 missing packets.
    """
    gaps = []
    for prev, curr in zip(packet_indices, packet_indices[1:]):
        step = (curr - prev) % PACKET_INDEX_MODULUS
        if step == 1:
            continue
        if step > PACKET_INDEX_MODULUS // 2:
            gaps.append((prev, curr, None))
        else:
            missing = [(prev + k) % PACKET_INDEX_MODULUS for k in range(1, step)]
            gaps.append((prev, curr, missing))
    return gaps


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    rows = read_rows(csv_path)

    # Walk the rows once per channel in arrival order. A new packet starts
    # whenever the packet index changes, so the same index can appear again
    # after wraparound (sessions longer than ~51 minutes) without being
    # mistaken for a duplicate.
    packets_by_channel = defaultdict(list)
    rows_by_channel = defaultdict(int)
    samples_in_current_packet = defaultdict(set)
    duplicates = []
    for row in rows:
        channel = row["channel"]
        packet_index = row["packet_index"]
        sample = row["sample_in_packet"]
        rows_by_channel[channel] += 1

        packets = packets_by_channel[channel]
        if not packets or packets[-1] != packet_index:
            packets.append(packet_index)
            samples_in_current_packet[channel] = set()

        if sample in samples_in_current_packet[channel]:
            duplicates.append((channel, packet_index, sample))
        samples_in_current_packet[channel].add(sample)

    session_ids = sorted({row["session_id"] for row in rows})
    elapsed = [row["elapsed_s"] for row in rows]

    # Show the path relative to where the script was run from, so output pasted
    # into a PR or doc doesn't include a personal home folder.
    try:
        shown_path = csv_path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        shown_path = csv_path
    print(f"File:            {shown_path}")
    print(f"Session ID(s):   {', '.join(session_ids)}")
    print(f"Total rows:      {len(rows)}")
    print(f"First elapsed_s: {min(elapsed):.6f}")
    print(f"Last elapsed_s:  {max(elapsed):.6f}")
    print()
    print("Rows per channel:")
    for channel in KNOWN_CHANNELS:
        print(f"  {channel:<5} {rows_by_channel[channel]}")
    print()
    print("Packet-index check (per channel):")
    any_gap = False
    any_step_back = False
    for channel in KNOWN_CHANNELS:
        indices = packets_by_channel[channel]
        if not indices:
            print(f"  {channel:<5} no packets")
            continue
        gaps = find_gaps(indices)
        span = f"packets {indices[0]}-{indices[-1]} ({len(indices)} present)"
        if not gaps:
            print(f"  {channel:<5} {span}, no gaps")
            continue
        for prev, curr, missing in gaps:
            if missing is None:
                any_step_back = True
                print(f"  {channel:<5} {span}, STEP BACK {prev} -> {curr} "
                      f"(repeated or out-of-order packet)")
            else:
                any_gap = True
                missing_text = ", ".join(str(m) for m in missing)
                print(f"  {channel:<5} {span}, GAP {prev} -> {curr}, missing: {missing_text}")

    if len(session_ids) > 1:
        print("\nWARNING: file contains more than one session_id")
    if any_step_back:
        print("\nWARNING: packet index stepped backwards at least once (see above)")
    if duplicates:
        print(f"\nWARNING: {len(duplicates)} duplicate sample row(s), first: "
              f"channel={duplicates[0][0]} packet={duplicates[0][1]} sample={duplicates[0][2]}")

    print()
    print("Summary: " + ("packet gaps found (see above)." if any_gap else "no packet gaps found."))


if __name__ == "__main__":
    main()
