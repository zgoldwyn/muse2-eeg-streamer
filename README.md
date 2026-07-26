# Muse 2 EEG Bridge

A macOS application that streams live EEG data from a Muse 2 headset over Bluetooth Low Energy, decodes the raw packets in C, and visualizes the signals in Python.

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

The acquisition and visualization pipeline is working as a research prototype.

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
