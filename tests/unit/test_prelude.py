"""Prelude generation is beat-relative, lossless for anchors, and repeatable."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from rb2engine.ir import (
    RGB,
    CueKind,
    SourceBeat,
    SourceBeatgrid,
    SourceCue,
    SourceLibrary,
    SourcePlaylist,
    SourceTrack,
)
from rb2engine.prelude import PreludeConfig, transform_library
from rb2engine.report import JOURNAL_FILENAME, REPORT_FILENAME
from rb2engine.verify import _load_recorded_prelude_config


def _grid(count: int = 160) -> SourceBeatgrid:
    # Deliberately variable: alternating beat lengths prove the transformation
    # indexes the dense grid instead of subtracting milliseconds at average BPM.
    offsets = [0]
    for i in range(1, count):
        offsets.append(offsets[-1] + (20_000 if i < 70 else 24_000))
    return SourceBeatgrid(
        beats=[
            SourceBeat(beat_in_bar=(i % 4) + 1, sample_offset=offset, bpm=132.3)
            for i, offset in enumerate(offsets)
        ],
        is_adjusted=True,
    )


def _cue(slot: int, beat: int, grid: SourceBeatgrid, name: str = "Drop") -> SourceCue:
    return SourceCue(
        kind=CueKind.HOT,
        hot_slot=slot,
        start_sample=grid.beats[beat].sample_offset,
        end_sample=None,
        color=RGB(255, 0, 64),
        name=name,
    )


def _track(grid: SourceBeatgrid, cues: list[SourceCue]) -> SourceTrack:
    return SourceTrack(
        rb_id=7,
        title="Variable Grid",
        artist="Tester",
        album="",
        genre="",
        label="",
        comment="",
        composer="",
        remixer="",
        year=2026,
        track_number=None,
        disc_number=None,
        bpm=132.3,
        key_name=None,
        rating=0,
        play_count=0,
        bitrate=320,
        file_size=1,
        file_type="mp3",
        sample_rate=44_100,
        duration_s=300,
        total_samples=13_230_000,
        raw_path="Contents/test.mp3",
        resolved_path=Path("/stick/Contents/test.mp3"),
        beatgrid=grid,
        cues=cues,
        artwork=None,
    )


def _library(track: SourceTrack) -> SourceLibrary:
    return SourceLibrary(
        drive_root=Path("/stick"),
        tracks={track.rb_id: track},
        playlists=[],
        warnings=[],
    )


def _slot(track: SourceTrack, slot: int) -> SourceCue | None:
    return next(
        (cue for cue in track.cues if cue.kind is CueKind.HOT and cue.hot_slot == slot),
        None,
    )


def test_variable_grid_moves_by_grid_beats_and_preserves_anchor() -> None:
    grid = _grid()
    original = _track(grid, [_cue(1, 100, grid, "Main drop")])
    converted, summary = transform_library(
        _library(original), PreludeConfig(bars=16, minimum_gap_bars=8)
    )

    track = converted.tracks[7]
    prelude = _slot(track, 1)
    anchor = _slot(track, 5)
    assert prelude is not None and anchor is not None
    assert prelude.start_sample == grid.beats[36].sample_offset
    assert prelude.name == "Prelude → E 16b [prelude:E]"
    assert anchor.start_sample == grid.beats[100].sample_offset
    assert anchor.name == "Main drop [anchor:A]"
    assert anchor.color == original.cues[0].color
    assert summary.anchors_moved == 1
    assert summary.preludes_created == 1


def test_repeat_is_idempotent_and_new_distance_rebuilds_from_source() -> None:
    grid = _grid()
    source = _library(_track(grid, [_cue(1, 100, grid)]))

    sixteen, _ = transform_library(source, PreludeConfig(bars=16))
    repeated, summary = transform_library(sixteen, PreludeConfig(bars=16))
    thirty_two, _ = transform_library(source, PreludeConfig(bars=32))

    assert repeated == sixteen
    assert summary.tracks_changed == 0
    assert _slot(sixteen.tracks[7], 1).start_sample == grid.beats[36].sample_offset  # type: ignore[union-attr]
    assert _slot(thirty_two.tracks[7], 1).start_sample == grid.beats[0].sample_offset  # type: ignore[union-attr]
    assert "25b start-limited" in (_slot(thirty_two.tracks[7], 1).name or "")  # type: ignore[union-attr]
    assert _slot(thirty_two.tracks[7], 5).start_sample == grid.beats[100].sample_offset  # type: ignore[union-attr]


def test_start_truncation_records_actual_runway() -> None:
    grid = _grid()
    converted, summary = transform_library(
        _library(_track(grid, [_cue(3, 18, grid)])), PreludeConfig(bars=16)
    )

    prelude = _slot(converted.tracks[7], 3)
    anchor = _slot(converted.tracks[7], 7)
    assert prelude is not None and anchor is not None
    assert prelude.start_sample == grid.beats[0].sample_offset
    assert prelude.name == "Prelude → G 4.5b start-limited [prelude:G]"
    assert summary.preludes_truncated == 1


def test_nearby_preludes_consolidate_to_earlier_launch_point() -> None:
    grid = _grid()
    cues = [_cue(1, 64, grid, "First"), _cue(3, 96, grid, "Second")]
    converted, summary = transform_library(
        _library(_track(grid, cues)), PreludeConfig(bars=16, minimum_gap_bars=8)
    )

    track = converted.tracks[7]
    assert _slot(track, 1).name == "Prelude → E 16b, G 24b [prelude:E,G]"  # type: ignore[union-attr]
    assert _slot(track, 3) is None
    assert _slot(track, 5).name == "First [anchor:A]"  # type: ignore[union-attr]
    assert _slot(track, 7).name == "Second [anchor:C]"  # type: ignore[union-attr]
    assert summary.anchors_moved == 2
    assert summary.preludes_created == 1
    assert summary.preludes_consolidated == 1


def test_zero_gap_keeps_both_preludes() -> None:
    grid = _grid()
    cues = [_cue(1, 64, grid), _cue(3, 96, grid)]
    converted, summary = transform_library(
        _library(_track(grid, cues)), PreludeConfig(bars=16, minimum_gap_bars=0)
    )
    assert _slot(converted.tracks[7], 1) is not None
    assert _slot(converted.tracks[7], 3) is not None
    assert summary.preludes_created == 2
    assert summary.preludes_consolidated == 0


def test_occupied_destination_is_reported_and_left_unchanged() -> None:
    grid = _grid()
    track = _track(grid, [_cue(1, 80, grid, "A"), _cue(5, 120, grid, "E")])
    converted, summary = transform_library(_library(track), PreludeConfig(bars=16))
    assert converted.tracks[7] == track
    assert len(summary.issues) == 1
    assert summary.issues[0].source_slot == 1
    assert summary.issues[0].reason == "destination pad E is occupied"


def test_hot_loop_does_not_block_engine_quick_cue_destination() -> None:
    grid = _grid()
    loop = SourceCue(
        kind=CueKind.HOT,
        hot_slot=5,
        start_sample=grid.beats[112].sample_offset,
        end_sample=grid.beats[116].sample_offset,
        color=RGB(0, 128, 255),
        name="Loop E",
    )
    converted, summary = transform_library(
        _library(_track(grid, [_cue(1, 80, grid, "A"), loop])),
        PreludeConfig(bars=16),
    )

    track = converted.tracks[7]
    assert _slot(track, 1) is not None
    assert len([cue for cue in track.cues if cue.hot_slot == 5]) == 2
    assert loop in track.cues
    assert summary.anchors_moved == 1


def test_verify_recovers_settings_from_journal_then_report(tmp_path: Path) -> None:
    engine_lib = tmp_path / "Engine Library"
    engine_lib.mkdir()
    (engine_lib / REPORT_FILENAME).write_text(
        json.dumps({"prelude": {"bars": 32, "minimum_gap_bars": 4}}),
        encoding="utf-8",
    )

    assert _load_recorded_prelude_config(engine_lib) == PreludeConfig(32, 4)

    (engine_lib / JOURNAL_FILENAME).write_text(
        json.dumps(
            {
                "prelude_bars": 16,
                "prelude_minimum_gap_bars": 0,
                "prelude_playlists": ["Sets/Prelude"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert _load_recorded_prelude_config(engine_lib) == PreludeConfig(
        16, 0, ("Sets/Prelude",)
    )


def test_playlist_scope_changes_only_tracks_in_selected_playlists() -> None:
    grid = _grid()
    selected = _track(grid, [_cue(1, 100, grid)])
    other = replace(selected, rb_id=8, title="Other")
    library = SourceLibrary(
        drive_root=Path("/stick"),
        tracks={7: selected, 8: other},
        playlists=[
            SourcePlaylist(1, 0, "Sets", 0, True, []),
            SourcePlaylist(2, 1, "Prelude", 0, False, [7]),
            SourcePlaylist(3, 1, "Other", 1, False, [8]),
        ],
        warnings=[],
    )

    converted, summary = transform_library(
        library,
        PreludeConfig(16, playlists=("Sets/Prelude",)),
    )

    assert converted.tracks[7] != selected
    assert converted.tracks[8] == other
    assert summary.tracks_selected == 1
    assert summary.tracks_changed == 1
