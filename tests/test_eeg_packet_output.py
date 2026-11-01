"""Checks the scanner's EEG_PACKET output without a headset.

Builds muse2-c/tests/emit_packets.c, which sends known packets through the real
C callback, and reads its stdout through a pipe the way a recorder would.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

MUSE2_C = Path(__file__).resolve().parents[1] / "muse2-c"
PACKET_LINE = re.compile(r"EEG_PACKET,(TP9|AF7|AF8|TP10),\d+,\d+(,-?\d+\.\d{8}){12}")
RECEIPT_NS = 1234567890123
READ_TIMEOUT_S = 5.0

REAL_RAW = [2092, 1605, 1737, 2243, 2234, 1736, 1648, 2129, 2340, 1855, 1599, 2031]
EXTREME_RAW = [0, 4095] * 6


def expected_line(channel: str, packet_index: int, raw_values: list[int]) -> str:
    microvolts = [(raw - 2048) * 0.48828125 for raw in raw_values]
    values = ",".join(f"{value:.8f}" for value in microvolts)
    return f"EEG_PACKET,{channel},{packet_index},{RECEIPT_NS},{values}"


EXPECTED_PACKET_LINES = [
    expected_line("TP9", 93, REAL_RAW),
    expected_line("AF7", 93, REAL_RAW),
    expected_line("AF8", 93, REAL_RAW),
    expected_line("TP10", 65535, EXTREME_RAW),
]


def read_until_last_packet(process: subprocess.Popen) -> str:
    """Reads stdout without ever waiting for the program to exit."""
    output = b""
    deadline = time.monotonic() + READ_TIMEOUT_S
    fd = process.stdout.fileno()
    while b"EEG_PACKET,TP10," not in output or not output.endswith(b"\n"):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise AssertionError(f"Packet lines did not arrive promptly: {output!r}")
        chunk = os.read(fd, 65536)
        if not chunk:
            raise AssertionError(f"Output ended early: {output!r}")
        output += chunk
    return output.decode()


@unittest.skipUnless(shutil.which("clang"), "needs clang to build the C test program")
class EegPacketOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as build_dir:
            program = Path(build_dir) / "emit_packets"
            subprocess.run(
                [
                    "clang", "-Wall", "-Wextra", "-Werror", "-std=c11",
                    str(MUSE2_C / "tests" / "emit_packets.c"),
                    str(MUSE2_C / "src" / "muse2_events.c"),
                    str(MUSE2_C / "src" / "muse2_decode.c"),
                    "-o", str(program),
                ],
                check=True,
            )
            process = subprocess.Popen(
                [str(program)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            try:
                cls.prompt_output = read_until_last_packet(process)
                cls.still_running = process.poll() is None
            finally:
                process.stdin.close()
                process.stdout.close()
                process.wait(timeout=READ_TIMEOUT_S)
        cls.lines = cls.prompt_output.splitlines()
        cls.packet_lines = [line for line in cls.lines if line.startswith("EEG_PACKET,")]

    def test_lines_arrive_while_the_program_is_still_running(self):
        self.assertTrue(self.still_running)

    def test_packet_lines_match_known_answers(self):
        self.assertEqual(self.packet_lines, EXPECTED_PACKET_LINES)

    def test_packet_lines_have_the_agreed_format(self):
        for line in self.packet_lines:
            self.assertIsNotNone(PACKET_LINE.fullmatch(line), line)
            fields = line.split(",")
            self.assertEqual(len(fields), 16)
            self.assertEqual(fields[3], str(RECEIPT_NS))
            self.assertEqual(len(fields[4:]), 12)

    def test_rejected_packets_produce_no_packet_line(self):
        self.assertEqual(len(self.packet_lines), 4)
        self.assertIn("Received EEG packet with unexpected length: 19 bytes", self.lines)
        self.assertIn("Received EEG packet with unexpected length: 21 bytes", self.lines)
        self.assertIn("Received EEG packet with NULL input.", self.lines)
        self.assertTrue(any("unknown characteristic" in line for line in self.lines))

    def test_aux_never_produces_a_packet_line(self):
        self.assertFalse(any(line.startswith("EEG_PACKET,AUX") for line in self.lines))

    def test_debug_lines_cannot_be_mistaken_for_packet_lines(self):
        debug_lines = [line for line in self.lines if line not in self.packet_lines]
        self.assertTrue(debug_lines)
        for line in debug_lines:
            self.assertFalse(line.startswith("EEG_PACKET,"), line)
            self.assertIsNone(PACKET_LINE.fullmatch(line), line)

    def test_old_graph_lines_are_kept_and_separate(self):
        graph_lines = [line for line in self.lines if line.startswith("EEG,")]
        self.assertIn("EEG,TP9,93,21.4844", graph_lines)
        self.assertIn("EEG,TP10,65535,-1000.0000", graph_lines)
        for line in graph_lines:
            self.assertEqual(len(line.split(",")), 4)


if __name__ == "__main__":
    unittest.main()
