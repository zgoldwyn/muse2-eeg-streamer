# Muse 2 C Driver

Low-level Muse 2 EEG reader for macOS.

This project connects directly to a Muse 2 headset over BLE, subscribes to EEG characteristics, decodes Muse EEG packets, and exposes live EEG samples to C code.

## Current goal

1. Decode raw Muse 2 EEG packets in C
2. Validate decoder against packets captured from muselsl
3. Build a macOS CoreBluetooth bridge
4. Receive live BLE notifications
5. Decode live EEG packets without muselsl

## Build

```bash
make
```
