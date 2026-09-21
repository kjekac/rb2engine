# MP3 timeline-offset investigation handoff

Last updated: 2026-09-21

This note records the state needed to continue the hardware investigation on
Linux. It is development evidence, not a claim that the MP3 fix on this branch
is ready to merge.

## Current status

- `fix/mp3-gapless-timeline` contains a **candidate** correction: for MP3s with
  a Xing/Info plus LAME header, subtract the LAME encoder delay plus 529 decoder
  samples from every Rekordbox beat, cue, and loop position. The affected test
  files report a 576-sample encoder delay, so the branch subtracts 1,105
  samples.
- That 1,105-sample theory is not validated by the Prime Go+. It is useful
  code and a reproducible hypothesis, but it should not be proposed upstream
  yet.
- The latest experiment on the physical test stick is different from the code:
  Neuron Collider's beat grid and all visible quick cues were moved one musical
  32nd note earlier, on top of the branch's 1,105-sample correction. This is
  still awaiting inspection on the player.
- A deliberately large `+250 ms` grid-only experiment proved that the player
  reads the current `beatData` from `m.db`. The remaining error is not explained
  by a stale beat-grid cache.
- Visible quick cues and the beat grid are independent. Moving only `beatData`
  moved the grid on the player but left the visible quick cues where they were.
- The separate variable-tempo work is much firmer: it reconstructs dense PQT2
  timing to within roughly three audio samples. Difficult source-analysis state
  can still make a grid disagree with what Rekordbox currently displays.

The important distinction is therefore:

1. the Git branch currently implements a fixed MP3 start-skip correction; and
2. the most recent database on the test stick/ZIP contains an additional,
   manual, tempo-relative experiment for one track only.

## Relevant Git history

The branch names and commits at handoff are:

| Branch | Commit | Purpose |
| --- | --- | --- |
| `main` | `1602d73` | Upstream v0.5.0 base |
| `fix/variable-tempo` | `e6895bf`, `0cf30a6` | Preserve variable geometry and decode PQT2 precision |
| `fix/artwork-id3` | `4f4beac` | ID3v2.4 artwork framing |
| `fix/text-encoding` | `bd2d4b0` | NFC-normalize Engine track paths |
| `feature/prelude-hotcues` | `fed45c3`..`566d142` | Private prelude generation |
| `fix/mp3-gapless-timeline` | `95b1cd3` | Candidate 1,105-sample MP3 correction |
| `fix/defer-waveform-analysis` | `66cc526` | Ask Engine to generate waveforms without replacing grids |
| `integration/all-changes` | `d7cfea0` | All of the above combined for personal use |

Use `fix/mp3-gapless-timeline` when changing the MP3 theory. Use
`integration/all-changes` when producing a stick with all current features,
including prelude generation. The integration branch includes the candidate
1,105-sample correction, but it does not include the final manual one-32nd-note
database edit.

The MP3 branch had 741 passing tests and 6 hardware tests skipped. The combined
integration branch had 772 passing tests and 6 skipped, and passed Ruff and
Mypy, before the manual database experiments.

## Portable and non-portable evidence

The minimal Rekordbox export ZIP and any post-player ZIP are the portable test
artifacts. Always unpack a fresh copy for an experiment; conversion writes only
under `Engine Library/`, but player writeback changes that library further.

The following working-tree paths were intentionally left untracked and are not
part of Git:

- `collider-export/`
- `post-mp3-offset-export/`
- `vacuum-decay-export/`
- `rb2engine-beatgrid-test-suite.m3u8` (contains the hardware observations as
  inline comments)

There are also Mac-local scratch files under `/private/tmp`. In particular:

- `rb2engine-neuron-grid-experiment-before.db`
- `rb2engine-neuron-grid-plus250ms.db`
- `shift_neuron_grid_experiment.py`
- `apply_neuron_thirty_second_correction.py`
- `compare_engine_dbs.py`
- `dump_engine_positions.py`
- `probe_collider_mapping.py`
- `compare_mp3_delay.py`

These will not travel with Git and should not be relied on. The ZIP containing
the latest test-stick state is the portable oracle.

## Test suite and baseline observations

The annotated M3U orders controls before edge cases:

| # | Track | Source case | Baseline result on Prime Go+ |
| --- | --- | --- | --- |
| 1 | Neuron Collider | fixed/x01, populated PQT2, MP3 with LAME delay | Grid about 1/32 note late; visible cues later confirmed similarly late |
| 2 | Phylyps Trak II/II | fixed/x01, populated PQT2, MP3 without usable delay header | Exact |
| 3 | King Of My Castle | fixed/x01, populated PQT2, FLAC | Exact |
| 4 | Species of the Pod | fixed/x01, empty PQT2, MP3 without usable delay header | One beat early; probably inconsistent/stale Rekordbox analysis state |
| 5 | Cellular Phone | gently variable/x02, populated PQT2, MP3 with LAME delay | Rekordbox's cue and displayed grid are already inconsistent; Engine differs by a quarter note overall, and the cue/transient comparison was about 1/32 late |
| 6 | Quadrant Dub II | gently variable/x02, populated PQT2, MP3 without usable delay header | Exact throughout |
| 7 | Club Soda | gently variable/x02, empty PQT2, MP3 without usable delay header | Exact throughout |
| 8 | Virtuous Reality | large variable ramp/x02, populated PQT2, FLAC | Grid visually exact through the ramp; Denon BPM display fluctuates more than Rekordbox |
| 9 | House Jam | live-drummed variable/x02, populated PQT2, MP3 with LAME delay | About 1/32 note late |
| 10 | Vacuum Decay, fixed analysis | fixed/x01, populated PQT2, MP3 with LAME delay | About 1/32 note late |
| 11 | Vacuum Decay, variable analysis | hostile dense variable/x02, populated PQT2, same recording as #10 | Not trustworthy: large and fluctuating disagreement with current Rekordbox display |

“1/32 note” means one eighth of a quarter-note beat, not one thirty-second of a
beat. The observations that were exactly one beat or one eighth note apart were
musically exact by eye; they were not approximate 9/32-style errors. Those
large errors are probably a different problem from the small MP3 offset.

## PQT2 findings relevant to this issue

The inspected library contained 2,111 tracks and 2,085 PQT2 tags. Observed
variant fields were:

- `0x01000002`: 1,990 tracks
- `0x02000002`: 94 tracks
- `0x00000002`: 1 track

Among populated tags, every x01 example inspected had one BPM value
(1,394/1,394), while every x02 example had variable BPM values (64/64). The
best current interpretation is that this encodes fixed/Normal versus
variable/Dynamic analysis, not whether a user corrected the grid. PQT2
presence by itself is not evidence of an edited grid.

The current PQT2 mapper reproduces the source's dense timestamps very closely.
That does not guarantee correspondence to Rekordbox's current UI when its PDB,
ANLZ files, and in-memory state disagree. Vacuum Decay's variable analysis and
the exact quarter/eighth-note discrepancies are examples where source-state
inconsistency remains the leading explanation.

## Experiments already performed

### 1. Fixed 576-sample correction

The LAME header on the affected MP3s stores a 576-sample encoder delay. An
early implementation subtracted 576 samples from grids, cues, and loops.

On hardware, tracks 9 and 10 appeared to improve from roughly 1/32 to roughly
1/64 note late. Track 1 looked unchanged by eye, and track 5 remained
contaminated by its larger Rekordbox grid-state discrepancy. This was suggestive
but not conclusive.

### 2. Fixed 1,105-sample correction

`ffprobe` packet metadata reported `skip_samples=1105` for all five MP3s with a
usable LAME delay header. The value is 576 encoder samples plus the conventional
529 Layer III decoder samples. Four unaffected MP3 controls had no skip
metadata.

The implementation was changed to subtract all 1,105 samples. A database diff
proved that affected grids and cues moved another 529 samples and controls did
not move. Nevertheless, hardware inspection reported exactly the same visible
problems as before.

This means `ffprobe`'s playback skip is real but does **not** prove that Denon's
waveform coordinate origin needs the same correction. Do not treat 1,105 as a
confirmed Engine conversion rule.

The returned stick was audited for stale state:

- the player had generated fresh overview waveforms for exactly the tested
  tracks (1, 5, 9, and 10);
- `m.db` still contained the newly shifted grids and cues;
- default and adjusted beat grids were equal;
- sibling `sm.db` and `stm.db` contained no alternative tracks;
- the database UUID carried forward.

There was no affirmative evidence that the converter wrote the wrong file or
that the player silently restored an older database.

### 3. Deliberate +250 ms grid-only shift

Neuron Collider's default and adjusted beat grids were shifted **later** by
11,025 samples (250 ms at 44.1 kHz). Quick cues and the existing waveform were
left untouched.

The player then showed:

- the grid about 17/32 note late instead of about 1/32; and
- the visible quick cues still about 1/32 late.

That is the expected additional half-beat-scale movement. It rules out a stale
beat-grid cache and confirms that `PerformanceData.beatData` is the field being
displayed.

During writeback, Engine changed the hidden `default_main_cue` and
`adjusted_main_cue` values to follow shifted beat zero. It did not move the
eight visible quick-cue slots. The visible cue positions live independently in
`PerformanceData.quickCues`.

### 4. Current one-32nd-note experiment (pending)

The +250 ms shift was undone. For Neuron Collider the measured beat interval
was:

```text
19,746.305997552 samples per beat
```

One musical 32nd note is one eighth of that interval:

```text
2,468.288249694 samples
55.970255095 ms at 44.1 kHz
```

Both beat grids and all populated visible quick-cue slots were moved earlier by
exactly that amount relative to the 1,105-sample branch build. The waveform was
preserved. Database integrity passed, and the track was left with
`isAnalyzed=1` and `isBeatGridLocked=1`.

The resulting beat-zero/main-cue position is:

```text
458.711750306 samples
```

The eight quick-cue slot offsets in the current database are:

```text
3475806.711750306
4897542.711750306
8214922.711750306
10742450.711750306
4107648.711750306
5529388.711750306
8846767.711750306
11374314.711750306
```

This manual database state is **not generated by the code on this branch**.
Checking out and running `fix/mp3-gapless-timeline` produces the preceding
1,105-sample state.

## Waveform generation

rb2engine writes `beatData`, quick cues, and loops but deliberately leaves
`overviewWaveFormData` empty. The old manual workaround was:

```bash
sqlite3 "/path/to/stick/Engine Library/Database2/m.db" \
  "BEGIN IMMEDIATE; UPDATE Track SET isAnalyzed = 0, isBeatGridLocked = 1; COMMIT;"
```

This asks Engine to analyze missing waveforms while locking the imported grid.
After analysis, the player sets `isAnalyzed` back to 1 and fills
`overviewWaveFormData`.

Commit `66cc526` on `fix/defer-waveform-analysis` automates this correctly for
new conversions by initially writing `isAnalyzed=0` and
`isBeatGridLocked=1`. It is included in `integration/all-changes`, but not in
the MP3 branch. This small fix is independently suitable for an upstream PR.

Inspect those fields with:

```bash
sqlite3 "/path/to/stick/Engine Library/Database2/m.db" \
  "SELECT t.id,t.title,t.isAnalyzed,t.isBeatGridLocked,length(p.overviewWaveFormData) FROM Track AS t JOIN PerformanceData AS p ON p.trackId=t.id ORDER BY t.id;"
```

## Resuming on Linux

Requirements are Python 3.11+ and `uv`.

```bash
git switch integration/all-changes
uv sync
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

For a normal test conversion, unpack a fresh copy of the minimal Rekordbox
export and run:

```bash
uv run rb2engine doctor /path/to/unpacked-stick
uv run rb2engine inspect /path/to/unpacked-stick
uv run rb2engine convert /path/to/unpacked-stick \
  --prelude-bars 8 --prelude-minimum-gap-bars 4
uv run rb2engine verify /path/to/unpacked-stick
```

The prelude options exist only on the private/integration history. Omit them
when testing a focused upstream branch. `convert` writes only under
`Engine Library/`; preserve each post-conversion and post-device state if it
will be compared later.

The blob codecs needed for further controlled edits are in
`src/rb2engine/writer/blobs.py`:

- `decode_beat_data` / `encode_beat_data`
- `decode_quick_cues` / `encode_quick_cues`
- `decode_loops` / `encode_loops`

`BeatMarker.sample_offset`, each populated `QuickCue.sample_offset`, and loop
start/end offsets are stored as sample positions. Both the default and adjusted
beat grids must be changed together. Preserve empty quick-cue sentinels and all
unknown/extra data by decoding, replacing only the relevant numeric fields,
and re-encoding with these project codecs.

## Recommended next experiment

1. Load Neuron Collider from the ZIP containing the current one-32nd-note
   experiment.
2. Inspect the grid and visible cues separately against the same waveform
   transient. Record direction and musical fraction for each.
3. If both now align, repeat a tempo-relative one-eighth-of-a-beat correction
   on House Jam and fixed-analysis Vacuum Decay. Their different BPMs help
   distinguish a musical-fraction correction from a fixed approximately 56 ms
   correction. Avoid variable-analysis Vacuum Decay for this grounding test.
4. Only after that result, replace or remove the branch's 1,105-sample rule and
   add a test whose expected value comes from the hardware evidence.

If the one-32nd correction does not align, continue with deliberately measured
database shifts rather than proposing another decoder-delay constant. The
+250 ms experiment established a reliable causal path from database sample
positions to the player display.

## Work not yet done

- No Engine-authored database has been captured for the exact same MP3s with
  manually aligned Engine grids and known Rekordbox positions. That would be
  the strongest native-coordinate comparison when Engine DJ is available
  again.
- Denon's precise MP3 waveform coordinate convention has not been derived.
- It is not known whether the correct adjustment is 576 samples, 1,105
  samples, a tempo-relative 1/32 note, or something else. The current evidence
  specifically argues against declaring 1,105 solved.
- The final one-32nd-note database experiment has not been checked on hardware.
- Variable-analysis Vacuum Decay has not been reconciled with Rekordbox's UI.
- No caching hypothesis remains supported after the +250 ms experiment.
- The MP3-offset commit should not be submitted upstream until the hardware
  result determines what the implementation should actually do.
