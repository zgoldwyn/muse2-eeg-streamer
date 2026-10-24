"""Generate the known-answer integration session ``integration-demo-001``.

Run from the repository root:

    python3 -m tests.fixtures.integration.generate_fixture

This writes ``tests/fixtures/integration/integration-demo-001/`` with the
existing session writer. The writer refuses to overwrite a session, so delete
that folder first to regenerate it. Pass --sessions-dir to write somewhere else.

SYNTHETIC ONLY: no headset, Bluetooth or C scanner is used. See README.md in
this folder for the exact answer key.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from math import pi, sin
from pathlib import Path

from eeg_app.recording import (
    NOMINAL_SAMPLE_RATE_HZ,
    SAMPLES_PER_PACKET,
    RecordingError,
    SampleRecord,
    record_session,
)
from eeg_app.preprocessing import REQUIRED_CHANNELS

SESSION_ID = "integration-demo-001"
FIXTURE_DIR = Path(__file__).resolve().parent

PACKET_SLOTS = range(0, 128)  # packet slots 0..127: 6 s at 256 Hz
MISSING_PACKET = 50  # absent on all four channels

# Baseline: a fixed offset per channel, a small 10 Hz wave and a slow 0.5 Hz drift.
CHANNEL_OFFSETS_UV = {"TP9": 0.0, "AF7": 5.0, "AF8": -5.0, "TP10": 10.0}
BASELINE_WAVE_HZ = 10.0
BASELINE_WAVE_UV = 4.0
DRIFT_HZ = 0.5
DRIFT_UV = 2.0

# Disturbance: AF7 only, packets 96..99 (all 12 samples of each), 48 samples,
# elapsed_s 4.5 to 4.68359375. A half-sine bump peaking at about +300 µV.
DISTURBANCE_CHANNEL = "AF7"
DISTURBANCE_PACKETS = range(96, 100)
DISTURBANCE_PEAK_UV = 300.0
DISTURBANCE_SAMPLES = len(DISTURBANCE_PACKETS) * SAMPLES_PER_PACKET


def elapsed_s(packet_index: int, sample_in_packet: int) -> float:
    """Sample-estimated time; a missing packet keeps its place in the grid."""
    return (packet_index * SAMPLES_PER_PACKET + sample_in_packet) / NOMINAL_SAMPLE_RATE_HZ


def baseline_uv(channel: str, t: float) -> float:
    return (
        CHANNEL_OFFSETS_UV[channel]
        + BASELINE_WAVE_UV * sin(2 * pi * BASELINE_WAVE_HZ * t)
        + DRIFT_UV * sin(2 * pi * DRIFT_HZ * t)
    )


def disturbance_uv(channel: str, packet_index: int, sample_in_packet: int) -> float:
    if channel != DISTURBANCE_CHANNEL or packet_index not in DISTURBANCE_PACKETS:
        return 0.0
    k = (packet_index - DISTURBANCE_PACKETS.start) * SAMPLES_PER_PACKET + sample_in_packet
    return DISTURBANCE_PEAK_UV * sin(pi * (k + 0.5) / DISTURBANCE_SAMPLES)


def integration_records() -> Iterator[SampleRecord]:
    """Yield records packet by packet, then channel by channel, then sample."""
    for packet_index in PACKET_SLOTS:
        if packet_index == MISSING_PACKET:
            continue  # left out, never filled with replacement values
        for channel in REQUIRED_CHANNELS:
            for position in range(SAMPLES_PER_PACKET):
                t = elapsed_s(packet_index, position)
                value = baseline_uv(channel, t) + disturbance_uv(channel, packet_index, position)
                yield SampleRecord(
                    channel=channel,
                    packet_index=packet_index,
                    sample_in_packet=position,
                    microvolts=round(value, 2),
                    elapsed_s=t,
                )


def generate(sessions_dir: str | Path = FIXTURE_DIR) -> Path:
    """Write the session with the existing writer and return its directory."""
    return record_session(integration_records(), sessions_dir, SESSION_ID, data_source="synthetic")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Write the synthetic {SESSION_ID} session.")
    parser.add_argument("--sessions-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args(argv)
    try:
        session_dir = generate(args.sessions_dir)
    except RecordingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"SYNTHETIC: wrote {session_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
