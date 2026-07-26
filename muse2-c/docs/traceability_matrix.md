# Traceability Matrix

| Requirement | Implementation | Verification |
|---|---|---|
| REQ-DEC-001 | `src/muse2_decode.c` input validation | TEST-DEC-001, TEST-DEC-002 |
| REQ-DEC-002 | `src/muse2_decode.c` length check | TEST-DEC-003 |
| REQ-DEC-003 | `src/muse2_decode.c` packet index decode | TEST-DEC-004 |
| REQ-DEC-004 | `src/muse2_decode.c` 12-bit sample unpacking | TEST-DEC-005, TEST-DEC-007 |
| REQ-DEC-005 | `src/muse2_decode.c` microvolt conversion | TEST-DEC-006, TEST-DEC-007 |
| REQ-DEC-006 | `src/muse2_decode.c` return codes | TEST-DEC-001 through TEST-DEC-007 |