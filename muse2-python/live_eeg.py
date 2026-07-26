import subprocess
import threading
from collections import deque
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


print("Looking for an EEG stream...")


buffers = {
    "TP9": deque(maxlen=512),
    "AF7": deque(maxlen=512),
    "AF8": deque(maxlen=512),
    "TP10": deque(maxlen=512),
}


def read_eeg_stream():
    project_root = Path(__file__).resolve().parents[1]
    scanner_path = project_root / "muse2-c" / "build" / "muse2_scan"

    process = subprocess.Popen(
        [str(scanner_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if process.stdout is None:
        print("Could not read EEG scanner output.")
        return

    for line in process.stdout:
        line = line.strip()

        if not line.startswith("EEG,"):
            continue

        split_line = line.split(",")

        if len(split_line) != 4:
            print(f"Unexpected EEG line format: {line}")
            continue

        electrode = split_line[1]

        try:
            packet_index = int(split_line[2])
            microvolts = float(split_line[3])
        except ValueError:
            print(f"Error parsing line: {line}")
            continue

        if electrode in buffers:
            buffers[electrode].append(microvolts)


if __name__ == "__main__":
    app = QApplication([])

    window = pg.GraphicsLayoutWidget(title="Muse 2 Live EEG")
    window.resize(1000, 800)

    curves = {}

    for row, channel in enumerate(buffers):
        plot = window.addPlot(
            row=row,
            col=0,
            title=channel,
        )

        plot.setLabel(
            "left",
            "Amplitude",
            units="uV",
        )

        plot.setLabel(
            "bottom",
            "Recent packets",
        )

        plot.showGrid(
            x=True,
            y=True,
        )

        curves[channel] = plot.plot()

    def update_graphs():
        for channel, values in buffers.items():
            curves[channel].setData(list(values))

    timer = QTimer(window)
    timer.timeout.connect(update_graphs)
    timer.start(30)

    reader_thread = threading.Thread(
        target=read_eeg_stream,
        daemon=True,
    )

    reader_thread.start()

    window.show()
    app.exec()