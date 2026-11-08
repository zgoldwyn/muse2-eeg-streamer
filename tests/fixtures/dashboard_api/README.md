# Dashboard API fixture: `fake_responses.json`

**Synthetic only.** These are example responses for every endpoint in [`docs/dashboard-api.md`](../../../docs/dashboard-api.md), so the dashboard can be built before the headset or backend is available. No headset, Bluetooth, C scanner or participant was involved.

The file is produced by the real `DashboardService`. Scripted `EEG_PACKET` lines and a fake clock are fed into it, so every shape matches what the backend actually sends. `tests/test_dashboard_service.py` fails if the committed file is out of date.

## Regenerate

From the repository root:

```bash
python3 -m tests.fixtures.dashboard_api.generate_fixture
```

The output is identical every run.

## Shape

Each entry is `{ "request": { "method", "path", "body"? }, "status", "body" }`.

| Key | What it shows |
|---|---|
| `status.scanner_missing`, `searching`, `idle_streaming`, `waiting_for_packets`, `recording`, `interrupted` | One status response per state |
| `pilot_sequence` | The agreed cues |
| `start_session` | `201` with session `ses-k7q2m9xa` |
| `live_first_poll`, `live_next_poll` | Live traces, first call and a follow-up with `after=<cursor>` |
| `add_event`, `add_event_retry_same_client_ref`, `add_correction` | Event creation (`201`), safe retry (`200`), correction |
| `end_session` | Ended early as `incomplete` |
| `list_sessions`, `session_summary`, `session_events`, `session_traces` | Review |
| `errors.<code>` | One example of every error code except `422` and `500` |

## Scenario

| | |
|---|---|
| Session | `ses-k7q2m9xa`, 12 s of EEG (256 packets × 12 samples per channel) |
| Packet index | Starts at 65500 and wraps past 65535 |
| Missing data | One AF7 packet at 9.375–9.421875 s (packet index 164). Shows in live `gaps`, `check.missing_packets` and one invalid window. |
| Blink-shaped bump | AF7 and AF8, 10.5–10.8 s, up to about +150 µV |
| Events | 7: contact-quality acknowledgment, pilot prompts, an observed blink, a jaw marker and its correction |
| Outcome | `incomplete`, saved cleanly (`recording_status: complete`) |
| Second session | `ses-lostconn`. The scanner is lost after 2 packets, giving the `interrupted` status and the `cannot_complete_interrupted` and `scanner_unavailable` errors. |
