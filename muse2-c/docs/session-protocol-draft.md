# End-to-End Session Workflow
| Stage | Participant action | Operator action | What the interface displays | What the system records | Potential failure cases |
| ----- | ------------------ | --------------- | --------------------------- | ----------------------- | ----------------------- |
| Begin session | Wait for operator | Start a session; the backend assigns a pseudonymous session ID. Do not enter the participant's name in the live app. | Session ID | Session ID and session start time | Backend cannot start the session |
| Connecting headset | Wait while the headset is connected and fitted | Connect the Muse headset and fit it as described below | Device state and whether packets are arriving | Device/packet status | Headset does not connect or packets do not arrive |
| Check EEG channel status | Help adjust the headset if asked | Complete the visual fit check and check that packets are arriving on the channels | Recent packet-arrival status and live traces | EEG samples and packet status | One or more channels has no recent packets or the stream stalls |
| Confirm that the system is ready to record | Wait for the operator | Acknowledge that contact quality is not measured, enter any setup notes and start the live recording | Visual fit checklist, contact-quality warning, setup notes, and start control | Contact-quality acknowledgment and optional setup note | Device or packet stream is unavailable |
| Start recording | Wait for the operator and follow the displayed cue when it begins | Start the live recording. Wait for the first EEG packet, which starts the pilot's EEG-time clock | Recorder state, live traces, phase and pilot cue display | EEG samples and time-stamped phase/prompt events | No EEG packets arrive or the recording is interrupted |
| Guide participant through planned prompts | Follow the displayed cue and the operator's instruction | Follow the live cue sequence. Each cue is time-stamped by the app | Pilot cue, phase, and live EEG displays | Time-stamped protocol prompts and phase events | Prompt is missed, the stream is interrupted, or the participant asks to stop |
| Add operator observations when relevant | Continue following the operator's instructions | Record an observation or operator note when appropriate; these are observations, not a diagnosis of the EEG trace | Observed-event controls and operator notes | Time-stamped operator event or note | Event is not saved or is recorded incorrectly |
| End the session when necessary | Stop following the last instruction if the operator asks you to stop | Use Stop to save a completed or incomplete session, or Abort Session to save an aborted session; enter a reason when prompted. Live recording cannot be paused or resumed. | Stop and Abort Session controls | Session outcome and end time; rows already written are retained | Application or recorder is interrupted |
| Review | Wait for operator | Review the saved session and its outcome | Session summary and review display | No new recording data | Session cannot be reviewed |
| Confirm saved session | Wait for operator | Confirm the session outcome and that the saved session is available through the study's approved workflow | Session ID, outcome, and review status | EEG samples, events, and session summary saved under the session ID | Session is incomplete, interrupted, or unavailable |

# Timed Participant Script
## Information to explain before consent

This session uses a Muse 2 headset to record EEG (electrical activity) from four scalp sensors: behind each ear (TP9 and TP10) and on the forehead (AF7 and AF8). The headset is fitted on the participant, who will sit still for quiet periods and follow three short prompts: blink softly twice, pause, and blink firmly once; raise and relax both eyebrows; and gently turn the head right, left, and back to center. Quiet periods separate the prompts. The live cue sequence has seven approximately 10-second windows, about 70 seconds total. Allow about 4-5 minutes for the explanation, headset fitting, recording, and wrap-up, plus extra time if fitting or the data stream takes longer.

Before inviting participation, the operator should confirm that the app is using a real Muse EEG stream. Fake-headset mode produces simulated test data and is not a participant recording.

The operator checks the headset's visual fit and whether EEG packets are arriving. The live app does not measure electrode contact quality and packet arrival does not establish that contact or signal quality is good. The app records EEG samples from the four channels, time-stamped prompts and phase events, and any setup notes or operator observations. The local recorder saves these under a pseudonymous session ID; the app does not ask for the participant's name. Because free-text notes are saved with the session, the operator should not put directly identifying information in them. A pseudonymous ID is not a guarantee of anonymity. This procedure does not specify who can access recordings, how long they are retained, or whether they will be shared. The study lead must explain those points using the applicable consent materials before consent is requested.

The headset should be adjusted for comfort. The participant may ask questions, decline a prompt, report discomfort, or ask to stop at any time. Live recording cannot be paused and resumed: if it is stopped, continuing later requires a new session. The operator ends the recording and records an outcome. The participant does not need to provide a reason for asking to stop; the operator can record that the participant requested it. The operator should explain any additional study-specific risks, benefits, data handling, and contact information in the approved consent materials.

## Timed procedure

The introduction is about 1 minute and headset fitting is about 1-2 minutes. The live pilot then runs seven 10-second cue windows (about 70 seconds total) on EEG time, which begins when the first EEG packet arrives. The interface shows cue start times and "Get ready"/"NOW" prompts; "Get ready" appears 3 seconds before blink, eyebrow, and head-movement cues. These are approximate EEG-time intervals. Follow the live interface if its sequence changes. The 2-second phase targets in the frontend protocol are demo-only. The ending and headset removal take about 1 minute after the cues finish.

| Approximate duration | Phase | Participant instruction | Operator action | Expected recorded event |
| ------------------- | ----- | ----------------------- | --------------- | ----------------------- |
| About 1 min | Introduction | Listen to the operator | Explain the session and what the participant will be asked to do. | None |
| About 1-2 min before EEG time | Headset fitting and signal check | Remain relaxed while the headset is fitted | Fit the headset level, place TP9/TP10 behind the ears and AF7/AF8 on skin, move hair aside, and confirm the participant is comfortable. Complete the visual fit checklist. The interface only reports recent packet arrival, electrode contact quality is not measured. Acknowledge this limitation, enter any setup notes, and start the live recording. The backend assigns a pseudonymous session ID. Do not enter participant names. | Contact-quality-unverified acknowledgment, optional setup note |
| About 10 s, EEG 0:00-0:10 | Baseline quiet period | Keep your head still, relax your face, look straight ahead, and do not speak | Monitor packet/channel status and the live traces. Follow the phase and cue displayed in the interface. | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 0:10-0:20 | Hard and soft blink prompt | Blink softly twice, pause, then close your eyes firmly for one hard blink and relax | Give the instruction when the live pilot cue says "NOW." | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 0:20-0:30 | Quiet period after blink prompt | Look straight ahead, keep your head still, and relax your face | Continue observing the stream and participant. | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 0:30-0:40 | Raise-eyebrows prompt | Raise both eyebrows, hold briefly, then lower them and relax your forehead | Give the instruction when the live pilot cue says "NOW." | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 0:40-0:50 | Quiet period after eyebrow prompt | Relax your face, remain still, and look straight ahead | Continue observing the stream and participant. | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 0:50-1:00 | Gentle head-movement prompt | Gently move your head all the way to the right, then all the way to the left, and return to center | Give the instruction when the live pilot cue says "NOW." | Protocol phase start, pilot cue prompt |
| About 10 s, EEG 1:00-1:10 | Quiet period after head movement | Return your head to center, remain still, and relax | Continue observing the stream and participant. | Protocol phase start, pilot cue prompt |
| About 1 min after the cue sequence | Ending procedure | Remain seated while the operator ends the recording and prepares to remove the headset | Wait for the 70-second pilot sequence to finish, then press Stop to save the session as completed. Review the saved session and remove the headset safely. If the sequence has not finished, Stop opens the stop-early flow and saves as incomplete, Abort saves as aborted. Both require a reason. | Session outcome |

Phase changes normally follow the pilot schedule. Prev Phase and Next Phase are available to the operator as manual overrides and record the selected phase. The live recording cannot be paused. Stopping or aborting ends the session. If the session is interrupted, already-written rows are retained, but the operator should end that session and start a new one rather than resume it. 

# Stopping or Aborting a Session
The live recording cannot be paused or resumed. If the participant expresses discomfort, stop giving instructions and end the recording using Abort Session if they do not wish to continue. If they are comfortable continuing after the concern is addressed, the operator may continue the active recording; if it has already been ended, start a new session.

If the participant explicitly requests to stop, end the session with Abort Session and enter the reason.

If the headset stream is interrupted or the recording fails, follow the interface warning, then end the session with Stop early or Abort and enter the reason. Already-written rows are retained. Do not treat packet arrival as confirmation of electrode contact quality.

# Session Outcomes Test (10/19/2026)
The following dated test notes describe earlier interface versions, not the current participant procedure. In particular, references to pausing/resuming are historical; live recording cannot be paused or resumed. The current live pilot sequence uses seven 10-second cue windows.

Before you run the app, make sure that you have npm and vite installed in the frontend folder. Once you do this, you can use `npm run dev` in your terminal to run the program, where you'll have the choice to run the app locally or on your browser of choice. 

Using this, I recorded two test demonstrations. At the time, I set each phase target to 2 seconds for efficiency; these were test settings, not participant timings. The phase iteration buttons were also available in that interface version.

The first demonstration was a complete run that completed all phases. In between phases, I added and corrected an observed marker, paused, and resumed the recording. I began the second demonstration from the "Start another session" option in the replay and review screen. In this demo, I started the session, let it automatically run for a little, then aborted it.

Both sessions' Event IDs were unique from each other. The timer in the first session did not interfere with the second session's timer. The interface labels all simulated data from the headset and its channels, such as the channel readings, as such. At this time, I have removed all export options from the replay and review screen to prevent any confusion. 

# Interface Test (10/31/2026)
These are historical test notes from an earlier interface version, not additional steps or current timing for participants.

For this test, I recorded three demonstrations. At this point, the app is set so that the headset and channel connection statuses are "not connected," forcing the operator to press the "Begin Session with Contact Quality Unverified" button and acknowledge the disclaimer before they can proceed with the recording. 

In the first demonstration, I let the entire procedure complete automatically with one pause in the middle. During this test, I added observed blinks and corrected one of them. After the procedure completed, I verified that the correction linked back to the marker that it was intended to correct. I also verified that `elapsed_s` represents the total running time of the procedure including pause time. 

From the replay and review screen, I began another session with a unique Session ID. I let it run automatically for two phases before stopping it. This test helped me verify that the procedure appeared as "incomplete" in the replay and review screen. I successfully exported the events for this test.

I ran one more session from the replay and review screen. This time, I aborted the session almost immediately. I verified that the procedure appeared as "aborted" in the replay and review screen and exported the events.