"""Local HTTP service that lets the operator dashboard run the real recorder.

Run from the repository root:

    python3 -m eeg_app.dashboard_service                 # real Muse via muse2-c/build/muse2_scan
    python3 -m eeg_app.dashboard_service --fake-headset  # generated EEG_PACKET lines, no headset

The API is described in docs/dashboard-api.md. This module adds no decoding or
saving rules of its own: packet lines go through LivePacketAdapter,
SessionWriter and PacketReceiptWriter in the same order as record_packet_lines,
and review uses read_session, check_session, create_fixed_windows and
export_review_bundle unchanged.

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .dataset import create_fixed_windows, load_synthetic_session
from .live_adapter import (
    PACKET_PREFIX,
    LivePacketAdapter,
    PacketBatch,
    PacketFormatError,
    PacketReceiptWriter,
    parse_eeg_packet_line,
)
from .pilot_sequence import CUES, READY, READY_LEAD_S
from .preprocessing import REQUIRED_CHANNELS
from .recording import (
    METADATA_FILENAME,
    NOMINAL_SAMPLE_RATE_HZ,
    PACKET_INDEX_MODULUS,
    SAMPLES_PER_PACKET,
    SessionFormatError,
    SessionInterruptedError,
    SessionWriter,
    check_session,
    read_session,
)
from .review import export_review_bundle

API_VERSION = "0.1"
DEFAULT_PORT = 8765
SCANNER = Path("muse2-c/build/muse2_scan")
SESSIONS_DIR = Path("data/sessions")
REVIEW_DIR = Path("recordings")

RECENT_WINDOW_S = 1.0  # a channel "has recent packets" if one arrived this recently
STALLED_AFTER_S = 3.0
SCANNER_RESTART_DELAY_S = 2.0
DISPLAY_STRIDE = 4  # live display keeps every 4th sample: 64 points/s per channel
LIVE_HISTORY_S = 10.0
LIVE_FIRST_WINDOW_S = 5.0
SESSION_OPEN_TIMEOUT_S = 5.0
SESSION_CLOSE_TIMEOUT_S = 10.0

EVENTS_FILENAME = "events.csv"
SESSION_FILENAME = "session.json"
EVENT_COLUMNS = (
    "event_id", "session_id", "event_type", "label", "source", "event_code",
    "corrects_event_id", "client_ref", "monotonic_ns", "session_elapsed_s",
    "eeg_elapsed_s", "received_at_utc",
)
# The live version has no pause: recording_paused / recording_resumed are not accepted.
EVENT_TYPES = (
    "phase_started", "prompt_shown", "observer_marker", "headset_adjustment",
    "operator_note", "marker_correction", "contact_quality_unverified",
)
EVENT_SOURCES = ("protocol", "operator")
OUTCOMES = ("completed", "incomplete", "aborted")

_SESSION_ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no 0/o or 1/l
_SESSION_ID_PATTERN = re.compile(r"ses-[a-z0-9]{8}")
_SAMPLE_S = 1 / NOMINAL_SAMPLE_RATE_HZ


class ApiError(Exception):
    """An error returned to the dashboard as ``{"error": {"code", "message"}}``."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ScannerLostError(RuntimeError):
    """The packet source stopped while a session was recording."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


# ---------------------------------------------------------------- Live session


_END = object()


@dataclass
class _Lost:
    reason: str


@dataclass
class ActiveSession:
    """Everything the backend tracks for the one session that is open."""

    session_id: str
    session_dir: Path
    protocol_id: str | None
    started_at_utc: str
    start_monotonic_ns: int
    data_source: str
    lines: queue.Queue = field(default_factory=queue.Queue)
    state: str = "waiting_for_packets"  # -> recording -> interrupted
    stop_reason: str | None = None
    first_packet_receipt_ns: int | None = None
    rows_written: int = 0
    samples_per_channel: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(REQUIRED_CHANNELS, 0)
    )
    # Display copy only: (cursor, elapsed_s, microvolts), every DISPLAY_STRIDE-th sample.
    live_points: dict[str, deque] = field(default_factory=lambda: {
        channel: deque(maxlen=int(LIVE_HISTORY_S * NOMINAL_SAMPLE_RATE_HZ / DISPLAY_STRIDE))
        for channel in REQUIRED_CHANNELS
    })
    live_gaps: deque = field(default_factory=lambda: deque(maxlen=200))
    last_packet: dict[str, tuple[int, float]] = field(default_factory=dict)
    cursor: int = 0
    latest_elapsed_s: float = 0.0
    events: list[dict] = field(default_factory=list)
    events_by_client_ref: dict[str, dict] = field(default_factory=dict)
    opened: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    open_error: BaseException | None = None
    thread: threading.Thread | None = None


class DashboardService:
    """Owns the packet source status, the open session, and saved-session review.

    The HTTP handler calls the public methods; a packet source thread calls
    ``on_scanner_line`` and ``on_scanner_stopped``. All shared state is guarded
    by ``self._lock``.
    """

    def __init__(
        self,
        sessions_dir: Path = SESSIONS_DIR,
        review_dir: Path = REVIEW_DIR,
        data_source: str = "live_eeg_packet",
    ):
        self.sessions_dir = Path(sessions_dir)
        self.review_dir = Path(review_dir)
        self.data_source = data_source
        self._lock = threading.RLock()
        self._active: ActiveSession | None = None
        self._scanner_state = "scanner_stopped"
        self._scanner_message = "The scanner has not started yet."
        self._last_packet_ns: dict[str, int] = {}
        self._packets_received = dict.fromkeys(REQUIRED_CHANNELS, 0)
        self._event_counter = 0
        self.fail_next_events = 0  # fake-headset testing only

    # ------------------------------------------------------- packet source side

    def on_scanner_started(self) -> None:
        with self._lock:
            self._scanner_state = "running"
            self._scanner_message = "Scanner running."

    def on_scanner_missing(self, message: str) -> None:
        with self._lock:
            self._scanner_state = "scanner_missing"
            self._scanner_message = message

    def on_scanner_line(self, line: str) -> None:
        """Handle one stdout line from the scanner (or the fake headset)."""
        if not line.startswith(f"{PACKET_PREFIX},"):
            return
        now = time.monotonic_ns()
        try:
            packet = parse_eeg_packet_line(line)
        except PacketFormatError:
            packet = None
        with self._lock:
            if packet is not None:
                self._last_packet_ns[packet.channel] = now
                self._packets_received[packet.channel] += 1
            session = self._active
            if session is not None and session.state != "interrupted":
                # Malformed lines are passed on too: the adapter rejects them
                # and the writer marks the session interrupted, as in
                # record_packet_lines.
                session.lines.put(line)

    def on_scanner_stopped(self, reason: str) -> None:
        with self._lock:
            self._scanner_state = "scanner_stopped"
            self._scanner_message = reason
            session = self._active
            if session is not None and session.state != "interrupted":
                session.lines.put(_Lost(reason))

    # ------------------------------------------------------------ status

    def status(self) -> dict:
        with self._lock:
            now = time.monotonic_ns()
            ages = {
                channel: (now - self._last_packet_ns[channel]) / 1e9
                for channel in self._last_packet_ns
            }
            channels = [
                {
                    "name": channel,
                    "recent_packets": channel in ages and ages[channel] <= RECENT_WINDOW_S,
                    "last_packet_age_s": round(ages[channel], 3) if channel in ages else None,
                    "packets_received": self._packets_received[channel],
                }
                for channel in REQUIRED_CHANNELS
            ]
            return {
                "api_version": API_VERSION,
                "data_source": self.data_source,
                "device": self._device_status(ages),
                "recent_window_s": RECENT_WINDOW_S,
                "channels": channels,
                "contact_quality": "not_measured",
                "recorder": self._recorder_status(now),
            }

    def _device_status(self, ages: dict[str, float]) -> dict:
        if self._scanner_state != "running":
            return {"state": self._scanner_state, "message": self._scanner_message}
        if not ages:
            return {"state": "searching", "message": "Scanner running; waiting for the first EEG packet."}
        newest = min(ages.values())
        if newest <= RECENT_WINDOW_S:
            return {"state": "streaming", "message": "Receiving EEG packets."}
        if newest >= STALLED_AFTER_S:
            return {"state": "stalled", "message": f"No EEG packets for {newest:.0f} s."}
        return {"state": "streaming", "message": f"Last EEG packet {newest:.1f} s ago."}

    def _recorder_status(self, now: int) -> dict:
        session = self._active
        if session is None:
            return {
                "state": "idle", "session_id": None, "session_elapsed_s": None,
                "eeg_elapsed_s": None, "rows_written": None, "samples_per_channel": None,
                "stop_reason": None,
            }
        return {
            "state": session.state,
            "session_id": session.session_id,
            "session_elapsed_s": round((now - session.start_monotonic_ns) / 1e9, 3),
            "eeg_elapsed_s": session.latest_elapsed_s if session.rows_written else None,
            "rows_written": session.rows_written,
            "samples_per_channel": dict(session.samples_per_channel),
            "stop_reason": session.stop_reason,
        }

    def pilot_sequence(self) -> dict:
        cues = []
        start_s = 0
        for index, (text, duration_s) in enumerate(CUES):
            cues.append({
                "index": index,
                "text": text,
                "start_s": start_s,
                "duration_s": duration_s,
                "get_ready": READY.get(index),
            })
            start_s += duration_s
        return {
            "source": "eeg_app/pilot_sequence.py",
            "clock": "eeg_elapsed_s",
            "get_ready_lead_s": READY_LEAD_S,
            "total_s": start_s,
            "cues": cues,
        }

    # ------------------------------------------------------------ start

    def start_session(self, body: dict) -> dict:
        protocol_id = body.get("protocol_id")
        if protocol_id is not None and not isinstance(protocol_id, str):
            raise ApiError(400, "invalid_request", "protocol_id must be text or null.")
        with self._lock:
            if self._active is not None:
                raise ApiError(
                    409, "session_already_active",
                    f"Session {self._active.session_id} is still open. End it before starting another.",
                )
            if self._scanner_state != "running":
                raise ApiError(
                    503, "scanner_unavailable",
                    f"The EEG scanner is not running: {self._scanner_message}",
                )
            session_id = self._new_session_id()
            session = ActiveSession(
                session_id=session_id,
                session_dir=self.sessions_dir / session_id,
                protocol_id=protocol_id,
                started_at_utc=_utc_now(),
                start_monotonic_ns=time.monotonic_ns(),
                data_source=self.data_source,
            )
            self._active = session

        session.thread = threading.Thread(
            target=self._record, args=(session,), name=f"recorder-{session_id}", daemon=True
        )
        session.thread.start()
        if not session.opened.wait(SESSION_OPEN_TIMEOUT_S) or session.open_error is not None:
            with self._lock:
                self._active = None
            session.lines.put(_END)
            raise ApiError(500, "internal_error", f"Could not open the session: {session.open_error}")

        with (session.session_dir / EVENTS_FILENAME).open("x", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(EVENT_COLUMNS)
        self._write_session_file(session, outcome=None, reason=None, ended_at_utc=None)
        with self._lock:
            return {
                "session_id": session_id,
                "protocol_id": protocol_id,
                "started_at_utc": session.started_at_utc,
                "start_monotonic_ns": session.start_monotonic_ns,
                "recorder": self._recorder_status(time.monotonic_ns()),
            }

    def _new_session_id(self) -> str:
        while True:
            session_id = "ses-" + "".join(secrets.choice(_SESSION_ID_ALPHABET) for _ in range(8))
            if not (self.sessions_dir / session_id).exists():
                return session_id

    def _record(self, session: ActiveSession) -> None:
        """Recorder thread: the same steps as live_adapter.record_packet_lines."""
        adapter = LivePacketAdapter()
        try:
            writer = SessionWriter(
                self.sessions_dir,
                session.session_id,
                timing_method="packet_index_estimate",
                data_source=session.data_source,
            )
            with writer:
                with PacketReceiptWriter(writer.session_dir, session.session_id) as receipts:
                    session.opened.set()
                    while True:
                        item = session.lines.get()
                        if item is _END:
                            break
                        if isinstance(item, _Lost):
                            raise ScannerLostError(item.reason)
                        batch = adapter.accept_line(item)
                        writer.write_all(batch.records)
                        receipts.write(batch.packet)
                        self._on_saved(session, batch, writer.rows_written)
        except SessionInterruptedError as error:
            cause = error.__cause__
            with self._lock:
                session.state = "interrupted"
                session.stop_reason = f"{type(cause).__name__}: {cause}" if cause else str(error)
        except BaseException as error:  # opening failed, before any data
            session.open_error = error
            session.opened.set()
        finally:
            session.finished.set()

    def _on_saved(self, session: ActiveSession, batch: PacketBatch, rows_written: int) -> None:
        packet = batch.packet
        with self._lock:
            if session.first_packet_receipt_ns is None:
                session.first_packet_receipt_ns = packet.receipt_monotonic_ns
            session.state = "recording"
            session.rows_written = rows_written
            session.samples_per_channel[packet.channel] += len(batch.records)
            first_s = batch.records[0].elapsed_s
            previous = session.last_packet.get(packet.channel)
            if previous is not None:
                previous_index, previous_first_s = previous
                step = (packet.packet_index - previous_index) % PACKET_INDEX_MODULUS
                if step > 1:
                    session.cursor += 1
                    session.live_gaps.append((session.cursor, {
                        "channel": packet.channel,
                        "start_s": previous_first_s + SAMPLES_PER_PACKET * _SAMPLE_S,
                        "end_s": first_s,
                    }))
            session.last_packet[packet.channel] = (packet.packet_index, first_s)
            points = session.live_points[packet.channel]
            for record in batch.records:
                if round(record.elapsed_s * NOMINAL_SAMPLE_RATE_HZ) % DISPLAY_STRIDE == 0:
                    session.cursor += 1
                    points.append((session.cursor, record.elapsed_s, record.microvolts))
            session.latest_elapsed_s = max(session.latest_elapsed_s, batch.records[-1].elapsed_s)

    # ------------------------------------------------------------ live data

    def live(self, session_id: str, after: int | None) -> dict:
        with self._lock:
            session = self._require_open(session_id)
            if after is None:
                since = session.latest_elapsed_s - LIVE_FIRST_WINDOW_S
                keep = lambda cursor, elapsed_s: elapsed_s >= since  # noqa: E731
            else:
                keep = lambda cursor, elapsed_s: cursor > after  # noqa: E731
            channels = {}
            for channel in REQUIRED_CHANNELS:
                selected = [p for p in session.live_points[channel] if keep(p[0], p[1])]
                channels[channel] = {
                    "elapsed_s": [p[1] for p in selected],
                    "microvolts": [p[2] for p in selected],
                }
            gaps = [gap for cursor, gap in session.live_gaps if keep(cursor, gap["end_s"])]
            return {
                "session_id": session_id,
                "recorder_state": session.state,
                "cursor": session.cursor,
                "reduction": _reduction(DISPLAY_STRIDE),
                "channels": channels,
                "gaps": gaps,
            }

    # ------------------------------------------------------------ events

    def add_event(self, session_id: str, body: dict) -> tuple[int, dict]:
        event_type = body.get("event_type")
        label = body.get("label")
        source = body.get("source")
        event_code = body.get("event_code")
        corrects_event_id = body.get("corrects_event_id")
        client_ref = body.get("client_ref")
        if event_type not in EVENT_TYPES:
            raise ApiError(400, "invalid_request", f"event_type must be one of: {', '.join(EVENT_TYPES)}.")
        if not isinstance(label, str) or not label.strip():
            raise ApiError(400, "invalid_request", "label must be nonempty text.")
        if source not in EVENT_SOURCES:
            raise ApiError(400, "invalid_request", "source must be 'protocol' or 'operator'.")
        if event_code is not None and not isinstance(event_code, str):
            raise ApiError(400, "invalid_request", "event_code must be text or null.")
        if not isinstance(client_ref, str) or not client_ref:
            raise ApiError(400, "invalid_request", "client_ref must be nonempty text.")
        if (event_type == "marker_correction") != (corrects_event_id is not None):
            raise ApiError(
                400, "invalid_request",
                "corrects_event_id is required for marker_correction and must be null otherwise.",
            )

        with self._lock:
            session = self._require_open(session_id)
            if client_ref in session.events_by_client_ref:
                return 200, session.events_by_client_ref[client_ref]
            if session.state == "interrupted":
                raise ApiError(
                    409, "session_not_recording",
                    f"Recording stopped ({session.stop_reason}). End the session; this event was not saved.",
                )
            if corrects_event_id is not None and not any(
                event["event_id"] == corrects_event_id for event in session.events
            ):
                raise ApiError(
                    409, "unknown_event_reference",
                    f"No event {corrects_event_id!r} in session {session_id}.",
                )
            if self.fail_next_events > 0:
                self.fail_next_events -= 1
                raise ApiError(500, "internal_error", "Simulated event failure (fake headset test).")

            now = time.monotonic_ns()
            session_counter = len(session.events) + 1
            event = {
                "event_id": f"evt-{session_counter:04d}",
                "session_id": session_id,
                "event_type": event_type,
                "label": label.strip(),
                "source": source,
                "event_code": event_code,
                "corrects_event_id": corrects_event_id,
                "client_ref": client_ref,
                "monotonic_ns": now,
                "session_elapsed_s": round((now - session.start_monotonic_ns) / 1e9, 3),
                "eeg_elapsed_s": (
                    round((now - session.first_packet_receipt_ns) / 1e9, 3)
                    if session.first_packet_receipt_ns is not None else None
                ),
                "received_at_utc": _utc_now(),
            }
            with (session.session_dir / EVENTS_FILENAME).open("a", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(
                    "" if event[column] is None else event[column] for column in EVENT_COLUMNS
                )
            session.events.append(event)
            session.events_by_client_ref[client_ref] = event
            return 201, event

    # ------------------------------------------------------------ end

    def end_session(self, session_id: str, body: dict) -> dict:
        outcome = body.get("outcome")
        reason = body.get("reason")
        if outcome not in OUTCOMES:
            raise ApiError(400, "invalid_request", f"outcome must be one of: {', '.join(OUTCOMES)}.")
        if reason is not None and not isinstance(reason, str):
            raise ApiError(400, "invalid_request", "reason must be text or null.")
        reason = reason.strip() if reason else None
        if outcome != "completed" and not reason:
            raise ApiError(400, "invalid_request", f"A reason is required for an {outcome} session.")

        with self._lock:
            session = self._require_open(session_id)
            if session.state == "interrupted" and outcome == "completed":
                raise ApiError(
                    409, "cannot_complete_interrupted",
                    f"Saving was interrupted ({session.stop_reason}). End it as incomplete or aborted.",
                )
            session.lines.put(_END)
        session.finished.wait(SESSION_CLOSE_TIMEOUT_S)

        with self._lock:
            if session.state == "interrupted" and outcome == "completed":
                # Saving failed on the last lines before _END was reached.
                raise ApiError(
                    409, "cannot_complete_interrupted",
                    f"Saving was interrupted ({session.stop_reason}). End it as incomplete or aborted.",
                )
            ended_at_utc = _utc_now()
            self._write_session_file(session, outcome=outcome, reason=reason, ended_at_utc=ended_at_utc)
            self._active = None
            metadata = json.loads((session.session_dir / METADATA_FILENAME).read_text(encoding="utf-8"))
            return {
                "session_id": session_id,
                "outcome": outcome,
                "reason": reason,
                "recording_status": metadata["status"],
                "stop_reason": metadata.get("stop_reason"),
                "ended_at_utc": ended_at_utc,
                "rows_written": metadata["eeg_row_count"],
            }

    def _write_session_file(self, session: ActiveSession, outcome, reason, ended_at_utc) -> None:
        _write_json(session.session_dir / SESSION_FILENAME, {
            "session_id": session.session_id,
            "protocol_id": session.protocol_id,
            "start_monotonic_ns": session.start_monotonic_ns,
            "first_packet_receipt_ns": session.first_packet_receipt_ns,
            "outcome": outcome,
            "reason": reason,
            "ended_at_utc": ended_at_utc,
        })

    def shutdown(self) -> None:
        """Called when the backend stops: an open session is kept and marked interrupted."""
        with self._lock:
            session = self._active
            if session is not None and session.state != "interrupted":
                session.lines.put(_Lost("the dashboard backend was stopped"))
        if session is not None:
            session.finished.wait(SESSION_CLOSE_TIMEOUT_S)

    def _require_open(self, session_id: str) -> ActiveSession:
        session = self._active
        if session is not None and session.session_id == session_id:
            return session
        if self._saved_dir(session_id) is not None:
            raise ApiError(409, "session_not_recording", f"Session {session_id} has already ended.")
        raise ApiError(404, "session_not_found", f"No session {session_id!r}.")

    # ------------------------------------------------------------ review

    def _saved_dir(self, session_id: str) -> Path | None:
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            return None
        directory = self.sessions_dir / session_id
        return directory if (directory / METADATA_FILENAME).is_file() else None

    def _require_saved(self, session_id: str) -> Path:
        with self._lock:
            if self._active is not None and self._active.session_id == session_id:
                raise ApiError(409, "session_still_recording", f"Session {session_id} is still open.")
        directory = self._saved_dir(session_id)
        if directory is None:
            raise ApiError(404, "session_not_found", f"No saved session {session_id!r}.")
        return directory

    def _session_file(self, directory: Path) -> dict:
        path = directory / SESSION_FILENAME
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def list_sessions(self) -> dict:
        sessions = []
        if self.sessions_dir.is_dir():
            for directory in self.sessions_dir.iterdir():
                if not (directory / SESSION_FILENAME).is_file() or not (directory / METADATA_FILENAME).is_file():
                    continue  # only sessions recorded through this service
                metadata = json.loads((directory / METADATA_FILENAME).read_text(encoding="utf-8"))
                extra = self._session_file(directory)
                sessions.append({
                    "session_id": directory.name,
                    "started_at_utc": metadata.get("started_at_utc"),
                    "ended_at_utc": extra.get("ended_at_utc"),
                    "outcome": extra.get("outcome"),
                    "recording_status": metadata.get("status"),
                })
        sessions.sort(key=lambda item: item["started_at_utc"] or "", reverse=True)
        return {"sessions": sessions}

    def summary(self, session_id: str) -> dict:
        directory = self._require_saved(session_id)
        try:
            saved = read_session(directory)
        except SessionFormatError as error:
            raise ApiError(422, "session_unreadable", str(error)) from None
        check = check_session(saved)
        metadata = saved.metadata
        extra = self._session_file(directory)
        events = self._read_events(directory)
        last = max((record.elapsed_s for record in saved.records), default=None)
        return {
            "session_id": session_id,
            "protocol_id": extra.get("protocol_id"),
            "started_at_utc": metadata.get("started_at_utc"),
            "ended_at_utc": extra.get("ended_at_utc"),
            "outcome": extra.get("outcome"),
            "reason": extra.get("reason"),
            "recording_status": metadata.get("status"),
            "stop_reason": metadata.get("stop_reason"),
            "data_source": metadata.get("data_source"),
            "nominal_sample_rate_hz": metadata.get("nominal_sample_rate_hz"),
            "samples_per_packet": metadata.get("samples_per_packet"),
            "channels": metadata.get("channels"),
            "eeg_span_s": 0.0 if last is None else last + _SAMPLE_S,
            "event_count": len(events),
            "check": {
                "ok": check.ok,
                "total_rows": check.total_rows,
                "rows_per_channel": check.rows_per_channel,
                "missing_packets": [
                    {"packet_index": index, "channels": channels}
                    for index, channels in check.missing_packets.items()
                ],
                "duplicate_samples": [
                    {"channel": channel, "packet_index": index, "sample_in_packet": position}
                    for channel, index, position in check.duplicates
                ],
                "problems": check.problems,
            },
            "windows": self._windows(directory, bool(saved.records)),
            "review_bundle": self._review_bundle(session_id, directory, bool(saved.records)),
        }

    def _windows(self, directory: Path, has_rows: bool) -> dict:
        if not has_rows:
            return {"window_s": 2.0, "total": 0, "valid": 0, "invalid": [], "error": None}
        try:
            session = load_synthetic_session(directory / "eeg.csv", directory / METADATA_FILENAME)
            windows = create_fixed_windows(session)
        except ValueError as error:
            return {"window_s": 2.0, "total": 0, "valid": 0, "invalid": [], "error": str(error)}
        return {
            "window_s": 2.0,
            "total": len(windows),
            "valid": sum(window.is_valid for window in windows),
            "invalid": [
                {
                    "window_id": window.window_id,
                    "start_s": window.start_time_s,
                    "end_s": window.end_time_s,
                    "reasons": list(window.invalid_reasons),
                }
                for window in windows if not window.is_valid
            ],
            "error": None,
        }

    def _review_bundle(self, session_id: str, directory: Path, has_rows: bool) -> dict:
        """Samuel's prediction-free bundle, created the first time it is asked for."""
        if not has_rows:
            return {"url": None, "error": "No EEG rows were saved, so there is nothing to review."}
        output = self.review_dir / f"{session_id}-review"
        try:
            if not (output / "index.html").is_file():
                export_review_bundle(directory, output)
        except (ValueError, OSError) as error:
            return {"url": None, "error": str(error)}
        return {"url": f"/review-bundles/{session_id}/index.html", "error": None}

    def review_bundle_file(self, session_id: str, relative: str) -> Path:
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ApiError(404, "session_not_found", f"No review bundle for {session_id!r}.")
        root = (self.review_dir / f"{session_id}-review").resolve()
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise ApiError(404, "session_not_found", "No such review bundle file.")
        return path

    def _read_events(self, directory: Path) -> list[dict]:
        path = directory / EVENTS_FILENAME
        if not path.is_file():
            return []
        events = []
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                event = {key: (value if value != "" else None) for key, value in row.items()}
                event["monotonic_ns"] = int(event["monotonic_ns"])
                event["session_elapsed_s"] = float(event["session_elapsed_s"])
                if event["eeg_elapsed_s"] is not None:
                    event["eeg_elapsed_s"] = float(event["eeg_elapsed_s"])
                events.append(event)
        return events

    def events(self, session_id: str) -> dict:
        directory = self._require_saved(session_id)
        return {"session_id": session_id, "events": self._read_events(directory)}

    def traces(self, session_id: str, start_s: float, end_s: float, max_points: int) -> dict:
        if not (math.isfinite(start_s) and math.isfinite(end_s)) or start_s < 0 or end_s <= start_s:
            raise ApiError(400, "invalid_request", "Need 0 <= start_s < end_s.")
        if max_points < 10:
            raise ApiError(400, "invalid_request", "max_points must be at least 10.")
        directory = self._require_saved(session_id)
        try:
            saved = read_session(directory)
        except SessionFormatError as error:
            raise ApiError(422, "session_unreadable", str(error)) from None
        span_samples = (end_s - start_s) * NOMINAL_SAMPLE_RATE_HZ
        stride = max(1, math.ceil(span_samples / max_points))
        channels = {channel: {"elapsed_s": [], "microvolts": []} for channel in REQUIRED_CHANNELS}
        gaps = []
        previous: dict[str, tuple[int, float]] = {}
        for record in saved.records:
            channel = record.channel
            if record.sample_in_packet == 0:
                before = previous.get(channel)
                if before is not None and (record.packet_index - before[0]) % PACKET_INDEX_MODULUS > 1:
                    gap = {"channel": channel, "start_s": before[1] + SAMPLES_PER_PACKET * _SAMPLE_S,
                           "end_s": record.elapsed_s}
                    if gap["end_s"] > start_s and gap["start_s"] < end_s:
                        gaps.append(gap)
                previous[channel] = (record.packet_index, record.elapsed_s)
            if start_s <= record.elapsed_s < end_s and (
                round(record.elapsed_s * NOMINAL_SAMPLE_RATE_HZ) % stride == 0
            ):
                channels[channel]["elapsed_s"].append(record.elapsed_s)
                channels[channel]["microvolts"].append(record.microvolts)
        return {
            "session_id": session_id,
            "start_s": start_s,
            "end_s": end_s,
            "reduction": _reduction(stride),
            "channels": channels,
            "gaps": gaps,
        }


def _reduction(stride: int) -> dict:
    return {
        "method": "stride",
        "factor": stride,
        "display_hz": round(NOMINAL_SAMPLE_RATE_HZ / stride, 3),
        "note": "Display only. The saved eeg.csv keeps every sample.",
    }


# ---------------------------------------------------------------- Packet sources


def run_scanner(service: DashboardService, scanner: Path, stop: threading.Event) -> None:
    """Run the real scanner, restarting it if it exits, and feed its stdout to the service."""
    while not stop.is_set():
        if not scanner.is_file():
            service.on_scanner_missing(f"{scanner} not found. Build it with: cd muse2-c && make scan")
            stop.wait(SCANNER_RESTART_DELAY_S)
            continue
        process = subprocess.Popen(
            [str(scanner)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
        )
        service.on_scanner_started()
        assert process.stdout is not None
        for line in process.stdout:
            if stop.is_set():
                break
            service.on_scanner_line(line)
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        service.on_scanner_stopped(f"Scanner exited with code {process.returncode}.")
        stop.wait(SCANNER_RESTART_DELAY_S)


class FakeHeadset:
    """Generated EEG_PACKET lines at the real packet rate. For testing without a Muse.

    The values are a small 10 Hz wave per channel, plus a blink-shaped bump on
    AF7 and AF8 every 7 s. They are not recordings and must never be analyzed.
    ``disconnect()`` makes the source exit (like the scanner crashing);
    ``stall(seconds)`` stops packets without exiting (like the headset going quiet).
    """

    first_packet_index = 65000  # wraps past 65535 after about 25 s

    def __init__(self):
        self.reconnect()

    def reconnect(self) -> None:
        self._disconnect = threading.Event()
        self._stall_until_ns = 0

    def disconnect(self) -> None:
        self._disconnect.set()

    def stall(self, seconds: float) -> None:
        self._stall_until_ns = time.monotonic_ns() + int(seconds * 1e9)

    def lines(self, stop: threading.Event) -> Iterator[str]:
        packet_period_s = SAMPLES_PER_PACKET / NOMINAL_SAMPLE_RATE_HZ
        start = time.monotonic()
        slot = 0
        while not stop.is_set() and not self._disconnect.is_set():
            delay = start + slot * packet_period_s - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            stalled = time.monotonic_ns() < self._stall_until_ns
            index = (self.first_packet_index + slot) % PACKET_INDEX_MODULUS
            for offset, channel in enumerate(REQUIRED_CHANNELS):
                if stalled:
                    continue
                values = []
                for position in range(SAMPLES_PER_PACKET):
                    t = (slot * SAMPLES_PER_PACKET + position) / NOMINAL_SAMPLE_RATE_HZ
                    value = 8 * math.sin(2 * math.pi * 10 * t + offset) + 3 * math.sin(2 * math.pi * 0.4 * t)
                    phase = t % 7.0
                    if channel in ("AF7", "AF8") and 3.0 <= phase < 3.3:
                        value += 150 * math.sin(math.pi * (phase - 3.0) / 0.3)
                    values.append(f"{value:.4f}")
                yield f"{PACKET_PREFIX},{channel},{index},{time.monotonic_ns()},{','.join(values)}"
            slot += 1


def run_fake_headset(service: DashboardService, headset: FakeHeadset, stop: threading.Event) -> None:
    while not stop.is_set():
        service.on_scanner_started()
        for line in headset.lines(stop):
            service.on_scanner_line(line)
        service.on_scanner_stopped("Fake headset disconnected (test).")
        stop.wait(SCANNER_RESTART_DELAY_S)
        headset.reconnect()  # come back like the real scanner restart


# ---------------------------------------------------------------- HTTP


_ROUTES = [
    ("GET", re.compile(r"/api/status"), "status"),
    ("GET", re.compile(r"/api/pilot-sequence"), "pilot_sequence"),
    ("GET", re.compile(r"/api/sessions"), "list_sessions"),
    ("POST", re.compile(r"/api/sessions"), "start_session"),
    ("GET", re.compile(r"/api/sessions/([^/]+)/live"), "live"),
    ("POST", re.compile(r"/api/sessions/([^/]+)/events"), "add_event"),
    ("POST", re.compile(r"/api/sessions/([^/]+)/end"), "end_session"),
    ("GET", re.compile(r"/api/sessions/([^/]+)"), "summary"),
    ("GET", re.compile(r"/api/sessions/([^/]+)/events"), "events"),
    ("GET", re.compile(r"/api/sessions/([^/]+)/traces"), "traces"),
    ("GET", re.compile(r"/review-bundles/([^/]+)/(.+)"), "review_bundle_file"),
    ("POST", re.compile(r"/api/fake/disconnect"), "fake_disconnect"),
    ("POST", re.compile(r"/api/fake/stall"), "fake_stall"),
    ("POST", re.compile(r"/api/fake/fail-next-event"), "fake_fail_next_event"),
]
_LOCAL_ORIGIN = re.compile(r"http://(localhost|127\.0\.0\.1)(:\d+)?")


def make_handler(service: DashboardService, headset: FakeHeadset | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EEGDashboardService/" + API_VERSION

        def log_message(self, format, *args):
            # Keep the frequent status and live polls out of the terminal.
            path = urlparse(self.path).path
            if path != "/api/status" and not path.endswith("/live"):
                sys.stderr.write("%s\n" % (format % args))

        def do_OPTIONS(self):
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _cors(self):
            origin = self.headers.get("Origin")
            if origin and _LOCAL_ORIGIN.fullmatch(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send_json(self, status: int, body: dict):
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                raise ApiError(400, "invalid_request", "Request body is not valid JSON.") from None
            if not isinstance(body, dict):
                raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
            return body

        def _dispatch(self, method: str):
            url = urlparse(self.path)
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            try:
                for route_method, pattern, name in _ROUTES:
                    match = pattern.fullmatch(url.path)
                    if route_method == method and match:
                        return self._handle(name, match.groups(), query)
                raise ApiError(404, "not_found", f"No endpoint {method} {url.path}.")
            except ApiError as error:
                self._send_json(error.status, {"error": {"code": error.code, "message": error.message}})
            except Exception as error:  # noqa: BLE001 - report, keep serving
                self._send_json(500, {"error": {"code": "internal_error", "message": f"{type(error).__name__}: {error}"}})

        def _handle(self, name: str, args: tuple, query: dict):
            if name == "status":
                return self._send_json(200, service.status())
            if name == "pilot_sequence":
                return self._send_json(200, service.pilot_sequence())
            if name == "list_sessions":
                return self._send_json(200, service.list_sessions())
            if name == "start_session":
                return self._send_json(201, service.start_session(self._body()))
            if name == "live":
                after = query.get("after")
                if after is not None and not after.isdigit():
                    raise ApiError(400, "invalid_request", "after must be a cursor from a previous response.")
                return self._send_json(200, service.live(args[0], int(after) if after else None))
            if name == "add_event":
                status, event = service.add_event(args[0], self._body())
                return self._send_json(status, event)
            if name == "end_session":
                return self._send_json(200, service.end_session(args[0], self._body()))
            if name == "summary":
                return self._send_json(200, service.summary(args[0]))
            if name == "events":
                return self._send_json(200, service.events(args[0]))
            if name == "traces":
                try:
                    start_s = float(query.get("start_s", 0))
                    end_s = float(query.get("end_s", 10))
                    max_points = int(query.get("max_points", 2000))
                except ValueError:
                    raise ApiError(400, "invalid_request", "start_s, end_s and max_points must be numbers.") from None
                return self._send_json(200, service.traces(args[0], start_s, end_s, max_points))
            if name == "review_bundle_file":
                path = service.review_bundle_file(*args)
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            if headset is None:
                raise ApiError(404, "not_found", "Test controls exist only with --fake-headset.")
            if name == "fake_disconnect":
                headset.disconnect()
            elif name == "fake_stall":
                headset.stall(float(query.get("seconds", 5)))
            elif name == "fake_fail_next_event":
                service.fail_next_events += 1
            return self._send_json(200, {"ok": True})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--fake-headset", action="store_true",
                        help="generate test packets instead of running the Muse scanner")
    parser.add_argument("--sessions-dir", type=Path, default=SESSIONS_DIR)
    parser.add_argument("--review-dir", type=Path, default=REVIEW_DIR)
    args = parser.parse_args(argv)

    service = DashboardService(
        args.sessions_dir, args.review_dir,
        data_source="fake_headset" if args.fake_headset else "live_eeg_packet",
    )
    stop = threading.Event()
    headset = FakeHeadset() if args.fake_headset else None
    source = threading.Thread(
        target=run_fake_headset if headset else run_scanner,
        args=(service, headset or SCANNER, stop),
        name="packet-source",
        daemon=True,
    )
    source.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, headset))
    mode = "FAKE HEADSET (generated test data)" if headset else f"real scanner {SCANNER}"
    print(f"Dashboard backend on http://127.0.0.1:{args.port} using {mode}. Ctrl+C stops.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.shutdown()
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
