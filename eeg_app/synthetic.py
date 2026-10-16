"""Synthetic EEG sample records for testing the recorder without a headset.

The default output matches ``scratch/benjamin/synthetic_eeg.csv``: packets
100, 101 and 103 (packet 102 deliberately missing) on all four channels, with
a 10 Hz, ±20 µV sine wave and a fixed offset per channel.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from math import pi, sin

from .preprocessing import REQUIRED_CHANNELS
from .recording import PACKET_INDEX_MODULUS, SAMPLE_RATE_HZ, SAMPLES_PER_PACKET, SampleRecord

DEMO_PACKETS = (100, 101, 103)
CHANNEL_OFFSETS_UV = {"TP9": 0.0, "AF7": 5.0, "AF8": -5.0, "TP10": 10.0}
SINE_HZ = 10.0
SINE_AMPLITUDE_UV = 20.0


def synthetic_records(
    packet_indices: Iterable[int] = DEMO_PACKETS,
    channels: Sequence[str] = REQUIRED_CHANNELS,
) -> Iterator[SampleRecord]:
    """Yield records packet by packet, then channel by channel, then sample.

    ``elapsed_s`` is estimated from packet timing, measured from the first
    packet (wraparound 65535 -> 0 is handled):

        elapsed_s = packets_since_first * 12/256 + sample_in_packet/256

    Leave an index out of ``packet_indices`` to create a gap.
    """
    first = None
    for packet_index in packet_indices:
        if first is None:
            first = packet_index
        packets_since_first = (packet_index - first) % PACKET_INDEX_MODULUS
        for channel in channels:
            for position in range(SAMPLES_PER_PACKET):
                elapsed_s = (packets_since_first * SAMPLES_PER_PACKET + position) / SAMPLE_RATE_HZ
                value = SINE_AMPLITUDE_UV * sin(2 * pi * SINE_HZ * elapsed_s)
                yield SampleRecord(
                    channel=channel,
                    packet_index=packet_index,
                    sample_in_packet=position,
                    microvolts=round(value + CHANNEL_OFFSETS_UV.get(channel, 0.0), 2),
                    elapsed_s=elapsed_s,
                )
