"""Checks for the dashboard backend (eeg_app/dashboard_service.py).

Packet lines are fed straight into the service, so no headset, Bluetooth or C
scanner is used.
"""

import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from eeg_app import dashboard_service
from eeg_app.dashboard_service import ApiError, DashboardService, make_handler
from eeg_app.recording import check_session, read_session

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "dashboard_api"
CHANNELS = ("TP9", "AF7", "AF8", "TP10")


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "dashboard_fixture_generator", FIXTURE_DIR / "generate_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet_line(channel: str, index: int) -> str:
    values = ",".join(str(float(position)) for position in range(12))
    return f"EEG_PACKET,{channel},{index},{time.monotonic_ns()},{values}"


def wait_for(condition, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the recorder thread")
        time.sleep(0.005)


def event(client_ref: str, **changes) -> dict:
    body = {
        "event_type": "observer_marker", "label": "Observed blink", "source": "operator",
        "event_code": None, "corrects_event_id": None, "client_ref": client_ref,
    }
    body.update(changes)
    return body


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.service = DashboardService(root / "sessions", root / "review", data_source="fake_headset")
        self.service.on_scanner_started()
        self.addCleanup(self.service.shutdown)

    def feed(self, indices, channels=CHANNELS):
        before = self.service._active.rows_written
        count = 0
        for index in indices:
            for channel in channels:
                self.service.on_scanner_line(packet_line(channel, index))
                count += 12
        wait_for(lambda: self.service._active.rows_written == before + count
                 or self.service._active.state == "interrupted")

    def start(self) -> str:
        session_id = self.service.start_session({"protocol_id": "test"})["session_id"]
        return session_id


class FixtureTest(unittest.TestCase):
    def test_committed_fixture_matches_generator(self):
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            fresh = generator.build(Path(tmp))
        committed = json.loads((FIXTURE_DIR / "fake_responses.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, fresh, "regenerate: python3 -m tests.fixtures.dashboard_api.generate_fixture")


class SessionLifecycleTest(ServiceTestCase):
    def test_participant_code_and_visit_are_saved_for_repeat_sessions(self):
        session_id = self.service.start_session({
            "protocol_id": "test", "participant_code": "P001", "visit_number": 2,
        })["session_id"]
        status = self.service.status()["recorder"]
        self.assertEqual(status["participant_code"], "P001")
        self.assertEqual(status["visit_number"], 2)
        self.feed(range(2))
        self.service.end_session(session_id, {"outcome": "incomplete", "reason": "test recording"})
        self.assertEqual(self.service.summary(session_id)["participant_code"], "P001")
        self.assertEqual(self.service.summary(session_id)["visit_number"], 2)
        self.assertEqual(self.service.list_sessions()["sessions"][0]["participant_code"], "P001")

    def test_completed_session_is_saved_and_reads_back(self):
        session_id = self.start()
        self.assertEqual(self.service.status()["recorder"]["state"], "waiting_for_packets")
        self.feed(range(0, 10))
        status, saved_event = self.service.add_event(session_id, event("a"))
        self.assertEqual(status, 201)
        self.assertEqual(saved_event["event_id"], "evt-0001")
        self.assertIsNotNone(saved_event["eeg_elapsed_s"])
        self.feed(range(10, 20))

        result = self.service.end_session(session_id, {"outcome": "completed"})
        self.assertEqual(result["recording_status"], "complete")
        self.assertEqual(result["rows_written"], 20 * 4 * 12)

        saved = read_session(Path(self.tmp.name) / "sessions" / session_id)
        self.assertTrue(check_session(saved).ok)
        summary = self.service.summary(session_id)
        self.assertEqual(summary["outcome"], "completed")
        self.assertEqual(summary["check"]["rows_per_channel"], dict.fromkeys(CHANNELS, 240))
        self.assertEqual(self.service.events(session_id)["events"], [saved_event])
        self.assertEqual(self.service.status()["recorder"]["state"], "idle")

    def test_gap_is_reported_not_filled(self):
        session_id = self.start()
        self.feed([0, 1, 3])
        live = self.service.live(session_id, None)
        self.assertEqual(len(live["gaps"]), 4)
        self.assertEqual(live["gaps"][0]["start_s"], 24 / 256)
        self.assertEqual(live["gaps"][0]["end_s"], 36 / 256)
        self.service.end_session(session_id, {"outcome": "completed"})
        summary = self.service.summary(session_id)
        self.assertEqual(summary["check"]["missing_packets"], [{"packet_index": 2, "channels": list(CHANNELS)}])
        self.assertEqual(summary["check"]["total_rows"], 3 * 4 * 12)

    def test_live_cursor_returns_only_new_points(self):
        session_id = self.start()
        self.feed(range(0, 4))
        first = self.service.live(session_id, None)
        self.assertEqual(len(first["channels"]["TP9"]["elapsed_s"]), 4 * 12 // 4)
        self.feed(range(4, 6))
        second = self.service.live(session_id, first["cursor"])
        self.assertEqual(second["channels"]["TP9"]["elapsed_s"][0], 48 / 256)
        self.assertEqual(len(second["channels"]["TP9"]["elapsed_s"]), 2 * 12 // 4)


class OutcomeTest(ServiceTestCase):
    def test_early_stop_and_abort_need_a_reason_and_keep_data(self):
        for outcome in ("incomplete", "aborted"):
            session_id = self.start()
            self.feed(range(0, 3))
            with self.assertRaises(ApiError) as caught:
                self.service.end_session(session_id, {"outcome": outcome})
            self.assertEqual(caught.exception.code, "invalid_request")
            result = self.service.end_session(session_id, {"outcome": outcome, "reason": "test"})
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(result["rows_written"], 3 * 4 * 12)

    def test_lost_scanner_interrupts_and_blocks_completed(self):
        session_id = self.start()
        self.feed(range(0, 3))
        self.service.on_scanner_stopped("Scanner exited with code 1.")
        wait_for(lambda: self.service._active.state == "interrupted")
        self.assertEqual(self.service.status()["device"]["state"], "scanner_stopped")

        with self.assertRaises(ApiError) as caught:
            self.service.add_event(session_id, event("late"))
        self.assertEqual(caught.exception.code, "session_not_recording")
        with self.assertRaises(ApiError) as caught:
            self.service.end_session(session_id, {"outcome": "completed"})
        self.assertEqual(caught.exception.code, "cannot_complete_interrupted")

        result = self.service.end_session(session_id, {"outcome": "incomplete", "reason": "lost"})
        self.assertEqual(result["recording_status"], "interrupted")
        self.assertEqual(result["rows_written"], 3 * 4 * 12)


class GuardTest(ServiceTestCase):
    def test_rejects_invalid_participant_and_visit_fields(self):
        for body in (
            {"participant_code": "Jane Doe"},
            {"participant_code": "P"},
            {"visit_number": 0},
            {"visit_number": True},
            {"visit_number": "2"},
        ):
            with self.subTest(body=body), self.assertRaises(ApiError) as caught:
                self.service.start_session(body)
            self.assertEqual(caught.exception.code, "invalid_request")

    def test_second_session_is_refused(self):
        session_id = self.start()
        with self.assertRaises(ApiError) as caught:
            self.service.start_session({})
        self.assertEqual(caught.exception.code, "session_already_active")
        self.service.end_session(session_id, {"outcome": "completed"})
        self.assertNotEqual(self.start(), session_id)

    def test_start_needs_a_running_scanner(self):
        self.service.on_scanner_stopped("stopped")
        with self.assertRaises(ApiError) as caught:
            self.service.start_session({})
        self.assertEqual((caught.exception.status, caught.exception.code), (503, "scanner_unavailable"))

    def test_retry_with_same_client_ref_saves_once(self):
        session_id = self.start()
        first = self.service.add_event(session_id, event("same"))
        again = self.service.add_event(session_id, event("same"))
        self.assertEqual((first[0], again[0]), (201, 200))
        self.assertEqual(first[1], again[1])
        self.assertEqual(len(self.service._active.events), 1)

    def test_pause_and_bad_corrections_are_rejected(self):
        session_id = self.start()
        with self.assertRaises(ApiError):
            self.service.add_event(session_id, event("p", event_type="recording_paused", label="Paused"))
        with self.assertRaises(ApiError) as caught:
            self.service.add_event(session_id, event(
                "c", event_type="marker_correction", label="Correction", corrects_event_id="evt-0042"))
        self.assertEqual(caught.exception.code, "unknown_event_reference")


class FailureTest(ServiceTestCase):
    """The failure cases listed in Part 3 of the assignment."""

    def sessions_dir(self) -> Path:
        return Path(self.tmp.name) / "sessions"

    def test_no_packets_arriving(self):
        session_id = self.start()
        self.assertEqual(self.service.status()["recorder"]["state"], "waiting_for_packets")
        self.assertEqual(self.service.live(session_id, None)["channels"]["TP9"]["elapsed_s"], [])
        result = self.service.end_session(session_id, {"outcome": "incomplete", "reason": "no packets"})
        self.assertEqual((result["rows_written"], result["recording_status"]), (0, "complete"))
        summary = self.service.summary(session_id)
        self.assertEqual(summary["outcome"], "incomplete")
        self.assertEqual(summary["check"]["total_rows"], 0)
        self.assertEqual(summary["windows"]["total"], 0)
        self.assertIsNone(summary["review_bundle"]["url"])

    def test_missing_channel(self):
        session_id = self.start()
        self.feed(range(0, 520), channels=("TP9", "AF7", "TP10"))  # about 24 s, AF8 silent
        status = self.service.status()
        recent = {channel["name"]: channel["recent_packets"] for channel in status["channels"]}
        self.assertEqual(recent, {"TP9": True, "AF7": True, "AF8": False, "TP10": True})
        self.assertEqual(status["recorder"]["samples_per_channel"]["AF8"], 0)
        self.service.end_session(session_id, {"outcome": "incomplete", "reason": "AF8 silent"})
        summary = self.service.summary(session_id)
        self.assertEqual(summary["check"]["rows_per_channel"]["AF8"], 0)
        self.assertEqual(summary["windows"]["valid"], 0)
        self.assertTrue(all(
            any("AF8" in reason for reason in window["reasons"]) for window in summary["windows"]["invalid"]
        ))

    def wait_rejected(self, count):
        wait_for(lambda: self.service._active.rejected_packets == count)

    def test_malformed_packet_is_skipped_and_logged(self):
        session_id = self.start()
        self.feed(range(0, 3))
        self.service.on_scanner_line("EEG_PACKET,TP9,3,123,not-a-number")
        self.wait_rejected(1)
        self.feed(range(4, 6))
        recorder = self.service.status()["recorder"]
        self.assertEqual(recorder["state"], "recording")
        self.assertIn("PacketFormatError", recorder["last_rejection"])
        result = self.service.end_session(session_id, {"outcome": "completed"})
        self.assertEqual((result["recording_status"], result["rows_written"]), ("complete", 5 * 4 * 12))
        summary = self.service.summary(session_id)
        self.assertEqual(summary["rejected_packets"]["count"], 1)
        self.assertEqual(summary["rejected_packets"]["examples"][0]["line"], "EEG_PACKET,TP9,3,123,not-a-number")
        self.assertEqual(summary["check"]["missing_packets"], [{"packet_index": 3, "channels": list(CHANNELS)}])
        self.assertTrue(summary["check"]["ok"])

    def test_repeated_packet_is_dropped_without_losing_data(self):
        session_id = self.start()
        self.feed(range(0, 3))
        self.service.on_scanner_line(packet_line("AF7", 2))
        self.wait_rejected(1)
        self.feed(range(3, 5))
        self.service.end_session(session_id, {"outcome": "completed"})
        summary = self.service.summary(session_id)
        self.assertIn("DuplicatePacketError", summary["rejected_packets"]["examples"][0]["reason"])
        self.assertEqual(summary["check"]["rows_per_channel"], dict.fromkeys(CHANNELS, 5 * 12))
        self.assertEqual(summary["check"]["duplicate_samples"], [])

    def test_out_of_order_packet_is_skipped(self):
        session_id = self.start()
        self.feed([0, 1, 3])
        self.service.on_scanner_line(packet_line("TP9", 2))  # arrives after packet 3
        self.wait_rejected(1)
        self.service.end_session(session_id, {"outcome": "completed"})
        summary = self.service.summary(session_id)
        self.assertIn("InvalidRecordError", summary["rejected_packets"]["examples"][0]["reason"])
        self.assertEqual(summary["check"]["rows_per_channel"]["TP9"], 3 * 12)
        self.assertTrue(summary["check"]["ok"])

    def test_long_run_of_rejected_packets_interrupts(self):
        session_id = self.start()
        self.feed(range(0, 3))
        for _ in range(dashboard_service.MAX_CONSECUTIVE_REJECTED):
            self.service.on_scanner_line("EEG_PACKET,TP9,garbage")
        wait_for(lambda: self.service._active.state == "interrupted")
        self.assertIn("TooManyRejectedPacketsError", self.service.status()["recorder"]["stop_reason"])
        result = self.service.end_session(session_id, {"outcome": "aborted", "reason": "stream unusable"})
        self.assertEqual((result["recording_status"], result["rows_written"]), ("interrupted", 3 * 4 * 12))
        saved = read_session(self.sessions_dir() / session_id)
        self.assertEqual(len(saved.records), 3 * 4 * 12)

    def test_existing_session_id_is_never_reused(self):
        existing = self.sessions_dir() / "ses-aaaaaaaa"
        existing.mkdir(parents=True)
        (existing / "keep.txt").write_text("untouched")
        letters = iter("a" * 8 + "b" * 8)

        class FakeSecrets:
            @staticmethod
            def choice(alphabet):
                return next(letters)

        original = dashboard_service.secrets
        dashboard_service.secrets = FakeSecrets
        try:
            session_id = self.start()
        finally:
            dashboard_service.secrets = original
        self.assertEqual(session_id, "ses-bbbbbbbb")
        self.assertEqual((existing / "keep.txt").read_text(), "untouched")

    def test_browser_disconnect_does_not_stop_recording(self):
        # The backend never depends on the browser: no polls, no events, still recording.
        session_id = self.start()
        self.feed(range(0, 5))
        recorder = self.service.status()["recorder"]
        self.assertEqual((recorder["state"], recorder["session_id"]), ("recording", session_id))
        # A reopened dashboard finds the session through /api/status and can end it.
        self.feed(range(5, 8))
        result = self.service.end_session(session_id, {"outcome": "incomplete", "reason": "browser closed"})
        self.assertEqual(result["rows_written"], 8 * 4 * 12)

    def test_backend_stopping_marks_session_interrupted(self):
        session_id = self.start()
        self.feed(range(0, 3))
        self.service.shutdown()
        metadata = read_session(self.sessions_dir() / session_id).metadata
        self.assertEqual(metadata["status"], "interrupted")
        self.assertIn("backend was stopped", metadata["stop_reason"])
        self.assertEqual(metadata["eeg_row_count"], 3 * 4 * 12)

    def test_second_session_starts_clean(self):
        first = self.start()
        self.feed(range(0, 5))
        self.service.add_event(first, event("first-1"))
        self.service.end_session(first, {"outcome": "completed"})

        second = self.start()
        self.assertEqual(self.service.status()["recorder"]["rows_written"], 0)
        self.assertEqual(self.service.live(second, None)["channels"]["TP9"]["elapsed_s"], [])
        self.feed(range(100, 102))
        _, saved = self.service.add_event(second, event("second-1"))
        self.assertEqual(saved["event_id"], "evt-0001")
        self.assertEqual(self.service.live(second, None)["channels"]["TP9"]["elapsed_s"][0], 0.0)
        self.service.end_session(second, {"outcome": "completed"})

        summary = self.service.summary(second)
        self.assertEqual(summary["check"]["total_rows"], 2 * 4 * 12)
        self.assertEqual(summary["check"]["duplicate_samples"], [])
        self.assertEqual([e["client_ref"] for e in self.service.events(second)["events"]], ["second-1"])
        self.assertEqual(self.service.summary(first)["check"]["total_rows"], 5 * 4 * 12)


class HttpTest(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service, None))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, method, path, body=None, origin=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if origin:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.headers, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read())

    def test_errors_use_the_agreed_shape(self):
        status, _, body = self.request("GET", "/api/sessions/ses-nosuchid")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "session_not_found")
        status, _, body = self.request("POST", "/api/sessions/ses-nosuchid/end", {"outcome": "done"})
        self.assertEqual((status, body["error"]["code"]), (400, "invalid_request"))

    def test_cors_only_for_local_origins(self):
        _, headers, _ = self.request("GET", "/api/status", origin="http://localhost:5173")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        _, headers, _ = self.request("GET", "/api/status", origin="https://example.com")
        self.assertIsNone(headers["Access-Control-Allow-Origin"])

    def test_fake_controls_need_fake_headset(self):
        status, _, body = self.request("POST", "/api/fake/disconnect")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
