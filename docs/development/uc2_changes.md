# Changes to UC2

This is the record of every change SLIAFlow makes to the vendored UC2
blood-vessel enhancement (`workspace/components/blood_vessels_enhancement`,
partner commit `1b5e9ae`). It follows the mechanism `ADR-0004` decision 3 set
for UC1: each change is a versioned patch in `scripts/development/uc2-patches/`,
applied at staging, and written down here with what it does, why, the command
that was run and what came out. The vendored copy is never written to, and
`BV_enhancement.c`, `png_writer.c` and `hdr_reader.c` are not changed: the
enhancement itself is UC2's, as delivered.

The two patches are the three changes the project owner made and tested in a
standalone copy of UC2 on 2026-10-05, transcribed here unchanged, comments
included. They exist so the map can be shown in Slicer now. If UC2's authors
adopt equivalent changes, the vendored copy is updated to their commit and these
patches are deleted (see [Retiring the patches](#retiring-the-patches)).

The map is a display enhancement, not a measurement, and it is not validated on
the LCTF cube. `normalize_rgb_array` rescales each channel within one image, so
colours are not comparable between captures.

## How the patches are applied

`scripts/development/build-uc2.ps1`:

1. checks that the vendored copy is at `1b5e9ae` with no tracked file modified;
2. copies its 13 C sources and headers into `build/uc2/source/`;
3. applies every `*.patch` in `scripts/development/uc2-patches/`, in name
   order, with `git apply` and `core.autocrlf` off. `git apply` refuses a hunk
   whose context does not match; a patch that does not apply stops the build
   with its name;
4. builds with the MSYS2 GCC (`uc2_local_build.md`) and fails unless the
   compiler prints exactly the four expected warnings;
5. rebuilds a reference (`build/uc2/expected/`) from a fresh copy of the
   vendored sources plus the same patches, and asserts the staged sources equal
   it by SHA-256.

The vendored sources are CRLF in the working tree (the partner repository stores
LF, and `core.autocrlf` is on), so the patches carry CRLF on every context and
added line. Their `.gitattributes` marks them `-text` so Git never converts
them.

```powershell
.\scripts\development\build-uc2.ps1 -Clean
.\.venv\Scripts\python.exe scripts\development\check-uc2.py
```

`check-uc2.py` runs three checks:

| Check | Patch | Oracle |
| --- | --- | --- |
| Calibrated cube `002-04` | 0001, 0002 | a NumPy replica of UC2's own steps on the bands at 480, 540 and 710 nm, pixel for pixel |
| Reference case `020-01`, uint16 with references | 0001 leaves it alone | the unpatched build's PNG, by SHA-256 |
| Calibrated cube holding five bands only | 0002 | refused: exit 1, `Error reading band`, no PNG |

## Patch 0001 - use the calibrated cube when the folder has one

`0001-calibrated-cube-path.patch`, `params.c`. The owner's step 1.

**What.** `initHSImagePaths` builds the paths of `raw.dat`, `raw.hdr` and the
references as before. Then, if the folder holds
`LCTF_Calibrated_Cube_Single.hdr`, the raw cube and header paths are replaced
by `LCTF_Calibrated_Cube_Single.dat` and `.hdr`. The references' paths are
unchanged and are not opened on the float32 path. A folder without that header
is read exactly as before.

**Why.** UC2 takes a folder and reads `raw.dat` and `raw.hdr` from it. IUMA's
`002-04` has neither: its calibrated cube is `LCTF_Calibrated_Cube_Single`.

**Command and result.** The unpatched build on `input/002-04`, 2026-10-05:

```text
Lines: 0
Samples: 0
Error opening file
Failed to open file: No such file or directory
exit 1, no PNG
```

The patched build on `020-01`, which has no calibrated cube, wrote a PNG
byte-identical to the unpatched build's
(`C1C7B940A3340ED8A66381692D1AFA231E3883560EBB4972AD3D583D26E01D9A`, 295,291
bytes).

## Patch 0002 - read the calibrated float32 cube without calibrating it

`0002-calibrated-float32-input.patch`: `functions.h`, `functions.c`, `main.c`.
The owner's steps 2 and 3, in one patch because the new function exists only
for the new case.

**What.**

- `read_selected_bands_BSQ_float` reads only the three needed bands of a
  float32 BSQ cube, seeking to each, and returns them as blue, green, red, the
  order `extract_selected_bands_LCTF_BSQ` gives. A failed open, allocation,
  seek or short read prints an error and exits with code 1.
- `main.c` gets `case 4` (ENVI float32) in its data-type switch. It checks the
  interleave is `bsq`, reads bands 4, 16 and 50, and passes them straight to
  `computeBVmapLCTF` with the same fixed parameters as `case 12`
  (`high_in 0.15`, `high_out 0.8`, `gamma 1`, `bValue 3`), then writes the PNG
  with the same `save_BVMap_as_png`. There is no calibration: the cube is
  already calibrated reflectance.

**Why.** Without it, data type 4 falls to the `default:` branch, which reads
the file as uint16, calibrates it against references `002-04` does not have,
and never writes the map.

**The bands.** The fixed indices 4, 16 and 50 are 480, 540 and 710 nm on the
LCTF grid (460-1000 nm, 5 nm steps: index = (nm - 460) / 5), the wavelengths
`case 12`'s comments name. They are fixed rather than looked up because UC2's
header reader returns no wavelengths for this header. It strips the 14
characters `wavelength = {` and then reads a line's numbers only if the line
starts with a digit. IUMA's header writes `wavelength = { 460, ...` and starts
every following line with a space, so no line qualifies; the HSI Human Brain
Database headers write `wavelength = {440, ...`, whose first line does.
SLIAFlow therefore refuses, before UC2
starts, a cube whose bands 4, 16 and 50 are not 480, 540 and 710 nm within
0.01 nm (`SLIAFlowUc2Run.py`).

**The interleave string.** `" bsq"`, with a leading space, is deliberate: UC2's
header reader keeps the space after `=`, and `case 12` compares the same way.

**Command and result.** `build-uc2.ps1 -Clean`, 2026-10-05: both patches
applied, exit 0. The `default:` branch's unused `BVMap` warning moved from
`main.c:167` to `main.c:196`, 29 lines down; no other warning appeared. Binary
417,718 bytes.

Then `check-uc2.py`, exit 0:

```text
002-04: exit 0, 0.22 s
  002-04-BVMap.png  1080 x 1080, identical to the NumPy replica (bands 4, 16, 50 = 480, 540, 710 nm)
  R at 255 0.7%, G at 255 0.8%, B at 255 69.9%
020-01: exit 0, 0.08 s
  020-01-BVMap.png  identical to the unpatched build  C1C7B940...
short-cube: exit 1, 0.02 s, no PNG
  Error reading band 16 from 'C:/stratum/build/uc2/check/short-input/short-cube/LCTF_Calibrated_Cube_Single.dat'
PASS
```

The replica is written from `BV_enhancement.c` and `png_writer.c`, in float32
as the C code computes: the blue plane as enhancer, `imadjust` to
`[0, 0.8]`, its complement `I2`, the planes `|I2 - red|`, `|I2 - green|` and
`|3 * I2 - blue|`, clipped to `[0, 1]` and normalised per channel. It
reproduces one quirk of `normalize_rgb_array`: every channel's minimum and
maximum start from the first value of the red plane, not of its own channel.
The owner's own replica in the standalone project also gave a difference of 0.

The 69.9 % of blue pixels at 255 is the `bValue = 3` multiply clipped at 1.0
before normalisation, as on the HSI Human Brain Database cases
(`uc2_local_build.md`). It is reported, not corrected.

## What none of this checks

That the map shows vessels correctly. There is no reference vessel map for
`002-04`. The checks show that UC2 runs on the LCTF cube and does exactly what
its delivered code does, on the bands its comments name.

## Findings for UC2's authors, not changed here

- The enhancer channel is taken from calibrated plane 0, which is the blue band,
  while the comment says red (reported on 2026-09-16).
- The header reader returns no wavelengths for IUMA's header (see patch 0002).
- `hdr_reader.c` uses `getline`, which the Windows C runtime does not have, so
  UC2 builds with the MSYS2 POSIX-layer GCC only. The owner's standalone copy
  replaced it with `fgets`; that change is not taken here because the build
  already works (`uc2_local_build.md`).
- The visualisation parameters are local variables in `main()` and cannot be
  set from outside.

## Retiring the patches

If UC2's authors deliver these changes, or their own equivalent:

1. update the vendored copy to their commit and change `$expectedCommit` in
   `build-uc2.ps1`;
2. delete the patches they cover from `scripts/development/uc2-patches/`;
3. update the expected warning lines in `build-uc2.ps1` and the hash in
   `check-uc2.py` if the delivered code moved them;
4. run `build-uc2.ps1 -Clean` and `check-uc2.py`, and record the result here.

`SLIAFlowUc2Run.py` depends only on the behaviour: a folder argument, the
calibrated cube's file names, the three bands and the PNG name. If the
delivered code reads other names or bands, those checks change with it.
