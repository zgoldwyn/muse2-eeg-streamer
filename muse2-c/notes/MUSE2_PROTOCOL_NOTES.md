# Muse 2 Protocol Notes for C/macOS Implementation

This file summarizes the `muselsl` implementation details needed to replace `muselsl` with a direct Muse 2 BLE client. The target is:

```text
Muse 2 headset
  -> macOS BLE connection
  -> raw BLE notification packets
  -> C packet decoder
  -> C project / game logic
```

The goal is to use `muselsl` only as a reference implementation, not as a runtime dependency.

---

## 0. Device Model Assumption

This project is for **Muse 2**.

In the uploaded `muselsl` source, Muse 2 uses the **legacy Muse protocol**, not the newer Athena protocol. Practically, that means:

- EEG is exposed through separate per-channel BLE characteristics.
- The useful EEG characteristics are `273e0003` through `273e0006`.
- Each EEG notification contains one channel's packet.
- Each EEG packet is 20 bytes:
  - 16-bit packet index
  - 12 packed 12-bit EEG samples
- Samples are scaled with:

```c
microvolts = 0.48828125f * (raw_sample - 2048.0f);
```

Ignore `athena.py` for Muse 2 unless a future headset exposes the Athena characteristic `273e0013`.

---

## 1. Source Files Used as Reference

From the uploaded `muselsl.zip`, these are the files that matter:

```text
muselsl/constants.py   -> UUIDs, sample rates, chunk sizes, scaling constants
muselsl/backends.py    -> BLE scan/connect/subscribe/write behavior via Bleak
muselsl/muse.py        -> Muse setup, commands, packet decoding, callbacks
muselsl/stream.py      -> high-level `muselsl stream` flow
muselsl/devices.py     -> model selection: legacy Muse vs Athena
```

Most of the implementation you need is in:

```text
constants.py
muse.py
backends.py
```

---

## 2. High-Level Flow from `muselsl`

The working flow is:

```text
scan for BLE devices
  -> find Muse by name/address
  -> connect with BLE client
  -> subscribe to control characteristic
  -> optionally request device info
  -> subscribe to EEG characteristics
  -> initialize sample buffers
  -> send start/resume command "d"
  -> receive EEG notifications
  -> decode each channel packet
  -> combine channel packets
  -> output samples
```

For the C/macOS implementation, use this simpler first target:

```text
scan for Muse 2
  -> connect
  -> discover characteristics
  -> subscribe to TP9, AF7, AF8, TP10
  -> write start command to control characteristic
  -> print raw packets
  -> decode packets with C decoder
  -> print microvolt values
```

---

## 3. Core Muse 2 BLE UUIDs

Found in `muselsl/constants.py`.

### Main Control Characteristic

```text
MUSE_GATT_ATTR_STREAM_TOGGLE
273e0001-4c4d-454d-96be-f03bac821358
```

Purpose:

- Subscribe to receive control responses.
- Write control commands to start/stop/keep alive.

In `muselsl`, commands are written through handle `0x000e`, which corresponds to the value handle for this stream-toggle/control characteristic. In CoreBluetooth, prefer using the characteristic UUID instead of hard-coding the numeric handle.

---

### EEG Characteristics

Muse 2 legacy EEG channels:

| Channel | UUID | Notes |
|---|---|---|
| TP9 | `273e0003-4c4d-454d-96be-f03bac821358` | left ear |
| AF7 | `273e0004-4c4d-454d-96be-f03bac821358` | left forehead |
| AF8 | `273e0005-4c4d-454d-96be-f03bac821358` | right forehead |
| TP10 | `273e0006-4c4d-454d-96be-f03bac821358` | right ear |
| Right AUX | `273e0007-4c4d-454d-96be-f03bac821358` | optional, skip first |

For your first implementation, subscribe only to:

```text
273e0003 TP9
273e0004 AF7
273e0005 AF8
273e0006 TP10
```

Do not include `RIGHTAUX` until the 4 main EEG channels work.

---

### Other Muse 2 Characteristics

Useful later, not needed for the first EEG implementation:

| Signal | UUID |
|---|---|
| Gyroscope | `273e0009-4c4d-454d-96be-f03bac821358` |
| Accelerometer | `273e000a-4c4d-454d-96be-f03bac821358` |
| Telemetry | `273e000b-4c4d-454d-96be-f03bac821358` |
| PPG ambient | `273e000f-4c4d-454d-96be-f03bac821358` |
| PPG infrared | `273e0010-4c4d-454d-96be-f03bac821358` |
| PPG red | `273e0011-4c4d-454d-96be-f03bac821358` |

---

## 4. Sample Rates and Packet Chunk Sizes

From `constants.py`:

```text
MUSE_SAMPLING_EEG_RATE = 256
LSL_EEG_CHUNK = 12
```

Meaning:

```text
EEG sample rate: 256 Hz
Samples per EEG packet per channel: 12
```

So each EEG characteristic sends packets containing **12 samples for that one channel**.

Other rates, for later:

```text
PPG: 64 Hz, chunk size 6
Accelerometer: 52 Hz, chunk size 1
Gyroscope: 52 Hz, chunk size 1
```

---

## 5. BLE Scanning and Connection Behavior

Reference: `backends.py`.

`muselsl` uses `bleak`:

```python
bleak.BleakScanner.discover(timeout)
bleak.BleakClient(address, timeout=30.0)
client.connect()
client.start_notify(uuid, callback)
client.write_gatt_char(...)
```

In macOS CoreBluetooth, the equivalent flow is:

```objc
CBCentralManager
  -> scanForPeripheralsWithServices:nil options:nil
  -> centralManager:didDiscoverPeripheral:advertisementData:RSSI:
  -> connectPeripheral:options:
  -> centralManager:didConnectPeripheral:
  -> peripheral.delegate = self
  -> discoverServices:nil
  -> peripheral:didDiscoverServices:
  -> discoverCharacteristics:nil forService:service
  -> peripheral:didDiscoverCharacteristicsForService:error:
```

Then, for each characteristic:

```objc
[peripheral setNotifyValue:YES forCharacteristic:characteristic];
```

Incoming packets arrive in:

```objc
- (void)peripheral:(CBPeripheral *)peripheral
 didUpdateValueForCharacteristic:(CBCharacteristic *)characteristic
              error:(NSError *)error
```

That callback is where raw BLE bytes enter your program.

---

## 6. Control Command Encoding

Reference: `muse.py`.

`muselsl` has:

```python
def _write_cmd(self, cmd):
    self.device.char_write_handle(0x000e, cmd, False)

def _write_cmd_str(self, cmd):
    self._write_cmd([len(cmd) + 1, *(ord(char) for char in cmd), ord('\n')])
```

The command format is:

```text
[length including newline] [ASCII command bytes] [newline]
```

Examples:

| Command | Meaning | Encoded bytes |
|---|---|---|
| `d` | start/resume streaming | `02 64 0A` |
| `h` | stop/halt streaming | `02 68 0A` |
| `k` | keep alive | `02 6B 0A` |
| `s` | ask control/status | `02 73 0A` |
| `v1` | ask device info | `03 76 31 0A` |

### C helper for command encoding

```c
#include <stdint.h>
#include <stddef.h>
#include <string.h>

size_t muse_encode_cmd_str(const char *cmd, uint8_t *out, size_t out_capacity) {
    size_t len = strlen(cmd);
    size_t needed = len + 2; // length byte + command bytes + newline

    if (out == NULL || out_capacity < needed || len + 1 > 255) {
        return 0;
    }

    out[0] = (uint8_t)(len + 1);
    memcpy(out + 1, cmd, len);
    out[len + 1] = '\n';

    return needed;
}
```

To start Muse 2 streaming:

```c
uint8_t cmd[8];
size_t n = muse_encode_cmd_str("d", cmd, sizeof(cmd));
// write cmd[0..n-1] to control characteristic 273e0001...
```

---

## 7. Start / Stop / Keep-Alive Sequence

Reference: `muse.py`.

`start()` does this conceptually:

```text
first_sample = true
initialize EEG sample buffers
initialize PPG sample buffers
last_tm = 0
initialize control message state
resume()
```

`resume()` sends:

```text
d
```

Encoded:

```text
02 64 0A
```

`stop()` sends:

```text
h
```

Encoded:

```text
02 68 0A
```

`keep_alive()` sends:

```text
k
```

Encoded:

```text
02 6B 0A
```

For the first C version:

1. Subscribe to EEG notifications.
2. Write `02 64 0A` to the control characteristic.
3. Confirm EEG notifications arrive.
4. On exit, write `02 68 0A`.

---

## 8. Optional Preset Command

Reference: `muse.py` method `select_preset()`.

Default preset is `p21`.

The command is encoded manually like this in `muselsl`:

```python
self._write_cmd([0x04, 0x70, *preset, 0x0a])
```

For preset `21`, bytes are:

```text
04 70 32 31 0A
```

Where:

```text
04 = length of "p21\n"
70 = 'p'
32 = '2'
31 = '1'
0A = newline
```

You probably do **not** need this at first. Only add preset selection if connecting/subscribing/start does not produce data.

---

## 9. EEG Packet Format

Reference: `muse.py`, `_unpack_eeg_channel()`.

`muselsl` says:

```text
Each packet is encoded with a 16-bit timestamp followed by 12 time samples with 12-bit resolution.
```

The bit layout is:

```text
uint16 packet_index
uint12 sample_0
uint12 sample_1
uint12 sample_2
uint12 sample_3
uint12 sample_4
uint12 sample_5
uint12 sample_6
uint12 sample_7
uint12 sample_8
uint12 sample_9
uint12 sample_10
uint12 sample_11
```

Total size:

```text
16 + 12*12 = 160 bits = 20 bytes
```

So an EEG packet should be exactly:

```text
20 bytes
```

---

## 10. EEG Scaling Formula

Reference: `muse.py`, `_unpack_eeg_channel()`.

Python:

```python
data = 0.48828125 * (np.array(samples) - 2048)
```

C equivalent:

```c
float microvolts = 0.48828125f * ((float)raw_sample - 2048.0f);
```

This matches the values seen from the working LSL stream, which were multiples of `0.48828125`.

Examples:

```text
raw = 2048 -> 0.000000 uV
raw = 2049 -> 0.48828125 uV
raw = 2047 -> -0.48828125 uV
```

---

## 11. C EEG Packet Decoder

Create `src/muse_decode.h`:

```c
#ifndef MUSE_DECODE_H
#define MUSE_DECODE_H

#include <stdint.h>
#include <stddef.h>

#define MUSE_EEG_SAMPLES_PER_PACKET 12

typedef struct {
    uint16_t packet_index;
    uint16_t raw[MUSE_EEG_SAMPLES_PER_PACKET];
    float microvolts[MUSE_EEG_SAMPLES_PER_PACKET];
} MuseEegPacket;

int muse_decode_eeg_packet(const uint8_t *bytes, size_t len, MuseEegPacket *out);

#endif
```

Create `src/muse_decode.c`:

```c
#include "muse_decode.h"

int muse_decode_eeg_packet(const uint8_t *bytes, size_t len, MuseEegPacket *out) {
    if (bytes == 0 || out == 0 || len < 20) {
        return -1;
    }

    out->packet_index = ((uint16_t)bytes[0] << 8) | bytes[1];

    const uint8_t *p = bytes + 2;

    for (int i = 0; i < MUSE_EEG_SAMPLES_PER_PACKET; i += 2) {
        uint8_t b0 = p[0];
        uint8_t b1 = p[1];
        uint8_t b2 = p[2];

        uint16_t s0 = ((uint16_t)b0 << 4) | (b1 >> 4);
        uint16_t s1 = (((uint16_t)b1 & 0x0F) << 8) | b2;

        out->raw[i] = s0;
        out->raw[i + 1] = s1;

        out->microvolts[i] = 0.48828125f * ((float)s0 - 2048.0f);
        out->microvolts[i + 1] = 0.48828125f * ((float)s1 - 2048.0f);

        p += 3;
    }

    return 0;
}
```

---

## 12. Test Program for Decoder

Create `tests/test_decode.c`:

```c
#include <stdio.h>
#include <stdint.h>
#include "muse_decode.h"

int main(void) {
    // Replace this with a real 20-byte raw packet captured from Muse 2.
    uint8_t packet[20] = {
        0x00, 0x01,
        0x80, 0x08, 0x00,
        0x80, 0x08, 0x00,
        0x80, 0x08, 0x00,
        0x80, 0x08, 0x00,
        0x80, 0x08, 0x00,
        0x80, 0x08, 0x00
    };

    MuseEegPacket decoded;

    if (muse_decode_eeg_packet(packet, 20, &decoded) != 0) {
        printf("decode failed\n");
        return 1;
    }

    printf("packet_index=%u\n", decoded.packet_index);

    for (int i = 0; i < MUSE_EEG_SAMPLES_PER_PACKET; i++) {
        printf("sample[%02d] raw=%u uv=%f\n",
               i,
               decoded.raw[i],
               decoded.microvolts[i]);
    }

    return 0;
}
```

Compile:

```bash
clang -I src src/muse_decode.c tests/test_decode.c -o test_decode
./test_decode
```

Expected for the dummy packet:

```text
packet_index=1
all raw samples around 2048
all microvolt values around 0
```

---

## 13. How `muselsl` Maps Handles to Channels

Reference: `muse.py`, `_handle_eeg()`.

`muselsl` uses numeric handles from Bleak callbacks. It computes:

```python
index = int((handle - 32) / 3)
```

The comments in `constants.py` show the relevant value handle ranges:

```text
TP9       0x1f-0x21
AF7       0x22-0x24
AF8       0x25-0x27
TP10      0x28-0x2a
RIGHTAUX  0x2b-0x2d
```

`muselsl` says packets arrive in this order:

```text
44, 41, 38, 32, 35
```

And waits until handle `35` before pushing a complete sample block.

For your CoreBluetooth version, do **not** rely on numeric handles at first. Instead, map channels by characteristic UUID:

```text
273e0003 -> TP9
273e0004 -> AF7
273e0005 -> AF8
273e0006 -> TP10
```

This is simpler and more reliable on macOS.

---

## 14. Simple Channel Data Structure

Use this for live storage:

```c
typedef enum {
    MUSE_CHANNEL_TP9,
    MUSE_CHANNEL_AF7,
    MUSE_CHANNEL_AF8,
    MUSE_CHANNEL_TP10,
    MUSE_CHANNEL_UNKNOWN
} MuseChannel;

typedef struct {
    MuseChannel channel;
    MuseEegPacket packet;
} MuseChannelPacket;
```

First live output format:

```text
TP9  packet=1234  -11.72 47.85 176.27 ...
AF7  packet=1234  ...
AF8  packet=1234  ...
TP10 packet=1234  ...
```

Do not try to synchronize channels until you can decode packets from all four characteristics.

---

## 15. CoreBluetooth Implementation Plan

Use an Objective-C bridge file for BLE and pure C for decoding.

Suggested files:

```text
src/main.c
src/muse_decode.c
src/muse_decode.h
src/muse_ble_bridge.m
src/muse_ble_bridge.h
Makefile
```

### BLE bridge responsibilities

`muse_ble_bridge.m` should handle:

```text
CBCentralManager setup
Bluetooth powered-on state
scan for Muse name
connect to peripheral
discover services
discover characteristics
store control characteristic
store EEG characteristics
subscribe to EEG notifications
write command bytes to control characteristic
call C decoder on incoming packet bytes
```

### C responsibilities

Pure C should handle:

```text
packet decoding
sample scaling
ring buffers
signal processing
game/project logic
```

---

## 16. Minimal CoreBluetooth Pseudocode

```objc
// 1. Wait until central.state == CBManagerStatePoweredOn

// 2. Scan
[central scanForPeripheralsWithServices:nil options:nil];

// 3. In didDiscoverPeripheral, look for Muse
if ([peripheral.name containsString:@"Muse"]) {
    self.musePeripheral = peripheral;
    [central stopScan];
    [central connectPeripheral:peripheral options:nil];
}

// 4. On connect
peripheral.delegate = self;
[peripheral discoverServices:nil];

// 5. On service discovery
for (CBService *service in peripheral.services) {
    [peripheral discoverCharacteristics:nil forService:service];
}

// 6. On characteristic discovery
if UUID == 273e0001: save as control characteristic
if UUID == 273e0003/0004/0005/0006: subscribe

[peripheral setNotifyValue:YES forCharacteristic:eegCharacteristic];

// 7. Start streaming
uint8_t start_cmd[] = {0x02, 0x64, 0x0A};
NSData *data = [NSData dataWithBytes:start_cmd length:sizeof(start_cmd)];
[peripheral writeValue:data
     forCharacteristic:self.controlCharacteristic
                  type:CBCharacteristicWriteWithoutResponse];

// 8. On packet notification
NSData *value = characteristic.value;
const uint8_t *bytes = value.bytes;
NSUInteger len = value.length;

MuseEegPacket decoded;
if (muse_decode_eeg_packet(bytes, len, &decoded) == 0) {
    // print/store/use decoded.microvolts
}
```

---

## 17. Build Command

Basic compile shape:

```bash
clang \
  src/main.c \
  src/muse_decode.c \
  src/muse_ble_bridge.m \
  -framework Foundation \
  -framework CoreBluetooth \
  -o muse_c
```

A starter `Makefile`:

```make
CC=clang
CFLAGS=-Wall -Wextra -I src
FRAMEWORKS=-framework Foundation -framework CoreBluetooth

SRC=src/main.c src/muse_decode.c src/muse_ble_bridge.m
OUT=muse_c

all:
	$(CC) $(CFLAGS) $(SRC) $(FRAMEWORKS) -o $(OUT)

clean:
	rm -f $(OUT) test_decode

test_decode:
	$(CC) $(CFLAGS) src/muse_decode.c tests/test_decode.c -o test_decode
	./test_decode
```

---

## 18. How to Capture Real Raw Packets from `muselsl` Before Deleting It

Before removing `muselsl`, capture a few real packets to validate the C decoder.

In `muse.py`, find:

```python
def _handle_eeg(self, handle, data):
```

Right before:

```python
tm, d = self._unpack_eeg_channel(data)
```

Add:

```python
print("HANDLE", handle, "RAW", data.hex())
```

Then run:

```bash
muselsl stream
```

Copy at least one line from each channel into notes:

```text
HANDLE 32 RAW <40 hex chars>
HANDLE 35 RAW <40 hex chars>
HANDLE 38 RAW <40 hex chars>
HANDLE 41 RAW <40 hex chars>
```

A 20-byte packet should print as **40 hex characters**.

Use those packets as fixtures in `tests/test_decode.c`.

---

## 19. What Can Be Ignored for Now

Do not port these yet:

```text
LSL output
viewer code
recording code
PPG
accelerometer
gyroscope
telemetry
Athena protocol
Muse S Gen 3 support
BlueMuse support
recursive least squares timestamp correction
full channel synchronization
```

Only port:

```text
UUIDs
BLE scan/connect/subscribe/write
command encoding
start/stop commands
EEG packet decoder
sample scaling
```

---

## 20. Validation Checklist

### Decoder validation

- [ ] C decoder compiles.
- [ ] Dummy packet decodes to 12 samples.
- [ ] Real packet from `muselsl` decodes without error.
- [ ] Real decoded values are plausible microvolt values.
- [ ] Values are multiples of `0.48828125`.

### BLE validation

- [ ] Program sees Muse 2 in BLE scan.
- [ ] Program connects to Muse 2.
- [ ] Program discovers `273e0001` control characteristic.
- [ ] Program discovers `273e0003` through `273e0006` EEG characteristics.
- [ ] Program subscribes to all four EEG characteristics.
- [ ] Program writes `02 64 0A` to start streaming.
- [ ] Program receives 20-byte EEG packets.
- [ ] Program decodes packets live.
- [ ] Program writes `02 68 0A` on exit.

---

## 21. First Three Milestones

### Milestone 1: Pure C decode

```text
Input: one 20-byte packet
Output: packet index + 12 microvolt values
```

### Milestone 2: BLE visibility

```text
Your own program prints: Found Muse-XXXX
```

### Milestone 3: Live decode

```text
Your own program prints live decoded EEG packets from TP9/AF7/AF8/TP10 without muselsl.
```

---

## 22. Final Minimal Target

Run:

```bash
make
./muse_c
```

Expected output shape:

```text
Bluetooth powered on
Scanning...
Found Muse-3785
Connected
Found control characteristic 273e0001...
Subscribed TP9
Subscribed AF7
Subscribed AF8
Subscribed TP10
Sent start command: 02 64 0A

TP9  packet=1234  -11.72  47.85  176.27  ...
AF7  packet=1234  ...
AF8  packet=1234  ...
TP10 packet=1234  ...
```

At that point, the project has replaced the core functionality you needed from `muselsl`.
