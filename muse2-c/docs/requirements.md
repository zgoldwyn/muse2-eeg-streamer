# Requirements

## Decoder Requirements

| ID | Requirement | Rationale |
|---|---|---|
| REQ-DEC-001 | The decoder shall reject null input pointers. | Prevent undefined behavior and crashes. |
| REQ-DEC-002 | The decoder shall reject EEG packets shorter than 20 bytes. | Prevent out-of-bounds reads. |
| REQ-DEC-003 | The decoder shall read the first two bytes as a big-endian 16-bit packet index. | Matches Muse 2 packet format. |
| REQ-DEC-004 | The decoder shall decode 18 packed bytes into 12 unsigned 12-bit raw EEG samples. | Matches Muse 2 EEG payload format. |
| REQ-DEC-005 | The decoder shall convert raw samples to microvolts using `(raw - 2048) * 0.48828125`. | Matches Muse 2 scaling behavior observed from muselsl. |
| REQ-DEC-006 | The decoder shall return 0 on success and a nonzero error code on failure. | Allows caller to detect invalid input. |