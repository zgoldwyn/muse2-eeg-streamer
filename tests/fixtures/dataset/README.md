# Synthetic dataset fixture

`complete_six_seconds.csv` contains six seconds of deterministic synthetic EEG
data at 256 Hz for TP9, AF7, AF8, and TP10. The fixture therefore contains
1,536 samples per channel and should produce three valid two-second windows.

The values are synthetic only. Packet indices use Muse's 12 samples per packet.
The JSON metadata uses the recorder's shared names: `nominal_sample_rate_hz`
and `samples_per_packet`.
