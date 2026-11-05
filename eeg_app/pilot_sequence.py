"""The agreed pilot cue sequence, shared by the terminal guide and the dashboard.

Pilot-only cues, not a finalized participant protocol. The cues are timing
hints, never reference EEG labels.
"""

# (cue text, seconds until the next cue)
CUES = (
    ("Rest quietly", 10),
    ("Blink softly twice, then firmly once", 10),
    ("Rest quietly", 10),
    ("Raise your eyebrows", 10),
    ("Rest quietly", 10),
    ("Move your head gently", 10),
    ("Rest quietly", 10),
)
# cue index -> action announced as "Get ready to ..." shortly before that cue
READY = {1: "blink", 3: "raise your eyebrows", 5: "move your head gently"}
READY_LEAD_S = 3
