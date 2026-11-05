# Dashboard ↔ backend API (v0.1)

The local API between Rushil's operator dashboard (`frontend/`) and Ben's recorder service (`eeg_app/dashboard_service.py`). Agreed by Ben and Rushil. If either of us needs a change, update this file first.

- **Fake responses** for building the UI with no backend: [`tests/fixtures/dashboard_api/fake_responses.json`](../tests/fixtures/dashboard_api/fake_responses.json). It's generated from the real service code, so its shapes are always current.
- **Fake headset** for testing the whole loop with no Muse: `python3 -m eeg_app.dashboard_service --fake-headset`.

## Who owns what

| Backend (Ben) | Dashboard (Rushil) |
|---|---|
| Session IDs | Operator buttons and keyboard shortcuts |
| Recorder state | What is shown, colors, marker categories |
| Saved files | Running the pilot cue sequence on screen |
| Every timestamp | The visual-fit check and contact-quality acknowledgment |
| Outcome once ended, read-back checks, review bundle | Choosing demo mode or live mode |

The dashboard never invents an ID or a timestamp. It asks the backend and shows what comes back.

The backend doesn't replace any validated code:
- It runs the existing scanner.
- It passes each `EEG_PACKET` line through `LivePacketAdapter` → `SessionWriter` → `PacketReceiptWriter`, in the same order as `record_packet_lines`.
- Review uses `read_session`, `check_session`, `create_fixed_windows`, and Samuel's `export_review_bundle`.

What's new is only the HTTP layer, a thinned-out copy of recent samples for the display, and two small files per session (`events.csv`, `session.json`).

## Running it

```bash
# Real headset (Mac): build the scanner once, then start the service
cd muse2-c && make scan && cd ..
python3 -m eeg_app.dashboard_service

# No headset: generated test packets, clearly labeled data_source "fake_headset"
python3 -m eeg_app.dashboard_service --fake-headset

# Dashboard
cd frontend && npm install && npm run dev
```

## Basics

- Base URL: `http://127.0.0.1:8765`. It listens on localhost only.
- JSON in, JSON out. CORS is allowed for `http://localhost:*` and `http://127.0.0.1:*` origins only.
- Only one session can be open at a time.
- Channels are always `TP9`, `AF7`, `AF8`, `TP10`, in that order.
- Field names are `snake_case`, matching the saved files and the dashboard's `Marker` type.

### Times

| Field | Meaning |
|---|---|
| `elapsed_s` on samples and traces | The saved sample time, `(packets_since_first × 12 + sample_in_packet) / 256`, counted from the session's first packet. It's the same number as in `eeg.csv`. |
| `monotonic_ns` on events | The backend's `time.monotonic_ns()` when it received the request. The scanner's `receipt_monotonic_ns` uses the same clock (`CLOCK_UPTIME_RAW` on macOS). |
| `session_elapsed_s` | Seconds since the start request was accepted. This is the recording timer. |
| `eeg_elapsed_s` on events and the recorder | **Approximate** position on the EEG time axis: the event time minus the first packet's receipt time. `null` before the first packet. Bluetooth delay is included, so it's close but not exact. |
| `*_utc` | Wall-clock time, for people only. Never used for alignment. |

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/status` | Device, channel and recorder status |
| `GET /api/pilot-sequence` | The agreed pilot cues |
| `POST /api/sessions` | Start one new session |
| `GET /api/sessions/{id}/live?after=<cursor>` | Recent EEG for the live traces |
| `POST /api/sessions/{id}/events` | Add a prompt or observer event |
| `POST /api/sessions/{id}/end` | End with an outcome |
| `GET /api/sessions` | List saved sessions |
| `GET /api/sessions/{id}` | Saved session summary, checks, windows and review bundle link |
| `GET /api/sessions/{id}/events` | Saved events |
| `GET /api/sessions/{id}/traces?start_s=&end_s=&max_points=` | Saved traces |
| `GET /review-bundles/{id}/index.html` | Samuel's prediction-free review bundle |

Every response below has a full example in the fixture. The key is shown after each heading.

### `GET /api/status` (fixture `status.*`)

Poll about once a second. There are fixture examples for `scanner_missing`, `searching`, `idle_streaming`, `waiting_for_packets`, `recording` and `interrupted`.

- `device.state`:
  - `scanner_missing`: the scanner binary isn't built.
  - `scanner_stopped`: the scanner exited. The backend restarts it after 2 s.
  - `searching`: the scanner is running, but no packet has arrived yet.
  - `streaming`: packets are arriving.
  - `stalled`: no packet for 3 s or more.
- `channels[]` has one entry per channel:
  - `recent_packets`: `true` if a packet arrived in the last `recent_window_s` (1 s).
  - `last_packet_age_s`
  - `packets_received`

  **`recent_packets` means packets are arriving. It is not contact quality.** Label it "Packets arriving", never "Good".
- `contact_quality` is always `"not_measured"`.
- `data_source` is `live_eeg_packet` (real Muse) or `fake_headset` (generated). The dashboard should show a fake-headset banner when it's `fake_headset`.
- `recorder` fields:
  - `state`: `idle`, `waiting_for_packets` (session open, nothing saved yet), `recording`, or `interrupted` (saving stopped by itself; the session stays open until ended)
  - `session_id`
  - `session_elapsed_s` (the timer)
  - `eeg_elapsed_s`
  - `rows_written`
  - `samples_per_channel`
  - `stop_reason`

### `GET /api/pilot-sequence` (fixture `pilot_sequence`)

The cues come from `eeg_app/pilot_sequence.py`, which the terminal guide (`guided_pilot.py`) uses too, so both stay identical.

- Each cue has `index`, `text`, `start_s`, `duration_s`, and `get_ready` (the action to announce, or `null`).
- Show "Get ready to {get_ready}" `get_ready_lead_s` seconds before that cue's `start_s`. Show "NOW: {text}" at `start_s`.
- `clock` is `eeg_elapsed_s`: cue times are measured from the first EEG packet of the session, like the terminal guide.
- Send each shown prompt as an event:
  - type `prompt_shown`
  - source `protocol`
  - `event_code` set to `PILOT_READY_{index}` or `PILOT_CUE_{index}`

### `POST /api/sessions` (fixture `start_session`)

Body: `{ "protocol_id": "eeg-artifact-observation-v1" }`. There is **no participant information**. The backend makes up a pseudonymous `ses-xxxxxxxx` ID that has never been used in the sessions folder.

Starting is allowed while the device is `searching`. The recorder then reports `waiting_for_packets` until data arrives.

Errors:
- `409 session_already_active`
- `503 scanner_unavailable` (the scanner isn't running or isn't built)

### `GET /api/sessions/{id}/live` (fixture `live_first_poll`, `live_next_poll`)

Poll every 100–250 ms. Leave out `after` the first time to get the last 5 s. After that, send the previous `cursor`.

- These are real saved samples, thinned out **for display only**. `reduction` (every 4th sample, 64 points/s) says so in every response. `eeg.csv` keeps all 256 samples/s.
- `gaps` lists missing packets per channel. Break the line there; never draw across a gap.
- `recorder_state` is included so the traces view can react without waiting for the next status poll.

Errors:
- `404 session_not_found`
- `409 session_not_recording`

### `POST /api/sessions/{id}/events` (fixture `add_event`, `add_event_retry_same_client_ref`, `add_correction`)

```json
{ "event_type": "observer_marker", "label": "Observed blink", "source": "operator",
  "event_code": null, "corrects_event_id": null, "client_ref": "<uuid made by the dashboard>" }
```

- `event_type` is one of:
  - `phase_started`
  - `prompt_shown`
  - `observer_marker`
  - `headset_adjustment`
  - `operator_note`
  - `marker_correction`
  - `contact_quality_unverified`

  There is no pause in live mode, so `recording_paused` and `recording_resumed` are rejected.
- `marker_correction` needs `corrects_event_id` pointing at an event in this session. The original event is never edited.
- Retries are safe: if the same `client_ref` arrives again, you get the already-saved event back with `200` instead of `201`.
- The response adds `event_id`, `monotonic_ns`, `session_elapsed_s`, `eeg_elapsed_s` and `received_at_utc`. The dashboard shows `event_id` and the approximate time.
- **An event is an observation, not an artifact label.** If the response isn't `200`/`201`, the dashboard must show the event as *not saved*.

Errors:
- `400 invalid_request`
- `404 session_not_found`
- `409 session_not_recording` (ended or interrupted)
- `409 unknown_event_reference`

### `POST /api/sessions/{id}/end` (fixture `end_session`)

Body: `{ "outcome": "completed" | "incomplete" | "aborted", "reason": "..." }`. `reason` is required unless the outcome is `completed`.

- Finishing the pilot sequence → `completed`. Stop early → `incomplete`. Abort → `aborted`.
- **Outcome and save status are separate.** `outcome` is the operator's call on the session. `recording_status` (`complete` / `interrupted`, from the existing writer) says whether saving finished cleanly. Saved rows are kept either way.

Errors:
- `400 invalid_request`
- `404 session_not_found`
- `409 session_not_recording`
- `409 cannot_complete_interrupted`

### `GET /api/sessions` (fixture `list_sessions`)

Sessions recorded through this service, newest first.

### `GET /api/sessions/{id}` (fixture `session_summary`)

- `outcome`, `reason`, `recording_status`, `stop_reason`, `data_source`, `eeg_span_s`, `event_count`.
- `check` comes straight from `check_session`: `ok`, `total_rows`, `rows_per_channel`, `missing_packets`, `problems`.
- `windows` comes from Namit's `create_fixed_windows` (2 s windows): `total`, `valid`, and `invalid[]` with each window's reasons.
- `review_bundle.url` is a link to Samuel's prediction-free bundle, created on first request in `recordings/{id}-review/`. Open it in a new tab. If it can't be made (for example, no rows were saved), `url` is `null` and `error` says why.

Errors:
- `404 session_not_found`
- `409 session_still_recording`
- `422 session_unreadable`

### `GET /api/sessions/{id}/events` and `/traces` (fixture `session_events`, `session_traces`)

- Events are listed in the order they were received.
- Traces have the same shape as live data, with `start_s` and `end_s` added. The stride is the smallest that fits `max_points` per channel, so a short range gives you `factor: 1`, which means the exact saved values.

## Errors

Every error has the same body: `{ "error": { "code": "...", "message": "..." } }`. The dashboard should switch on `code`. `message` is written for the operator. Each code has an example under `errors.*` in the fixture.

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_request` | Missing or wrong field. `message` names it. |
| 404 | `session_not_found` | Unknown session ID |
| 409 | `session_already_active` | Start while a session is open |
| 409 | `session_not_recording` | Live, event or end on a session that has ended or been interrupted |
| 409 | `session_still_recording` | Review endpoints on an open session |
| 409 | `unknown_event_reference` | Bad `corrects_event_id` |
| 409 | `cannot_complete_interrupted` | `completed` after saving was interrupted |
| 422 | `session_unreadable` | Saved files fail `read_session` |
| 503 | `scanner_unavailable` | Scanner not running or not built |
| 500 | `internal_error` | Bug. Rows already written are kept. |

If the backend isn't running, `fetch` itself throws. Show "Backend not reachable" for that case.

## Test-only controls (`--fake-headset` only)

| Call | Simulates |
|---|---|
| `POST /api/fake/disconnect` | Scanner crash. An open session becomes `interrupted`, and the fake headset comes back after 2 s. |
| `POST /api/fake/stall?seconds=5` | Headset goes quiet. The device shows `stalled`, and the gap appears in traces. |
| `POST /api/fake/fail-next-event` | The next event request fails with `500`. |

Without `--fake-headset`, these return `404`.

## Files per session

```text
data/sessions/<session_id>/          (git-ignored)
    eeg.csv               SessionWriter, unchanged
    metadata.json         SessionWriter, unchanged
    packet_receipts.csv   PacketReceiptWriter, unchanged
    events.csv            one row per event, fields as in the event response
    session.json          protocol_id, start_monotonic_ns, first_packet_receipt_ns, outcome, reason, ended_at_utc
recordings/<session_id>-review/      Samuel's review bundle (git-ignored)
```

## Decisions made while agreeing this

1. **Polling, not a stream.** It's easy to fake, and 4–10 polls/s is enough for a rolling window. If traces look choppy, we can switch to Server-Sent Events with the same data shape.
2. **Start doesn't wait for packets.** The dashboard shows "waiting for packets" until `recorder.state` is `recording`.
3. **No pause in live mode.** To handle an interruption, stop early (`incomplete`) and start a new session.
4. **Display thinning is every 4th sample.** Min/max buckets would keep very short spikes. That's a possible later change, and the response's `reduction.method` would say so.
