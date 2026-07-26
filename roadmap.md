# Muse C Project Roadmap

## Goal

Build a low-level C/macOS implementation that connects directly to a Muse EEG headset, receives Bluetooth packets, decodes the raw Muse protocol, and makes the decoded EEG data available to a C project.

The goal is **not** to depend on `muselsl` at runtime. Instead, `muselsl` will be used as a reference implementation so this project can recreate the important parts in C / Objective-C.

---

## Current Status

- [x] Confirmed Muse headset can stream successfully using `muselsl`
- [x] Confirmed Python can read live EEG samples through LSL
- [x] Located installed `muselsl` source code through `pipx`
- [x] Opened `muselsl` source in VS Code
- [x] Identify exact files/functions responsible for Muse BLE connection
- [x] Identify exact files/functions responsible for packet decoding
- [x] Recreate BLE scanning/connection in macOS code
- [x] Recreate Muse packet decoder in C
- [x] Stream decoded samples into the C project

---

## Reference Source Location

`muselsl` is installed with `pipx`, not inside the local project `.venv`.

Actual source folder:

```bash
/Users/zachgoldwyn/.local/pipx/venvs/muselsl/lib/python3.12/site-packages/muselsl
```

Open it with:

```bash
code "/Users/zachgoldwyn/.local/pipx/venvs/muselsl/lib/python3.12/site-packages/muselsl"
```

Useful commands:

```bash
which muselsl
pipx list
pipx runpip muselsl show muselsl
```

---

# Project Architecture

## Target Pipeline

```text
Muse headset
   ↓ BLE
macOS Bluetooth bridge
   ↓ raw notification bytes
C Muse packet decoder
   ↓ decoded EEG samples
C project / game / experiment logic
```

## Planned File Structure

```text
muse-c/
  README.md
  Makefile

  src/
    main.c
    muse_decode.c
    muse_decode.h
    muse_ble_bridge.m
    muse_ble_bridge.h

  notes/
    muselsl_findings.md
    packet_examples.md
    uuid_reference.md

  tests/
    test_decode.c
```

## Language Split

The project should probably use:

```text
Objective-C / CoreBluetooth:
  BLE scanning
  BLE connection
  GATT service discovery
  characteristic subscription
  raw packet notifications

Pure C:
  Muse packet decoding
  sample scaling
  data structs
  project/game logic
```

Reason: macOS BLE access is easiest through Apple’s CoreBluetooth framework, which is Objective-C based. The actual Muse protocol decoder can still be pure C.

---

# Phase 1 — Understand `muselsl`

## 1. Locate key files

Search inside the opened `muselsl` folder for:

```text
Muse
EEG
273e
subscribe
notification
decode
unpack
control
start
```

Checklist:

- [ ] Find the file that defines the `Muse` class
- [ ] Find the BLE backend file
- [ ] Find the EEG callback function
- [ ] Find where `muselsl stream` starts the Muse
- [ ] Find where Muse control commands are sent
- [ ] Find where EEG packets are decoded
- [ ] Find where values are scaled into microvolts
- [ ] Find where LSL output is created

Likely files to inspect:

```text
muse.py
stream.py
backends.py
constants.py
```

Exact filenames may vary, so search by behavior, not just filename.

---

## 2. Record Muse UUIDs

Create:

```text
notes/uuid_reference.md
```

Fill it with the UUIDs found in `muselsl`.

Checklist:

- [ ] Muse service UUID
- [ ] Control characteristic UUID
- [ ] EEG channel characteristic UUIDs
- [ ] Battery characteristic UUID
- [ ] Telemetry characteristic UUID
- [ ] Accelerometer characteristic UUID
- [ ] Gyroscope characteristic UUID, if present

Known style of Muse UUIDs:

```text
273eXXXX-4c4d-454d-96be-f03bac821358
```

Likely EEG characteristics:

```text
273e0003-4c4d-454d-96be-f03bac821358
273e0004-4c4d-454d-96be-f03bac821358
273e0005-4c4d-454d-96be-f03bac821358
273e0006-4c4d-454d-96be-f03bac821358
```

Do not rely only on memory. Confirm these from the installed `muselsl` source.

---

## 3. Identify the control/start command

Muse will not necessarily stream data just because the program connects to it. `muselsl` sends one or more commands to start streaming.

Checklist:

- [ ] Find the function that sends commands to the Muse
- [ ] Find the exact command used to start EEG streaming
- [ ] Find the command used to stop streaming
- [ ] Find whether commands need to be encoded with a length prefix
- [ ] Find whether commands are sent as bytes, ASCII, or JSON-like strings
- [ ] Save findings in `notes/muselsl_findings.md`

Questions to answer:

```text
What characteristic receives commands?
What bytes are written to start EEG?
What bytes are written to stop EEG?
Does the Muse send an ACK/response?
Does the command differ by Muse model?
```

---

## 4. Identify EEG packet format

Create:

```text
notes/packet_examples.md
```

Checklist:

- [ ] Find the EEG notification callback
- [ ] Print or inspect raw notification bytes
- [ ] Confirm packet length
- [ ] Confirm timestamp size
- [ ] Confirm sample packing format
- [ ] Confirm number of samples per packet
- [ ] Confirm conversion/scaling formula
- [ ] Confirm channel order

Expected classic format:

```text
20-byte EEG packet:
  2 bytes timestamp
  18 bytes packed sample data

18 bytes = 12 samples × 12 bits
```

Do not assume this blindly. Verify against the exact `muselsl` version that works with the headset.

---

# Phase 2 — Build Pure C Decoder

## 1. Create decoder files

Create:

```text
src/muse_decode.h
src/muse_decode.c
tests/test_decode.c
```

Checklist:

- [ ] Define `MuseEegPacket`
- [ ] Define channel enum
- [ ] Decode timestamp
- [ ] Decode 12 packed 12-bit samples
- [ ] Return error on invalid packet length
- [ ] Add scaling function if needed
- [ ] Add unit test using known packet bytes

Example data structure:

```c
typedef struct {
    unsigned short timestamp;
    unsigned short raw_samples[12];
    float scaled_samples[12];
} MuseEegPacket;
```

---

## 2. Write first decoder

Minimum goal:

```text
Input:
  raw 20-byte EEG notification

Output:
  timestamp
  12 raw sample values
```

Checklist:

- [ ] Decode two samples from every three bytes
- [ ] Print all 12 samples
- [ ] Compare output with `muselsl` behavior
- [ ] Adjust byte order if needed
- [ ] Adjust signed/unsigned interpretation if needed
- [ ] Add scaling only after raw decode is confirmed

---

## 3. Save real packet examples

Modify or instrument `muselsl` temporarily to print raw packet bytes as hex.

Example desired note format:

```text
Channel: TP9
Raw packet:
12 34 80 00 80 81 00 82 ...

Decoded:
timestamp = ...
samples = ...
```

Checklist:

- [ ] Capture at least 5 packets from each EEG channel
- [ ] Save raw hex in `notes/packet_examples.md`
- [ ] Use those packets as test cases for the C decoder
- [ ] Confirm C decoder output matches the Python decoder

---

# Phase 3 — Build macOS BLE Scanner

## 1. Create BLE bridge files

Create:

```text
src/muse_ble_bridge.h
src/muse_ble_bridge.m
```

Checklist:

- [ ] Import Foundation
- [ ] Import CoreBluetooth
- [ ] Create `CBCentralManager`
- [ ] Wait for Bluetooth powered-on state
- [ ] Scan for BLE peripherals
- [ ] Print discovered device names
- [ ] Detect device name beginning with `Muse`
- [ ] Stop scan after finding Muse

Success condition:

```text
Found Muse device: Muse-3785
```

---

## 2. Add build command

Create a `Makefile`.

Minimum compile shape:

```bash
clang src/main.c src/muse_decode.c src/muse_ble_bridge.m \
  -framework Foundation \
  -framework CoreBluetooth \
  -o muse_c
```

Checklist:

- [ ] Compile Objective-C bridge with `clang`
- [ ] Link Foundation framework
- [ ] Link CoreBluetooth framework
- [ ] Confirm terminal app has Bluetooth permission if macOS asks
- [ ] Run binary and print nearby BLE devices

---

# Phase 4 — Connect to Muse

## 1. Connect to selected device

Checklist:

- [ ] Save discovered `CBPeripheral`
- [ ] Connect to Muse
- [ ] Set peripheral delegate
- [ ] Print connection success
- [ ] Handle disconnects
- [ ] Handle connection failures

Success condition:

```text
Connected to Muse-3785
```

---

## 2. Discover services and characteristics

Checklist:

- [ ] Discover Muse service
- [ ] Print all services
- [ ] Print all characteristics
- [ ] Confirm expected `273e...` UUIDs appear
- [ ] Save actual UUID dump in `notes/uuid_reference.md`

Success condition:

```text
Found Muse service
Found control characteristic
Found EEG characteristic TP9
Found EEG characteristic AF7
Found EEG characteristic AF8
Found EEG characteristic TP10
```

---

# Phase 5 — Start Streaming

## 1. Subscribe to characteristics

Checklist:

- [ ] Subscribe to EEG characteristic 1
- [ ] Subscribe to EEG characteristic 2
- [ ] Subscribe to EEG characteristic 3
- [ ] Subscribe to EEG characteristic 4
- [ ] Confirm notification callback fires
- [ ] Print raw bytes as hex

Success condition:

```text
EEG notification:
12 34 80 00 80 ...
```

---

## 2. Send Muse start command

Checklist:

- [ ] Write command to control characteristic
- [ ] Confirm write succeeds
- [ ] Confirm Muse begins sending EEG notifications
- [ ] Confirm stop command works
- [ ] Confirm reconnect works after stopping

Possible failure cases:

```text
Connected but no data:
  probably did not send start command correctly

Start command fails:
  wrong control characteristic or wrong command encoding

Notifications fail:
  not subscribed to characteristics or permissions issue
```

---

# Phase 6 — Decode Live Data

## 1. Route BLE notifications into decoder

When CoreBluetooth receives a packet:

```text
didUpdateValueForCharacteristic
```

Pass the bytes to the C decoder.

Checklist:

- [ ] Identify which channel the characteristic belongs to
- [ ] Pass raw bytes to `muse_decode_eeg_packet`
- [ ] Print timestamp and decoded samples
- [ ] Print channel name
- [ ] Compare rough values against `muselsl`

Success condition:

```text
TP9 timestamp=12345 samples=[...]
AF7 timestamp=12345 samples=[...]
AF8 timestamp=12345 samples=[...]
TP10 timestamp=12345 samples=[...]
```

---

## 2. Convert raw samples to usable values

Checklist:

- [ ] Confirm `muselsl` scaling formula
- [ ] Implement scaling in C
- [ ] Confirm C values match `muselsl` values approximately
- [ ] Store values as `float`
- [ ] Track sample timestamps

Success condition:

```text
TP9: -11.72 uV
AF7: 47.85 uV
AF8: 176.27 uV
TP10: -37.11 uV
```

---

# Phase 7 — Make Data Useful for Project

## 1. Create stream state

Create a shared data structure:

```c
typedef struct {
    float tp9;
    float af7;
    float af8;
    float tp10;
    unsigned short timestamp;
} MuseSample;
```

Checklist:

- [ ] Store latest sample from each channel
- [ ] Keep a ring buffer of recent samples
- [ ] Track dropped packets
- [ ] Track connection status
- [ ] Track last update time

---

## 2. Add simple signal processing

Initial features:

- [ ] Moving average
- [ ] Signal magnitude
- [ ] Threshold detection
- [ ] Baseline calibration
- [ ] Artifact detection
- [ ] Simple blink/jaw/forehead movement detection if useful

Possible first control signal:

```text
If signal magnitude crosses threshold:
  trigger action
else:
  no action
```

---

## 3. Connect to C game/project

Checklist:

- [ ] Define control events
- [ ] Map signal event to action
- [ ] Add debounce/cooldown
- [ ] Avoid repeated triggering from one movement
- [ ] Print debug info
- [ ] Test with intentional movement/blink/jaw clench

Example events:

```c
typedef enum {
    MUSE_EVENT_NONE,
    MUSE_EVENT_TRIGGER,
    MUSE_EVENT_LEFT,
    MUSE_EVENT_RIGHT
} MuseEvent;
```

---

# Debugging Checklist

## Muse not found

- [ ] Is the headset powered on?
- [ ] Is the headset already connected to another app?
- [ ] Is `muselsl stream` still running somewhere?
- [ ] Is Bluetooth enabled?
- [ ] Did macOS give Bluetooth permission to Terminal or VS Code?
- [ ] Is the Muse charged?
- [ ] Does `muselsl list` or `muselsl stream` still find it?

---

## Muse connects but no packets arrive

- [ ] Did you discover the correct service?
- [ ] Did you subscribe to the EEG characteristics?
- [ ] Did you send the start command?
- [ ] Was the command encoded correctly?
- [ ] Did the write go to the control characteristic?
- [ ] Is another process already connected to Muse?
- [ ] Did the Muse disconnect silently?

---

## Packets arrive but decode is wrong

- [ ] Confirm packet length
- [ ] Confirm endian format
- [ ] Confirm 12-bit packing
- [ ] Confirm signed vs unsigned sample interpretation
- [ ] Confirm offset/scaling formula
- [ ] Compare against raw packet examples from `muselsl`
- [ ] Test one packet by hand

---

## Values look noisy

- [ ] Check electrode contact
- [ ] Wet/adjust sensors if needed
- [ ] Keep headset still
- [ ] Check whether one channel is disconnected
- [ ] Add smoothing
- [ ] Add artifact filtering
- [ ] Compare with `muselsl` live output

---

# Development Rules

## Rule 1 — Do not build everything at once

Each step should have a visible success condition.

Bad milestone:

```text
Build Muse C driver
```

Good milestone:

```text
Print raw BLE packet bytes from TP9
```

---

## Rule 2 — Keep `muselsl` as a reference only

Use `muselsl` to answer:

```text
What UUIDs are used?
What command starts streaming?
How are packets decoded?
How are samples scaled?
```

But the final project should connect to the Muse directly.

---

## Rule 3 — First match raw behavior, then improve

Before adding filters, controls, or game logic:

- [ ] Raw packets match expected length
- [ ] Decoded samples match expected ranges
- [ ] Scaled values roughly match `muselsl`
- [ ] All four EEG channels work

---

## Rule 4 — Save notes aggressively

Every time something is discovered in `muselsl`, write it down.

Use:

```text
notes/muselsl_findings.md
notes/uuid_reference.md
notes/packet_examples.md
```

Future you should not have to rediscover the same protocol details.

---

# Immediate Next Steps

## Right now

- [ ] Open the `muselsl` source folder in VS Code
- [ ] Search for `273e`
- [ ] Search for `subscribe`
- [ ] Search for `unpack`
- [ ] Search for `start`
- [ ] Find the EEG callback function
- [ ] Find the Muse command/start-stream logic
- [ ] Write notes in `notes/muselsl_findings.md`

## After that

- [ ] Create `src/muse_decode.c`
- [ ] Create `src/muse_decode.h`
- [ ] Create `tests/test_decode.c`
- [ ] Copy one real raw packet from `muselsl`
- [ ] Decode it in C
- [ ] Compare decoded values with Python

## First major win

The first major success target is:

```text
My own C decoder can decode one real Muse EEG packet captured from muselsl.
```

## Second major win

The second major success target is:

```text
My own macOS program can find and connect to the Muse over BLE.
```

## Third major win

The third major success target is:

```text
My own program receives raw EEG notifications and decodes them live without muselsl.
```

---

# Final Target

The final project should be able to run something like:

```bash
make
./muse_c
```

And print live decoded EEG data:

```text
Connected to Muse-3785
Streaming EEG...

TP9  -11.72
AF7   47.85
AF8  176.27
TP10 -37.11
```

At that point, the project has recreated the core low-level functionality needed from `muselsl` and can be connected directly to the C game/project logic.