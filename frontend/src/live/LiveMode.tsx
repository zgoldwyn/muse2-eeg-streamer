import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import protocol from "../protocol.json"

import LiveTraces from "./LiveTraces"

import {
  ApiFailure,
  BACKEND_URL,
  CHANNEL_NAMES,
  api,
  type ChannelName,
  type EventRequest,
  type Gap,
  type Outcome,
  type PilotSequence,
  type Reduction,
  type SavedEvent,
  type Status,
  type Summary,
} from "./api"

import {
  appendRolling,
  duePrompts,
  formatClock,
  formatMarkerTime,
  pilotPhaseAtTime,
  pilotPrompts,
  type PilotPrompt,
  type Trace,
} from "./logic"

const PROTOCOL_ID = "pilot-sequence-v0"

const TRACE_WINDOW_S = 10

const LIVE_POLL_MS = 250

function failureText(error: unknown): string {
  if (error instanceof ApiFailure)
    return error.code ? `${error.message} (${error.code})` : error.message

  return error instanceof Error ? error.message : String(error)
}

// ------------------------------------------------------------------ status polling

function useStatus(intervalMs: number) {
  const [status, setStatus] = useState<Status | null>(null)

  const [error, setError] = useState<ApiFailure | null>(null)

  useEffect(() => {
    let cancelled = false

    let inFlight = false

    const poll = async () => {
      if (inFlight) return

      inFlight = true

      try {
        const next = await api.status()

        if (!cancelled) {
          setStatus(next)

          setError(null)
        }
      } catch (caught) {
        if (!cancelled)
          setError(
            caught instanceof ApiFailure
              ? caught
              : new ApiFailure("unreachable", String(caught)),
          )
      } finally {
        inFlight = false
      }
    }

    poll()

    const timer = window.setInterval(poll, intervalMs)

    return () => {
      cancelled = true

      window.clearInterval(timer)
    }
  }, [intervalMs])

  return { status, error }
}

// ------------------------------------------------------------------ shared pieces

function Banner({
  tone,
  children,
}: {
  tone: "red" | "amber" | "blue"
  children: React.ReactNode
}) {
  const styles = {
    red: "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",

    amber: "border-[#fde68a] bg-[#fffbeb] text-[#92400e]",

    blue: "border-[#bfdbfe] bg-[#eff6ff] text-[#1d4ed8]",
  }

  return (
    <div
      role="status"
      className={`rounded-lg border px-4 py-2 text-xs font-semibold ${styles[tone]}`}
    >
      {children}
    </div>
  )
}

function ModeBadge({ status }: { status: Status | null }) {
  if (status?.data_source === "fake_headset") {
    return (
      <span className="rounded bg-[#d97706] px-2.5 py-1 text-[11px] font-bold uppercase text-white">
        Live mode · FAKE HEADSET test data
      </span>
    )
  }

  return (
    <span className="rounded bg-[#16a34a] px-2.5 py-1 text-[11px] font-bold uppercase text-white">
      Live local recording
    </span>
  )
}

const deviceLabels: Record<string, string> = {
  scanner_missing: "Scanner not built",

  scanner_stopped: "Scanner stopped",

  searching: "Searching for Muse",

  streaming: "Packets arriving",

  stalled: "Packets stalled",
}

function ChannelPackets({
  status,
  showSaved,
}: {
  status: Status | null
  showSaved: boolean
}) {
  const saved = status?.recorder.samples_per_channel

  return (
    <div className="flex flex-wrap items-center gap-2">
      {CHANNEL_NAMES.map((name) => {
        const channel = status?.channels.find((item) => item.name === name)

        const arriving = Boolean(channel?.recent_packets)

        return (
          <span
            key={name}
            className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-semibold ${
              arriving
                ? "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]"
                : "border-[#e2e8f0] bg-[#f8fafc] text-[#64748b]"
            }`}
            title="Shows only whether packets are arriving. Electrode contact quality is not measured."
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                arriving ? "bg-[#16a34a]" : "bg-[#94a3b8]"
              }`}
            />
            {name}: {arriving ? "packets arriving" : "no recent packets"}
            {showSaved && saved
              ? ` · ${saved[name].toLocaleString()} samples saved`
              : ""}
          </span>
        )
      })}
    </div>
  )
}

function DeviceLine({
  status,
  error,
}: {
  status: Status | null
  error: ApiFailure | null
}) {
  if (error) {
    return (
      <span className="font-semibold text-[#b91c1c]">
        ● Backend not reachable
      </span>
    )
  }

  if (!status)
    return <span className="text-[#64748b]">Connecting to backend…</span>

  const good = status.device.state === "streaming"

  return (
    <span
      className={`font-semibold ${good ? "text-[#15803d]" : "text-[#b91c1c]"}`}
    >
      ● {deviceLabels[status.device.state] ?? status.device.state}
      <span className="ml-2 font-normal text-[#64748b]">
        {status.device.message}
      </span>
    </span>
  )
}

type DisplayEvent = {
  id: string
  recordedId?: string
  label: string
  eventType: string
  source: "protocol" | "operator"
  timeS: number | null
  timeSource?: "EEG" | "session"
  state?: "saving" | "saved" | "failed"
  request?: EventRequest
  error?: string
}

function eventColor(event: Pick<DisplayEvent, "eventType" | "source">): string {
  if (event.eventType === "marker_correction") return "#64748b"
  if (event.eventType === "contact_quality_unverified") return "#dc2626"
  if (
    event.eventType === "recording_paused" ||
    event.eventType === "recording_resumed"
  )
    return "#dc2626"
  if (event.source === "protocol") {
    return event.eventType === "prompt_shown" ? "#16a34a" : "#7c3aed"
  }
  return "#eab308"
}

function LiveEventSidebar({
  events,
  elapsedS,
  samples,
  phaseCount,
  completedPhaseCount,
  outcome,
  onRetry,
}: {
  events: DisplayEvent[]
  elapsedS: number
  samples: number | null
  phaseCount: number
  completedPhaseCount?: number
  outcome?: Outcome | null
  onRetry?: (request: EventRequest) => void
}) {
  const legends = [
    ["Protocol phase", "#7c3aed"],
    ["Protocol prompt", "#16a34a"],
    ["Operator observation", "#eab308"],
    ["Recording / correction", "#dc2626"],
  ] as const

  const markerListRef = useRef<HTMLDivElement>(null)
  const markerContentRef = useRef<HTMLDivElement>(null)
  const latestEventId = events.at(-1)?.id

  useEffect(() => {
    const markerList = markerListRef.current
    if (markerList) markerList.scrollTop = markerList.scrollHeight
  }, [events.length, latestEventId])

  useEffect(() => {
    const markerList = markerListRef.current
    const markerContent = markerContentRef.current
    if (!markerList || !markerContent) return

    const resizeObserver = new ResizeObserver(() => {
      markerList.scrollTop = markerList.scrollHeight
    })
    resizeObserver.observe(markerContent)
    return () => resizeObserver.disconnect()
  }, [])

  return (
    <aside className="flex h-full min-h-0 flex-col border-r border-[#e2e8f0] bg-white">
      <div className="flex items-center gap-2 border-b border-[#e2e8f0] px-4 py-3.5">
        <img src="/assets/20de1%20(1).svg" alt="" width="16" height="16" />
        <h2 className="text-sm font-semibold text-[#1e293b]">Markers</h2>
        <span className="rounded-full bg-[#2563eb] px-1.5 py-0.5 text-[10px] font-bold text-white">
          {events.length}
        </span>
      </div>
      <div className="flex justify-between border-b border-[#e2e8f0] px-4 py-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
        <span>Label</span>
        <span>Timestamp</span>
      </div>
      <div ref={markerListRef} className="min-h-0 flex-1 overflow-y-auto">
        <div ref={markerContentRef}>
          {events.length === 0 ? (
            <p className="border-b border-[#e2e8f0] px-4 py-8 text-center text-xs text-[#94a3b8]">
              No markers recorded
            </p>
          ) : (
            events.map((event, index) => (
              <div
                key={event.id}
                className={`flex min-h-10 items-center justify-between gap-2 border-b border-[#e2e8f0] px-4 py-2.5 text-xs ${
                  index % 2 === 0 ? "bg-[#fafafa]" : ""
                }`}
              >
                <span className="flex min-w-0 items-center gap-1.5 text-[#334155]">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: eventColor(event) }}
                  />
                  <span className="min-w-0">
                    <span className="line-clamp-2">{event.label}</span>
                    <span
                      className="block text-[8px] font-semibold uppercase text-[#64748b]"
                      title={event.recordedId ?? event.id}
                    >
                      {event.eventType.replace(/_/g, " ")}
                      {event.state === "saving" && " · saving"}
                      {event.state === "failed" && " · not saved"}
                    </span>
                    {event.recordedId && (
                      <span
                        className="block break-all font-mono text-[8px] text-[#64748b]"
                        title={event.recordedId}
                      >
                        Event ID: {event.recordedId}
                      </span>
                    )}
                    {event.state === "failed" && event.request && onRetry && (
                      <>
                        {event.error && (
                          <span className="block text-[9px] text-[#b91c1c]">
                            {event.error}
                          </span>
                        )}
                        <button
                          type="button"
                          className="text-[9px] font-semibold text-[#b91c1c] underline"
                          onClick={() => {
                            if (event.request) onRetry(event.request)
                          }}
                        >
                          Retry save
                        </button>
                      </>
                    )}
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end text-[#64748b]">
                  {event.timeS === null
                    ? "—"
                    : `~${formatMarkerTime(event.timeS)}`}
                  {event.timeS !== null && (
                    <span className="text-[8px] uppercase">
                      {event.timeSource ?? "EEG"} time
                    </span>
                  )}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
      <div className="shrink-0 space-y-1.5 border-t border-[#e2e8f0] p-4 text-[11px] text-[#64748b]">
        <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
          Color legend
        </h3>
        {legends.map(([label, color]) => (
          <div key={label} className="flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: color }}
            />
            {label}
          </div>
        ))}
      </div>
      <div className="shrink-0 space-y-1.5 border-t border-[#e2e8f0] bg-[#f8fafc] p-4 text-[11px] text-[#64748b]">
        <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
          Session summary
        </h3>
        <p>
          Total Duration:{" "}
          <b className="text-[#1e293b]">{formatClock(elapsedS)}</b>
        </p>
        <p>
          Total Markers: <b className="text-[#1e293b]">{events.length}</b>
        </p>
        <p>
          Samples:{" "}
          <b className="text-[#1e293b]">{samples?.toLocaleString() ?? "—"}</b>
        </p>
        <p>
          Phases:{" "}
          <b className="text-[#1e293b]">
            {completedPhaseCount ?? phaseCount} of {phaseCount}
          </b>
        </p>
        {outcome && (
          <p>
            Outcome: <b className="capitalize text-[#1e293b]">{outcome}</b>
          </p>
        )}
      </div>
    </aside>
  )
}

function LiveStatusStrip({
  status,
  error,
  showSaved = false,
}: {
  status: Status | null
  error: ApiFailure | null
  showSaved?: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#e2e8f0] bg-white px-3 py-2 text-[11px] text-[#64748b]">
      <div className="flex items-center gap-2 border-r border-[#e2e8f0] pr-3">
        <img src="/assets/eb16c.svg" alt="" width="18" height="18" />
        <div>
          <span className="block text-[9px] uppercase text-[#94a3b8]">
            Muse headset
          </span>
          <strong
            className={
              status?.device.state === "streaming"
                ? "text-[#16a34a]"
                : "text-[#dc2626]"
            }
          >
            ●{" "}
            {status
              ? deviceLabels[status.device.state]
              : error
                ? "Backend unavailable"
                : "Connecting"}
          </strong>
        </div>
      </div>
      <span className="text-[10px] font-semibold uppercase text-[#94a3b8]">
        Channel status
      </span>
      {CHANNEL_NAMES.map((name) => {
        const channel = status?.channels.find((item) => item.name === name)
        const samples = status?.recorder.samples_per_channel?.[name]
        const arriving = Boolean(channel?.recent_packets)
        return (
          <span
            key={name}
            className={`flex items-center gap-1 rounded border px-2 py-1 font-semibold ${
              arriving
                ? "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]"
                : "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]"
            }`}
            title="Packet arrival is shown; electrode contact quality is not measured."
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                arriving ? "bg-[#16a34a]" : "bg-[#dc2626]"
              }`}
            />
            {name}: {arriving ? "Packets arriving" : "No recent packets"}
            {showSaved &&
              samples !== undefined &&
              ` · ${samples.toLocaleString()} saved`}
          </span>
        )
      })}
      <span className="ml-auto shrink-0 rounded border border-[#cbd5e1] bg-[#f8fafc] px-2 py-1 text-[10px] font-semibold uppercase text-[#64748b]">
        {status?.data_source === "fake_headset"
          ? "Fake headset test data"
          : "Live local data"}
      </span>
    </div>
  )
}

// ------------------------------------------------------------------ setup

function LiveSetup({
  status,

  statusError,

  onStarted,

  onResume,

  onExit,
}: {
  status: Status | null

  statusError: ApiFailure | null

  onStarted: (sessionId: string, notes: string) => void

  onResume: (sessionId: string) => void

  onExit: () => void
}) {
  const fitChecks = [
    "Headset sits level, ear sensors (TP9/TP10) behind the ears",

    "Forehead sensors (AF7/AF8) rest on skin, hair moved aside",

    "Participant reports the fit is comfortable",
  ]

  const [checked, setChecked] = useState<boolean[]>(() =>
    fitChecks.map(() => false),
  )

  const [acknowledged, setAcknowledged] = useState(false)

  const [notes, setNotes] = useState("")

  const [starting, setStarting] = useState(false)

  const [startError, setStartError] = useState<string | null>(null)

  const openSession =
    status && status.recorder.state !== "idle"
      ? status.recorder.session_id
      : null

  const scannerUsable =
    status &&
    !["scanner_missing", "scanner_stopped"].includes(status.device.state)

  const blockers = [
    statusError && "The backend is not reachable.",

    !statusError && !status && "Waiting for backend status.",

    status &&
      !scannerUsable &&
      `${deviceLabels[status.device.state]}: ${status.device.message}`,

    openSession &&
      `Session ${openSession} is already open. Open it or end it first.`,

    !checked.every(Boolean) && "Complete the visual fit check.",

    !acknowledged && "Acknowledge that contact quality is unverified.",
  ].filter(Boolean) as string[]

  const start = async () => {
    setStarting(true)

    setStartError(null)

    try {
      const started = await api.startSession(PROTOCOL_ID)

      onStarted(started.session_id, notes.trim())
    } catch (error) {
      setStartError(failureText(error))
    } finally {
      setStarting(false)
    }
  }

  return (
    <main className="h-full overflow-y-auto bg-[#f9fafb] px-20 py-6">
      <header className="mx-auto flex max-w-[1040px] items-center gap-3">
        <button
          type="button"
          className="text-xs font-semibold text-[#2563eb] underline"
          onClick={onExit}
        >
          ← Change mode
        </button>
        <h1 className="text-[26px] font-bold text-[#111827]">
          Live Session Setup
        </h1>
        <ModeBadge status={status} />
      </header>

      <section className="mx-auto mt-4 flex max-w-[1040px] flex-col gap-4 rounded-2xl border border-[#e5e7eb] bg-white p-6 shadow-[0_4px_6px_rgba(0,0,0,0.05)]">
        {status?.data_source === "fake_headset" && (
          <Banner tone="amber">
            The backend is running with --fake-headset. Traces are generated
            test data, not EEG. Use this only for testing the dashboard.
          </Banner>
        )}
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-[#111827]">
            Recorder backend and headset stream
          </h2>
          <p className="text-sm">
            <DeviceLine status={status} error={statusError} />
          </p>
          {statusError && (
            <p className="text-xs text-[#b91c1c]">{statusError.message}</p>
          )}
          <ChannelPackets status={status} showSaved={false} />
          <p className="text-[12px] text-[#6b7280]">
            Channel chips show only whether each channel has sent packets in the
            last {status?.recent_window_s ?? 1} s. Electrode contact quality is{" "}
            <b>not measured</b>.
          </p>
        </div>

        {openSession && (
          <Banner tone="blue">
            Session {openSession} is already open on the backend (
            {status?.recorder.state.replace(/_/g, " ")}).{" "}
            <button
              type="button"
              className="underline"
              onClick={() => onResume(openSession)}
            >
              Open it
            </button>
          </Banner>
        )}

        <div className="h-px bg-[#e5e7eb]" />
        <div className="grid grid-cols-2 gap-6">
          <div className="flex flex-col gap-2">
            <h2 className="text-base font-semibold text-[#111827]">
              Visual fit check
            </h2>
            {fitChecks.map((label, index) => (
              <label
                key={label}
                className="flex items-center gap-2 text-sm text-[#374151]"
              >
                <input
                  type="checkbox"
                  checked={checked[index]}
                  onChange={(event) =>
                    setChecked((current) =>
                      current.map((value, i) =>
                        i === index ? event.target.checked : value,
                      ),
                    )
                  }
                />
                {label}
              </label>
            ))}
            <label className="mt-2 flex items-start gap-2 rounded-lg border border-[#fde68a] bg-[#fffbeb] p-3 text-sm text-[#92400e]">
              <input
                type="checkbox"
                className="mt-1"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              I understand electrode contact quality is not measured. A visual
              fit check does not verify signal quality, and continuing does not
              make missing channels or gaps acceptable.
            </label>
          </div>
          <div className="flex flex-col gap-2">
            <h2 className="text-base font-semibold text-[#111827]">Session</h2>
            <p className="text-sm text-[#6b7280]">
              The backend assigns a new pseudonymous session ID when you start.
              Do not enter participant names here.
            </p>
            <label className="flex flex-col gap-1.5">
              <span className="text-sm font-semibold text-[#6b7280]">
                Setup notes (saved as an operator note)
              </span>
              <textarea
                className="form-textarea min-h-20"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                placeholder="Fit adjustments, environment, anything unusual…"
              />
            </label>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            type="button"
            className="primary-button disabled:cursor-not-allowed disabled:opacity-45"
            disabled={blockers.length > 0 || starting}
            onClick={start}
          >
            {starting ? "Starting…" : "Start live recording"}
          </button>
          {blockers.length > 0 && (
            <span className="text-xs text-[#6b7280]">{blockers[0]}</span>
          )}
        </div>
        {startError && (
          <Banner tone="red">Could not start: {startError}</Banner>
        )}
      </section>
    </main>
  )
}

function LivePhaseControl({
  currentPhase,
  phaseTimes,
  nextPhaseAtS,
  hasStarted,
  disabled,
  onPrevious,
  onNext,
  children,
}: {
  currentPhase: number
  phaseTimes: number[]
  nextPhaseAtS: number | null
  hasStarted: boolean
  disabled: boolean
  onPrevious: () => void
  onNext: () => void
  children: React.ReactNode
}) {
  const phases = protocol.phases
  const phase = phases[currentPhase]

  return (
    <section className="dashboard-card min-h-0 overflow-y-auto">
      {children}
      <div className="flex items-center gap-2">
        <img src="/assets/4e3e5.svg" alt="" width="16" height="16" />
        <h2 className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#1e293b]">
          Experiment Phase
        </h2>
      </div>
      <div className="rounded-lg border border-[#ddd6fe] bg-[#f5f3ff] px-3.5 py-3">
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-[#7c3aed] px-1.5 py-0.5 font-['Inter:Bold'] text-[10px] font-bold text-white">
            Phase {currentPhase + 1} of {phases.length}
          </span>
          <span className="text-[11px] text-[#7c3aed]">
            {hasStarted ? "Active" : "Ready"}
          </span>
        </div>
        <p className="mt-1 font-['Inter:Bold'] text-base font-bold text-[#4c1d95]">
          {phase.displayName}
        </p>
        <p className="mt-1 text-[10px] leading-3 text-[#6d28d9]">
          {phase.participantInstruction}
        </p>
        <p className="mt-1 text-[11px] text-[#6d28d9]">
          Phase elapsed:{" "}
          <b className="text-[#4c1d95]">
            {formatClock(phaseTimes[currentPhase])}
          </b>
          <span className="ml-2 text-[#7c3aed]">
            {nextPhaseAtS === null
              ? "No matching pilot cue"
              : `Next phase at ${formatClock(nextPhaseAtS)} EEG time`}
          </span>
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          className="phase-button border border-[#e2e8f0] bg-[#f8fafc] text-[#475569]"
          onClick={onPrevious}
          disabled={disabled || currentPhase === 0}
        >
          <img src="/assets/5f9b6.svg" alt="" width="14" height="14" />
          Prev Phase
        </button>
        <button
          type="button"
          className="phase-button bg-[#7c3aed] text-white"
          onClick={onNext}
          disabled={disabled || currentPhase === phases.length - 1}
        >
          Next Phase
          <img src="/assets/745f4.svg" alt="" width="14" height="14" />
        </button>
      </div>
      <div>
        <h3 className="mb-1 text-[10px] font-semibold uppercase text-[#94a3b8]">
          All phases
        </h3>
        <ol className="space-y-1">
          {phases.map((item, index) => (
            <li
              key={item.phaseId}
              className={`flex items-center gap-1 text-[10px] leading-3 ${
                index === currentPhase
                  ? "font-['Inter:Bold'] font-bold text-[#4c1d95]"
                  : index < currentPhase
                    ? "text-[#64748b]"
                    : "text-[#94a3b8]"
              }`}
            >
              <img
                src={
                  index === currentPhase
                    ? "/assets/65551.svg"
                    : index < currentPhase
                      ? "/assets/03c33.svg"
                      : "/assets/3a0f8.svg"
                }
                alt=""
                width="7"
                height="7"
              />
              {index + 1} - {item.displayName}
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

// ------------------------------------------------------------------ recording

type LocalMarker = {
  request: EventRequest

  state: "saving" | "saved" | "failed"

  saved?: SavedEvent

  error?: string

  retried?: boolean
}

const observationActions = [
  { key: "a", label: "Observed blink", event_type: "observer_marker" },

  {
    key: "s",
    label: "Observed jaw / facial muscle",
    event_type: "observer_marker",
  },

  { key: "d", label: "Observed head movement", event_type: "observer_marker" },

  { key: "f", label: "Headset adjustment", event_type: "headset_adjustment" },

  { key: "g", label: "Operator note", event_type: "operator_note" },
] as const

const emptyTraces = (): Record<ChannelName, Trace> => ({
  TP9: { elapsed_s: [], microvolts: [] },

  AF7: { elapsed_s: [], microvolts: [] },

  AF8: { elapsed_s: [], microvolts: [] },

  TP10: { elapsed_s: [], microvolts: [] },
})

type ReviewTraceData = {
  traces: Record<ChannelName, Trace>

  gaps: Gap[]

  reduction: Reduction | null
}

function LiveRecording({
  sessionId,

  status,

  statusError,

  setupNotes,

  isNewSession,

  onEnded,
}: {
  sessionId: string

  status: Status | null

  statusError: ApiFailure | null

  setupNotes: string

  isNewSession: boolean

  onEnded: (data: ReviewTraceData) => void
}) {
  const [markers, setMarkers] = useState<LocalMarker[]>([])

  const [traces, setTraces] = useState(emptyTraces)

  const [gaps, setGaps] = useState<Gap[]>([])

  const [reduction, setReduction] = useState<Reduction | null>(null)

  const [liveError, setLiveError] = useState<string | null>(null)

  const [sequence, setSequence] = useState<PilotSequence | null>(null)

  const [sequenceError, setSequenceError] = useState<string | null>(null)

  const [currentPrompt, setCurrentPrompt] = useState<PilotPrompt | null>(null)

  const [currentPhase, setCurrentPhase] = useState(0)

  const [phaseTimes, setPhaseTimes] = useState(() =>
    protocol.phases.map(() => 0),
  )

  const [noteText, setNoteText] = useState("")

  const [yRange, setYRange] = useState(250)

  const [endDialog, setEndDialog] = useState<Outcome | null>(null)

  const [endReason, setEndReason] = useState("")

  const [ending, setEnding] = useState(false)

  const [endError, setEndError] = useState<string | null>(null)

  const cursor = useRef<number | null>(null)

  const reviewTraces = useRef(emptyTraces())

  const reviewGaps = useRef<Gap[]>([])

  const reviewReduction = useRef<Reduction | null>(null)

  const shownPrompts = useRef(new Set<string>())

  const initialEventsSent = useRef(false)

  const initialPhaseSent = useRef(false)

  const previousEegClock = useRef(0)

  const lastScheduledPhase = useRef(0)

  const recorder =
    status?.recorder.session_id === sessionId ? status.recorder : null

  const recorderState = recorder?.state ?? null

  const interrupted = recorderState === "interrupted"

  const eegNow = useMemo(
    () =>
      Math.max(
        0,
        ...CHANNEL_NAMES.map(
          (name) =>
            traces[name].elapsed_s[traces[name].elapsed_s.length - 1] ?? 0,
        ),
      ),

    [traces],
  )

  const hasData = CHANNEL_NAMES.some(
    (name) => traces[name].elapsed_s.length > 0,
  )

  const prompts = useMemo(
    () =>
      sequence ? pilotPrompts(sequence.cues, sequence.get_ready_lead_s) : [],

    [sequence],
  )

  const sequenceDone =
    sequence !== null && hasData && eegNow >= sequence.total_s

  // Send one event; the marker shows Saving… until the backend confirms it.

  const sendEvent = useCallback(
    async (request: EventRequest) => {
      setMarkers((current) =>
        current.some(
          (marker) => marker.request.client_ref === request.client_ref,
        )
          ? current.map((marker) =>
              marker.request.client_ref === request.client_ref
                ? {
                    request,
                    state: "saving",
                    retried: marker.state === "failed" || marker.retried,
                  }
                : marker,
            )
          : [...current, { request, state: "saving" }],
      )

      try {
        const saved = await api.addEvent(sessionId, request)

        setMarkers((current) =>
          current.map((marker) =>
            marker.request.client_ref === request.client_ref
              ? { ...marker, state: "saved", saved, error: undefined }
              : marker,
          ),
        )
      } catch (error) {
        setMarkers((current) =>
          current.map((marker) =>
            marker.request.client_ref === request.client_ref
              ? { ...marker, state: "failed", error: failureText(error) }
              : marker,
          ),
        )
      }
    },

    [sessionId],
  )

  const sendPhaseStarted = useCallback(
    (phaseIndex: number, source: "protocol" | "operator") => {
      const phase = protocol.phases[phaseIndex]

      sendEvent({
        event_type: "phase_started",
        label: phase.displayName,
        source,
        event_code: phase.eventCode,
        corrects_event_id: null,
        client_ref: `${sessionId}-phase-${crypto.randomUUID()}`,
      })
    },
    [sendEvent, sessionId],
  )

  const moveToPhase = (phaseIndex: number) => {
    if (!hasData || interrupted || ending) return

    setCurrentPhase(phaseIndex)
    sendPhaseStarted(phaseIndex, "operator")
  }

  useEffect(() => {
    if (!hasData) return
    const delta = Math.max(0, eegNow - previousEegClock.current)
    previousEegClock.current = eegNow

    if (delta > 0) {
      setPhaseTimes((current) =>
        current.map((time, index) =>
          index === currentPhase ? time + delta : time,
        ),
      )
    }

    if (sequence) {
      const scheduledPhase = pilotPhaseAtTime(
        sequence.cues,
        eegNow,
        protocol.phases.length,
      )

      if (scheduledPhase !== lastScheduledPhase.current) {
        lastScheduledPhase.current = scheduledPhase
        setCurrentPhase(scheduledPhase)
        if (initialPhaseSent.current)
          sendPhaseStarted(scheduledPhase, "protocol")
      }
    }
  }, [currentPhase, eegNow, hasData, sequence, sendPhaseStarted])

  useEffect(() => {
    if (!hasData || initialPhaseSent.current) return

    initialPhaseSent.current = true
    const scheduledPhase = sequence
      ? pilotPhaseAtTime(sequence.cues, eegNow, protocol.phases.length)
      : currentPhase
    lastScheduledPhase.current = scheduledPhase
    if (scheduledPhase !== currentPhase) setCurrentPhase(scheduledPhase)
    sendPhaseStarted(scheduledPhase, "protocol")
  }, [currentPhase, eegNow, hasData, sequence, sendPhaseStarted])

  // Acknowledgment and setup notes, once per new session. Fixed client_refs make retries safe.

  useEffect(() => {
    if (!isNewSession || initialEventsSent.current) return

    initialEventsSent.current = true

    sendEvent({
      event_type: "contact_quality_unverified",

      label:
        "Contact quality not measured; operator acknowledged warning after visual fit check",

      source: "operator",

      event_code: null,

      corrects_event_id: null,

      client_ref: `${sessionId}-contact-ack`,
    })

    if (setupNotes) {
      sendEvent({
        event_type: "operator_note",

        label: `Setup note: ${setupNotes}`,

        source: "operator",

        event_code: null,

        corrects_event_id: null,

        client_ref: `${sessionId}-setup-note`,
      })
    }
  }, [isNewSession, sessionId, setupNotes, sendEvent])

  useEffect(() => {
    api
      .pilotSequence()
      .then(setSequence, (error) => setSequenceError(failureText(error)))
  }, [])

  // Live traces: poll with the cursor so each response only carries new points.

  useEffect(() => {
    let cancelled = false

    let inFlight = false

    let stopped = false

    const poll = async () => {
      if (inFlight || stopped) return

      inFlight = true

      try {
        const live = await api.live(sessionId, cursor.current)

        if (cancelled) return

        cursor.current = live.cursor

        reviewReduction.current = live.reduction

        setReduction(live.reduction)

        setLiveError(null)

        for (const name of CHANNEL_NAMES) {
          const added = live.channels[name]

          reviewTraces.current[name] = {
            elapsed_s: reviewTraces.current[name].elapsed_s.concat(
              added.elapsed_s,
            ),

            microvolts: reviewTraces.current[name].microvolts.concat(
              added.microvolts,
            ),
          }
        }

        setTraces((current) => {
          const next = { ...current }

          for (const name of CHANNEL_NAMES) {
            const added = live.channels[name]

            next[name] = appendRolling(current[name], added, TRACE_WINDOW_S)
          }

          return next
        })

        if (live.gaps.length) {
          reviewGaps.current = [...reviewGaps.current, ...live.gaps]

          setGaps((current) => [...current, ...live.gaps].slice(-200))
        }
      } catch (error) {
        if (cancelled) return

        if (
          error instanceof ApiFailure &&
          error.code === "session_not_recording"
        )
          stopped = true

        setLiveError(failureText(error))
      } finally {
        inFlight = false
      }
    }

    const timer = window.setInterval(poll, LIVE_POLL_MS)

    poll()

    return () => {
      cancelled = true

      window.clearInterval(timer)
    }
  }, [sessionId])

  // Pilot prompts run on the EEG clock (time since the first packet), like the terminal guide.

  useEffect(() => {
    if (!hasData || interrupted || !prompts.length) return

    const due = duePrompts(prompts, eegNow, shownPrompts.current)

    for (const prompt of due) {
      shownPrompts.current.add(prompt.key)

      sendEvent({
        event_type: "prompt_shown",

        label: prompt.text,

        source: "protocol",

        event_code: prompt.event_code,

        corrects_event_id: null,

        client_ref: `${sessionId}-${prompt.key}`,
      })
    }

    if (due.length) setCurrentPrompt(due[due.length - 1])
  }, [eegNow, hasData, interrupted, prompts, sendEvent, sessionId])

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()

    window.addEventListener("beforeunload", warn)

    return () => window.removeEventListener("beforeunload", warn)
  }, [])

  const addObservation = (key: string) => {
    const action = observationActions.find((item) => item.key === key)

    if (!action || interrupted) return

    const label =
      action.event_type === "operator_note" && noteText.trim()
        ? `Operator note: ${noteText.trim()}`
        : action.label

    if (action.event_type === "operator_note") setNoteText("")

    sendEvent({
      event_type: action.event_type,

      label,

      source: "operator",

      event_code: null,

      corrects_event_id: null,

      client_ref: crypto.randomUUID(),
    })
  }

  const correctedIds = new Set(
    markers
      .map((marker) => marker.request.corrects_event_id)
      .filter((id): id is string => Boolean(id)),
  )

  const correctable = markers.filter(
    (marker) =>
      marker.state === "saved" &&
      marker.request.source === "operator" &&
      ["observer_marker", "headset_adjustment", "operator_note"].includes(
        marker.request.event_type,
      ) &&
      !correctedIds.has(marker.saved!.event_id),
  )

  const lastCorrectable = correctable[correctable.length - 1] ?? null

  const correctLast = () => {
    if (!lastCorrectable?.saved || interrupted) return

    sendEvent({
      event_type: "marker_correction",

      label: `Correction: accidental marker — ${lastCorrectable.request.label}`,

      source: "operator",

      event_code: null,

      corrects_event_id: lastCorrectable.saved.event_id,

      client_ref: crypto.randomUUID(),
    })
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || endDialog) return

      const target = event.target

      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      ) {
        return
      }

      const key = event.key.toLowerCase()

      if (observationActions.some((item) => item.key === key)) {
        event.preventDefault()

        addObservation(key)
      } else if (key === "c") {
        event.preventDefault()

        correctLast()
      }
    }

    window.addEventListener("keydown", handleKeyDown)

    return () => window.removeEventListener("keydown", handleKeyDown)
  })

  const end = async (outcome: Outcome, reason: string | null) => {
    setEnding(true)

    setEndError(null)

    try {
      await api.endSession(sessionId, outcome, reason)

      onEnded({
        traces: reviewTraces.current,

        gaps: reviewGaps.current,

        reduction: reviewReduction.current,
      })
    } catch (error) {
      if (
        error instanceof ApiFailure &&
        error.code === "session_not_recording"
      ) {
        onEnded({
          traces: reviewTraces.current,

          gaps: reviewGaps.current,

          reduction: reviewReduction.current,
        })
      } else setEndError(failureText(error))
    } finally {
      setEnding(false)
    }
  }

  const nextPrompt =
    prompts.find((prompt) => !shownPrompts.current.has(prompt.key)) ?? null

  const unsaved = markers.filter((marker) => marker.state !== "saved").length
  const displayEvents: DisplayEvent[] = markers.map((marker) => ({
    id: marker.request.client_ref,
    recordedId: marker.saved?.event_id,
    label: marker.request.label,
    eventType: marker.request.event_type,
    source: marker.request.source,
    timeS: marker.saved
      ? (marker.saved.eeg_elapsed_s ?? marker.saved.session_elapsed_s)
      : null,
    timeSource: marker.saved?.eeg_elapsed_s === null ? "session" : "EEG",
    state: marker.state,
    request: marker.request,
    error: marker.error,
  }))

  return (
    <main className="h-full w-full overflow-hidden bg-[#f0f2f5] text-[#1e293b]">
      <header className="flex h-[50px] flex-nowrap items-center gap-x-6 border-b border-[#e2e8f0] bg-white px-6 text-xs">
        <span>
          <span className="text-[#64748b]">Session ID: </span>
          <b>{sessionId}</b>
        </span>
        <span className="flex gap-1.5">
          <span className="text-[#64748b]">Participant:</span>
          <b>Not collected</b>
        </span>
        <span className="flex gap-1.5">
          <span className="text-[#64748b]">Visit / Session:</span>
          <b>Live pilot</b>
        </span>
        <ModeBadge status={status} />
        <span className="rounded bg-[#f1f5f9] px-2.5 py-1 font-semibold text-[#475569]">
          Recorder:{" "}
          {recorderState ? recorderState.replace(/_/g, " ") : "unknown"}
        </span>
      </header>

      <div className="grid h-[850px] grid-cols-[260px_minmax(0,1fr)] overflow-hidden">
        <LiveEventSidebar
          events={displayEvents}
          elapsedS={recorder?.session_elapsed_s ?? 0}
          samples={recorder?.rows_written ?? null}
          phaseCount={protocol.phases.length}
          completedPhaseCount={hasData ? currentPhase + 1 : 0}
          onRetry={sendEvent}
        />

        <div className="grid h-full min-w-0 grid-rows-[auto_minmax(300px,1fr)_minmax(0,1fr)] gap-2.5 overflow-hidden p-3.5">
          <div className="space-y-2 overflow-y-auto">
            {statusError && (
              <Banner tone="red">
                Backend not reachable. Nothing new is being confirmed. If the
                backend stopped, the recording was interrupted; restart it and
                open the session from Setup to end it.
              </Banner>
            )}
            {interrupted && (
              <Banner tone="red">
                Recording interrupted: {recorder?.stop_reason}. Rows already
                written are kept. End this session with Stop early or Abort,
                then start a new one.
              </Banner>
            )}
            {!interrupted && status?.device.state === "stalled" && (
              <Banner tone="amber">
                {status.device.message} The gap will be saved as missing data.
                If it does not recover, Stop early.
              </Banner>
            )}
            {recorderState === "waiting_for_packets" && (
              <Banner tone="blue">
                Waiting for the first EEG packets. Device:{" "}
                {deviceLabels[status!.device.state]} — {status!.device.message}
              </Banner>
            )}
            {status?.data_source === "fake_headset" && (
              <Banner tone="amber">
                FAKE HEADSET: generated test data from the backend, not EEG.
              </Banner>
            )}
            {liveError && !statusError && (
              <Banner tone="red">Live traces: {liveError}</Banner>
            )}

            <LiveStatusStrip status={status} error={statusError} showSaved />
          </div>

          <div className="min-h-0">
            <LiveTraces
              traces={traces}
              gaps={gaps}
              reduction={reduction}
              windowS={TRACE_WINDOW_S}
              yRangeUv={yRange}
              onYRangeChange={setYRange}
              waiting={!hasData}
              viewLabel={
                status?.data_source === "fake_headset"
                  ? "Simulated data"
                  : "Live EEG"
              }
              heading={
                status?.data_source === "fake_headset"
                  ? "Generated test channels"
                  : "Real channels from the recorder"
              }
            />
          </div>

          <div className="grid min-h-0 grid-cols-[480px_380px_minmax(0,1fr)] gap-2.5 overflow-hidden">
            <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-2.5 overflow-hidden">
              <section className="dashboard-card min-h-0 overflow-y-auto">
                <div className="flex flex-wrap items-center gap-4">
                  <div>
                    <h2 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                      Protocol Active
                    </h2>
                    <p className="font-['Inter:Bold'] text-[34px] font-bold text-[#1e293b]">
                      {formatClock(eegNow)}
                    </p>
                  </div>
                  <div className="space-y-1 text-[11px] text-[#64748b]">
                    <strong
                      className={`flex items-center gap-1.5 ${
                        recorderState === "recording"
                          ? "text-[#dc2626]"
                          : "text-[#64748b]"
                      }`}
                    >
                      <img
                        src="/assets/4179f.svg"
                        alt=""
                        width="10"
                        height="10"
                      />
                      {recorderState === "recording"
                        ? "RECORDING"
                        : interrupted
                          ? "INTERRUPTED"
                          : recorderState === "waiting_for_packets"
                            ? "WAITING FOR EEG"
                            : "READY"}
                    </strong>
                    <p>
                      Session clock:{" "}
                      <b className="text-[#1e293b]">
                        {formatClock(recorder?.session_elapsed_s ?? null)}
                      </b>
                    </p>
                    <p>
                      Samples saved:{" "}
                      <b className="text-[#1e293b]">
                        {recorder?.rows_written?.toLocaleString() ?? "–"}
                      </b>
                    </p>
                    <p>
                      Display rate:{" "}
                      <b className="text-[#1e293b]">
                        {reduction ? `${reduction.display_hz} Hz` : "–"}
                      </b>
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="control-button border border-[#fecdd3] bg-[#fff1f2] text-[#e11d48]"
                    disabled={ending}
                    title={
                      sequenceDone && !interrupted
                        ? "Stop and save the completed session."
                        : "Stop early and save the session as incomplete."
                    }
                    onClick={() => {
                      if (sequenceDone && !interrupted) {
                        end("completed", null)
                      } else {
                        setEndReason("")
                        setEndDialog("incomplete")
                      }
                    }}
                  >
                    <img
                      src="/assets/ba401.svg"
                      alt=""
                      width="16"
                      height="16"
                    />
                    Stop
                  </button>
                  <button
                    type="button"
                    className="control-button border border-[#fca5a5] bg-white text-[#dc2626]"
                    disabled={ending}
                    onClick={() => {
                      setEndReason("")

                      setEndDialog("aborted")
                    }}
                  >
                    <img
                      src="/assets/99cb2.svg"
                      alt=""
                      width="16"
                      height="16"
                    />
                    Abort Session
                  </button>
                </div>
                <p className="font-['Inter:Italic'] text-[10px] italic text-[#94a3b8]">
                  Live capture starts with the session and cannot be paused. To
                  interrupt, stop or abort this session, then start a new one.
                  Display rate is reduced for visualization only.
                </p>
                {endError && !endDialog && (
                  <p className="text-[11px] font-semibold text-[#b91c1c]">
                    {endError}
                  </p>
                )}
              </section>

              <section className="dashboard-card">
                <label className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Operator notes
                  <textarea
                    className="form-textarea mt-3 min-h-[72px] normal-case"
                    value={noteText}
                    onChange={(event) => setNoteText(event.target.value)}
                    placeholder="Add a short observation or setup note…"
                  />
                </label>
              </section>
            </div>

            <LivePhaseControl
              currentPhase={currentPhase}
              phaseTimes={phaseTimes}
              nextPhaseAtS={
                sequence?.cues.find((cue) => cue.index > currentPhase)
                  ?.start_s ?? null
              }
              hasStarted={hasData}
              disabled={interrupted || ending}
              onPrevious={() => moveToPhase(currentPhase - 1)}
              onNext={() => moveToPhase(currentPhase + 1)}
            >
              <div className="mb-3 border-b border-[#e2e8f0] pb-3">
                <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Live pilot cue
                </h3>
                {interrupted ? (
                  <p className="text-sm font-bold text-[#b91c1c]">
                    Pilot stopped: recording interrupted.
                  </p>
                ) : sequenceError ? (
                  <p className="text-sm font-semibold text-[#b91c1c]">
                    Could not load pilot sequence: {sequenceError}
                  </p>
                ) : sequenceDone ? (
                  <p className="text-sm font-bold text-[#15803d]">
                    Sequence finished. Press Stop to save as completed.
                  </p>
                ) : currentPrompt ? (
                  <p
                    className={`text-base font-bold ${
                      currentPrompt.kind === "now"
                        ? "text-[#1d4ed8]"
                        : "text-[#b45309]"
                    }`}
                  >
                    {currentPrompt.text}
                  </p>
                ) : (
                  <p className="text-sm font-semibold text-[#64748b]">
                    Starts when EEG arrives…
                  </p>
                )}
                {nextPrompt && hasData && !sequenceDone && !interrupted && (
                  <p className="text-[11px] text-[#64748b]">
                    Next: {nextPrompt.text} in{" "}
                    {Math.max(0, nextPrompt.at_s - eegNow).toFixed(0)} s
                  </p>
                )}
                {sequence && (
                  <>
                    <div className="mt-2 h-1.5 rounded bg-[#e2e8f0]">
                      <div
                        className="h-full rounded bg-[#2563eb]"
                        style={{
                          width: `${Math.min(100, (eegNow / sequence.total_s) * 100)}%`,
                        }}
                      />
                    </div>
                    <ol className="mt-2 space-y-1">
                      {sequence.cues.map((cue) => (
                        <li
                          key={cue.index}
                          className={`flex items-center gap-1 text-[10px] leading-3 ${
                            eegNow >= cue.start_s
                              ? "text-[#475569]"
                              : "text-[#94a3b8]"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              eegNow >= cue.start_s
                                ? "bg-[#16a34a]"
                                : "bg-[#cbd5e1]"
                            }`}
                          />
                          {cue.index + 1} - {cue.text}
                          <span className="ml-auto">
                            {formatClock(cue.start_s)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                <p className="mt-2 text-[10px] text-[#94a3b8]">
                  Pilot prompts follow EEG time; phase controls log the
                  operator-selected protocol phase. Displayed phase targets are
                  demo-only.
                </p>
              </div>
            </LivePhaseControl>

            <section className="dashboard-card min-h-0 overflow-y-auto">
              <h2 className="text-sm font-semibold">Observed events</h2>
              <div className="grid grid-cols-2 gap-1.5">
                {observationActions.map((action) => (
                  <button
                    key={action.key}
                    type="button"
                    className="flex min-h-8 items-center gap-2 rounded-md border border-[#fde047] bg-[#fefce8] px-2 text-left text-[10px] font-semibold text-[#854d0e] disabled:cursor-not-allowed disabled:opacity-45"
                    disabled={interrupted}
                    onClick={() => addObservation(action.key)}
                  >
                    <kbd className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#facc15] bg-white">
                      {action.key.toUpperCase()}
                    </kbd>
                    {action.label}
                  </button>
                ))}
                <button
                  type="button"
                  className="flex min-h-8 items-center gap-2 rounded-md border border-[#e2e8f0] bg-[#f8fafc] px-2 text-left text-[10px] font-semibold text-[#475569] disabled:cursor-not-allowed disabled:opacity-45"
                  disabled={!lastCorrectable || interrupted}
                  onClick={correctLast}
                >
                  <kbd className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#cbd5e1] bg-white">
                    C
                  </kbd>
                  Mark last as mistake
                </button>
              </div>
              <input
                className="meta-input h-8 text-xs"
                value={noteText}
                onChange={(event) => setNoteText(event.target.value)}
                placeholder="Text for the next operator note (G)…"
              />
            </section>
          </div>
        </div>
      </div>

      {endDialog && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-[#0f172a]/25 backdrop-blur-sm">
          <section
            role="dialog"
            aria-modal="true"
            className="w-[480px] rounded-2xl bg-white p-6 shadow-xl"
          >
            <h2 className="text-lg font-bold">
              {endDialog === "aborted" ? "Abort session" : "Stop early"}
            </h2>
            <p className="mt-1 text-sm text-[#64748b]">
              The session will be saved as <b>{endDialog}</b>. All rows already
              recorded are kept.
              {unsaved > 0 &&
                ` ${unsaved} event(s) are not confirmed by the backend and will not be in the saved record.`}
            </p>
            <label className="mt-3 flex flex-col gap-1 text-sm font-semibold text-[#475569]">
              Reason (required)
              <textarea
                autoFocus
                className="form-textarea min-h-20 font-normal"
                value={endReason}
                onChange={(event) => setEndReason(event.target.value)}
              />
            </label>
            {endError && (
              <p className="mt-2 text-xs font-semibold text-[#b91c1c]">
                {endError}
              </p>
            )}
            <div className="mt-4 grid grid-cols-2 gap-3">
              <button
                type="button"
                className="rounded-lg bg-[#dc2626] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-45"
                disabled={!endReason.trim() || ending}
                onClick={() => end(endDialog, endReason.trim())}
              >
                {ending
                  ? "Ending…"
                  : endDialog === "aborted"
                    ? "Abort session"
                    : "Stop and save as incomplete"}
              </button>
              <button
                type="button"
                className="rounded-lg border border-[#cbd5e1] bg-[#e5e7eb] px-4 py-2.5 text-sm font-semibold text-[#475569]"
                onClick={() => {
                  setEndDialog(null)

                  setEndError(null)
                }}
              >
                Keep recording
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}

// ------------------------------------------------------------------ review

/** Group consecutive missing packet indices that affect the same channels. */
type MissingPacketRange = {
  first: number
  last: number
  channels: string
}

function missingRanges(missing: Summary["check"]["missing_packets"]) {
  const ranges: MissingPacketRange[] = []

  for (const packet of missing) {
    const channels = packet.channels.join(", ")

    const previous = ranges[ranges.length - 1]

    if (
      previous &&
      previous.channels === channels &&
      packet.packet_index === previous.last + 1
    ) {
      previous.last = packet.packet_index
    } else {
      ranges.push({
        first: packet.packet_index,
        last: packet.packet_index,
        channels,
      })
    }
  }

  return ranges
}

function LiveReviewLayout({
  sessionId,
  summary,
  events,
  displayEvents,
  traceData,
  status,
  statusError,
  sequence,
  sequenceError,
  traceStartS,
  traceCoverage,
  playbackPosition,
  setPlaybackPosition,
  isPlaying,
  setIsPlaying,
  reviewYRange,
  setReviewYRange,
  onAnother,
  onExit,
}: {
  sessionId: string
  summary: Summary
  events: SavedEvent[]
  displayEvents: DisplayEvent[]
  traceData: ReviewTraceData | null
  status: Status | null
  statusError: ApiFailure | null
  sequence: PilotSequence | null
  sequenceError: string | null
  traceStartS: number
  traceCoverage: string | null
  playbackPosition: number
  setPlaybackPosition: (time: number) => void
  isPlaying: boolean
  setIsPlaying: (playing: boolean) => void
  reviewYRange: number
  setReviewYRange: (range: number) => void
  onAnother: () => void
  onExit: () => void
}) {
  const duration = summary.eeg_span_s
  const currentCue =
    sequence?.cues.filter((cue) => cue.start_s <= playbackPosition).at(-1) ??
    null
  const notes = events
    .filter((event) => event.event_type === "operator_note")
    .map((event) => event.label)
    .join("\n")
  const outcomeStyle = {
    completed: "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]",
    incomplete: "border-[#fde047] bg-[#fef9c3] text-[#92400e]",
    aborted: "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",
  }

  return (
    <main className="h-full w-full overflow-hidden bg-[#f0f2f5] text-[#1e293b]">
      <header className="flex h-[50px] flex-nowrap items-center gap-x-6 border-b border-[#e2e8f0] bg-white px-6 text-xs">
        <span className="flex gap-1.5">
          <span className="text-[#64748b]">Participant:</span>
          <b>Not collected</b>
        </span>
        <span className="flex gap-1.5">
          <span className="text-[#64748b]">Session ID:</span>
          <b>{sessionId}</b>
        </span>
        <span className="flex gap-1.5">
          <span className="text-[#64748b]">Visit:</span>
          <b>Live pilot</b>
        </span>
        <span
          className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 font-bold capitalize ${
            summary.outcome === "completed"
              ? "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]"
              : summary.outcome === "aborted"
                ? "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]"
                : "border-[#fde047] bg-[#fef9c3] text-[#92400e]"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              summary.outcome === "completed"
                ? "bg-[#16a34a]"
                : summary.outcome === "aborted"
                  ? "bg-[#dc2626]"
                  : "bg-[#d97706]"
            }`}
          />
          {summary.outcome ?? "not recorded"}
        </span>
        <span className="rounded bg-[#f1f5f9] px-2.5 py-1 text-[11px] text-[#64748b]">
          {summary.data_source === "fake_headset"
            ? "FAKE HEADSET test data"
            : "live EEG data"}
        </span>
        <span className="ml-auto rounded border border-[#bfdbfe] bg-[#eff6ff] px-2.5 py-1 font-bold text-[#1d4ed8]">
          REVIEW MODE
        </span>
        <button
          type="button"
          className="rounded-lg border border-[#cbd5e1] px-3 py-1.5 font-semibold text-[#475569] hover:bg-[#f8fafc]"
          aria-label="Back to EEG Operator Dashboard"
          title="Back to EEG Operator Dashboard"
          onClick={onExit}
        >
          ← Dashboard
        </button>
      </header>

      <div className="grid h-[850px] grid-cols-[260px_minmax(0,1fr)] overflow-hidden">
        <LiveEventSidebar
          events={displayEvents}
          elapsedS={summary.eeg_span_s}
          samples={summary.check.total_rows}
          phaseCount={sequence?.cues.length ?? 0}
          completedPhaseCount={
            sequence?.cues.filter((cue) => cue.start_s <= playbackPosition)
              .length ?? 0
          }
          outcome={summary.outcome}
        />
        <div className="grid h-full min-w-0 grid-rows-[auto_300px_93px_minmax(0,1fr)] gap-2.5 overflow-hidden p-3.5">
          <div className="space-y-2 overflow-y-auto">
            {statusError && (
              <Banner tone="red">
                Backend not reachable: {statusError.message}
              </Banner>
            )}
            {summary.data_source === "fake_headset" && (
              <Banner tone="amber">
                Recorded from the FAKE HEADSET: generated test data, not EEG.
              </Banner>
            )}
            <LiveStatusStrip status={status} error={statusError} />
          </div>

          <section className="min-h-0 overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white">
            {traceData &&
            CHANNEL_NAMES.some(
              (name) => traceData.traces[name].elapsed_s.length > 0,
            ) ? (
              <LiveTraces
                traces={traceData.traces}
                gaps={traceData.gaps}
                reduction={traceData.reduction}
                windowS={TRACE_WINDOW_S}
                startS={traceStartS}
                cursorS={playbackPosition}
                yRangeUv={reviewYRange}
                onYRangeChange={setReviewYRange}
                waiting={false}
                viewLabel="EEG replay"
                heading="Recorded channels from this session"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                <h2 className="text-sm font-semibold">
                  EEG channel traces unavailable in this browser visit
                </h2>
                <p className="max-w-[620px] text-xs text-[#64748b]">
                  Display samples received while this page was open are used for
                  replay. Open the prediction-free review bundle below to
                  inspect the saved signal.
                </p>
              </div>
            )}
          </section>

          <section className="rounded-[10px] border border-[#e2e8f0] bg-white px-4 py-2.5">
            <div className="mb-2 flex items-center gap-2">
              <img src="/assets/62339.svg" alt="" width="14" height="14" />
              <h2 className="text-xs font-semibold text-[#1e293b]">
                Full Session Overview
              </h2>
              <span className="text-[11px] text-[#94a3b8]">
                Total: {formatClock(duration)}
              </span>
              <span className="ml-auto text-[11px] text-[#64748b]">
                Zoom:{" "}
                <b className="rounded border border-[#bfdbfe] bg-[#eff6ff] px-2 py-1 text-[#2563eb]">
                  2×
                </b>
              </span>
            </div>
            <div className="relative flex h-9 overflow-hidden rounded-md border border-[#e2e8f0] bg-[#f8fafc]">
              {sequence?.cues.map((cue, index) => (
                <span
                  key={cue.index}
                  className="absolute inset-y-0 opacity-70"
                  style={{
                    left: `${(cue.start_s / Math.max(duration, 1)) * 100}%`,
                    width: `${Math.max((cue.duration_s / Math.max(duration, 1)) * 100, 0.3)}%`,
                    backgroundColor: [
                      "#dbeafe",
                      "#fef3c7",
                      "#ede9fe",
                      "#dcfce7",
                      "#f1f5f9",
                    ][index % 5],
                  }}
                  title={cue.text}
                />
              ))}
              {displayEvents
                .filter(
                  (event): event is DisplayEvent & { timeS: number } =>
                    event.timeS !== null,
                )
                .map((event) => (
                  <span
                    key={event.id}
                    className="absolute inset-y-0 z-[1] w-px opacity-80"
                    style={{
                      left: `${(event.timeS / Math.max(duration, 1)) * 100}%`,
                      backgroundColor: eventColor(event),
                    }}
                    title={`${event.label} · ${formatMarkerTime(event.timeS)}`}
                  />
                ))}
              <span
                className="absolute inset-y-0 z-[2] w-0.5 bg-[#2563eb]"
                style={{
                  left: `${Math.min(100, (playbackPosition / Math.max(duration, 1)) * 100)}%`,
                }}
              />
            </div>
            <div className="mt-1 flex gap-1 overflow-hidden text-[8px]">
              {sequence?.cues.map((cue, index) => (
                <span
                  key={cue.index}
                  className="truncate rounded px-1 py-0.5 text-[#475569]"
                  style={{
                    backgroundColor: [
                      "#dbeafe",
                      "#fef3c7",
                      "#ede9fe",
                      "#dcfce7",
                      "#f1f5f9",
                    ][index % 5],
                  }}
                >
                  {index + 1}-{cue.text}
                </span>
              ))}
            </div>
          </section>

          <div className="grid min-h-0 grid-cols-[480px_380px_minmax(0,1fr)] gap-2.5 overflow-hidden">
            <div className="grid min-h-0 grid-rows-[132px_minmax(0,1fr)] gap-2.5">
              <section className="rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
                <div className="flex items-center gap-5">
                  <div>
                    <h2 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                      Playback Position
                    </h2>
                    <p className="text-[30px] font-bold leading-tight">
                      {formatClock(playbackPosition)}{" "}
                      <span className="text-sm font-normal text-[#94a3b8]">
                        / {formatClock(duration)}
                      </span>
                    </p>
                  </div>
                  <div className="text-[11px] text-[#64748b]">
                    <b className="text-[#475569]">
                      ● {isPlaying ? "PLAYING" : "PAUSED"}
                    </b>
                    <p>
                      Session duration:{" "}
                      <b className="text-[#1e293b]">{formatClock(duration)}</b>
                    </p>
                    <p>
                      Total samples:{" "}
                      <b className="text-[#1e293b]">
                        {summary.check.total_rows.toLocaleString()}
                      </b>
                    </p>
                  </div>
                </div>
                <input
                  aria-label="EEG playback position"
                  className="mt-1.5 h-1.5 w-full accent-[#2563eb]"
                  type="range"
                  min={0}
                  max={duration}
                  step={0.25}
                  value={Math.min(playbackPosition, duration)}
                  disabled={duration <= 0}
                  onChange={(event) => {
                    setPlaybackPosition(Number(event.target.value))
                    setIsPlaying(false)
                  }}
                />
                <div className="mt-1 flex items-center gap-1.5">
                  <button
                    type="button"
                    className="review-control-button"
                    onClick={() =>
                      setPlaybackPosition(Math.max(0, playbackPosition - 10))
                    }
                  >
                    <img
                      src="/assets/deb5e.svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    10s
                  </button>
                  <button
                    type="button"
                    className="review-control-button bg-[#2563eb] text-white"
                    disabled={duration <= 0 || isPlaying}
                    onClick={() => {
                      if (playbackPosition >= duration) setPlaybackPosition(0)
                      setIsPlaying(true)
                    }}
                    aria-label="Play EEG replay"
                  >
                    <img
                      src="/assets/399bb%20(1).svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    Play
                  </button>
                  <button
                    type="button"
                    className="review-control-button"
                    disabled={!isPlaying}
                    onClick={() => setIsPlaying(false)}
                    aria-label="Pause EEG replay"
                  >
                    <img
                      src="/assets/a7a3c.svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    Pause
                  </button>
                  <button
                    type="button"
                    className="review-control-button"
                    onClick={() =>
                      setPlaybackPosition(
                        Math.min(duration, playbackPosition + 10),
                      )
                    }
                  >
                    <img
                      src="/assets/6671c.svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    10s
                  </button>
                  <p className="ml-auto text-[9px] text-[#94a3b8]">
                    Trace coverage: {traceCoverage ?? "none"}
                  </p>
                </div>
              </section>
              <section className="min-h-0 rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
                <h2 className="mb-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Operator notes
                </h2>
                <div className="h-[76px] whitespace-pre-line overflow-y-auto rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-3 text-[12px] leading-4 text-[#334155]">
                  {notes || "No notes were recorded for this session."}
                </div>
              </section>
            </div>

            <section className="min-h-0 overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
              <div className="mb-2 flex items-center gap-2">
                <img src="/assets/4e3e5.svg" alt="" width="16" height="16" />
                <h2 className="text-sm font-semibold">Experiment Phases</h2>
                <span className="rounded border border-[#bbf7d0] bg-[#f0fdf4] px-1.5 py-0.5 text-[10px] font-bold text-[#15803d]">
                  {sequence?.cues.filter(
                    (cue) => cue.start_s <= playbackPosition,
                  ).length ?? 0}{" "}
                  completed
                </span>
              </div>
              <div className="mb-2 rounded-lg border border-[#ddd6fe] bg-[#f5f3ff] px-3.5 py-2">
                <span className="rounded bg-[#7c3aed] px-1.5 py-0.5 text-[10px] font-bold text-white">
                  Viewing phase
                </span>
                <p className="mt-1 text-sm font-bold text-[#4c1d95]">
                  {currentCue?.text ??
                    sequenceError ??
                    "No phase active at this position"}
                </p>
                {currentCue && (
                  <p className="text-[11px] text-[#6d28d9]">
                    Window: {formatClock(currentCue.start_s)} –{" "}
                    {formatClock(currentCue.start_s + currentCue.duration_s)}
                  </p>
                )}
              </div>
              <h3 className="mb-1 text-[10px] font-semibold uppercase text-[#94a3b8]">
                All phases
              </h3>
              <ol className="space-y-0.5 overflow-y-auto">
                {sequence?.cues.map((cue) => (
                  <li
                    key={cue.index}
                    className={`flex items-center gap-1 text-[10px] leading-3 ${
                      cue.start_s <= playbackPosition
                        ? "text-[#64748b]"
                        : "text-[#94a3b8]"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        cue.start_s <= playbackPosition
                          ? "bg-[#16a34a]"
                          : "bg-[#cbd5e1]"
                      }`}
                    />
                    {cue.index + 1} - {cue.text}
                    <span className="ml-auto">{formatClock(cue.start_s)}</span>
                  </li>
                ))}
              </ol>
            </section>

            <section className="dashboard-card min-h-0 overflow-y-auto">
              <div
                className={`rounded-lg border p-3 ${
                  summary.outcome ? outcomeStyle[summary.outcome] : ""
                }`}
              >
                <p className="text-[10px] font-semibold uppercase">
                  Session outcome
                </p>
                <p className="text-xl font-bold capitalize">
                  {summary.outcome ?? "not recorded"}
                </p>
                {summary.reason && (
                  <p className="mt-1 text-[12px]">Reason: {summary.reason}</p>
                )}
              </div>
              <p className="text-[12px]">
                Saving: <b>{summary.recording_status}</b>
                {summary.stop_reason && (
                  <span className="text-[#b91c1c]">
                    {" "}
                    — {summary.stop_reason}
                  </span>
                )}
              </p>
              <p className="text-[12px]">
                {summary.check.total_rows.toLocaleString()} rows ·{" "}
                {summary.check.missing_packets.length} missing packets ·{" "}
                {summary.event_count} events
              </p>
              <table className="mt-1 text-[11px]">
                <thead>
                  <tr className="text-left text-[9px] uppercase text-[#94a3b8]">
                    <th className="pr-4">Channel</th>
                    <th>Rows saved</th>
                  </tr>
                </thead>
                <tbody>
                  {CHANNEL_NAMES.map((name) => (
                    <tr key={name}>
                      <td className="pr-4 font-semibold">{name}</td>
                      <td>
                        {summary.check.rows_per_channel[
                          name
                        ]?.toLocaleString() ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3 className="mt-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
                Missing packets ({summary.check.missing_packets.length})
              </h3>
              {summary.check.missing_packets.length === 0 ? (
                <p className="text-[11px] text-[#15803d]">None</p>
              ) : (
                <ul className="text-[10px]">
                  {missingRanges(summary.check.missing_packets)
                    .slice(0, 8)
                    .map((range) => (
                      <li key={range.first}>
                        {range.first === range.last
                          ? `Packet ${range.first}`
                          : `Packets ${range.first}–${range.last}`}
                        : {range.channels}
                      </li>
                    ))}
                </ul>
              )}
              <h3 className="mt-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
                Read-back check
              </h3>
              {summary.check.problems.length === 0 ? (
                <p className="text-[12px] text-[#15803d]">No problems found</p>
              ) : (
                <ul className="list-disc pl-4 text-[11px] text-[#b91c1c]">
                  {summary.check.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              )}
              <h3 className="mt-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
                2-second windows
              </h3>
              {summary.windows.error ? (
                <p className="text-[11px] text-[#b91c1c]">
                  {summary.windows.error}
                </p>
              ) : (
                <p className="text-[12px]">
                  <b>{summary.windows.valid}</b> of{" "}
                  <b>{summary.windows.total}</b> valid
                </p>
              )}
              {summary.windows.invalid.length > 0 && (
                <ul className="mt-1 space-y-1 text-[10px]">
                  {summary.windows.invalid.slice(0, 8).map((window) => (
                    <li key={window.window_id}>
                      [{window.start_s}, {window.end_s}) s:{" "}
                      {window.reasons.join("; ")}
                    </li>
                  ))}
                </ul>
              )}
              <h3 className="mt-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
                Inspect saved traces
              </h3>
              {summary.review_bundle.url ? (
                <a
                  className="block rounded-lg border border-[#bfdbfe] bg-[#eff6ff] px-3 py-2 text-center text-[12px] font-semibold text-[#1d4ed8]"
                  href={BACKEND_URL + summary.review_bundle.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open prediction-free review bundle
                </a>
              ) : (
                <p className="text-[12px] text-[#b91c1c]">
                  Review bundle unavailable: {summary.review_bundle.error}
                </p>
              )}
              <button
                type="button"
                className="mt-2 w-full rounded-lg bg-[#2563eb] px-3 py-2.5 text-[12px] font-semibold text-white"
                onClick={onAnother}
              >
                Start Another Session
              </button>
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}

function LiveReview({
  sessionId,

  traceData,

  status,

  statusError,

  onAnother,
  onExit,
}: {
  sessionId: string

  traceData: ReviewTraceData | null

  status: Status | null

  statusError: ApiFailure | null

  onAnother: () => void
  onExit: () => void
}) {
  const [summary, setSummary] = useState<Summary | null>(null)

  const [events, setEvents] = useState<SavedEvent[]>([])

  const [error, setError] = useState<string | null>(null)

  const [attempt, setAttempt] = useState(0)

  const [playbackPosition, setPlaybackPosition] = useState(0)

  const [isPlaying, setIsPlaying] = useState(false)

  const [reviewYRange, setReviewYRange] = useState(250)
  const [sequence, setSequence] = useState<PilotSequence | null>(null)
  const [sequenceError, setSequenceError] = useState<string | null>(null)

  useEffect(() => {
    api
      .pilotSequence()
      .then(setSequence, (caught) => setSequenceError(failureText(caught)))
  }, [])

  useEffect(() => {
    let cancelled = false

    setError(null)

    Promise.all([api.summary(sessionId), api.events(sessionId)]).then(
      ([loadedSummary, loadedEvents]) => {
        if (cancelled) return

        setSummary(loadedSummary)

        setEvents(loadedEvents)
      },

      (caught) => !cancelled && setError(failureText(caught)),
    )

    return () => {
      cancelled = true
    }
  }, [sessionId, attempt])

  const duration = summary?.eeg_span_s ?? 0

  const hasReviewTraces =
    traceData !== null &&
    CHANNEL_NAMES.some((name) => traceData.traces[name].elapsed_s.length > 0)

  const traceTimes =
    traceData === null
      ? []
      : CHANNEL_NAMES.flatMap((name) => {
          const elapsed = traceData.traces[name].elapsed_s
          return elapsed.length ? [elapsed[0], elapsed[elapsed.length - 1]] : []
        })

  const traceCoverage =
    traceTimes.length > 0
      ? `${Math.min(...traceTimes).toFixed(1)}–${Math.max(...traceTimes).toFixed(1)} s`
      : null

  const traceStartS = Math.max(
    0,

    Math.min(
      Math.max(0, duration - TRACE_WINDOW_S),
      playbackPosition - TRACE_WINDOW_S / 2,
    ),
  )
  const displayEvents: DisplayEvent[] = events.map((event) => ({
    id: event.event_id,
    recordedId: event.event_id,
    label: event.label,
    eventType: event.event_type,
    source: event.source,
    timeS: event.eeg_elapsed_s ?? event.session_elapsed_s,
    timeSource: event.eeg_elapsed_s === null ? "session" : "EEG",
    state: "saved",
  }))
  const noteText = events
    .filter((event) => event.event_type === "operator_note")
    .map((event) => event.label)
    .join("\n")
  const currentCue =
    sequence?.cues.filter((cue) => cue.start_s <= playbackPosition).at(-1) ??
    null

  useEffect(() => {
    if (!isPlaying || duration <= 0) return

    const timer = window.setInterval(() => {
      setPlaybackPosition((position) => Math.min(duration, position + 0.25))
    }, 250)

    return () => window.clearInterval(timer)
  }, [duration, isPlaying])

  useEffect(() => {
    if (isPlaying && duration > 0 && playbackPosition >= duration)
      setIsPlaying(false)
  }, [duration, isPlaying, playbackPosition])

  const outcomeStyle = {
    completed: "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]",

    incomplete: "border-[#fde047] bg-[#fef9c3] text-[#92400e]",

    aborted: "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",
  }

  if (summary && Number.isFinite(summary.eeg_span_s)) {
    return (
      <LiveReviewLayout
        sessionId={sessionId}
        summary={summary}
        events={events}
        displayEvents={displayEvents}
        traceData={traceData}
        status={status}
        statusError={statusError}
        sequence={sequence}
        sequenceError={sequenceError}
        traceStartS={traceStartS}
        traceCoverage={traceCoverage}
        playbackPosition={playbackPosition}
        setPlaybackPosition={setPlaybackPosition}
        isPlaying={isPlaying}
        setIsPlaying={setIsPlaying}
        reviewYRange={reviewYRange}
        setReviewYRange={setReviewYRange}
        onAnother={onAnother}
        onExit={onExit}
      />
    )
  }

  return (
    <main className="h-full w-full overflow-hidden bg-[#f0f2f5] text-[#1e293b]">
      <header className="flex h-14 items-center gap-5 border-b border-[#e2e8f0] bg-white px-6 text-xs">
        <span>
          <span className="text-[#64748b]">Session ID: </span>
          <b>{sessionId}</b>
        </span>
        <span className="rounded border border-[#bfdbfe] bg-[#eff6ff] px-2.5 py-1 font-bold text-[#1d4ed8]">
          SAVED SESSION REVIEW
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            className="rounded-lg border border-[#cbd5e1] px-3 py-1.5 text-[12px] font-semibold text-[#475569]"
            aria-label="Back to EEG Operator Dashboard"
            title="Back to EEG Operator Dashboard"
            onClick={onExit}
          >
            ← Dashboard
          </button>
          <button
            type="button"
            className="rounded-lg bg-[#2563eb] px-4 py-2 text-[12px] font-semibold text-white"
            onClick={onAnother}
          >
            Start another session
          </button>
        </div>
      </header>

      {error && (
        <div className="p-6">
          <Banner tone="red">
            Could not load the saved session: {error}{" "}
            <button
              type="button"
              className="underline"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Retry
            </button>
          </Banner>
        </div>
      )}
      {!summary && !error && (
        <p className="p-6 text-sm text-[#64748b]">Loading saved session…</p>
      )}

      {summary && (
        <div className="grid h-[844px] grid-rows-[330px_72px_minmax(0,1fr)] gap-2.5 overflow-hidden p-3.5">
          <section className="min-h-0 overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white">
            {hasReviewTraces && traceData ? (
              <LiveTraces
                traces={traceData.traces}
                gaps={traceData.gaps}
                reduction={traceData.reduction}
                windowS={TRACE_WINDOW_S}
                startS={traceStartS}
                cursorS={playbackPosition}
                yRangeUv={reviewYRange}
                onYRangeChange={setReviewYRange}
                waiting={false}
                viewLabel="EEG replay"
                heading="Recorded channels from this session"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                <h2 className="text-sm font-semibold">
                  EEG channel traces unavailable in this browser visit
                </h2>
                <p className="max-w-[620px] text-xs text-[#64748b]">
                  The backend keeps the complete recording, but this page only
                  plots display samples received while it was open. Open the
                  prediction-free review bundle below to inspect the saved
                  signal.
                </p>
              </div>
            )}
          </section>

          <section className="flex flex-col justify-center gap-1 rounded-[10px] border border-[#e2e8f0] bg-white px-4 py-2">
            <div className="flex items-center gap-3">
              <span className="min-w-[136px] text-xs font-semibold text-[#475569]">
                Playback {formatClock(playbackPosition)} /{" "}
                {formatClock(duration)}
              </span>
              <input
                aria-label="EEG playback position"
                className="min-w-0 flex-1 accent-[#2563eb]"
                type="range"
                min={0}
                max={duration}
                step={0.25}
                value={Math.min(playbackPosition, duration)}
                disabled={duration <= 0}
                onChange={(event) => {
                  setPlaybackPosition(Number(event.target.value))

                  setIsPlaying(false)
                }}
              />
              <button
                type="button"
                className="flex items-center gap-2 rounded-lg bg-[#2563eb] px-4 py-2 text-xs font-semibold text-white disabled:opacity-45"
                disabled={duration <= 0}
                onClick={() => {
                  if (isPlaying) {
                    setIsPlaying(false)
                  } else {
                    if (playbackPosition >= duration) setPlaybackPosition(0)

                    setIsPlaying(true)
                  }
                }}
              >
                <img
                  src={
                    isPlaying ? "/assets/a7a3c.svg" : "/assets/399bb%20(1).svg"
                  }
                  alt=""
                  width="14"
                  height="14"
                />
                {isPlaying ? "Pause" : "Play"}
              </button>
              <span className="text-[10px] text-[#64748b]">
                Purple line = playback position
              </span>
            </div>
            <p className="text-[10px] text-[#64748b]">
              Browser-held display trace coverage: {traceCoverage ?? "none"} of{" "}
              {duration.toFixed(1)} s. Display data is downsampled; the review
              bundle below provides the saved signal.
            </p>
          </section>

          <div className="grid min-h-0 grid-cols-[380px_minmax(0,1fr)_420px] gap-3 overflow-hidden">
            <section className="dashboard-card min-h-0 overflow-y-auto">
              {summary.data_source === "fake_headset" && (
                <Banner tone="amber">
                  Recorded from the FAKE HEADSET: generated test data, not EEG.
                </Banner>
              )}
              <div
                className={`rounded-lg border p-3 ${
                  summary.outcome ? outcomeStyle[summary.outcome] : ""
                }`}
              >
                <p className="text-[10px] font-semibold uppercase">
                  Session outcome
                </p>
                <p className="text-xl font-bold capitalize">
                  {summary.outcome ?? "not recorded"}
                </p>
                {summary.reason && (
                  <p className="mt-1 text-[12px]">Reason: {summary.reason}</p>
                )}
              </div>
              <p className="text-[12px]">
                Saving: <b>{summary.recording_status}</b>
                {summary.stop_reason && (
                  <span className="text-[#b91c1c]">
                    {" "}
                    — {summary.stop_reason}
                  </span>
                )}
              </p>
              <p className="text-[12px]">
                EEG span: <b>{summary.eeg_span_s.toFixed(2)} s</b> · total rows:{" "}
                <b>{summary.check.total_rows.toLocaleString()}</b> · events:{" "}
                <b>{summary.event_count}</b>
              </p>
              <table className="text-[12px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase text-[#94a3b8]">
                    <th className="pr-6">Channel</th>
                    <th>Rows saved</th>
                  </tr>
                </thead>
                <tbody>
                  {CHANNEL_NAMES.map((name) => (
                    <tr key={name}>
                      <td className="pr-6 font-semibold">{name}</td>
                      <td>
                        {summary.check.rows_per_channel[
                          name
                        ]?.toLocaleString() ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div>
                <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Missing packets ({summary.check.missing_packets.length})
                </h3>
                {summary.check.missing_packets.length === 0 ? (
                  <p className="text-[12px] text-[#15803d]">None</p>
                ) : (
                  <ul className="text-[11px]">
                    {missingRanges(summary.check.missing_packets)
                      .slice(0, 12)
                      .map((range) => (
                        <li key={range.first}>
                          {range.first === range.last
                            ? `Packet ${range.first}`
                            : `Packets ${range.first}–${range.last}`}
                          : {range.channels}
                        </li>
                      ))}
                    {missingRanges(summary.check.missing_packets).length >
                      12 && <li>…more ranges not shown</li>}
                  </ul>
                )}
              </div>
              <div>
                <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Read-back check
                </h3>
                {summary.check.problems.length === 0 ? (
                  <p className="text-[12px] text-[#15803d]">
                    No problems found
                  </p>
                ) : (
                  <ul className="list-disc pl-4 text-[11px] text-[#b91c1c]">
                    {summary.check.problems.map((problem) => (
                      <li key={problem}>{problem}</li>
                    ))}
                  </ul>
                )}
              </div>
            </section>

            <section className="dashboard-card min-h-0 overflow-y-auto">
              <h2 className="text-sm font-semibold">
                Saved events ({events.length})
              </h2>
              <p className="text-[10px] text-[#94a3b8]">
                As saved by the backend. Observations and prompts, not artifact
                labels.
              </p>
              <table className="text-[11px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase text-[#94a3b8]">
                    <th className="pr-3">ID</th>
                    <th className="pr-3">≈ EEG s</th>
                    <th className="pr-3">Type</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr
                      key={event.event_id}
                      className="border-t border-[#f1f5f9] align-top"
                    >
                      <td className="pr-3 font-mono">{event.event_id}</td>
                      <td className="pr-3">
                        {event.eeg_elapsed_s?.toFixed(2) ?? "–"}
                      </td>
                      <td className="pr-3">
                        {event.event_type.replace(/_/g, " ")}
                      </td>
                      <td>
                        {event.label}
                        {event.corrects_event_id &&
                          ` (corrects ${event.corrects_event_id})`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="dashboard-card min-h-0 overflow-y-auto">
              <h2 className="text-sm font-semibold">2-second windows</h2>
              {summary.windows.error ? (
                <p className="text-[12px] text-[#b91c1c]">
                  {summary.windows.error}
                </p>
              ) : (
                <p className="text-[12px]">
                  <b>{summary.windows.valid}</b> of{" "}
                  <b>{summary.windows.total}</b> windows are technically valid.
                </p>
              )}
              {summary.windows.invalid.length > 0 && (
                <ul className="space-y-1 text-[11px]">
                  {summary.windows.invalid.map((window) => (
                    <li key={window.window_id}>
                      <b>
                        [{window.start_s}, {window.end_s}) s
                      </b>
                      : {window.reasons.join("; ")}
                    </li>
                  ))}
                </ul>
              )}
              <div className="h-px bg-[#e5e7eb]" />
              <h2 className="text-sm font-semibold">Inspect saved traces</h2>
              {summary.review_bundle.url ? (
                <a
                  className="rounded-lg border border-[#bfdbfe] bg-[#eff6ff] px-3 py-2 text-center text-[12px] font-semibold text-[#1d4ed8]"
                  href={BACKEND_URL + summary.review_bundle.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open prediction-free review bundle
                </a>
              ) : (
                <p className="text-[12px] text-[#b91c1c]">
                  Review bundle unavailable: {summary.review_bundle.error}
                </p>
              )}
              <p className="text-[10px] text-[#94a3b8]">
                Samuel's bundle shows the saved microvolt values per window with
                gaps left as breaks. It contains no detector output or suggested
                labels.
              </p>
            </section>
          </div>
        </div>
      )}
    </main>
  )
}

// ------------------------------------------------------------------ mode root

export default function LiveMode({ onExit }: { onExit: () => void }) {
  const [screen, setScreen] = useState<"setup" | "recording" | "review">(
    "setup",
  )

  const [sessionId, setSessionId] = useState<string | null>(null)

  const [setupNotes, setSetupNotes] = useState("")

  const [isNewSession, setIsNewSession] = useState(false)

  const [reviewTraceData, setReviewTraceData] =
    useState<ReviewTraceData | null>(null)

  const { status, error } = useStatus(screen === "recording" ? 500 : 1000)

  if (screen === "recording" && sessionId) {
    return (
      <LiveRecording
        key={sessionId}
        sessionId={sessionId}
        status={status}
        statusError={error}
        setupNotes={setupNotes}
        isNewSession={isNewSession}
        onEnded={(data) => {
          setReviewTraceData(data)

          setScreen("review")
        }}
      />
    )
  }

  if (screen === "review" && sessionId) {
    return (
      <LiveReview
        sessionId={sessionId}
        traceData={reviewTraceData}
        status={status}
        statusError={error}
        onExit={onExit}
        onAnother={() => {
          setSessionId(null)

          setSetupNotes("")

          setReviewTraceData(null)

          setScreen("setup")
        }}
      />
    )
  }

  return (
    <LiveSetup
      status={status}
      statusError={error}
      onExit={onExit}
      onStarted={(id, notes) => {
        setSessionId(id)

        setSetupNotes(notes)

        setIsNewSession(true)

        setReviewTraceData(null)

        setScreen("recording")
      }}
      onResume={(id) => {
        setSessionId(id)

        setIsNewSession(false)

        setReviewTraceData(null)

        setScreen("recording")
      }}
    />
  )
}
