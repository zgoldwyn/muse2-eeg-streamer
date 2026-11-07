import assert from "node:assert/strict"

import test from "node:test"

import {
  appendRolling,
  duePrompts,
  formatClock,
  formatMarkerTime,
  pilotPhaseAtTime,
  pilotPrompts,
  traceSegments,
} from "../src/live/logic.ts"

// Shaped like GET /api/pilot-sequence in docs/dashboard-api.md.

const sequence = {
  get_ready_lead_s: 3,

  cues: [
    { index: 0, text: "Rest quietly", start_s: 0, get_ready: null },

    {
      index: 1,
      text: "Blink softly twice, then firmly once",
      start_s: 10,
      get_ready: "blink",
    },

    { index: 2, text: "Rest quietly", start_s: 20, get_ready: null },
  ],
}

test("pilot prompts include get-ready cues before their action", () => {
  const prompts = pilotPrompts(sequence.cues, sequence.get_ready_lead_s)

  assert.equal(
    prompts.filter((prompt) => prompt.kind === "now").length,

    sequence.cues.length,
  )

  const ready = prompts.find((prompt) => prompt.key === "ready-1")

  assert.equal(ready.text, "Get ready to blink")

  assert.equal(ready.at_s, 10 - sequence.get_ready_lead_s)

  assert.equal(ready.event_code, "PILOT_READY_1")

  for (let i = 1; i < prompts.length; i++) {
    assert.ok(prompts[i - 1].at_s <= prompts[i].at_s)
  }
})

test("due prompts fire once each on the EEG clock", () => {
  const prompts = pilotPrompts(
    [
      { index: 0, text: "Rest quietly", start_s: 0, get_ready: null },

      { index: 1, text: "Blink", start_s: 10, get_ready: "blink" },
    ],

    3,
  )

  const shown = new Set()

  assert.deepEqual(
    duePrompts(prompts, 0.1, shown).map((prompt) => prompt.key),

    ["now-0"],
  )

  shown.add("now-0")

  assert.deepEqual(duePrompts(prompts, 6.9, shown), [])

  assert.deepEqual(
    duePrompts(prompts, 7, shown).map((prompt) => prompt.key),

    ["ready-1"],
  )
})

test("automatic phases follow pilot cue start times", () => {
  const cues = [
    { index: 0, start_s: 0 },

    { index: 1, start_s: 10 },

    { index: 2, start_s: 25 },
  ]

  assert.equal(pilotPhaseAtTime(cues, 9.99, 3), 0)

  assert.equal(pilotPhaseAtTime(cues, 10, 3), 1)

  assert.equal(pilotPhaseAtTime(cues, 24.99, 3), 1)

  assert.equal(pilotPhaseAtTime(cues, 25, 3), 2)
})

test("the rolling window keeps only recent points", () => {
  const trace = appendRolling(
    { elapsed_s: [0, 1, 2], microvolts: [1, 2, 3] },

    { elapsed_s: [11, 12], microvolts: [4, 5] },

    10,
  )

  assert.deepEqual(trace.elapsed_s, [2, 11, 12])

  assert.deepEqual(trace.microvolts, [3, 4, 5])
})

test("trace lines break at reported gaps and never bridge them", () => {
  // One missing AF7 packet (12 samples) at 9.375 s, displayed every 4th sample.

  const step = 4 / 256

  const times = []

  for (let n = 2368; n < 2432; n += 4) times.push(n / 256)

  const af7Times = times.filter((t) => t < 9.375 || t >= 9.421875)

  const live = {
    channels: {
      TP9: { elapsed_s: times, microvolts: times.map(() => 0) },

      AF7: { elapsed_s: af7Times, microvolts: af7Times.map(() => 0) },
    },

    gaps: [{ channel: "AF7", start_s: 9.375, end_s: 9.421875 }],
  }

  const af7 = traceSegments(live.channels.AF7, live.gaps, "AF7", step)

  assert.equal(af7.length, 2)

  const gap = live.gaps.find((item) => item.channel === "AF7")

  assert.ok(af7[0].elapsed_s.at(-1) < gap.start_s)

  assert.ok(af7[1].elapsed_s[0] >= gap.end_s)

  const tp9 = traceSegments(live.channels.TP9, live.gaps, "TP9", step)

  assert.equal(tp9.length, 1)
})

test("clock formatting", () => {
  assert.equal(formatClock(3725.4), "01:02:05")
  assert.equal(formatClock(null), "--:--:--")
})

test("marker timestamps show hundredths without an hours field", () => {
  assert.equal(formatMarkerTime(0), "00:00.00")
  assert.equal(formatMarkerTime(12.345), "00:12.35")
  assert.equal(formatMarkerTime(59.999), "01:00.00")
  assert.equal(formatMarkerTime(3725.4), "62:05.40")
})
