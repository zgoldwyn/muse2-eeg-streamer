import { useEffect, useRef } from "react"

import {
  CHANNEL_NAMES,
  type ChannelName,
  type Gap,
  type Reduction,
} from "./api"

import { traceSegments, type Trace } from "./logic"

export const Y_RANGES_UV = [150, 175, 200, 225, 250] as const

/**
 * Four real EEG channels on a rolling window: time (s) on x, fixed microvolt
 * scale on y. Values outside the scale are clipped at the edge and flagged.
 */

export default function LiveTraces({
  traces,

  gaps,

  reduction,

  windowS,

  startS,

  cursorS,

  yRangeUv,

  onYRangeChange,

  waiting,

  viewLabel = "Live EEG",

  heading = "Real channels from the recorder",
}: {
  traces: Record<ChannelName, Trace>

  gaps: Gap[]

  reduction: Reduction | null

  windowS: number

  startS?: number

  cursorS?: number

  yRangeUv: number

  onYRangeChange: (value: number) => void

  waiting: boolean

  viewLabel?: string

  heading?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current

    if (!canvas) return

    const context = canvas.getContext("2d")

    if (!context) return

    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect()
      if (width === 0 || height === 0) return

      const pixelRatio = window.devicePixelRatio || 1
      const pixelWidth = Math.round(width * pixelRatio)
      const pixelHeight = Math.round(height * pixelRatio)
      if (canvas.width !== pixelWidth) canvas.width = pixelWidth
      if (canvas.height !== pixelHeight) canvas.height = pixelHeight
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)

      const left = 92
      const right = 12
      const top = 8
      const bottom = 26
      const rowHeight = (height - top - bottom) / CHANNEL_NAMES.length
      const plotWidth = width - left - right
      const newest = Math.max(
        0,
        ...CHANNEL_NAMES.map(
          (name) =>
            traces[name].elapsed_s[traces[name].elapsed_s.length - 1] ?? 0,
        ),
      )
      const start = startS ?? Math.max(0, newest - windowS)
      const end = start + windowS
      const x = (t: number) => left + ((t - start) / windowS) * plotWidth
      const stepS = (reduction?.factor ?? 4) / 256

      context.clearRect(0, 0, width, height)
      context.fillStyle = "#ffffff"
      context.fillRect(0, 0, width, height)
      context.font = "11px Arial, sans-serif"

      CHANNEL_NAMES.forEach((name, row) => {
        const rowTop = top + row * rowHeight
        const mid = rowTop + rowHeight / 2
        const half = rowHeight / 2 - 6
        const y = (uv: number) =>
          mid - (Math.max(-yRangeUv, Math.min(yRangeUv, uv)) / yRangeUv) * half

        context.strokeStyle = "#e2e8f0"
        context.lineWidth = 1
        for (const value of [-yRangeUv, 0, yRangeUv]) {
          context.beginPath()
          context.moveTo(left, y(value))
          context.lineTo(width - right, y(value))
          context.stroke()
        }

        context.fillStyle = "#64748b"
        context.textAlign = "right"
        context.fillText(`+${yRangeUv}`, left - 6, y(yRangeUv) + 4)
        context.fillText("0", left - 6, y(0) + 4)
        context.fillText(`−${yRangeUv}`, left - 6, y(-yRangeUv) + 4)

        context.textAlign = "left"
        context.fillStyle = "#1e293b"
        context.font = "bold 12px Arial, sans-serif"
        context.fillText(name, 6, mid + 4)
        context.font = "11px Arial, sans-serif"

        context.fillStyle = "rgba(220, 38, 38, 0.12)"
        for (const gap of gaps) {
          if (gap.channel !== name || gap.end_s < start) continue
          const gapLeft = Math.max(left, x(gap.start_s))
          context.fillRect(
            gapLeft,
            rowTop + 2,
            Math.max(2, x(gap.end_s) - gapLeft),
            rowHeight - 4,
          )
        }

        context.strokeStyle = "#2563eb"
        context.lineWidth = 1.2
        let clipped = false
        for (const segment of traceSegments(traces[name], gaps, name, stepS)) {
          context.beginPath()
          segment.elapsed_s.forEach((t, i) => {
            if (t < start) return
            const uv = segment.microvolts[i]
            if (Math.abs(uv) > yRangeUv) clipped = true
            if (i === 0 || segment.elapsed_s[i - 1] < start)
              context.moveTo(x(t), y(uv))
            else context.lineTo(x(t), y(uv))
          })
          context.stroke()
        }

        if (clipped) {
          context.fillStyle = "#b45309"
          context.textAlign = "right"
          context.fillText(
            "values beyond scale clipped",
            width - right - 4,
            rowTop + 14,
          )
          context.textAlign = "left"
        }
      })

      if (cursorS !== undefined && cursorS >= start && cursorS <= end) {
        context.strokeStyle = "#7c3aed"
        context.lineWidth = 1.5
        context.beginPath()
        context.moveTo(x(cursorS), top)
        context.lineTo(x(cursorS), height - bottom)
        context.stroke()
      }

      context.fillStyle = "#64748b"
      context.textAlign = "center"
      const firstTick = Math.ceil(start)
      for (let t = firstTick; t <= end; t += windowS > 10 ? 2 : 1) {
        context.fillText(`${t}`, x(t), height - 8)
      }
      context.textAlign = "left"
    }

    draw()
    const resizeObserver = new ResizeObserver(draw)
    resizeObserver.observe(canvas)
    return () => resizeObserver.disconnect()
  }, [traces, gaps, reduction, windowS, startS, cursorS, yRangeUv])

  return (
    <section className="flex h-full min-h-0 flex-col rounded-[10px] border-2 border-[#16a34a] bg-white p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-[#16a34a] px-2 py-0.5 text-[10px] font-bold uppercase text-white">
          {viewLabel}
        </span>
        <h2 className="text-sm font-semibold text-[#1e293b]">{heading}</h2>
        <span className="text-[11px] text-[#64748b]">
          x: EEG time since first packet (s) · y: microvolts (µV), fixed scale
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-[#64748b]">
          Scale ±
          <select
            className="rounded border border-[#cbd5e1] bg-white px-1 py-0.5 text-[11px]"
            value={yRangeUv}
            onChange={(event) => onYRangeChange(Number(event.target.value))}
          >
            {Y_RANGES_UV.map((value) => (
              <option key={value} value={value}>
                {value} µV
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="relative min-h-0 flex-1">
        <canvas ref={canvasRef} className="h-full w-full" />
        {waiting && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 text-sm font-semibold text-[#475569]">
            Waiting for the first EEG packets…
          </div>
        )}
      </div>
      <p className="mt-1 text-[10px] text-[#94a3b8]">
        {reduction
          ? `Display shows every ${reduction.factor}th sample (${reduction.display_hz} points/s per channel). ${reduction.note}`
          : "Display may be thinned for speed; the saved file keeps every sample."}{" "}
        Shaded red = missing packets (not filled in).
      </p>
    </section>
  )
}
