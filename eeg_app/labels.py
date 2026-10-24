"""Conservative joining of independently reviewed reference labels to windows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from .dataset import EegWindow


REFERENCE_LABELS = frozenset({"clean", "artifact", "uncertain", "invalid"})


@dataclass(frozen=True)
class ReferenceLabelInterval:
    """A human-reviewed label interval; detector predictions are not accepted here."""

    session_id: str
    start_s: float
    end_s: float
    label: str
    reviewer_id: str
    label_version: str
    subtype: str | None = None
    affected_channels: tuple[str, ...] = ()
    boundary_uncertainty_s: float = 0.0
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("Reference label interval session_id must not be empty.")
        if self.label not in REFERENCE_LABELS:
            raise ValueError(f"Unsupported reference label: {self.label!r}.")
        if not self.reviewer_id or not self.label_version:
            raise ValueError("Reference labels require reviewer_id and label_version.")
        if not all(isfinite(value) for value in (self.start_s, self.end_s)):
            raise ValueError("Reference label interval boundaries must be finite.")
        if self.start_s >= self.end_s:
            raise ValueError("Reference label interval start_s must be before end_s.")
        if not isfinite(self.boundary_uncertainty_s) or self.boundary_uncertainty_s < 0:
            raise ValueError("boundary_uncertainty_s must be a finite nonnegative value.")


@dataclass(frozen=True)
class WindowReferenceLabel:
    """A joined label or a reason why a window needs additional human review."""

    window_id: str
    session_id: str
    label: str | None
    status: str
    reasons: tuple[str, ...]
    source_intervals: tuple[ReferenceLabelInterval, ...]


def join_reference_label_intervals(
    windows: Iterable[EegWindow], intervals: Iterable[ReferenceLabelInterval]
) -> list[WindowReferenceLabel]:
    """Join independent human labels without resolving partial-overlap policy.

    A label is assigned only when matching reference interval(s) fully cover a
    technically valid window and agree on one operational label. Partial
    overlaps, uncertain boundaries, and disagreements remain unassigned for
    adjudication. No prompt, marker, or detector output is used as a label.
    """
    intervals_by_session: dict[str, list[ReferenceLabelInterval]] = {}
    for interval in intervals:
        intervals_by_session.setdefault(interval.session_id, []).append(interval)

    joined: list[WindowReferenceLabel] = []
    for window in windows:
        if not window.is_valid:
            joined.append(
                WindowReferenceLabel(
                    window_id=window.window_id,
                    session_id=window.session_id,
                    label="invalid",
                    status="technical_invalid",
                    reasons=("window failed technical validation",) + window.invalid_reasons,
                    source_intervals=(),
                )
            )
            continue

        overlapping = tuple(
            interval
            for interval in intervals_by_session.get(window.session_id, [])
            if interval.start_s < window.end_time_s and interval.end_s > window.start_time_s
        )
        if not overlapping:
            joined.append(
                WindowReferenceLabel(
                    window_id=window.window_id,
                    session_id=window.session_id,
                    label=None,
                    status="no_reference_label",
                    reasons=("no reviewed reference interval overlaps this window",),
                    source_intervals=(),
                )
            )
            continue

        labels = {interval.label for interval in overlapping}
        if len(labels) > 1:
            joined.append(
                WindowReferenceLabel(
                    window_id=window.window_id,
                    session_id=window.session_id,
                    label=None,
                    status="conflicting_reference_labels",
                    reasons=("overlapping reference intervals disagree on the operational label",),
                    source_intervals=overlapping,
                )
            )
            continue

        full_coverage = tuple(
            interval
            for interval in overlapping
            if interval.start_s <= window.start_time_s and interval.end_s >= window.end_time_s
        )
        if full_coverage:
            joined.append(
                WindowReferenceLabel(
                    window_id=window.window_id,
                    session_id=window.session_id,
                    label=full_coverage[0].label,
                    status="assigned",
                    reasons=(),
                    source_intervals=full_coverage,
                )
            )
            continue

        has_boundary_uncertainty = any(
            interval.boundary_uncertainty_s > 0 for interval in overlapping
        )
        reason = (
            "partial reference-label overlap has a stated uncertain boundary"
            if has_boundary_uncertainty
            else "partial reference-label overlap has no approved window-overlap rule"
        )
        joined.append(
            WindowReferenceLabel(
                window_id=window.window_id,
                session_id=window.session_id,
                label=None,
                status="needs_adjudication",
                reasons=(reason,),
                source_intervals=overlapping,
            )
        )
    return joined
