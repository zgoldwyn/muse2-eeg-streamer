from pylsl import StreamInlet, resolve_streams
import time

print("Looking for an EEG stream...")

streams = resolve_streams(wait_time=5.0)

eeg_streams = [
    stream for stream in streams
    if stream.type() == "EEG"
]

if not eeg_streams:
    print("No EEG stream found.")
    print("Make sure this is running in another terminal:")
    print("muselsl stream")
    raise SystemExit

inlet = StreamInlet(eeg_streams[0])

print("Connected to EEG stream.")
print("Reading samples... Press Ctrl+C to stop.")

try:
    while True:
        sample, timestamp = inlet.pull_sample()
        print(timestamp, sample)
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nStopped.")