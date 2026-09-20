"""Generate Engine-only prelude cues from Rekordbox hot cues.

The transformation runs on the source IR after the Rekordbox USB has been
parsed and before Engine cue blobs are built.  Rekordbox data is never
modified.  Re-running conversion with another lead length therefore starts
from the same anchors instead of shifting an already-generated prelude again.
"""

from __future__ import annotations

import bisect
import dataclasses
import re
from dataclasses import dataclass, field

from rb2engine.ir import CueKind, SourceBeat, SourceCue, SourceLibrary, SourceTrack
from rb2engine.playlist_naming import format_path, resolve_paths

SOURCE_SLOTS = range(1, 5)
DESTINATION_OFFSET = 4
BEATS_PER_BAR = 4
_MARKER_RE = re.compile(r"\[(?:prelude|anchor):", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PreludeConfig:
    """Requested cue transformation.

    ``minimum_gap_bars`` consolidates generated preludes whose grid positions
    are at most that far apart.  The earlier prelude wins because it provides
    usable runway into every later anchor in the cluster.
    """

    bars: int
    minimum_gap_bars: int = 8
    playlists: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.bars <= 0:
            raise ValueError("prelude bars must be > 0")
        if self.minimum_gap_bars < 0:
            raise ValueError("minimum prelude gap must be >= 0")

    @property
    def lead_beats(self) -> int:
        return self.bars * BEATS_PER_BAR

    @property
    def minimum_gap_beats(self) -> int:
        return self.minimum_gap_bars * BEATS_PER_BAR


@dataclass(frozen=True, slots=True)
class PreludeIssue:
    track_id: int
    title: str
    source_slot: int
    reason: str


@dataclass(slots=True)
class PreludeSummary:
    config: PreludeConfig
    tracks_selected: int = 0
    tracks_changed: int = 0
    anchors_moved: int = 0
    preludes_created: int = 0
    preludes_consolidated: int = 0
    preludes_truncated: int = 0
    issues: list[PreludeIssue] = field(default_factory=list)

    def to_json_obj(self) -> dict[str, object]:
        return {
            "bars": self.config.bars,
            "minimum_gap_bars": self.config.minimum_gap_bars,
            "playlists": list(self.config.playlists),
            "tracks_selected": self.tracks_selected,
            "tracks_changed": self.tracks_changed,
            "anchors_moved": self.anchors_moved,
            "preludes_created": self.preludes_created,
            "preludes_consolidated": self.preludes_consolidated,
            "preludes_truncated": self.preludes_truncated,
            "issues": [dataclasses.asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class _Candidate:
    cue: SourceCue
    source_slot: int
    destination_slot: int
    anchor_beat: int
    prelude_beat: int
    truncated: bool


def transform_library(
    library: SourceLibrary,
    config: PreludeConfig,
) -> tuple[SourceLibrary, PreludeSummary]:
    """Return a transformed copy of *library* and a machine-readable summary."""
    summary = PreludeSummary(config=config)
    selected_track_ids = _selected_track_ids(library, config.playlists)
    summary.tracks_selected = len(selected_track_ids)
    tracks: dict[int, SourceTrack] = {}
    for track_id, track in library.tracks.items():
        transformed = (
            _transform_track(track, config, summary)
            if track_id in selected_track_ids
            else track
        )
        tracks[track_id] = transformed
        if transformed is not track:
            summary.tracks_changed += 1

    return dataclasses.replace(library, tracks=tracks), summary


def _selected_track_ids(
    library: SourceLibrary,
    selectors: tuple[str, ...],
) -> set[int]:
    if not selectors:
        return set(library.tracks)

    by_id = {playlist.rb_id: playlist for playlist in library.playlists}
    paths = resolve_paths(library.playlists)
    display_paths = {rb_id: format_path(path) for rb_id, path in paths.items()}
    selected: set[int] = set()

    for raw_selector in selectors:
        selector = raw_selector.strip("/")
        matches = [
            rb_id for rb_id, display in display_paths.items() if display == selector
        ]
        if not matches and "/" not in selector:
            matches = [
                rb_id
                for rb_id, path in paths.items()
                if path and path[-1] == selector
            ]
        if not matches:
            raise ValueError(f"prelude playlist not found: {raw_selector!r}")
        if len(matches) > 1:
            choices = ", ".join(repr(display_paths[rb_id]) for rb_id in matches)
            raise ValueError(
                f"prelude playlist {raw_selector!r} is ambiguous; use one of: {choices}"
            )

        playlist = by_id[matches[0]]
        if playlist.is_folder:
            raise ValueError(
                f"prelude selector {raw_selector!r} names a folder, not a playlist"
            )
        selected.update(playlist.track_rb_ids)

    return selected.intersection(library.tracks)


def _transform_track(
    track: SourceTrack,
    config: PreludeConfig,
    summary: PreludeSummary,
) -> SourceTrack:
    point_cues_by_slot: dict[int, list[SourceCue]] = {}
    occupied_slots: set[int] = set()
    for cue in track.cues:
        if cue.kind is CueKind.HOT and cue.hot_slot is not None and not cue.is_loop:
            occupied_slots.add(cue.hot_slot)
            point_cues_by_slot.setdefault(cue.hot_slot, []).append(cue)

    candidates: list[_Candidate] = []
    for source_slot in SOURCE_SLOTS:
        slot_cues = point_cues_by_slot.get(source_slot, [])
        if not slot_cues:
            continue
        if len(slot_cues) > 1:
            _issue(summary, track, source_slot, "multiple point cues occupy this pad")
            continue

        cue = slot_cues[0]
        if _is_marked(cue.name):
            continue

        destination = source_slot + DESTINATION_OFFSET
        if destination in occupied_slots:
            _issue(summary, track, source_slot, f"destination pad {_pad(destination)} is occupied")
            continue
        if track.beatgrid is None or not track.beatgrid.beats:
            _issue(summary, track, source_slot, "track has no beatgrid")
            continue

        anchor_beat = _nearest_beat(track.beatgrid.beats, cue.start_sample)
        available_beats = min(anchor_beat, config.lead_beats)
        actual_lead_beats = (available_beats // BEATS_PER_BAR) * BEATS_PER_BAR
        if actual_lead_beats == 0:
            _issue(
                summary,
                track,
                source_slot,
                "fewer than one full bar is available before the cue",
            )
            continue
        prelude_beat = anchor_beat - actual_lead_beats
        candidates.append(
            _Candidate(
                cue=cue,
                source_slot=source_slot,
                destination_slot=destination,
                anchor_beat=anchor_beat,
                prelude_beat=prelude_beat,
                truncated=actual_lead_beats != config.lead_beats,
            )
        )

    if not candidates:
        return track

    kept, covered_by = _consolidate(candidates, config.minimum_gap_beats)
    candidate_by_cue = {id(candidate.cue): candidate for candidate in candidates}
    kept_by_slot = {candidate.source_slot: candidate for candidate in kept}

    transformed: list[SourceCue] = []
    for cue in track.cues:
        candidate = candidate_by_cue.get(id(cue))
        if candidate is None:
            transformed.append(cue)
            continue

        # The original musical event moves to its paired upper pad.
        transformed.append(
            dataclasses.replace(
                cue,
                hot_slot=candidate.destination_slot,
                name=_append_marker(cue.name, f"[anchor:{_pad(candidate.source_slot)}]"),
            )
        )
        summary.anchors_moved += 1

    # Generated lower-pad cues are appended after source cues; their explicit
    # hot slots mean source ordering cannot change pad assignment.
    beats = track.beatgrid.beats if track.beatgrid is not None else []
    for source_slot in sorted(kept_by_slot):
        candidate = kept_by_slot[source_slot]
        covered = covered_by.get(source_slot, [])
        destinations = [candidate.destination_slot, *(c.destination_slot for c in covered)]
        label = _prelude_label(candidate.prelude_beat, destinations, candidates, config)
        transformed.append(
            SourceCue(
                kind=CueKind.HOT,
                hot_slot=source_slot,
                start_sample=beats[candidate.prelude_beat].sample_offset,
                end_sample=None,
                color=candidate.cue.color,
                name=label,
            )
        )
        summary.preludes_created += 1
        if candidate.truncated:
            summary.preludes_truncated += 1

    summary.preludes_consolidated += len(candidates) - len(kept)
    return dataclasses.replace(track, cues=transformed)


def _consolidate(
    candidates: list[_Candidate], minimum_gap_beats: int
) -> tuple[list[_Candidate], dict[int, list[_Candidate]]]:
    ordered = sorted(candidates, key=lambda c: (c.prelude_beat, c.source_slot))
    if minimum_gap_beats == 0:
        return ordered, {}

    kept: list[_Candidate] = []
    covered: dict[int, list[_Candidate]] = {}
    for candidate in ordered:
        if (
            kept
            and candidate.prelude_beat - kept[-1].prelude_beat <= minimum_gap_beats
            and (candidate.anchor_beat - kept[-1].prelude_beat) % BEATS_PER_BAR == 0
        ):
            covered.setdefault(kept[-1].source_slot, []).append(candidate)
        else:
            kept.append(candidate)
    return kept, covered


def _prelude_label(
    prelude_beat: int,
    destination_slots: list[int],
    all_candidates: list[_Candidate],
    config: PreludeConfig,
) -> str:
    by_destination = {c.destination_slot: c for c in all_candidates}
    parts: list[str] = []
    truncated = False
    for destination in destination_slots:
        candidate = by_destination[destination]
        actual_beats = candidate.anchor_beat - prelude_beat
        parts.append(f"{_pad(destination)} {_format_bars(actual_beats)}b")
        truncated = truncated or actual_beats < config.lead_beats
    suffix = " start-limited" if truncated else ""
    marker = ",".join(_pad(slot) for slot in destination_slots)
    return f"Prelude → {', '.join(parts)}{suffix} [prelude:{marker}]"


def _format_bars(beats: int) -> str:
    if beats % BEATS_PER_BAR:
        raise ValueError(f"prelude lead must contain whole bars, got {beats} beats")
    return str(beats // BEATS_PER_BAR)


def _nearest_beat(beats: list[SourceBeat], sample: int) -> int:
    offsets = [beat.sample_offset for beat in beats]
    right = bisect.bisect_left(offsets, sample)
    if right <= 0:
        return 0
    if right >= len(offsets):
        return len(offsets) - 1
    before = right - 1
    return before if sample - offsets[before] <= offsets[right] - sample else right


def _append_marker(name: str | None, marker: str) -> str:
    return f"{name.strip()} {marker}" if name and name.strip() else marker


def _is_marked(name: str | None) -> bool:
    return bool(name and _MARKER_RE.search(name))


def _pad(slot: int) -> str:
    return chr(ord("A") + slot - 1)


def _issue(
    summary: PreludeSummary,
    track: SourceTrack,
    source_slot: int,
    reason: str,
) -> None:
    summary.issues.append(
        PreludeIssue(
            track_id=track.rb_id,
            title=track.title,
            source_slot=source_slot,
            reason=reason,
        )
    )
