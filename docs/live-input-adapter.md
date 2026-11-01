# Live EEG packet adapter

`eeg_app.live_adapter` accepts only complete scanner stdout lines in this exact
format:

```text
EEG_PACKET,<channel>,<packet_index>,<receipt_monotonic_ns>,<uv0>,...,<uv11>
```

There are exactly 16 comma-separated fields. `channel` is one of `TP9`, `AF7`,
`AF8`, or `TP10`; the original 16-bit packet index is 0 through 65535; receipt
time is a nonnegative integer; and all 12 microvolt values must be finite.
Lines such as the legacy `EEG,...` graph format, debug output, and stderr are
not packet input.

## EEG sample-time rule

The first accepted packet in a short capture establishes the shared session
origin. If its original packet index is `first_packet_index`, then for every
sample in a later accepted packet:

```text
packets_since_first = (packet_index - first_packet_index) mod 65536
elapsed_s = (packets_since_first * 12 + sample_in_packet) / 256
```

`sample_in_packet` is 0 through 11. The rule handles the normal 65535-to-0
index wraparound. A packet that would place data before this origin is rejected
as unalignable. Missing packets are represented by absent `eeg.csv` rows;
neither samples nor timestamps are filled, shifted, or interpolated.

## Receipt-time sidecar

`record_packet_lines` writes `packet_receipts.csv` alongside `eeg.csv` and
`metadata.json`. Its `receipt_monotonic_ns` values share the scanner process's
`time.monotonic_ns()` clock. They are not browser UI times and not UTC wall-clock
timestamps. They record packet arrival and never replace sample-estimated
`elapsed_s`.

The existing `SessionWriter` owns `eeg.csv` and metadata completion status. A
normal close marks a session `complete`. A malformed packet or another error
retains already written rows and marks the session `interrupted`.

## Feature handoff

Only windows whose `is_valid` field is true may enter Samuel's continuous-EEG
feature calculations. Invalid windows and their reasons remain available for
exclusion reporting.
