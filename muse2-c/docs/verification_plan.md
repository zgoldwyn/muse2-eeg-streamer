# Verification Plan

## Decoder Verification

| Test ID | Requirement Covered | Test Description | Expected Result |
|---|---|---|---|
| TEST-DEC-001 | REQ-DEC-001 | Pass `NULL` as the byte pointer. | Function returns nonzero error. |
| TEST-DEC-002 | REQ-DEC-001 | Pass `NULL` as the output pointer. | Function returns nonzero error. |
| TEST-DEC-003 | REQ-DEC-002 | Pass a packet shorter than 20 bytes. | Function returns nonzero error. |
| TEST-DEC-004 | REQ-DEC-003 | Pass packet beginning `00 5D`. | Packet index equals 93. |
| TEST-DEC-005 | REQ-DEC-004 | Decode fake packet containing repeated `AB CD EF`. | Raw samples alternate between `0xABC` and `0xDEF`. |
| TEST-DEC-006 | REQ-DEC-005 | Decode fake packet containing repeated `80 08 00`. | All microvolt values equal 0.0. |
| TEST-DEC-007 | REQ-DEC-004, REQ-DEC-005 | Decode real Muse 2 packet captured from handle 41. | Output matches known expected raw and microvolt values. |