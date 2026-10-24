# Muse 2 EEG Bridge

A macOS application that streams live EEG data from a Muse 2 headset over Bluetooth Low Energy, decodes the raw packets in C, and visualizes the signals in Python.
<img width="1112" height="944" alt="Screenshot 2026-07-28 at 6 22 48 PM" src="https://github.com/user-attachments/assets/01650731-bf16-4cc3-81f4-29df52d2ade7" />

## Overview

This project implements a direct Muse 2 EEG pipeline without relying on `muselsl` during live acquisition.

```text
Muse 2 headset
    ↓ Bluetooth Low Energy
Objective-C CoreBluetooth bridge
    ↓ raw 20-byte EEG packets
C packet decoder
    ↓ machine-readable EEG output
Python + PyQtGraph
    ↓
Live four-channel visualization
```

## CS+AI Research Project

This repository is also the shared codebase for a CS+AI student research project on trustworthy analysis of consumer EEG. The team will build on the working Muse 2 acquisition pipeline to investigate this question:

> On unseen recording sessions, does agreement between mathematical and machine-learning artifact detectors identify reliable Muse 2 EEG more accurately than either method alone?

The primary goal is to collect and independently label EEG artifacts, compare interpretable signal-processing rules with a trained model, and measure both accuracy and retained usable data. If time and data permit, the team will test whether artifact-aware processing improves a controlled mental-workload analysis. Agreement between two detectors is a hypothesis to evaluate, not proof that a signal is clean.

The initial semester scope is:

1. Preserve and document the working recorder.
2. Save synchronized EEG, session metadata, and event markers.
3. Create reviewed labels for blinks, jaw or muscle activity, head movement, and headset disturbance.
4. Compare a mathematical detector, a machine-learning detector, and an agreement-based policy on held-out sessions.
5. Build a local browser interface for guided recording and evaluated replay.

Live predictions and broader mental-state claims are stretch goals. Raw or identifiable participant recordings must not be committed to this repository.

The four primary EEG channels are:

- TP9
- AF7
- AF8
- TP10

## Current Features

- Discovers and connects to a Muse 2 on macOS
- Uses CoreBluetooth to discover Muse services and characteristics
- Subscribes to the four primary EEG characteristics
- Starts the Muse EEG stream
- Passes raw BLE packets from Objective-C into C
- Decodes Muse packet indices and packed 12-bit EEG samples
- Converts raw values to microvolts
- Emits machine-readable output such as:

```text
EEG,TP9,81,-60.5469
EEG,AF7,81,-284.1797
```

- Reads the stream from Python using `subprocess`
- Stores recent values in bounded rolling buffers
- Displays live EEG graphs with PyQtGraph

## Repository Structure

```text
MuseProject/
├── README.md
├── muse2-c/
│   ├── Makefile
│   ├── include/
│   │   ├── muse2_ble.h
│   │   ├── muse2_constants.h
│   │   ├── muse2_decode.h
│   │   └── muse2_ringbuffer.h
│   ├── src/
│   │   ├── muse2_ble.m
│   │   ├── muse2_decode.c
│   │   └── muse2_events.c
│   └── tests/
└── muse2-python/
    └── live_eeg.py
```

## Requirements

### macOS Acquisition Layer

- macOS with Bluetooth enabled
- Apple Clang
- Foundation framework
- CoreBluetooth framework
- Muse 2 headset

### Python Visualization

- Python 3
- PySide6
- PyQtGraph

## Contributing

New contributors should begin with the exercise in [`docs/bootcamp/readme.md`](docs/bootcamp/readme.md). The team workflow is:

1. Start from an up-to-date `main` branch.
2. Create one short-lived branch for one task.
3. Make a focused change and test it locally.
4. Open a pull request describing what changed and how it was checked.
5. Request review before merging into `main`.

Do not commit virtual environments, build products, Finder metadata, generated recordings, or participant data. Preserve raw research data separately from processed outputs, and do not change labels or evaluation data to make a model perform better.

## Build the Scanner

From the `muse2-c` directory:

```bash
make scan
```

The executable is created at:

```text
muse2-c/build/muse2_scan
```

Run it directly with:

```bash
./build/muse2_scan
```

Stop the program with `Ctrl+C`.

## Set Up the Python Environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install pyqtgraph PySide6
```

## Run the Live EEG Graph

First build the scanner, then run:

```bash
python3 muse2-python/live_eeg.py
```

The Python application launches the scanner as a subprocess and displays rolling graphs for TP9, AF7, AF8, and TP10.

## Packet Decoding

Each Muse EEG notification contains 20 bytes:

- Bytes `0-1`: big-endian packet index
- Bytes `2-19`: twelve packed 12-bit EEG samples

The decoded raw values are converted to microvolts using:

```text
microvolts = (raw - 2048) × 0.48828125
```

## Project Status

The acquisition and visualization pipeline is working as a research prototype. The CS+AI research work is beginning with team onboarding, recorder documentation, experiment design, and data-contract planning.

Planned improvements include:

- Outputting all 12 samples from each EEG packet
- Detecting packet loss and sequence gaps
- Improving subprocess shutdown
- Adding automatic reconnection
- Adding signal-quality indicators
- Recording EEG sessions to files
- Adding automated integration tests

## Safety Notice

This project is an experimental research and educational prototype.

It is not a medical device, is not safety-certified, and must not be used for diagnosis, treatment, emergency monitoring, or control of any system where failure could cause harm.

## License

No license has been selected yet. Until a license is added, the source code remains under the copyright of its author.
