# Risk Analysis

## Scope

This project is a research/prototype Muse 2 EEG decoder and BLE interface. It is not certified medical-device software and must not be used for diagnosis, treatment, or safety-critical control.

## Preliminary Hazards

| Hazard ID | Hazard | Cause | Possible Effect | Mitigation |
|---|---|---|---|---|
| HAZ-001 | Program reads out of bounds | Malformed or short BLE packet | Crash or undefined behavior | Reject packets shorter than 20 bytes. |
| HAZ-002 | Incorrect EEG values | Packet unpacking bug | Incorrect downstream interpretation | Unit tests with known fake and real packets. |
| HAZ-003 | Stale data used as current data | BLE disconnect or packet loss | Misleading output/control | Track timestamps and connection state. |
| HAZ-004 | Unsafe downstream control | EEG artifact interpreted as command | Unintended action | Do not directly control safety-relevant hardware; add thresholds, debounce, and manual override. |
| HAZ-005 | Device compatibility mismatch | Different Muse model/protocol | Wrong decoding | Restrict documented scope to Muse 2 and validate UUIDs/packet format. |