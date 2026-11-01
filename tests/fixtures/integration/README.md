# Integration fixture: `integration-demo-001`

**Synthetic only.** This session was written by the real session writer (`eeg_app/recording.py`) from generated values. No headset, Bluetooth, C scanner or participant was involved. It is a known test scenario with a fixed answer key, not a realistic recording.

## Regenerate

From the repository root:

```bash
rm -r tests/fixtures/integration/integration-demo-001   # the writer refuses to overwrite a session
python3 -m tests.fixtures.integration.generate_fixture
```

The values are deterministic, so `eeg.csv` comes out byte-for-byte identical every time. In `metadata.json`, only `started_at_utc` and `ended_at_utc` change, because they record when the generator ran. `tests/test_integration_fixture.py` checks this.

## Answer key

| | |
|---|---|
| Channels | TP9, AF7, AF8, TP10 |
| `nominal_sample_rate_hz` | 256 |
| `samples_per_packet` | 12 |
| Packet slots | 0 to 127 (a nominal 6 s span: 128 × 12 = 1,536 expected samples per channel) |
| Missing packet | 50, absent on **all four** channels. No replacement values are written. |
| Sample positions | 0 to 11 in every packet that is present |
| Rows per channel | 1,524 (1,536 − 12) |
| Total EEG rows | 6,096 |
| `status` | `complete` |

Sample times are estimated from the packet index, so the missing packet keeps its place in the time grid:

```
elapsed_s = (packet_index × 12 + sample_in_packet) / 256
```

For example, TP9 packet 49 sample 11 is at 2.33984375 s, and the next saved row, packet 51 sample 0, is at 2.390625 s. The 47 ms in between, 2.34375 to 2.38671875 s, is where packet 50 would be.

There is no packet receipt time in this fixture. A synthetic session has no Bluetooth callback, so any receipt time would be invented.

## Values

Every channel has a low-amplitude, varying baseline:

```
microvolts = offset + 4·sin(2π·10·t) + 2·sin(2π·0.5·t)       rounded to 0.01 µV
offset: TP9 0, AF7 +5, AF8 −5, TP10 +10 µV
```

That keeps every baseline value within ±16 µV.

### Injected disturbance (AF7 only)

One large disturbance is added to **AF7** in **packets 96, 97, 98 and 99**, at every sample position 0 to 11. That's 48 samples, from **4.5 s** (packet 96, sample 0) to **4.68359375 s** (packet 99, sample 11). It's a half-sine bump added on top of the baseline:

```
k = (packet_index − 96) × 12 + sample_in_packet      k = 0 … 47
added µV = 300 · sin(π · (k + 0.5) / 48)
```

It peaks at about +300 µV in the middle (k = 23 and 24, packet 97 sample 11 and packet 98 sample 0). TP9, AF8 and TP10 are not changed.

This is a deliberately planted test scenario. It is **not** a realistic blink, and it is **not** a label produced by a person or a detector.

## Expected 2-second windows

With the loader in PR #12 (`eeg_app/dataset.py`), the session splits into three windows:

| Window | Expected | Why |
|---|---|---|
| 0–2 s | valid | 512 samples per channel, no gaps |
| 2–4 s | invalid | 500 samples per channel, because packet 50 is missing |
| 4–6 s | valid | complete; the AF7 disturbance is inside it, but "valid" means complete data, not artifact-free |
