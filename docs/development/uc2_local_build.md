# Building and running the genuine UC2 blood-vessel enhancement locally

This describes how the vendored UC2 component is compiled and run on this
machine, and what was measured when it was. Nothing in
`workspace/components/blood_vessels_enhancement` is modified: the sources are
staged, patched, built and run under `build\uc2\`, and every build re-checks
that the vendored copy is untouched and that the staged sources are that copy
plus the versioned patches. The patches and their results are recorded in
[`uc2_changes.md`](uc2_changes.md).

Since `SLIA-021` SLIAFlow runs UC2 itself on every Capture, on IUMA's
calibrated LCTF cube `input\002-04` (`extensions\SLIAFlow\README.md`). The
enhancement is the vendored C code doing real work. Only the acquisition is
simulated, so the map carries `simulated` with the detail
`real UC2 blood-vessel enhancement, recorded IUMA LCTF capture 002-04, calibrated
by IUMA (simulated acquisition)`. It is a visual enhancement, not a quantitative
map and not a clinical result.

The sections from *Run* on record the first build of 2026-09-16, before any
patch, on HSI Human Brain Database cases. The Python runner they describe was
retired with the other standalone producers in `SLIA-028`.

## Build

```powershell
.\scripts\development\build-uc2.ps1 -Clean
```

What the script does, in order:

1. Checks the vendored copy through its own Git repository. The outer repository
   ignores `/workspace/`, so `git status` from the project root says nothing
   about it. The copy must be at partner commit `1b5e9ae` with no tracked file
   modified. `CODE_REVIEW.md` is untracked there and expected.
2. Copies the 13 C sources and headers into `build\uc2\source\`.
3. Applies the patches in `scripts\development\uc2-patches\`, in name order
   (`uc2_changes.md`).
4. Compiles there:

   ```text
   C:\msys64\usr\bin\gcc.exe -Wall -O3 -g main.c params.c functions.c hdr_reader.c BV_enhancement.c png_writer.c -lm -o uc2_bvmap.exe
   ```

5. Copies `msys-2.0.dll` beside the binary.
6. Fails unless the compiler printed exactly the four expected warnings.
7. Fails unless every staged source equals, by SHA-256, its vendored original
   plus the patches, rebuilt from scratch in `build\uc2\expected\`.

### Toolchain

| Component | Value |
| --- | --- |
| Compiler | `gcc (GCC) 15.3.0`, MSYS2 `usr\bin`, target `x86_64-pc-cygwin` |
| Runtime | `msys-2.0.dll`, copied from `C:\msys64\usr\bin` |

The compiler is the MSYS2 POSIX-layer GCC, **not** the UCRT64 one.
`hdr_reader.c` calls `getline`, which the Windows C runtime does not provide.
UCRT64 GCC 16.2.0 stops with `implicit declaration of function 'getline'`, which
GCC 14 and later treat as an error. The `main.out` that first ran UC2 on this
machine was built the same way: it reports `GCC: (GNU) 15.3.0` and imports
`msys-2.0.dll`.

`cc1` loads its DLLs from PATH. Run from Git Bash, whose own MSYS runtime comes
first on PATH, it fails with `error while loading shared libraries`. The script
puts `C:\msys64\usr\bin` first for the compile only.

The compile line is the vendored README's minus `logger.h`. Naming a header on
the command line makes GCC write `logger.h.gch`; `main.c` includes the header
anyway.

### Expected warnings

| Location | Flag | Why |
| --- | --- | --- |
| `main.c:196` | `-Wunused-variable` | The `default:` branch, taken for any data type other than 12 or 4, computes `BVMap` and never writes it. Line 167 before patch 0002 |
| `hdr_reader.c:50`, `:102`, `:109` | `-Wchar-subscripts` | `isdigit` called with a `char` |

They are not silenced and the source is not edited to remove them.

### Measured

| Item | 2026-09-16, no patch | 2026-10-05, patches 0001 and 0002 |
| --- | --- | --- |
| Binary | 413,364 bytes | 417,718 bytes |
| SHA-256 | `8A9D192C...958C321` | Varied across clean builds: `B93EE364...`, `E398B649...` |
| Vendored copy | `1b5e9ae`, 0 tracked changes, untracked `CODE_REVIEW.md` | the same |

The binary's hash depends on the build directory, because `-g` embeds source
paths. It also varied across two clean builds in the same directory on
2026-10-05, with the same size, staged sources, compiler warnings and checked
PNG outputs. The binary hash is therefore recorded as an observation, not an
acceptance oracle.

## How SLIAFlow runs it

On Capture, `SLIAFlowUc2Run.py` starts `build\uc2\source\uc2_bvmap.exe` with
one argument, the cube's folder in forward slashes (`C:/.../input/002-04`), and
`build\uc2\run\` as its working directory, as a background `QProcess` with no
shell and a 30 s timeout, holding `build\uc2\.uc2-runner.lock`. UC2 wrote
`002-04-BVMap.png` (1080 x 1080) in 0.2 to 0.35 s.

Before the process starts: the cube is described again and must be unchanged
since Capture; its files must be `LCTF_Calibrated_Cube_Single.hdr` and `.dat`;
its bands 4, 16 and 50 must be 480, 540 and 710 nm within 0.01 nm; the binary
and `msys-2.0.dll` must be staged; the paths must fit UC2's buffers (511
characters for the input, 255 for the output). After it: a non-zero exit, a
crash, a timeout, any of UC2's error lines on either stream whatever the exit
code, or a missing, stale, undecodable or wrongly sized PNG fails the run. A
failed or refused UC2 run never fails UC1's.

## Run (2026-09-16, retired runner)

```powershell
cd tools\simulators
# Run UC2 and report the map without opening a server.
..\..\.venv\Scripts\python.exe -m stratum_sim uc2-real ..\..\input\bin\bin\004-02 --build-root ..\..\build\uc2 --run-only
# Serve UC2_BV on 127.0.0.1:18946 until Ctrl-C.
..\..\.venv\Scripts\python.exe -m stratum_sim uc2-real ..\..\input\bin\bin\004-02 --build-root ..\..\build\uc2
```

The binary runs with `build\uc2\run\` as its working directory, because it writes
`<case>-BVMap.png` into `"."`.

### Fixed inputs, reported with every run

| Input | Value | Where |
| --- | --- | --- |
| Band indices | 54, 20, 8 (710, 540, 480 nm on the recorded grid) | locals in `main()` |
| `high_in` | 0.15 | local in `main()` |
| `high_out` | 0.8 | local in `main()` |
| `gamma` | 1 | local in `main()` |
| `bValue` | 3 | local in `main()` |

The binary takes one argument, the folder, so none of these can be set from
outside. The runner prints them and does not pretend otherwise.

### Refusals

Before the process starts: a folder that is not a recorded case; a header whose
`data type` is not 12 or whose `interleave` is not `bsq`; a `.dat` file whose
size does not match the header; bands 54, 20 or 8 more than 2.5 nm from 710, 540
or 480 nm.

After it: a non-zero exit; any of `Usage:`, `Error: Directory path is too long!`,
`Error: File path is too long!`, `Error opening file`, `Error reading file`,
`Unknown format.` or `Failed to save the image.` on stdout or stderr, whatever
the exit code; a missing, empty, stale or undecodable PNG; a PNG that is not
three-channel `uint8` of the header's lines and samples.

The message scan exists because the binary exits 0 after most failures. A short
read prints `Error reading file` and processes whatever the buffer held, so a
fresh PNG from that run looks exactly like a result.

### Results, 2026-09-16

`--run-only` on five recorded cases. Wall-clock is the process alone. The last
three columns are the fraction of pixels at 255 in each output channel.

| Case | Size (lines x samples) | Wall-clock | R at 255 | G at 255 | B at 255 |
| --- | --- | ---: | ---: | ---: | ---: |
| 004-02 | 389 x 345 | 0.196 s | 8.3% | 1.3% | 24.0% |
| 007-01 | 582 x 400 | 0.201 s | 3.1% | 1.3% | 47.1% |
| 008-01 | 460 x 549 | 0.223 s | 0.1% | 0.0% | 96.3% |
| 008-02 | 480 x 553 | 0.214 s | 0.5% | 0.2% | 69.7% |
| 010-03 | 371 x 461 | 0.136 s | 0.1% | 0.0% | 89.2% |

The PNGs for 007-01, 008-01, 008-02 and 010-03 are **pixel-identical** to the
ones the earlier `main.out` wrote into the desktop copy, so this build reproduces
that binary's output.

The blue saturation is the `bValue = 3` multiply clipped at 1.0 before
normalization, as `WP5_MS5_DEMO_PLAN.md` records. It is reported, not corrected.

`normalize_rgb_array` rescales each channel to its own minimum and maximum within
one image, so colours are not comparable between captures. That is on the
partner request list.

A pyigtl client on 18946 received three `UC2_BV` messages from a `--cycles 3`
run on 004-02: shape `(1, 389, 345, 3)`, `uint8`, with role `bloodVesselMap`,
origin `simulated` and the recorded-case detail, and no other device name.
