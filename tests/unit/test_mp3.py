"""MP3 encoder-delay parsing and positional timeline adjustment."""

from __future__ import annotations

from pathlib import Path

from rb2engine.ir import CueKind, SourceBeat, SourceBeatgrid, SourceCue
from rb2engine.reader.library import _shift_positions
from rb2engine.reader.mp3 import read_mp3_start_skip


def _mp3_with_lame_delay(
    delay: int,
    *,
    info: bool = False,
    with_id3: bool = False,
    with_crc: bool = False,
) -> bytes:
    """Hand-author the minimum MPEG-1 stereo Xing/LAME layout we consume."""
    protection_bit = 0 if with_crc else 1
    word = (
        0x7FF << 21
        | 0x3 << 19  # MPEG-1
        | 0x1 << 17  # Layer III
        | protection_bit << 16
        | 0x9 << 12  # valid bitrate index
        | 0x0 << 10  # 44.1 kHz
        | 0x0 << 6  # stereo
    )
    frame = bytearray(word.to_bytes(4, "big"))
    frame.extend(b"\x00" * (34 if with_crc else 32))
    frame.extend(b"Info" if info else b"Xing")
    frame.extend((0xF).to_bytes(4, "big"))
    frame.extend((1234).to_bytes(4, "big"))
    frame.extend((5678).to_bytes(4, "big"))
    frame.extend(bytes(range(100)))
    frame.extend((42).to_bytes(4, "big"))
    frame.extend(b"LAME3.100")
    extension = bytearray(27)
    extension[12] = delay >> 4
    extension[13] = (delay & 0xF) << 4
    frame.extend(extension)

    if not with_id3:
        return bytes(frame)
    id3_body = b"metadata"
    size = len(id3_body)
    syncsafe = bytes(
        (
            (size >> 21) & 0x7F,
            (size >> 14) & 0x7F,
            (size >> 7) & 0x7F,
            size & 0x7F,
        )
    )
    return b"ID3\x04\x00\x00" + syncsafe + id3_body + bytes(frame)


def test_reads_effective_start_skip_from_xing_lame_header(tmp_path: Path) -> None:
    """Effective skip combines LAME's 576 samples with 529 decoder samples."""
    track = tmp_path / "delayed.mp3"
    track.write_bytes(_mp3_with_lame_delay(576, with_id3=True))

    assert read_mp3_start_skip(track) == 1105


def test_reads_info_header_and_crc_frame(tmp_path: Path) -> None:
    track = tmp_path / "constant.mp3"
    track.write_bytes(_mp3_with_lame_delay(576, info=True, with_crc=True))

    assert read_mp3_start_skip(track) == 1105


def test_missing_or_non_lame_header_has_no_adjustment(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp3"
    not_lame = tmp_path / "other.mp3"
    not_lame.write_bytes(_mp3_with_lame_delay(576).replace(b"LAME3.100", b"Lavc59.37"))

    assert read_mp3_start_skip(missing) == 0
    assert read_mp3_start_skip(not_lame) == 0


def test_shift_positions_moves_grid_cues_and_loop_end_together() -> None:
    """Grid and saved points must remain aligned after changing timelines."""
    grid = SourceBeatgrid(
        beats=[SourceBeat(beat_in_bar=1, sample_offset=4_032, bpm=134.0)],
        is_adjusted=False,
    )
    cues = [
        SourceCue(
            kind=CueKind.HOT,
            hot_slot=1,
            start_sample=4_032,
            end_sample=None,
            color=None,
            name="point",
        ),
        SourceCue(
            kind=CueKind.MEMORY,
            hot_slot=None,
            start_sample=44_100,
            end_sample=88_200,
            color=None,
            name="loop",
        ),
    ]

    shifted_grid, shifted_cues = _shift_positions(grid, cues, -1105)

    assert shifted_grid is not None
    assert shifted_grid.beats[0].sample_offset == 2_927
    assert shifted_cues[0].start_sample == 2_927
    assert shifted_cues[0].end_sample is None
    assert shifted_cues[1].start_sample == 42_995
    assert shifted_cues[1].end_sample == 87_095
