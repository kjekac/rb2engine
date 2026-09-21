# rb2engine-prelude

`rb2engine-prelude` converts a Rekordbox USB export into an Engine DJ library
on the same drive, then optionally turns Rekordbox hot cues into adjustable
runway cues for Engine gear. It is a focused fork of
[rb2engine](https://github.com/jrgutier/rb2engine), packaged with Nix for
reproducible use on Linux and Apple Silicon macOS.

The converter references the audio already exported by Rekordbox. It writes an
Engine database under `Engine Library/`; it does not copy audio or alter
`PIONEER/`, `Contents/`, or the Rekordbox database.

## Prelude cues

With `--prelude-bars 16`, each eligible point hot cue in A–D becomes an Engine
anchor in E–H and gets a new cue 16 musical bars earlier:

```text
Rekordbox A at bar 64  ->  Engine E at bar 64 + Engine A at bar 48
Rekordbox C at bar 96  ->  Engine G at bar 96 + Engine C at bar 80
```

The transform:

- counts beats on Rekordbox's dense beatgrid, so tempo changes and variable
  grids work correctly;
- preserves the original anchor's exact sample position, colour, and name;
- labels generated cues compactly, for example `16b:E` or
  `16b:E (Drop), 24b:G`, and labels moved anchors with `[anchor:A]`;
- shortens the runway at the beginning of a track to the largest available
  whole-bar lead and records it, for example `6b:E`;
- consolidates nearby generated preludes by default. If two would be eight bars
  or less apart, the earlier one covers both anchors and its label names both;
- leaves a source cue unchanged and reports an issue if its E–H destination is
  occupied, it lacks a usable beatgrid, less than one full bar is available,
  or the source pad is ambiguous;
- leaves hot-cue loops and cues already carrying a prelude/anchor marker alone.

The operation is idempotent in the useful sense: each conversion starts with
the untouched Rekordbox export and rebuilds the Engine database. Re-run with
`--prelude-bars 8`, `16`, or `32` to experiment without cumulative shifts.
The transform itself also ignores its own markers if it is accidentally applied
twice in memory.

Set `--prelude-minimum-gap-bars 0` to keep every generated prelude. Any other
value sets the maximum spacing at which the earlier prelude covers a later
anchor.

To affect only tracks in a Rekordbox playlist, pass its path from the playlist
root. Repeat the option to take the union of several playlists; tracks present
in more than one are transformed once:

```bash
--prelude-playlist "Sets/Engine preludes" \
--prelude-playlist "Moods/Heat Death Disco/Crates/120–126"
```

A unique leaf name can be used by itself. If that name exists in several
folders, the command reports the full paths and asks for an exact one. Without
`--prelude-playlist`, cue generation applies to the whole library.

## Prepare the drive

Export the library to a USB or other removable volume from Rekordbox. This tool
needs the traditional Device Library files, including
`PIONEER/rekordbox/export.pdb`; a OneLibrary-only export is not enough. Eject or
close the drive in Rekordbox and Engine DJ before conversion.

Keep a backup until the result has been tested on the target player. Conversion
preserves Engine history and ancillary databases, but it rebuilds `m.db`, so
edits made only in Engine are not a source of truth.

## Run with Nix

The flake is pinned and supports `x86_64-linux`, `aarch64-linux`, and
`aarch64-darwin`. No system Python or `uv` installation is needed.

From this checkout, first inspect the drive and preview the operation:

```bash
nix run . -- doctor /run/media/$USER/DJ_USB
nix run . -- convert /run/media/$USER/DJ_USB \
  --prelude-bars 16 \
  --prelude-minimum-gap-bars 8 \
  --prelude-playlist "Sets/Engine preludes" \
  --dry-run
```

Then build the Engine library and verify it against the Rekordbox source:

```bash
nix run . -- convert /run/media/$USER/DJ_USB \
  --prelude-bars 16 \
  --prelude-minimum-gap-bars 8 \
  --prelude-playlist "Sets/Engine preludes"

nix run . -- verify /run/media/$USER/DJ_USB
```

On macOS, use the mounted volume path such as `/Volumes/DJ_USB`. `verify`
automatically reads the recorded prelude length and spacing from the conversion
journal. Explicit `--prelude-bars` and `--prelude-minimum-gap-bars` options are
available if the journal or report has been moved.

Every conversion writes:

- `Engine Library/Database2/m.db`, the Engine DJ database;
- `Engine Library/rb2engine-report.json`, including cue counts, start-limited
  cues, consolidations, and per-track issues;
- `Engine Library/rb2engine-journal.jsonl`, an append-only conversion journal
  used by verification.

`--no-artwork` skips reading embedded artwork and makes conversion faster.
`inspect --json` exposes the parsed Rekordbox library. `doctor` and `inspect`
are read-only; `verify` reads both sides; only `convert` writes.
Dry runs print every prelude issue with the artist, title, source pad, track ID,
and reason. Completed conversions retain the same list in the JSON report.

Exit status is `0` for success, `1` for a completed operation with discrepancies
or skipped tracks, and `2` for a fatal error.

## What transfers

- Track metadata, paths, keys, BPM, ratings, and other library fields
- Playlist folder hierarchy and track order
- Beatgrids, including manually adjusted grids and tempo changes
- Hot cues, colours, names, memory cues, and saved loops
- Embedded album art

Engine DJ cannot represent duplicate playlist names in one folder or the same
track twice in one playlist. The converter deterministically renames duplicate
playlist names and keeps the first duplicate track occurrence. Engine generates
waveforms itself when it analyses a track.

Supported Engine schemas are 3.0.1 and 3.0.2. Rekordbox Device Library exports
from Rekordbox 5, 6, and 7 are supported. If an existing Engine database uses
an unknown schema, conversion refuses to overwrite it.

## Development

Enter the pinned environment and run the checks:

```bash
nix develop
pytest -q
ruff check src tests
mypy src/rb2engine
```

Or run the complete build gate directly:

```bash
nix flake check
nix build
./result/bin/rb2engine-prelude --help
```

The prelude transform is implemented as a pure Source IR transformation before
rb2engine maps cues into Engine blobs. Its unit tests cover variable grids,
start truncation, consolidation, collisions, and repeated application. The
upstream conversion and binary-codec suite is retained.

## Upstream and license

This repository started from rb2engine 0.5.0, upstream commit `1602d73`. Keep
the upstream remote under the name `upstream` when pulling future fixes.

MIT; see [LICENSE](LICENSE). [NOTICE](NOTICE) contains the upstream format and
dependency acknowledgements.
