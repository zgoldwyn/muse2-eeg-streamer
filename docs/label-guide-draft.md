# EEG Window Label Guide — Draft v0.1

## Purpose and review rules

This guide defines reference labels for fixed EEG windows. Reviewers label windows independently and must not see either artifact detector's prediction. Observer markers may help identify a possible event, but they do not prove its exact EEG boundaries. A missing observer marker is not evidence that a window is clean.

## Operational labels

### Clean

Label a window **clean** only when all usable channels have sufficient, continuous data and independent visual review finds no contamination that would make the window unsuitable for the intended EEG analysis. The reviewer should check for abrupt non-physiological changes, sustained muscle-like activity, movement-related disturbance, and headset-contact problems. A marker's absence alone cannot justify a clean label.

### Artifact

Label a window **artifact** when visible evidence indicates contamination that makes the window unsuitable for the intended analysis. Record a suspected subtype whenever possible: `blink`, `jaw_or_muscle_activity`, `head_movement`, `headset_disturbance`, or `other`. An artifact in even one primary channel labels the whole window as artifact, because the window cannot be treated as a fully reliable multichannel observation; record the affected channel(s) in the note.

### Uncertain

Label a window **uncertain** when data are present and technically usable, but the reviewer cannot decide reliably whether apparent activity is neural signal or artifact. Use this label rather than guessing when the evidence is weak, conflicting, or the artifact boundary is too ambiguous. Uncertain windows are excluded from primary metric calculations and reported separately.

### Invalid

Label a window **invalid** when a technical problem prevents meaningful interpretation: for example, missing samples, a recording gap, a corrupted packet sequence, a disconnected headset, or a channel that is unavailable for the needed portion of the window. Invalid means the data cannot be reviewed—not that they are merely hard to classify. Missing samples and recording gaps must never be labeled clean. Invalid windows are excluded from primary metric calculations and reported separately.

## Disagreements and difficult cases

Two reviewers should first label independently. If their labels disagree, retain both initial labels and ask a third reviewer or designated adjudicator to review the window without detector predictions. The adjudicated label, rationale, reviewer IDs, and guide version should be recorded; unresolved cases remain uncertain.

**Ambiguous example:** A window contains a brief, high-amplitude deflection in AF7 near a blink marker, but the waveform is weak and could be normal activity; data are continuous and all channels are present. Label it **uncertain**, not artifact or clean, because the marker supports review but does not prove the event or its timing.

## Example label record

```yaml
session_id: demo-001
start_s: 12.30
end_s: 12.80
label: artifact
subtype: blink
affected_channels: [AF7, AF8]
reviewer_id: reviewer-01
evidence_source: observer marker and visible EEG deflection
boundary_uncertainty_s: 0.10
label_version: v0.1
note: onset is clear; ending boundary is approximate
```

An observer marker is helpful because it points reviewers to a possible event. It is imperfect because a prompt, button press, or observer action may occur before or after the EEG change and therefore cannot establish the exact artifact boundaries.

## Questions to resolve before finalizing

- What window length and overlap should the project use?
- What objective criteria define sufficient data quality for a clean label?
- Should a one-channel artifact always invalidate the entire window for every downstream analysis, or should some channel-specific analyses retain unaffected channels?
- Who is the designated adjudicator when reviewers disagree?
