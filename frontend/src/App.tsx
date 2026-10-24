import { useEffect, useLayoutEffect, useRef, useState } from "react"
import protocol from "./protocol.json"
import sessionMetadataFixture from "./session-metadata.json"

type SessionMetadata = {
  nominal_sample_rate_hz: number
  samples_per_packet: number
}

const syntheticSessionMetadata: SessionMetadata = sessionMetadataFixture

const channels = [
  { name: "TP9", samples: "99.8%" },
  { name: "AF7", samples: "99.6%" },
  { name: "AF8", samples: "99.9%" },
  { name: "TP10", samples: "99.4%" },
]

const protocolPhases = protocol.phases
const phases = protocolPhases.map((phase) => phase.displayName)

const markerTypes = [
  {
    name: "Introduction",
    color: "#2563eb",
    background: "#eff6ff",
    border: "#bfdbfe",
  },
  {
    name: "Phase boundary",
    color: "#7c3aed",
    background: "#f5f3ff",
    border: "#ddd6fe",
  },
  {
    name: "Prompt",
    color: "#16a34a",
    background: "#f0fdf4",
    border: "#bbf7d0",
  },
  {
    name: "Observed event",
    color: "#eab308",
    background: "#fefce8",
    border: "#fde047",
  },
  {
    name: "Recording control",
    color: "#dc2626",
    background: "#fef2f2",
    border: "#fecaca",
  },
]

type Marker = {
  event_id: string
  session_id: string
  elapsed_s: number
  event_type: "phase_started" | "prompt_shown" | "observer_marker" | "headset_adjustment" | "operator_note" | "marker_correction" | "recording_paused" | "recording_resumed"
  label: string
  source: "protocol" | "operator"
  type: string
  color: string
  event_code?: string
  corrects_event_id?: string
}

type ObservationKind = "blink" | "facial-muscle" | "head-movement" | "headset-adjustment" | "operator-note"

const observationActions = [
  { kind: "blink", key: "a", keyLabel: "A", label: "Observed blink" },
  {
    kind: "facial-muscle",
    key: "s",
    keyLabel: "S",
    label: "Observed jaw / facial muscle",
  },
  {
    kind: "head-movement",
    key: "d",
    keyLabel: "D",
    label: "Observed head movement",
  },
  {
    kind: "headset-adjustment",
    key: "f",
    keyLabel: "F",
    label: "Headset adjustment",
  },
  { kind: "operator-note", key: "g", keyLabel: "G", label: "Operator note" },
] as const

function createEventId() {
  return crypto.randomUUID()
}

const traces = [
  {
    name: "TP9",
    position: "Left temporal",
    color: "#2563eb",
    asset: "/assets/4c05a.svg",
  },
  {
    name: "AF7",
    position: "Left prefrontal",
    color: "#d97706",
    asset: "/assets/0ab84.svg",
  },
  {
    name: "AF8",
    position: "Right prefrontal",
    color: "#ea580c",
    asset: "/assets/be437.svg",
  },
  {
    name: "TP10",
    position: "Right temporal",
    color: "#2563eb",
    asset: "/assets/7557a.svg",
  },
]

function formatTime(seconds: number) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainingSeconds = seconds % 60
  return [hours, minutes, remainingSeconds]
    .map((value) => value.toString().padStart(2, "0"))
    .join(":")
}

function formatPhaseTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`
}

function formatMarkerTime(seconds: number) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainingSeconds = (seconds % 60).toFixed(2).padStart(5, "0")
  return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${remainingSeconds}`
}

function ChannelCard({ name, samples }: { name: string samples: string }) {
  return (
    <article className="rounded-xl border border-[#e5e7eb] bg-white p-3">
      <h3 className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#111827]">
        {name}
      </h3>
      <div className="mt-2.5 space-y-2 text-[13px]">
        <div className="flex items-center justify-between gap-4">
          <span className="text-[#6b7280]">Signal quality</span>
          <span className="flex items-center gap-1.5 font-['Inter:Semi_Bold'] font-semibold text-[#10b981]">
            <span className="h-1.5 w-6 rounded-full bg-[#10b981]" />
            Good
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-[#6b7280]">Samples received</span>
          <span className="font-['Inter:Semi_Bold'] font-semibold text-[#111827]">
            {samples}
          </span>
        </div>
      </div>
    </article>
  )
}

type SessionDetails = {
  sessionId: string
  participantName: string
  visit: string
}

type SessionOutcome = "Completed" | "Incomplete" | "Aborted"

type SessionRecord = SessionMetadata & {
  elapsed: number
  markers: Marker[]
  phaseTimes: number[]
  completedPhases: number
  currentPhase: number
  operatorNotes: string
  outcome: SessionOutcome
}

function DesktopCanvas({ children }: { children: React.ReactNode }) {
  const [viewport, setViewport] = useState(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }))

  useLayoutEffect(() => {
    const updateViewport = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight })

    updateViewport()
    window.addEventListener("resize", updateViewport)
    return () => window.removeEventListener("resize", updateViewport)
  }, [])

  const scale = Math.min(viewport.width / 1440, viewport.height / 900, 1)
  const left = Math.max(0, (viewport.width - 1440 * scale) / 2)
  const top = Math.max(0, (viewport.height - 900 * scale) / 2)

  return (
    <div className="relative h-dvh w-screen overflow-hidden bg-[#f0f2f5]">
      <div
        className="absolute h-[900px] w-[1440px] origin-top-left overflow-hidden"
        style={{ left, top, transform: `scale(${scale})` }}
      >
        {children}
      </div>
    </div>
  )
}

function SetupScreen({
  details,
  setDetails,
  notes,
  setNotes,
  onBegin,
}: {
  details: SessionDetails
  setDetails: (details: SessionDetails) => void
  notes: string
  setNotes: (notes: string) => void
  onBegin: () => void
}) {
  const fields = [
    ["Session ID", "sessionId"],
    ["Participant Name", "participantName"],
    ["Visit / Session", "visit"],
  ] as const
  const [missingFields, setMissingFields] = useState<keyof SessionDetails[]>([])
  const missingFieldLabels = fields
    .filter(([, key]) => missingFields.includes(key))
    .map(([label]) => label)
  const validationMessage =
    missingFieldLabels.length > 0
      ? `Please fill out: ${missingFieldLabels.join(", ")}.`
      : ""

  const beginSession = () => {
    const missing = fields
      .filter(([, key]) => !details[key].trim())
      .map(([, key]) => key)
    setMissingFields(missing)
    if (missing.length === 0) onBegin()
  }

  return (
    <main className="h-full bg-[#f9fafb] px-20 py-6">
      <header className="mx-auto flex max-w-[1040px] flex-col items-center gap-1.5 text-center">
        <h1 className="font-['Inter:Bold'] text-[28px] leading-normal font-bold text-[#111827]">
          Session Setup
        </h1>
        <p className="text-sm text-[#6b7280]">
          Prepare the Muse headset and verify channel connectivity before
          starting the experiment.
        </p>
      </header>

      <section className="mx-auto mt-4 flex max-w-[1040px] flex-col gap-3 rounded-2xl border border-[#e5e7eb] bg-white p-6 shadow-[0_4px_6px_rgba(0,0,0,0.05)]">
        <div className="grid grid-cols-3 gap-4">
          {fields.map(([label, key]) => (
            <label key={key} className="flex min-w-0 flex-col gap-2">
              <span className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#6b7280]">
                {label}
              </span>
              <input
                className={`meta-input ${
                  missingFields.includes(key)
                    ? "border-[#ef4444] ring-1 ring-[#fecaca]"
                    : ""
                }`}
                value={details[key]}
                onChange={(event) => {
                  setDetails({ ...details, [key]: event.target.value })
                  if (event.target.value.trim()) {
                    setMissingFields((current) =>
                      current.filter((field) => field !== key),
                    )
                  }
                }}
                aria-label={label}
                aria-invalid={missingFields.includes(key)}
                aria-describedby={
                  missingFields.includes(key)
                    ? "setup-validation-error"
                    : undefined
                }
              />
            </label>
          ))}
        </div>
        <div className="h-px bg-[#e5e7eb]" />
        <section className="flex flex-col items-start gap-3">
          <div className="flex w-full items-center justify-between gap-4">
            <h2 className="font-['Inter:Semi_Bold'] text-base font-semibold text-[#111827]">
              Headset Connection
            </h2>
            <div className="shrink-0 rounded-full bg-[#f3f4f6] px-2.5 py-1.5 font-['Inter:Semi_Bold'] text-xs font-semibold text-[#6b7280]">
              Simulated readings · Not live
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-[#ecfdf5] px-4 py-2">
            <img src="/assets/b215c.svg" alt="" width="8" height="8" />
            <span className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#065f46]">
              Connected to Muse
            </span>
          </div>
        </section>
        <div className="h-px bg-[#e5e7eb]" />
        <section className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1.5">
              <h2 className="font-['Inter:Semi_Bold'] text-base font-semibold text-[#111827]">
                Channel Status
              </h2>
              <p className="text-[13px] leading-6 text-[#6b7280]">
                Signal quality: Good, Fair, Poor, or No signal. Samples received
                = unique samples / expected samples ×100 over the last 10
                seconds.
              </p>
            </div>
            <div className="shrink-0 rounded-full bg-[#f3f4f6] px-2.5 py-1.5 font-['Inter:Semi_Bold'] text-xs font-semibold text-[#6b7280]">
              Simulated readings · Not live
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {channels.map((channel) => (
              <ChannelCard key={channel.name} {...channel} />
            ))}
          </div>
        </section>
        <div className="h-px bg-[#e5e7eb]" />
        <label className="flex flex-col gap-1.5">
          <span className="font-['Inter:Semi_Bold'] text-base font-semibold text-[#111827]">
            Setup Notes
          </span>
          <textarea
            className="form-textarea min-h-12"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Add setup notes, observations, or adjustments for this session..."
          />
        </label>
        <div className="flex flex-col items-start gap-3">
          <button
            type="button"
            className="primary-button"
            onClick={beginSession}
          >
            <img src="/assets/399bb.svg" alt="" width="16" height="16" />
            Begin Session
          </button>
          {validationMessage && (
            <p
              id="setup-validation-error"
              role="alert"
              className="text-xs font-medium text-[#dc2626]"
            >
              {validationMessage}
            </p>
          )}
        </div>
      </section>
    </main>
  )
}

function MarkerPanel({
  markers,
  onCorrect,
}: {
  markers: Marker[]
  onCorrect: (eventId: string) => void
}) {
  const correctedEventIds = new Set(
    markers
      .map((marker) => marker.corrects_event_id)
      .filter((eventId): eventId is string => Boolean(eventId)),
  )

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-hidden border-r border-[#e2e8f0] bg-white">
      <div className="flex items-center gap-2 border-b border-[#e2e8f0] px-4 py-4">
        <img src="/assets/20de1.svg" alt="" width="16" height="16" />
        <h2 className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#1e293b]">
          Markers
        </h2>
        <span className="rounded-full bg-[#2563eb] px-1.5 py-0.5 font-['Inter:Bold'] text-[10px] font-bold text-white">
          {markers.length}
        </span>
      </div>
      <div className="flex justify-between border-b border-[#e2e8f0] px-4 py-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
        <span>Label</span>
        <span>Timestamp</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          {markers.length === 0 && (
            <p className="border-b border-[#e2e8f0] px-4 py-6 text-center text-xs text-[#94a3b8]">
              No markers added
            </p>
          )}
          {markers.map((marker, index) => (
            <div
              key={marker.event_id}
              className={`flex min-h-10 items-center justify-between gap-2 border-b border-[#e2e8f0] px-4 py-2.5 text-xs ${
                index % 2 === 0 ? "bg-[#fafafa]" : ""
              }`}
            >
              <span className="flex min-w-0 items-center gap-1.5 text-[#334155]">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: marker.color }}
                />
                <span className="min-w-0">
                  <span className="line-clamp-2">{marker.label}</span>
                  <span
                    className={`mt-0.5 block text-[8px] font-semibold uppercase ${
                      marker.source === "protocol"
                        ? "text-[#16a34a]"
                        : "text-[#dc2626]"
                    }`}
                  >
                    {marker.event_type.replaceAll("_", " ")}
                  </span>
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1 font-['Inter:Medium'] text-[#64748b]">
                {formatMarkerTime(marker.elapsed_s)}
                {marker.source === "operator" &&
                  marker.event_type !== "marker_correction" &&
                  !correctedEventIds.has(marker.event_id) && (
                    <button
                      type="button"
                      className="text-[9px] font-semibold text-[#b91c1c] underline"
                      onClick={() => onCorrect(marker.event_id)}
                    >
                      Correct
                    </button>
                  )}
              </span>
            </div>
          ))}
        </div>
        <div className="shrink-0 space-y-1.5 border-t border-[#e2e8f0] bg-white p-4 text-[11px] text-[#64748b]">
          <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
            Color legend
          </h3>
          {markerTypes.map((type) => (
            <div key={type.name} className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: type.color }}
              />
              {type.name}
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}

function StatusStrip() {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#e2e8f0] bg-white px-3 py-2 text-[11px] text-[#64748b]">
      <div className="flex items-center gap-2 border-r border-[#e2e8f0] pr-3">
        <img src="/assets/eb16c.svg" alt="" width="18" height="18" />
        <div>
          <span className="block text-[9px] uppercase text-[#94a3b8]">
            Muse headset
          </span>
          <strong className="text-[#16a34a]">● Connected</strong>
        </div>
      </div>
      <span>
        Signal <strong className="text-[#1e293b]">Excellent</strong>
      </span>
      <span>
        Battery <strong className="text-[#16a34a]">78%</strong>
      </span>
      <span className="text-[10px] font-semibold uppercase text-[#94a3b8]">
        Channel contact
      </span>
      {["TP9 Good", "AF7 Fair", "AF8 Good", "TP10 Good"].map(
        (status, index) => (
          <span
            key={status}
            className={`flex items-center gap-1 ${
              index === 1 ? "text-[#d97706]" : "text-[#16a34a]"
            }`}
          >
            <img
              src={index === 1 ? "/assets/c024a.svg" : "/assets/03c33.svg"}
              alt=""
              width="8"
              height="8"
            />
            {status}
          </span>
        ),
      )}
      <span className="flex items-center gap-1 rounded border border-[#fde68a] bg-[#fef3c7] px-2 py-1 text-[#92400e]">
        <img src="/assets/6482e.svg" alt="" width="12" height="12" />
        AF7 contact reduced — check electrode
      </span>
      <span className="ml-auto shrink-0 rounded border border-[#cbd5e1] bg-[#f8fafc] px-2 py-1 text-[10px] font-semibold uppercase text-[#64748b]">
        Simulated data
      </span>
    </div>
  )
}

function TracesCard() {
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#e2e8f0] px-5 py-3">
        <img src="/assets/4a76e.svg" alt="" width="16" height="16" />
        <h2 className="font-['Inter:Semi_Bold'] text-sm font-semibold text-[#1e293b]">
          EEG Channel Traces
        </h2>
        <span className="rounded-md border border-[#7c3aed] bg-[#f5f3ff] px-2 py-1 text-[10px] font-semibold text-[#334155]">
          <img
            className="mr-1 inline-block"
            src="/assets/27f4c.svg"
            alt=""
            width="6"
            height="6"
          />
          Intentional eye activity, end, return to quiet begin
        </span>
        <div className="ml-auto flex gap-4 text-[11px] text-[#94a3b8]">
          <span>
            Scale: <b className="text-[#1e293b]">±150 µV</b>
          </span>
          <span>
            Sweep: <b className="text-[#1e293b]">10 s/div</b>
          </span>
          <span>
            Filter: <b className="text-[#1e293b]">1–40 Hz</b>
          </span>
          <span className="flex items-center gap-1 text-[#dc2626]">
            <img src="/assets/2ca2d.svg" alt="" width="6" height="6" />
            LIVE
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-x-auto">
        <div className="flex h-full min-w-[1040px] flex-col">
          {traces.map((trace) => (
            <div
              key={trace.name}
              className="relative min-h-0 flex-1 overflow-hidden border-b border-[#e2e8f0] bg-[#fafcff] last:border-0"
            >
              <div className="absolute inset-x-0 top-[55px] h-px bg-[#e2e8f0]" />
              <div className="absolute left-2 top-1 z-10">
                <strong
                  className="block text-[11px]"
                  style={{ color: trace.color }}
                >
                  {trace.name}
                </strong>
                <span className="text-[9px] text-[#94a3b8]">
                  {trace.position}
                </span>
              </div>
              <img src={trace.asset} alt="" width="1040" height="110" />
            </div>
          ))}
        </div>
      </div>
      <div className="flex h-7 items-center justify-around border-t border-[#e2e8f0] bg-[#f8fafc] text-[9px] text-[#94a3b8]">
        {[
          "00:00:00",
          "00:00:10",
          "00:00:20",
          "00:00:30",
          "00:00:40",
          "00:00:50",
        ].map((time) => (
          <span key={time}>{time}</span>
        ))}
        <span>t (s)</span>
      </div>
    </section>
  )
}

function RecordingControls({
  elapsed,
  protocolElapsed,
  isRunning,
  hasStarted,
  onPlay,
  onPause,
  onStop,
  onAbort,
}: {
  elapsed: number
  protocolElapsed: number
  isRunning: boolean
  hasStarted: boolean
  onPlay: () => void
  onPause: () => void
  onStop: () => void
  onAbort: () => void
}) {
  return (
    <section className="dashboard-card">
      <div className="flex flex-wrap items-center gap-4">
        <div>
          <h2 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
            Protocol Active
          </h2>
          <p className="font-['Inter:Bold'] text-[34px] font-bold text-[#1e293b]">
            {formatTime(protocolElapsed)}
          </p>
        </div>
        <div className="space-y-1 text-[11px] text-[#64748b]">
          <strong
            className={`flex items-center gap-1.5 ${
              isRunning ? "text-[#dc2626]" : "text-[#64748b]"
            }`}
          >
            <img src="/assets/4179f.svg" alt="" width="10" height="10" />
            {isRunning ? "RECORDING" : hasStarted ? "PAUSED" : "READY"}
          </strong>
          <p>
            Session clock:{" "}
            <b className="text-[#1e293b]">{formatTime(elapsed)}</b>
          </p>
          <p>
            Samples:{" "}
            <b className="text-[#1e293b]">
              {(
                protocolElapsed *
                syntheticSessionMetadata.nominal_sample_rate_hz
              ).toLocaleString()}
            </b>
          </p>
          <p>
            Nominal rate:{" "}
            <b className="text-[#1e293b]">
              {syntheticSessionMetadata.nominal_sample_rate_hz} Hz
            </b>
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="control-button bg-[#2563eb] text-white"
          onClick={onPlay}
          disabled={isRunning}
        >
          <img src="/assets/399bb.svg" alt="" width="16" height="16" />
          Play
        </button>
        <button
          type="button"
          className="control-button border border-[#e2e8f0] bg-[#f1f5f9] text-[#475569]"
          onClick={onPause}
          disabled={!isRunning}
        >
          <img src="/assets/a7a3c.svg" alt="" width="16" height="16" />
          Pause
        </button>
        <button
          type="button"
          className="control-button border border-[#fecdd3] bg-[#fff1f2] text-[#e11d48]"
          onClick={onStop}
        >
          <img src="/assets/ba401.svg" alt="" width="16" height="16" />
          Stop
        </button>
        <button
          type="button"
          className="control-button border border-[#fca5a5] bg-white text-[#dc2626]"
          onClick={onAbort}
        >
          <img src="/assets/99cb2.svg" alt="" width="16" height="16" />
          Abort Session
        </button>
      </div>
      <p className="font-['Inter:Italic'] text-[10px] italic text-[#94a3b8]">
        Timer and sample count are illustrative (simulated data)
      </p>
    </section>
  )
}

function PhaseControl({
  currentPhase,
  phaseTimes,
  hasStarted,
  onPrevious,
  onNext,
}: {
  currentPhase: number
  phaseTimes: number[]
  hasStarted: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  const phase = protocolPhases[currentPhase]

  return (
    <section className="dashboard-card">
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
            {formatPhaseTime(phaseTimes[currentPhase])}
          </b>
          <span className="ml-2 text-[#7c3aed]">
            Target: {phase.suggestedDuration.proposedParticipantProtocolSeconds}
            s
          </span>
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          className="phase-button border border-[#e2e8f0] bg-[#f8fafc] text-[#475569]"
          onClick={onPrevious}
          disabled={!hasStarted || currentPhase === 0}
        >
          <img src="/assets/5f9b6.svg" alt="" width="14" height="14" />
          Prev Phase
        </button>
        <button
          type="button"
          className="phase-button bg-[#7c3aed] text-white"
          onClick={onNext}
          disabled={!hasStarted || currentPhase === phases.length - 1}
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
          {phases.map((phase, index) => (
            <li
              key={`${index}-${phase}`}
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
              {index + 1} - {phase}
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function ObservationControls({
  hasStarted,
  onEvent,
  onCorrectLast,
  canCorrect,
}: {
  hasStarted: boolean
  onEvent: (kind: ObservationKind) => void
  onCorrectLast: () => void
  canCorrect: boolean
}) {
  return (
    <section className="dashboard-card">
      <div className="flex items-center gap-2">
        <img src="/assets/20de1.svg" alt="" width="16" height="16" />
        <h2 className="text-sm font-semibold text-[#1e293b]">
          Observed Events
        </h2>
      </div>
      <p className="text-[11px] leading-4 text-[#64748b]">
        Operator observations are yellow and remain distinct from protocol and
        recording-control markers.
      </p>
      <div className="grid grid-cols-2 gap-1.5">
        {observationActions.map((action) => (
          <button
            key={action.kind}
            type="button"
            className="flex min-h-9 items-center gap-2 rounded-md border border-[#fde047] bg-[#fefce8] px-2 text-left text-[10px] font-semibold leading-3 text-[#854d0e] disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => onEvent(action.kind)}
            disabled={!hasStarted}
          >
            <kbd className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#facc15] bg-white font-['Inter:Bold'] text-[10px]">
              {action.keyLabel}
            </kbd>
            {action.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="flex w-full items-center justify-center gap-2 rounded-md border border-[#e2e8f0] bg-[#f8fafc] py-2 text-[10px] font-semibold text-[#475569] disabled:cursor-not-allowed disabled:opacity-45"
        onClick={onCorrectLast}
        disabled={!hasStarted || !canCorrect}
      >
        <kbd className="rounded border border-[#cbd5e1] bg-white px-1.5 py-0.5 font-['Inter:Bold']">
          C
        </kbd>
        Mark last operator event as mistake
      </button>
      <p className="text-[9px] leading-3 text-[#94a3b8]">
        Keybinds work while recording or paused. Held keys and keystrokes inside
        text fields are ignored.
      </p>
    </section>
  )
}

function Dashboard({
  details,
  onFinish,
}: {
  details: SessionDetails
  onFinish: (record: SessionRecord) => void
}) {
  const [elapsed, setElapsed] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const [hasStarted, setHasStarted] = useState(false)
  const [currentPhase, setCurrentPhase] = useState(0)
  const [phaseTimes, setPhaseTimes] = useState(() => phases.map(() => 0))
  const [operatorNotes, setOperatorNotes] = useState("")
  const [markers, setMarkers] = useState<Marker[]>([])
  const hasFinished = useRef(false)
  const sessionStartedAt = useRef<number | null>(null)
  const protocolElapsed = phaseTimes.reduce((total, time) => total + time, 0)

  const getPreciseElapsedSeconds = () => {
    if (sessionStartedAt.current === null) return 0
    return Math.round((performance.now() - sessionStartedAt.current) / 10) / 100
  }

  useEffect(() => {
    if (!hasStarted) return
    const interval = window.setInterval(() => {
      setElapsed((value) => value + 1)
      if (isRunning) {
        setPhaseTimes((times) =>
          times.map((time, index) =>
            index === currentPhase ? time + 1 : time,
          ),
        )
      }
    }, 1000)
    return () => window.clearInterval(interval)
  }, [hasStarted, isRunning, currentPhase])

  const recordPhaseTransition = (phaseIndex: number) => {
    const phase = protocolPhases[phaseIndex]
    const isPrompt = phase.phaseId.includes("prompt")
    const markerType = isPrompt ? markerTypes[2] : markerTypes[1]
    setMarkers((currentMarkers) => [
      ...currentMarkers,
      {
        event_id: createEventId(),
        session_id: details.sessionId || "unspecified-session",
        elapsed_s: getPreciseElapsedSeconds(),
        event_type: isPrompt ? "prompt_shown" : "phase_started",
        label: `${phase.eventCode}: ${phase.displayName}`,
        source: "protocol",
        type: markerType.name,
        color: markerType.color,
        event_code: phase.eventCode,
      },
    ])
  }

  const addObservation = (kind: ObservationKind) => {
    if (!hasStarted) return
    const action = observationActions.find((item) => item.kind === kind)
    if (!action) return
    const isHeadsetAdjustment = kind === "headset-adjustment"
    const isOperatorNote = kind === "operator-note"
    const markerType = markerTypes[3]
    const noteLabel =
      isOperatorNote && operatorNotes.trim()
        ? `Operator note: ${operatorNotes.trim()}`
        : action.label

    setMarkers((currentMarkers) => [
      ...currentMarkers,
      {
        event_id: createEventId(),
        session_id: details.sessionId || "unspecified-session",
        elapsed_s: getPreciseElapsedSeconds(),
        event_type: isHeadsetAdjustment
          ? "headset_adjustment"
          : isOperatorNote
            ? "operator_note"
            : "observer_marker",
        label: noteLabel,
        source: "operator",
        type: markerType.name,
        color: markerType.color,
      },
    ])
  }

  const correctEvent = (eventId: string) => {
    const originalEvent = markers.find((marker) => marker.event_id === eventId)
    if (!originalEvent || originalEvent.source !== "operator") return
    if (markers.some((marker) => marker.corrects_event_id === eventId)) return

    setMarkers((currentMarkers) => [
      ...currentMarkers,
      {
        event_id: createEventId(),
        session_id: details.sessionId || "unspecified-session",
        elapsed_s: getPreciseElapsedSeconds(),
        event_type: "marker_correction",
        label: `Correction: accidental marker — ${originalEvent.label}`,
        source: "operator",
        type: "Observed event",
        color: "#64748b",
        corrects_event_id: originalEvent.event_id,
      },
    ])
  }

  const correctedEventIds = new Set(
    markers
      .map((marker) => marker.corrects_event_id)
      .filter((eventId): eventId is string => Boolean(eventId)),
  )
  const correctableEvents = markers.filter(
    (marker) =>
      marker.source === "operator" &&
      marker.event_type !== "marker_correction" &&
      marker.event_type !== "recording_paused" &&
      marker.event_type !== "recording_resumed" &&
      !correctedEventIds.has(marker.event_id),
  )
  const lastCorrectableEvent =
    correctableEvents[correctableEvents.length - 1] ?? null

  const recordRecordingControl = (
    eventType: "recording_paused" | "recording_resumed",
    label: string,
  ) => {
    const markerType = markerTypes[4]
    setMarkers((currentMarkers) => [
      ...currentMarkers,
      {
        event_id: createEventId(),
        session_id: details.sessionId || "unspecified-session",
        elapsed_s: getPreciseElapsedSeconds(),
        event_type: eventType,
        label,
        source: "operator",
        type: markerType.name,
        color: markerType.color,
      },
    ])
  }

  const play = () => {
    if (!hasStarted) {
      sessionStartedAt.current = performance.now()
      recordPhaseTransition(0)
    } else {
      recordRecordingControl("recording_resumed", "Recording resumed")
    }
    setHasStarted(true)
    setIsRunning(true)
  }

  const pause = () => {
    recordRecordingControl("recording_paused", "Recording paused")
    setIsRunning(false)
  }

  const transitionToPhase = (phaseIndex: number) => {
    if (phaseIndex === currentPhase) return
    setCurrentPhase(phaseIndex)
    recordPhaseTransition(phaseIndex)
  }

  const finishSession = (outcome: SessionOutcome) => {
    if (hasFinished.current) return
    hasFinished.current = true
    setIsRunning(false)
    const completedPhases =
      outcome === "Completed" ? phases.length : hasStarted ? currentPhase : 0
    onFinish({
      ...syntheticSessionMetadata,
      elapsed,
      markers,
      phaseTimes,
      completedPhases,
      currentPhase,
      operatorNotes,
      outcome,
    })
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || !hasStarted) return
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
      const action = observationActions.find((item) => item.key === key)
      if (action) {
        event.preventDefault()
        addObservation(action.kind)
      } else if (key === "c" && lastCorrectableEvent) {
        event.preventDefault()
        correctEvent(lastCorrectableEvent.event_id)
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [elapsed, hasStarted, lastCorrectableEvent, markers, operatorNotes])

  useEffect(() => {
    if (!isRunning || hasFinished.current) return
    const phaseDuration =
      protocolPhases[currentPhase].suggestedDuration
        .proposedParticipantProtocolSeconds
    if (phaseTimes[currentPhase] < phaseDuration) return

    if (currentPhase < phases.length - 1) {
      transitionToPhase(currentPhase + 1)
    } else {
      finishSession("Completed")
    }
  }, [currentPhase, isRunning, phaseTimes])

  return (
    <main className="h-full w-full overflow-hidden bg-[#f0f2f5] text-[#1e293b]">
      <header className="flex h-[50px] flex-nowrap items-center gap-x-6 border-b border-[#e2e8f0] bg-white px-6 text-xs">
        {[
          ["Session ID:", details.sessionId],
          ["Participant:", details.participantName],
          ["Visit / Session:", details.visit],
        ].map(([label, value]) => (
          <div key={label} className="flex gap-1.5">
            <span className="text-[#64748b]">{label}</span>
            <strong className="font-['Inter:Semi_Bold'] font-semibold text-[#1e293b]">
              {value}
            </strong>
          </div>
        ))}
        <span className="rounded bg-[#f1f5f9] px-2.5 py-1 font-['Inter:Italic'] text-[11px] italic text-[#94a3b8]">
          demonstration mode&nbsp;&nbsp;&nbsp;
        </span>
      </header>

      <div className="grid h-[850px] grid-cols-[260px_minmax(0,1fr)] overflow-hidden">
        <MarkerPanel markers={markers} onCorrect={correctEvent} />
        <div className="grid h-full min-w-0 grid-rows-[auto_minmax(0,1fr)_325px] gap-2.5 overflow-hidden p-3.5">
          <StatusStrip />
          <TracesCard />
          <div className="grid h-[325px] min-h-0 grid-cols-[480px_380px_minmax(0,1fr)] items-start gap-2.5 overflow-hidden">
            <div className="h-[325px] space-y-2.5 overflow-hidden">
              <RecordingControls
                elapsed={elapsed}
                protocolElapsed={protocolElapsed}
                isRunning={isRunning}
                hasStarted={hasStarted}
                onPlay={play}
                onPause={pause}
                onStop={() => finishSession("Incomplete")}
                onAbort={() => finishSession("Aborted")}
              />
              <section className="dashboard-card">
                <label className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                  Operator notes
                  <textarea
                    className="form-textarea mt-3 min-h-[72px] normal-case"
                    value={operatorNotes}
                    onChange={(event) => setOperatorNotes(event.target.value)}
                    placeholder="Add a short observation or setup note…"
                  />
                </label>
              </section>
            </div>
            <div className="h-[325px] [&>section]:h-full [&>section]:overflow-hidden">
              <PhaseControl
                currentPhase={currentPhase}
                phaseTimes={phaseTimes}
                hasStarted={hasStarted}
                onPrevious={() =>
                  transitionToPhase(Math.max(0, currentPhase - 1))
                }
                onNext={() =>
                  transitionToPhase(
                    Math.min(phases.length - 1, currentPhase + 1),
                  )
                }
              />
            </div>
            <div className="h-[325px] [&>section]:h-full [&>section]:overflow-hidden">
              <ObservationControls
                hasStarted={hasStarted}
                onEvent={addObservation}
                onCorrectLast={() => {
                  if (lastCorrectableEvent)
                    correctEvent(lastCorrectableEvent.event_id)
                }}
                canCorrect={Boolean(lastCorrectableEvent)}
              />
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

const reviewTraces = [
  {
    name: "TP9",
    position: "Left temporal",
    color: "#2563eb",
    asset: "/assets/2afb9.svg",
  },
  {
    name: "AF7",
    position: "Left prefrontal",
    color: "#d97706",
    asset: "/assets/3177a.svg",
  },
  {
    name: "AF8",
    position: "Right prefrontal",
    color: "#ea580c",
    asset: "/assets/c6462.svg",
  },
  {
    name: "TP10",
    position: "Right temporal",
    color: "#2563eb",
    asset: "/assets/e3a9c.svg",
  },
]

const phaseTimelineColors = [
  "#dbeafe",
  "#fef3c7",
  "#ede9fe",
  "#dcfce7",
  "#f1f5f9",
  "#ede9fe",
  "#f1f5f9",
  "#fff7ed",
  "#f1f5f9",
  "#f0fdf4",
]

function OutcomeBadge({ outcome }: { outcome: SessionOutcome }) {
  const styles = {
    Completed: "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]",
    Incomplete: "border-[#fde047] bg-[#fef9c3] text-[#92400e]",
    Aborted: "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]",
  }
  const dots = {
    Completed: "#16a34a",
    Incomplete: "#d97706",
    Aborted: "#dc2626",
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 font-['Inter:Bold'] text-xs font-bold ${styles[outcome]}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: dots[outcome] }}
      />
      {outcome}
    </span>
  )
}

function ReviewSidebar({ record }: { record: SessionRecord }) {
  const protocolElapsed = record.phaseTimes.reduce(
    (total, time) => total + time,
    0,
  )

  return (
    <aside className="flex h-full min-h-0 flex-col border-r border-[#e2e8f0] bg-white">
      <div className="flex items-center gap-2 border-b border-[#e2e8f0] px-4 py-3.5">
        <img src="/assets/20de1.svg" alt="" width="16" height="16" />
        <h2 className="text-sm font-semibold text-[#1e293b]">Markers</h2>
        <span className="rounded-full bg-[#2563eb] px-1.5 py-0.5 text-[10px] font-bold text-white">
          {record.markers.length}
        </span>
      </div>
      <div className="flex justify-between border-b border-[#e2e8f0] px-4 py-2 text-[10px] font-semibold uppercase text-[#94a3b8]">
        <span>Label</span>
        <span>Timestamp</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {record.markers.length === 0 ? (
          <p className="border-b border-[#e2e8f0] px-4 py-8 text-center text-xs text-[#94a3b8]">
            No markers recorded
          </p>
        ) : (
          record.markers.map((marker, index) => (
            <div
              key={marker.event_id}
              className={`flex min-h-10 items-center justify-between gap-2 border-b border-[#e2e8f0] px-4 py-2.5 text-xs ${
                index % 2 === 0 ? "bg-[#fafafa]" : ""
              }`}
            >
              <span className="flex min-w-0 items-center gap-1.5 text-[#334155]">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: marker.color }}
                />
                <span className="min-w-0">
                  <span className="line-clamp-2">{marker.label}</span>
                  <span
                    className={`block text-[8px] font-semibold uppercase ${
                      marker.source === "protocol"
                        ? "text-[#16a34a]"
                        : "text-[#dc2626]"
                    }`}
                  >
                    {marker.event_type.replaceAll("_", " ")}
                  </span>
                </span>
              </span>
              <span className="shrink-0 font-['Inter:Medium'] text-[#64748b]">
                  {formatMarkerTime(marker.elapsed_s)}
              </span>
            </div>
          ))
        )}
      </div>
      <div className="shrink-0 space-y-1.5 border-t border-[#e2e8f0] p-4 text-[11px] text-[#64748b]">
        <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
          Color legend
        </h3>
        {markerTypes.map((type) => (
          <div key={type.name} className="flex items-center gap-1.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: type.color }}
            />
            {type.name}
          </div>
        ))}
      </div>
      <div className="shrink-0 space-y-1.5 border-t border-[#e2e8f0] bg-[#f8fafc] p-4 text-[11px]">
        <h3 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
          Session summary
        </h3>
        <p className="text-[#64748b]">
          Total Duration:{" "}
          <b className="text-[#1e293b]">{formatTime(record.elapsed)}</b>
        </p>
        <p className="text-[#64748b]">
          Total Markers:{" "}
          <b className="text-[#1e293b]">{record.markers.length}</b>
        </p>
        <p className="text-[#64748b]">
          Protocol Active:{" "}
          <b className="text-[#1e293b]">{formatTime(protocolElapsed)}</b>
        </p>
        <p className="text-[#64748b]">
          Samples:{" "}
          <b className="text-[#1e293b]">
            {(protocolElapsed * record.nominal_sample_rate_hz).toLocaleString()}
          </b>
        </p>
        <p className="text-[#64748b]">
          Phases:{" "}
          <b className="text-[#1e293b]">
            {record.completedPhases} of {phases.length}
          </b>
        </p>
        <div className="flex items-center gap-1.5 text-[#64748b]">
          Outcome: <OutcomeBadge outcome={record.outcome} />
        </div>
      </div>
    </aside>
  )
}

function ReviewTraces() {
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white">
      <div className="flex h-[45px] shrink-0 items-center gap-3 border-b border-[#e2e8f0] px-5">
        <img src="/assets/4a76e.svg" alt="" width="16" height="16" />
        <h2 className="text-sm font-semibold text-[#1e293b]">
          EEG Channel Traces
        </h2>
        <span className="rounded bg-[#f1f5f9] px-2 py-1 text-[11px] text-[#64748b]">
          At-recording signal
        </span>
        <div className="ml-auto flex gap-4 text-[11px] text-[#94a3b8]">
          <span>
            Scale: <b className="text-[#1e293b]">±150 µV</b>
          </span>
          <span>
            Sweep: <b className="text-[#1e293b]">10 s/div</b>
          </span>
          <span>
            Filter: <b className="text-[#1e293b]">1–40 Hz</b>
          </span>
          <span className="rounded bg-[#f1f5f9] px-2 py-0.5 font-semibold text-[#475569]">
            ● PAUSED
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {reviewTraces.map((trace) => (
          <div
            key={trace.name}
            className="relative h-1/4 overflow-hidden border-b border-[#e2e8f0] bg-[#fafcff] last:border-0"
          >
            <div className="absolute left-3 top-1 z-10">
              <strong
                className="block text-[11px]"
                style={{ color: trace.color }}
              >
                {trace.name}
              </strong>
              <span className="text-[9px] text-[#94a3b8]">
                {trace.position}
              </span>
            </div>
            <img
              className="absolute left-12 top-0 h-full w-[calc(100%-48px)]"
              src={trace.asset}
              alt=""
            />
          </div>
        ))}
      </div>
      <div className="flex h-5 shrink-0 items-center justify-around border-t border-[#e2e8f0] bg-[#f8fafc] text-[9px] text-[#94a3b8]">
        {[
          "00:00:00",
          "00:00:10",
          "00:00:20",
          "00:00:30",
          "00:00:40",
          "00:00:50",
        ].map((time) => (
          <span key={time}>{time}</span>
        ))}
        <span>t (s)</span>
      </div>
    </section>
  )
}

function SessionOverview({ record }: { record: SessionRecord }) {
  const total = Math.max(record.elapsed, 1)
  return (
    <section className="rounded-[10px] border border-[#e2e8f0] bg-white px-4 py-2.5">
      <div className="mb-2 flex items-center gap-2">
        <img src="/assets/62339.svg" alt="" width="14" height="14" />
        <h2 className="text-xs font-semibold text-[#1e293b]">
          Full Session Overview
        </h2>
        <span className="text-[11px] text-[#94a3b8]">
          Total: {formatTime(record.elapsed)}
        </span>
        <span className="ml-auto text-[11px] text-[#64748b]">
          Zoom:{" "}
          <b className="rounded border border-[#bfdbfe] bg-[#eff6ff] px-2 py-1 text-[#2563eb]">
            2×
          </b>
        </span>
      </div>
      <div className="relative flex h-9 overflow-hidden rounded-md border border-[#e2e8f0] bg-[#f8fafc]">
        {record.phaseTimes.map((time, index) => (
          <div
            key={phases[index]}
            className="h-full min-w-[2px] opacity-70"
            style={{
              width: `${Math.max((time / total) * 100, index < record.completedPhases ? 2 : 0)}%`,
              backgroundColor: phaseTimelineColors[index],
            }}
          />
        ))}
        {record.markers.map((marker) => (
          <span
            key={marker.event_id}
            className="absolute inset-y-0 w-px opacity-70"
            style={{
              left: `${(marker.elapsed_s / total) * 100}%`,
              backgroundColor: marker.color,
            }}
          />
        ))}
      </div>
      <div className="mt-1 flex gap-1 text-[8px]">
        {[
          "1-Intro",
          "2-Setup",
          "3-Baseline",
          "4-Eye activity",
          "5-Quiet",
          "6-Facial muscle",
          "7-Quiet",
          "8-Head movement",
          "9-Quiet",
          "10-Ending",
        ].map((label, index) => (
          <span
            key={label}
            className="rounded px-1 py-0.5 text-[#475569]"
            style={{ backgroundColor: phaseTimelineColors[index] }}
          >
            {label}
          </span>
        ))}
      </div>
    </section>
  )
}

function ReviewScreen({
  details,
  setupNotes,
  record,
  onStartAnotherSession,
}: {
  details: SessionDetails
  setupNotes: string
  record: SessionRecord
  onStartAnotherSession: () => void
}) {
  const [playbackPosition, setPlaybackPosition] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const outcomeStyles =
    record.outcome === "Completed"
      ? "border-[#bbf7d0] bg-[#f0fdf4] text-[#15803d]"
      : record.outcome === "Incomplete"
        ? "border-[#fde047] bg-[#fef9c3] text-[#92400e]"
        : "border-[#fecaca] bg-[#fef2f2] text-[#b91c1c]"
  const noteText = [
    setupNotes && `Setup: ${setupNotes}`,
    record.operatorNotes && `Recording: ${record.operatorNotes}`,
  ]
    .filter(Boolean)
    .join("\n")
  const playbackProgress =
    record.elapsed === 0 ? 0 : (playbackPosition / record.elapsed) * 100
  const protocolElapsed = record.phaseTimes.reduce(
    (total, time) => total + time,
    0,
  )

  useEffect(() => {
    if (!isPlaying || record.elapsed === 0) return
    const interval = window.setInterval(() => {
      setPlaybackPosition((position) => {
        if (position >= record.elapsed - 1) {
          setIsPlaying(false)
          return record.elapsed
        }
        return position + 1
      })
    }, 1000)
    return () => window.clearInterval(interval)
  }, [isPlaying, record.elapsed])

  const seek = (amount: number) => {
    setPlaybackPosition((position) =>
      Math.min(record.elapsed, Math.max(0, position + amount)),
    )
  }

  const exportMarkers = () => {
    const exportedMarkers = record.markers.map(
      ({ event_id, session_id, elapsed_s, event_type, label, source }) => ({
        event_id,
        session_id,
        elapsed_s,
        event_type,
        label,
        source,
      }),
    )
    const fileContents = JSON.stringify(exportedMarkers, null, 2)
    const file = new Blob([fileContents], { type: "application/json" })
    const downloadUrl = URL.createObjectURL(file)
    const sessionId =
      details.sessionId
        .trim()
        .replace(/[^a-z0-9_-]+/gi, "-")
        .replace(/^-+|-+$/g, "") || "session"
    const downloadLink = document.createElement("a")

    downloadLink.href = downloadUrl
    downloadLink.download = `${sessionId}-markers.json`
    document.body.appendChild(downloadLink)
    downloadLink.click()
    downloadLink.remove()
    URL.revokeObjectURL(downloadUrl)
  }

  return (
    <main className="h-full w-full overflow-hidden bg-[#f0f2f5] text-[#1e293b]">
      <header className="flex h-14 items-center justify-between border-b border-[#e2e8f0] bg-white px-6 text-xs">
        <div className="flex items-center gap-6">
          {[
            ["Participant:", details.participantName],
            ["Session ID:", details.sessionId],
            ["Visit:", details.visit],
          ].map(([label, value]) => (
            <div key={label} className="flex gap-1.5">
              <span className="text-[#64748b]">{label}</span>
              <b>{value}</b>
            </div>
          ))}
          <OutcomeBadge outcome={record.outcome} />
          <span className="rounded bg-[#f1f5f9] px-2.5 py-1 font-['Inter:Italic'] text-[11px] italic text-[#94a3b8]">
            simulated data
          </span>
        </div>
        <div className="flex gap-2">
          <span className="flex items-center gap-1.5 rounded border border-[#bfdbfe] bg-[#eff6ff] px-2.5 py-1 font-bold text-[#1d4ed8]">
            <img src="/assets/d9fac.svg" alt="" width="14" height="14" /> REVIEW
            MODE
          </span>
          <span className="rounded border border-[#fde047] bg-[#fef9c3] px-2.5 py-1 text-[11px] font-semibold text-[#92400e]">
            At-recording data only — not live
          </span>
        </div>
      </header>
      <div className="grid h-[844px] grid-cols-[260px_minmax(0,1fr)]">
        <ReviewSidebar record={record} />
        <div className="grid min-w-0 grid-rows-[36px_292px_93px_minmax(0,1fr)] gap-2.5 overflow-hidden p-3.5">
          <div className="flex items-center gap-3 text-[11px]">
            <div className="flex h-full items-center gap-3 rounded-lg border border-[#e2e8f0] bg-white px-3">
              <b className="text-[10px] uppercase text-[#94a3b8]">
                At recording
              </b>
              <span>Muse Headset</span>
              <span className="text-[#64748b]">
                Signal <b className="text-[#1e293b]">Excellent</b>
              </span>
              <span className="text-[#64748b]">
                Battery <b className="text-[#16a34a]">78%</b>
              </span>
            </div>
            <div
              className={`flex h-full items-center rounded-lg border px-3 font-bold ${outcomeStyles}`}
            >
              Session outcome&nbsp;·&nbsp;{record.outcome}
            </div>
            <span className="rounded bg-[#f1f5f9] px-2 py-1 italic text-[#94a3b8]">
              contact ≠ artifact-free signal
            </span>
            <span className="shrink-0 rounded border border-[#cbd5e1] bg-[#f8fafc] px-2 py-1 text-[10px] font-semibold uppercase text-[#64748b]">
              Simulated data
            </span>
          </div>
          <ReviewTraces />
          <SessionOverview record={record} />
          <div className="grid min-h-0 grid-cols-[480px_380px_minmax(0,1fr)] gap-2.5">
            <div className="grid min-h-0 grid-rows-[132px_minmax(0,1fr)] gap-2.5">
              <section className="rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
                <div className="flex items-center gap-5">
                  <div>
                    <h2 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                      Playback Position
                    </h2>
                    <p className="text-[30px] font-bold leading-tight">
                      {formatTime(playbackPosition)}{" "}
                      <span className="text-sm font-normal text-[#94a3b8]">
                        / {formatTime(record.elapsed)}
                      </span>
                    </p>
                  </div>
                  <div className="text-[11px] text-[#64748b]">
                    <b className="text-[#475569]">
                      ● {isPlaying ? "PLAYING" : "PAUSED"}
                    </b>
                    <p>
                      Session duration:{" "}
                      <b className="text-[#1e293b]">
                        {formatTime(record.elapsed)}
                      </b>
                    </p>
                    <p>
                      Total samples:{" "}
                      <b className="text-[#1e293b]">
                        {(
                          protocolElapsed * record.nominal_sample_rate_hz
                        ).toLocaleString()}
                      </b>
                    </p>
                  </div>
                </div>
                <div className="mt-1.5 h-1.5 rounded bg-[#e2e8f0]">
                  <div
                    className="h-full rounded bg-[#2563eb]"
                    style={{ width: `${playbackProgress}%` }}
                  />
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                  <button
                    type="button"
                    className="review-control-button"
                    onClick={() => seek(-10)}
                    aria-label="Skip backward 10 seconds"
                    title="Skip backward 10 seconds"
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
                    onClick={() => setIsPlaying(true)}
                    disabled={isPlaying || playbackPosition >= record.elapsed}
                  >
                    <img
                      src="/assets/399bb.svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    Play
                  </button>
                  <button
                    type="button"
                    className="review-control-button"
                    onClick={() => setIsPlaying(false)}
                    disabled={!isPlaying}
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
                    onClick={() => seek(10)}
                    aria-label="Skip forward 10 seconds"
                    title="Skip forward 10 seconds"
                  >
                    <img
                      src="/assets/6671c.svg"
                      alt=""
                      width="14"
                      height="14"
                    />
                    10s
                  </button>
                  <p className="ml-auto text-[9px] italic text-[#94a3b8]">
                    Simulated playback
                  </p>
                </div>
              </section>
              <section className="min-h-0 rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
                <div className="mb-2 flex justify-between">
                  <h2 className="text-[10px] font-semibold uppercase text-[#94a3b8]">
                    Operator notes
                  </h2>
                  <span className="rounded border border-[#bbf7d0] bg-[#f0fdf4] px-2 py-0.5 text-[10px] font-semibold text-[#15803d]">
                    Saved
                  </span>
                </div>
                <div className="h-[76px] whitespace-pre-line overflow-y-auto rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-3 text-[12px] leading-4 text-[#334155]">
                  {noteText || "No notes were recorded for this session."}
                </div>
              </section>
            </div>
            <section className="min-h-0 overflow-hidden rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
              <div className="mb-2 flex items-center gap-2">
                <img src="/assets/4e3e5.svg" alt="" width="16" height="16" />
                <h2 className="text-sm font-semibold">Experiment Phases</h2>
                <span className="rounded border border-[#bbf7d0] bg-[#f0fdf4] px-1.5 py-0.5 text-[10px] font-bold text-[#15803d]">
                  {record.completedPhases} completed
                </span>
              </div>
              <div className="mb-2 rounded-lg border border-[#ddd6fe] bg-[#f5f3ff] px-3.5 py-2">
                <span className="rounded bg-[#7c3aed] px-1.5 py-0.5 text-[10px] font-bold text-white">
                  Final phase
                </span>
                <p className="mt-1 text-sm font-bold text-[#4c1d95]">
                  {phases[record.currentPhase]}
                </p>
                <p className="text-[11px] text-[#6d28d9]">
                  Accumulated:{" "}
                  <b>
                    {formatPhaseTime(record.phaseTimes[record.currentPhase])}
                  </b>
                </p>
              </div>
              <h3 className="mb-1 text-[10px] font-semibold uppercase text-[#94a3b8]">
                All phases
              </h3>
              <ol className="space-y-0.5">
                {phases.map((phase, index) => (
                  <li
                    key={`${index}-${phase}`}
                    className={`flex items-center gap-1 text-[10px] leading-3 ${
                      index < record.completedPhases
                        ? "text-[#64748b]"
                        : "text-[#94a3b8]"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        index < record.completedPhases
                          ? "bg-[#16a34a]"
                          : "bg-[#cbd5e1]"
                      }`}
                    />
                    {index + 1} - {phase}{" "}
                    <span className="ml-auto">
                      {formatPhaseTime(record.phaseTimes[index])}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
            <section className="min-h-0 rounded-[10px] border border-[#e2e8f0] bg-white px-5 py-3">
              <div className="mb-3 flex items-center gap-2">
                <img src="/assets/39800.svg" alt="" width="16" height="16" />
                <h2 className="text-sm font-semibold">Session Record</h2>
              </div>
              <div className={`rounded-lg border p-3 ${outcomeStyles}`}>
                <p className="text-[10px] font-semibold uppercase">
                  Session outcome
                </p>
                <p className="text-lg font-bold">{record.outcome}</p>
                <p className="mt-1 text-[11px]">
                  {record.completedPhases} of {phases.length} phases recorded.
                </p>
              </div>
              <button
                type="button"
                className="mt-3 w-full rounded-lg border border-[#bfdbfe] bg-[#eff6ff] px-3 py-2 text-[12px] font-semibold text-[#1d4ed8] hover:bg-[#dbeafe]"
                onClick={exportMarkers}
              >
                Export Marker JSON
              </button>
              <button
                type="button"
                className="mt-2 w-full rounded-lg bg-[#2563eb] px-3 py-2.5 text-[12px] font-semibold text-white hover:bg-[#1d4ed8]"
                onClick={onStartAnotherSession}
              >
                Start Another Session
              </button>
              <p className="mt-2 text-[10px] italic text-[#94a3b8]">
                Simulated data — not for clinical use
              </p>
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}

function App() {
  const [screen, setScreen] = useState<"setup" | "dashboard" | "review">(
    "setup",
  )
  const [details, setDetails] = useState<SessionDetails>({
    sessionId: "",
    participantName: "",
    visit: "",
  })
  const [setupNotes, setSetupNotes] = useState("")
  const [record, setRecord] = useState<SessionRecord | null>(null)

  return (
    <DesktopCanvas>
      {screen === "setup" ? (
        <SetupScreen
          details={details}
          setDetails={setDetails}
          notes={setupNotes}
          setNotes={setSetupNotes}
          onBegin={() => setScreen("dashboard")}
        />
      ) : screen === "dashboard" ? (
        <Dashboard
          details={details}
          onFinish={(finalRecord) => {
            setRecord(finalRecord)
            setScreen("review")
          }}
        />
      ) : record ? (
        <ReviewScreen
          details={details}
          setupNotes={setupNotes}
          record={record}
          onStartAnotherSession={() => {
            setDetails({
              sessionId: "",
              participantName: "",
              visit: "",
            })
            setSetupNotes("")
            setRecord(null)
            setScreen("setup")
          }}
        />
      ) : null}
    </DesktopCanvas>
  )
}

export default App