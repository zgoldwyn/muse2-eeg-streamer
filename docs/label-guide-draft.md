# EEG Window Label Guide — Draft v0.1

## Purpose and review rules

This guide defines reference labels for fixed EEG windows. Reviewers label windows independently and must not see either artifact detector's prediction. Observer markers may help identify a possible event, but they do not prove its exact EEG boundaries. A missing observer marker is not evidence that a window is clean.

## Operational labels

### Clean

Label a window **clean** only when all usable channels have sufficient, continuous data and independent visual review finds no contamination that would make the window unsuitable for the intended EEG analysis. The reviewer should check for abrupt non-physiological changes, sustained muscle-like activity, movement-related disturbance, and headset-contact problems. A marker's absence alone cannot justify a clean label.

### Artifact

Label a window **artifact** when visible evidence indicates contamination that makes the window unsuitable for the intended analysis. Record a suspected subtype whenever possible: `blink`, `jaw_or_muscle_activity`, `head_movement`, `headset_disturbance`, or `other`.

For this draft, the primary evaluated channels are **TP9, AF7, AF8, and TP10**. Our proposed multichannel evaluation rule is that an artifact visible in any one of these channels labels the shared window as `artifact`; record the affected channel(s) in the note. This is a proposed rule for multichannel evaluation, not a final decision about every downstream analysis.

### Uncertain

Label a window **uncertain** when data are present and technically usable, but the reviewer cannot decide reliably whether apparent activity is neural signal or artifact. Use this label rather than guessing when the evidence is weak or conflicting. An approximate artifact boundary makes a window uncertain only when the boundary ambiguity could change whether that particular window is `clean` or `artifact`. A window with clearly visible contamination remains `artifact` even when its exact onset or ending time is approximate. Uncertain windows are excluded from primary metric calculations and reported separately.

### Invalid

Label a window **invalid** when a technical problem prevents meaningful interpretation: for example, missing samples, a recording gap, a corrupted packet sequence, a disconnected headset, or a channel that is unavailable for the needed portion of the window. Invalid means the data cannot be reviewed—not that they are merely hard to classify. Missing samples and recording gaps must never be labeled clean. Invalid windows are excluded from primary metric calculations and reported separately.

## Disagreements and difficult cases

Two reviewers should first label independently. If their labels disagree, retain both initial labels and ask a third reviewer or designated adjudicator to review the window without detector predictions. The adjudicated label, rationale, reviewer IDs, and guide version should be recorded; unresolved cases remain uncertain.

**Ambiguous example:** A window contains a brief, high-amplitude deflection in AF7 near a blink marker, but the waveform is weak and could be normal activity; data are continuous and all channels are present. Label it **uncertain**, not artifact or clean, because the evidence is too weak to decide whether this window contains contamination. In contrast, a clear large deflection in the window remains `artifact` even if its exact boundary relative to a neighboring window is approximate.

## Independent-label example (synthetic only)

The two reviewers below receive only the six synthetic EEG windows and the review guide. They do **not** see detector predictions while assigning their original labels. Their original decisions are preserved even when a later final decision is recorded.

| Window | Reviewer A: original label and evidence | Reviewer B: original label and evidence | Initial result |
| --- | --- | --- | --- |
| `synthetic-w01` | `clean` — continuous TP9, AF7, AF8, and TP10 traces; no abrupt shift or sustained high-frequency activity. | `clean` — all four channels are present and stable; no visible contamination. | Agree: clean |
| `synthetic-w02` | `artifact` — large, synchronous frontal deflection in AF7 and AF8, consistent with a blink. | `artifact` — sharp AF7/AF8 transient with a matching observer blink marker. | Agree: artifact |
| `synthetic-w03` | `uncertain` — short AF7 deflection is weak and might be neural activity; data are otherwise continuous. | `uncertain` — no technical failure, but the apparent event is too weak to classify confidently. | Agree: uncertain |
| `synthetic-w04` | `invalid` — TP10 has a missing segment during the window. | `invalid` — packet gap leaves TP10 incomplete, so the four-channel window cannot be interpreted. | Agree: invalid |
| `synthetic-w05` | `artifact` — sustained, high-frequency activity across AF7 and AF8 is consistent with jaw or facial-muscle activity. | `uncertain` — broad activity is visible, but the reviewer is not initially certain it is muscle contamination. | Disagree |
| `synthetic-w06` | `clean` — most of the window is stable; the late transient initially appears brief. | `artifact` — a clear movement-related shift is visible in TP9 and TP10 before the window ends. | Disagree |

### Final decisions after disagreement review

| Window | Final decision | Brief reason |
| --- | --- | --- |
| `synthetic-w05` | `artifact` | An independent adjudicator finds sustained, non-physiological high-frequency activity in both frontal channels. The evidence is strong enough to classify it as artifact despite Reviewer B's initial uncertainty. |
| `synthetic-w06` | `artifact` | The movement-related shift clearly occurs inside this window. Its exact onset is approximate, but that does not change whether this window contains contamination. |

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
