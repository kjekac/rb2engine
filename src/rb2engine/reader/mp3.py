"""Read MP3 gapless start skip without a runtime metadata dependency.

Rekordbox ANLZ positions for delayed MP3s land later than Engine's displayed
waveform. Positions therefore need the effective gapless start skip subtracted
before they are written to Engine's performance blobs. That skip combines the
encoder delay stored in the Xing/LAME header with Layer III's decoder delay.

The reader is deliberately narrow: unsupported or malformed files return
zero and retain the existing behaviour. It never modifies the audio file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

_MAX_FRAME_SCAN = 64 * 1024
_LAYER_III_DECODER_DELAY = 529


def read_mp3_start_skip(path: Path) -> int:
    """Return the effective gapless start skip, or zero when unavailable."""
    try:
        with Path(path).open("rb") as source:
            header = source.read(10)
            audio_start = _id3_end(header)
            source.seek(audio_start)
            data = source.read(_MAX_FRAME_SCAN)
    except OSError:
        return 0

    for frame_start in _mpeg_layer3_headers(data):
        word = int.from_bytes(data[frame_start : frame_start + 4], "big")
        version = (word >> 19) & 0x3
        channel_mode = (word >> 6) & 0x3
        has_crc = ((word >> 16) & 0x1) == 0

        if version == 0x3:  # MPEG-1
            xing_offset = 21 if channel_mode == 0x3 else 36
        else:  # MPEG-2 or MPEG-2.5
            xing_offset = 13 if channel_mode == 0x3 else 21

        # A protected frame carries a two-byte CRC between its four-byte MPEG
        # header and side information. Xing sits after both.
        if has_crc:
            xing_offset += 2

        delay = _delay_from_xing(data, frame_start + xing_offset)
        if delay is not None:
            return delay + _LAYER_III_DECODER_DELAY
    return 0


def _mpeg_layer3_headers(data: bytes) -> Iterator[int]:
    """Yield plausible MPEG Layer III header offsets in scan order."""
    offset = data.find(b"\xff")
    while offset >= 0 and offset + 4 <= len(data):
        if data[offset + 1] & 0xE0 != 0xE0:
            offset = data.find(b"\xff", offset + 1)
            continue
        word = int.from_bytes(data[offset : offset + 4], "big")
        version = (word >> 19) & 0x3
        layer = (word >> 17) & 0x3
        bitrate_index = (word >> 12) & 0xF
        sample_rate_index = (word >> 10) & 0x3
        if (
            version != 0x1
            and layer == 0x1
            and bitrate_index not in (0x0, 0xF)
            and sample_rate_index != 0x3
        ):
            yield offset
        offset = data.find(b"\xff", offset + 1)


def _id3_end(header: bytes) -> int:
    """Return the first byte after an ID3v2 tag, or zero when none is present."""
    if len(header) < 10 or header[:3] != b"ID3":
        return 0
    size_bytes = header[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        return 0
    size = (
        (size_bytes[0] << 21)
        | (size_bytes[1] << 14)
        | (size_bytes[2] << 7)
        | size_bytes[3]
    )
    footer_size = 10 if header[3] == 4 and header[5] & 0x10 else 0
    return 10 + size + footer_size


def _delay_from_xing(data: bytes, xing_start: int) -> int | None:
    if xing_start < 0 or xing_start + 8 > len(data):
        return None
    if data[xing_start : xing_start + 4] not in (b"Xing", b"Info"):
        return None

    flags = int.from_bytes(data[xing_start + 4 : xing_start + 8], "big")
    cursor = xing_start + 8
    if flags & 0x1:  # frame count
        cursor += 4
    if flags & 0x2:  # byte count
        cursor += 4
    if flags & 0x4:  # seek table
        cursor += 100
    if flags & 0x8:  # VBR quality
        cursor += 4

    # Nine-byte encoder version followed by the extended LAME header. Within
    # that extension, bytes 12..14 pack 12-bit delay and 12-bit end padding.
    if cursor + 24 > len(data):
        return None
    version = data[cursor : cursor + 9]
    if not version.startswith((b"LAME", b"L3.99")):
        return None
    if data[cursor + 9] >> 4 != 0:  # unsupported LAME tag revision
        return None

    packed = data[cursor + 21 : cursor + 24]
    return (packed[0] << 4) | (packed[1] >> 4)
