// Client for Ben's local recorder service. The contract is docs/dashboard-api.md;
// example responses are in tests/fixtures/dashboard_api/fake_responses.json.

export const BACKEND_URL: string =
  import.meta.env.VITE_EEG_BACKEND_URL ?? "http://127.0.0.1:8765"

export const CHANNEL_NAMES = ["TP9", "AF7", "AF8", "TP10"] as const
export type ChannelName = (typeof CHANNEL_NAMES)[number]

export type DeviceState =
  | "scanner_missing"
  | "scanner_stopped"
  | "searching"
  | "streaming"
  | "stalled"

export type RecorderState =
  | "idle"
  | "waiting_for_packets"
  | "recording"
  | "interrupted"

export type Recorder = {
  state: RecorderState
  session_id: string | null
  session_elapsed_s: number | null
  eeg_elapsed_s: number | null
  rows_written: number | null
  samples_per_channel: Record<ChannelName, number> | null
  stop_reason: string | null
}

export type Status = {
  api_version: string
  data_source: "live_eeg_packet" | "fake_headset"
  device: { state: DeviceState; message: string }
  recent_window_s: number
  channels: {
    name: ChannelName
    recent_packets: boolean
    last_packet_age_s: number | null
    packets_received: number
  }[]
  contact_quality: "not_measured"
  recorder: Recorder
}

export type PilotCue = {
  index: number
  text: string
  start_s: number
  duration_s: number
  get_ready: string | null
}

export type PilotSequence = {
  source: string
  clock: "eeg_elapsed_s"
  get_ready_lead_s: number
  total_s: number
  cues: PilotCue[]
}

export type TraceChannel = { elapsed_s: number[]; microvolts: number[] }
export type Gap = { channel: ChannelName; start_s: number; end_s: number }
export type Reduction = {
  method: string
  factor: number
  display_hz: number
  note: string
}

export type LiveData = {
  session_id: string
  recorder_state: RecorderState
  cursor: number
  reduction: Reduction
  channels: Record<ChannelName, TraceChannel>
  gaps: Gap[]
}

export type EventType =
  | "phase_started"
  | "prompt_shown"
  | "observer_marker"
  | "headset_adjustment"
  | "operator_note"
  | "marker_correction"
  | "contact_quality_unverified"

export type EventRequest = {
  event_type: EventType
  label: string
  source: "protocol" | "operator"
  event_code: string | null
  corrects_event_id: string | null
  client_ref: string
}

export type SavedEvent = EventRequest & {
  event_id: string
  session_id: string
  monotonic_ns: number
  session_elapsed_s: number
  eeg_elapsed_s: number | null
  received_at_utc: string
}

export type Outcome = "completed" | "incomplete" | "aborted"

export type EndResult = {
  session_id: string
  outcome: Outcome
  reason: string | null
  recording_status: "complete" | "interrupted"
  stop_reason: string | null
  ended_at_utc: string
  rows_written: number
}

export type Summary = {
  session_id: string
  protocol_id: string | null
  started_at_utc: string
  ended_at_utc: string | null
  outcome: Outcome | null
  reason: string | null
  recording_status: string
  stop_reason: string | null
  data_source: string
  eeg_span_s: number
  event_count: number
  check: {
    ok: boolean
    total_rows: number
    rows_per_channel: Record<ChannelName, number>
    missing_packets: { packet_index: number; channels: ChannelName[] }[]
    problems: string[]
  }
  windows: {
    window_s: number
    total: number
    valid: number
    invalid: { window_id: string; start_s: number; end_s: number; reasons: string[] }[]
    error: string | null
  }
  review_bundle: { url: string | null; error: string | null }
}

/** A failed request: the backend could not be reached, or it returned an error code. */
export class ApiFailure extends Error {
  readonly kind: "unreachable" | "api"
  readonly status: number | null
  readonly code: string | null

  constructor(kind: "unreachable" | "api", message: string, status: number | null = null, code: string | null = null) {
    super(message)
    this.kind = kind
    this.status = status
    this.code = code
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<{ status: number; body: T }> {
  let response: Response
  try {
    response = await fetch(BACKEND_URL + path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiFailure(
      "unreachable",
      `Backend not reachable at ${BACKEND_URL}. Start it with: python3 -m eeg_app.dashboard_service`,
    )
  }
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    // fall through: reported below
  }
  if (!response.ok) {
    const error = (data as { error?: { code?: string; message?: string } } | null)?.error
    throw new ApiFailure(
      "api",
      error?.message ?? `Backend returned HTTP ${response.status}.`,
      response.status,
      error?.code ?? null,
    )
  }
  return { status: response.status, body: data as T }
}

export const api = {
  status: () => request<Status>("GET", "/api/status").then((r) => r.body),
  pilotSequence: () => request<PilotSequence>("GET", "/api/pilot-sequence").then((r) => r.body),
  startSession: (protocolId: string | null) =>
    request<{ session_id: string; started_at_utc: string; recorder: Recorder }>("POST", "/api/sessions", {
      protocol_id: protocolId,
    }).then((r) => r.body),
  live: (sessionId: string, after: number | null) =>
    request<LiveData>(
      "GET",
      `/api/sessions/${encodeURIComponent(sessionId)}/live${after === null ? "" : `?after=${after}`}`,
    ).then((r) => r.body),
  addEvent: (sessionId: string, event: EventRequest) =>
    request<SavedEvent>("POST", `/api/sessions/${encodeURIComponent(sessionId)}/events`, event).then((r) => r.body),
  endSession: (sessionId: string, outcome: Outcome, reason: string | null) =>
    request<EndResult>("POST", `/api/sessions/${encodeURIComponent(sessionId)}/end`, { outcome, reason }).then(
      (r) => r.body,
    ),
  summary: (sessionId: string) =>
    request<Summary>("GET", `/api/sessions/${encodeURIComponent(sessionId)}`).then((r) => r.body),
  events: (sessionId: string) =>
    request<{ session_id: string; events: SavedEvent[] }>(
      "GET",
      `/api/sessions/${encodeURIComponent(sessionId)}/events`,
    ).then((r) => r.body.events),
}
