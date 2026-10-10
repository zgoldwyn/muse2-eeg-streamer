# Synthetic dataset fixture

`complete_six_seconds.csv` contains six seconds of deterministic synthetic EEG
data at 256 Hz for TP9, AF7, AF8, and TP10. The fixture therefore contains
1,536 samples per channel and should produce three valid two-second windows.

The values are synthetic only. Packet indices use 16 samples per packet and
the JSON metadata file defines the session and development-list contract used
by the tests.
