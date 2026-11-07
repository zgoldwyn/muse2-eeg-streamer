// Pure helpers for live mode, kept free of React and fetch so tests can run them

// with plain Node (frontend/tests/live-logic-test.mjs).

export type PilotPrompt = {
  key: string

  kind: "ready" | "now"

  at_s: number

  text: string

  event_code: string
}

type CueLike = {
  index: number
  text: string
  start_s: number
  get_ready: string | null
}

interface PhaseCueLike {
  index: number
  start_s: number
}

/** Resolve the protocol phase scheduled by the latest pilot cue start time. */

export function pilotPhaseAtTime(
  cues: PhaseCueLike[],

  eegElapsedS: number,

  phaseCount: number,
): number {
  if (phaseCount <= 0) return 0

  const activeCue = cues.reduce<PhaseCueLike | null>(
    (latest, cue) =>
      cue.start_s <= eegElapsedS && (!latest || cue.start_s >= latest.start_s)
        ? cue
        : latest,

    null,
  )

  return Math.max(0, Math.min(phaseCount - 1, activeCue?.index ?? 0))
}

/** Every "Get ready…" and "NOW" prompt in the pilot sequence, in time order. */

export function pilotPrompts(
  cues: CueLike[],
  readyLeadS: number,
): PilotPrompt[] {
  const prompts: PilotPrompt[] = []

  for (const cue of cues) {
    if (cue.get_ready) {
      prompts.push({
        key: `ready-${cue.index}`,

        kind: "ready",

        at_s: Math.max(0, cue.start_s - readyLeadS),

        text: `Get ready to ${cue.get_ready}`,

        event_code: `PILOT_READY_${cue.index}`,
      })
    }

    prompts.push({
      key: `now-${cue.index}`,

      kind: "now",

      at_s: cue.start_s,

      text: `NOW: ${cue.text}`,

      event_code: `PILOT_CUE_${cue.index}`,
    })
  }

  return prompts.sort((a, b) => a.at_s - b.at_s)
}

/** Prompts whose time has come on the EEG clock and that have not been shown yet. */

export function duePrompts(
  prompts: PilotPrompt[],
  eegElapsedS: number,
  shown: ReadonlySet<string>,
): PilotPrompt[] {
  return prompts.filter(
    (prompt) => prompt.at_s <= eegElapsedS && !shown.has(prompt.key),
  )
}

export interface Trace {
  elapsed_s: number[]
  microvolts: number[]
}

interface GapLike {
  channel: string
  start_s: number
  end_s: number
}

/** Append new points to a rolling trace and drop points older than windowS before the newest. */

export function appendRolling(
  trace: Trace,
  added: Trace,
  windowS: number,
): Trace {
  const elapsed = trace.elapsed_s.concat(added.elapsed_s)

  const microvolts = trace.microvolts.concat(added.microvolts)

  const newest = elapsed.length ? elapsed[elapsed.length - 1] : 0

  let first = 0

  while (first < elapsed.length && elapsed[first] < newest - windowS) first++

  return {
    elapsed_s: elapsed.slice(first),
    microvolts: microvolts.slice(first),
  }
}

/**
 * Split a trace into line segments that never cross a reported gap, or any jump
 * in time longer than 1.5 display steps (so a missed gap report is still a break).
 */

export function traceSegments(
  trace: Trace,
  gaps: GapLike[],
  channel: string,
  stepS: number,
): Trace[] {
  const channelGaps = gaps.filter((gap) => gap.channel === channel)

  const segments: Trace[] = []

  let current: Trace = { elapsed_s: [], microvolts: [] }

  for (let i = 0; i < trace.elapsed_s.length; i++) {
    const t = trace.elapsed_s[i]

    if (current.elapsed_s.length) {
      const previous = current.elapsed_s[current.elapsed_s.length - 1]

      const crossesGap = channelGaps.some(
        (gap) =>
          previous < gap.end_s && t >= gap.end_s && previous <= gap.start_s,
      )

      if (crossesGap || t - previous > stepS * 1.5) {
        segments.push(current)

        current = { elapsed_s: [], microvolts: [] }
      }
    }

    current.elapsed_s.push(t)

    current.microvolts.push(trace.microvolts[i])
  }

  if (current.elapsed_s.length) segments.push(current)

  return segments
}

export function formatClock(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "--:--:--"

  const whole = Math.max(0, Math.floor(seconds))

  const h = Math.floor(whole / 3600)

  const m = Math.floor((whole % 3600) / 60)

  const s = whole % 60

  return [h, m, s].map((value) => value.toString().padStart(2, "0")).join(":")
}

export function formatMarkerTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "--:--.--"

  const totalCentiseconds = Math.round(Math.max(0, seconds) * 100)
  const totalMinutes = Math.floor(totalCentiseconds / 6000)
  const remainingCentiseconds = totalCentiseconds % 6000
  const wholeSeconds = Math.floor(remainingCentiseconds / 100)
  const centiseconds = remainingCentiseconds % 100

  return `${totalMinutes.toString().padStart(2, "0")}:${wholeSeconds
    .toString()
    .padStart(2, "0")}.${centiseconds.toString().padStart(2, "0")}`
}
