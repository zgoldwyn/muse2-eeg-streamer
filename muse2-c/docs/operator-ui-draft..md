# Current browser-demo scope
The interface does not connect to the Muse, measure electrode contact, receive EEG samples, or save an EEG recording. The timer, phase progression, illustrative sample count, and operator events are browser-only. The operator can note a visual headset-fit check, but it is not a measured contact-quality result. Only the event JSON is downloadable; it is not synchronized to the saved EEG session.

# Browser to recorder handoff proposal
A possible solution is to not rely on the browser clock or recorder's time-keeping system at all. Instead, we can run a small local Python server. Whenever a marker is added in the app, we can simply tell the Python server all associated information about the marker (e.g. event_id, session_id), ignoring the elapsed_s field. It would be the server's job to give the marker a timestamp using its own built-in clock and hand all the information, including the timestamp, to the recorder.

# Clarifications about the timer
`elapsed_s` is based on the browser's monotonic time since the first Play and includes pauses. The phase countdown stops during pauses. Neither clock is aligned with Namit's EEG sample times or Ben's packet-receipt clock. The pre-Play contact-quality acknowledgment has `elapsed_s: 0` plus `acknowledged_at_utc`, a browser wall-clock timestamp that is also not synchronized to the recorder.

# Operator flow
The operator can continue with contact quality unverified after acknowledging a warning. This bypasses an unavailable browser measurement; it does not assert that the physical headset is disconnected or that missing channels or recording gaps are acceptable. The acknowledgment is included in the event export.

In `frontend/src/protocol.json`, each phase has `demoDurationSeconds: 4` for a 40-second UI walkthrough. These are not approved participant-protocol durations. Timed transitions and manual phase changes are distinguished by `transition_trigger` in the event export.

The operator can pause, resume, stop early, abort, correct a marker, export events, and start another demo. `elapsed_s` includes pauses; the phase countdown does not. Stopping early is incomplete, not completed. Corrections retain the original event and link to it with `corrects_event_id`.

## Original concept sketches

The sketches and descriptions below depict a possible future live interface, not the current browser implementation. They should not be used as evidence that live EEG, contact-quality measurement, or EDF export exists.

![Session Setup](images\eeg-operator-ui-draft-session-setup.jpg)
During this phase, the operator can add notes in the setup notes box. Once all the channel signal qualities are "good," the "begin session" button becomes available. Once pressed, the screen transfers to the live recording page. The session ID, participant name, and visit number are visible at the top of the screen. In the middle, the headset and channel connection statuses are visible. For each channel, there is an associated signal quality and samples received count, which measures the success rate at which samples come in from each channel. If any of the channels don't have a "good" signal quality, there is an error box that gives advice on what to change to achieve an acceptable signal quality.

![Live Recording](images\eeg-operator-ui-draft-live-recording.jpg)
The top of the screen displays the participant name, session ID, and visit number. Below it, there are headset and channel connection statuses that update live during the recording. The main features of this screen are the EEG channel traces in the middle which display the activity coming in from each of the four channels live for a certain time window close to what the current elapsed recording time is. Any recently placed markers will be visible at their respective timestamps on the traces. The list of all markers is visible at the left, with an option to add a marker at the current timestamp available. There is also a color legend for identifying what each kind of marker represents. At the bottom of the screen, there is a recording time box which displays the current elapsed time. It displays the number of unique samples collected in the elapsed time as well as the sample collection rate. There is a pause button, stop button, and abort session button. Below the recording time, there is a box to add session notes for the operator. The experiment phase list is next to the notes and recording time. It allows the operator to iterate through each phase of the experiment and adds the corresponding phase boundary markers for each press of the next phase or previous phase button. Lastly, there is a more in-depth option for adding markers which allows the operaotr to place a marker at the current timestamp, as well as select the marker type and add an additional note. 

![Replay and Review](images\eeg-operator-ui-draft-replay-and-review.jpg)
The replay and review screen displays much of the same information as the live recording screen. However, the channel activity screen is minimized a small bit to make way for a full session overview that displays each phase and marker that was added or completed during the run. The recording time screen has more playback options for going through the recording. The add marker option at the bottom right is replaced by a session record screen, which includes multiple export options for the operator.
